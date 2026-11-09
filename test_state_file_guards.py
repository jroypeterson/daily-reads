"""#685: an unreadable state file must never be replaced by a default."""

import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

import main as daily_main
import preference_learning
import process_dropbox_exemplars
import process_email_feedback
import process_feedback
import project_data
import taste_sync
from project_data import UnreadableStateFile, load_json, load_json_strict, save_json

CORRUPT_CONTENTS = [b"", b"\x00" * 64, b'[{"id": "a"', b"\xff\xfe not utf-8"]


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(project_data, "_UNREADABLE_PATHS", set())


@pytest.mark.parametrize("content", CORRUPT_CONTENTS)
def test_save_refuses_a_file_that_failed_to_load_and_leaves_its_bytes(content):
    path = Path("state.json")
    path.write_bytes(content)
    assert load_json(str(path), []) == []
    with pytest.raises(UnreadableStateFile):
        save_json(str(path), [])
    assert path.read_bytes() == content


def test_absent_file_is_a_first_run_and_can_be_saved():
    assert load_json("new.json", {"a": 1}) == {"a": 1}
    save_json("new.json", [1])
    assert json.loads(Path("new.json").read_text()) == [1]


def test_a_repaired_file_can_be_saved_again():
    path = Path("state.json")
    path.write_bytes(b"{broken")
    load_json(str(path))
    path.write_text("[1]")
    assert load_json(str(path)) == [1]
    save_json(str(path), [1, 2])
    assert json.loads(path.read_text()) == [1, 2]


def test_a_relative_and_absolute_path_are_the_same_file():
    path = Path("state.json")
    path.write_bytes(b"{broken")
    load_json("state.json")
    with pytest.raises(UnreadableStateFile):
        save_json(str(path.resolve()), [])


def test_strict_load_raises_on_unreadable_but_not_on_absent():
    assert load_json_strict("absent.json", []) == []
    Path("bad.json").write_bytes(b"{broken")
    with pytest.raises(UnreadableStateFile):
        load_json_strict("bad.json", [])


def test_append_taste_evidence_keeps_a_corrupt_store():
    path = Path(project_data.taste_evidence_path())
    path.write_bytes(b'[{"id": "a"')
    with pytest.raises(UnreadableStateFile):
        project_data.append_taste_evidence([{"id": "b"}])
    assert path.read_bytes() == b'[{"id": "a"'


def test_dropbox_ingest_stops_before_moving_any_source_file(tmp_path, monkeypatch):
    Path(project_data.taste_evidence_path()).write_bytes(b"\x00" * 16)
    root = tmp_path / "samples"
    root.mkdir()
    sample = root / "article.txt"
    sample.write_text("some note", encoding="utf-8")
    monkeypatch.setenv("DROPBOX_TASTE_DIR", str(root))
    with pytest.raises(UnreadableStateFile):
        process_dropbox_exemplars.main()
    assert sample.exists()
    assert not process_dropbox_exemplars.archive_dir(root).exists()


def test_preferences_are_not_rebuilt_from_evidence_that_failed_to_load():
    Path(project_data.taste_evidence_path()).write_bytes(b"\x00" * 16)
    prefs = Path(preference_learning.LEARNED_PREFERENCES_JSON_PATH)
    prefs.write_text('{"topic_preferences": [{"topic": "kept"}]}', encoding="utf-8")
    before = prefs.read_bytes()
    with pytest.raises(UnreadableStateFile):
        preference_learning.update_learned_preferences()
    assert prefs.read_bytes() == before


@pytest.mark.parametrize("module", [process_feedback, process_email_feedback])
def test_feedback_writers_use_the_guarded_store(module):
    assert module.load_json is project_data.load_json
    assert module.save_json is project_data.save_json


def test_a_refused_save_marks_the_daily_run_partial_instead_of_raising(monkeypatch):
    monkeypatch.setitem(daily_main._RUN_STATE, "partial_reasons", [])
    Path("log.json").write_bytes(b"{broken")
    load_json("log.json", [])
    assert daily_main._persist_or_flag(save_json, "log.json", []) is False
    assert "log.json" in daily_main._RUN_STATE["partial_reasons"][0]
    assert Path("log.json").read_bytes() == b"{broken"


def test_a_normal_save_is_not_flagged(monkeypatch):
    monkeypatch.setitem(daily_main._RUN_STATE, "partial_reasons", [])
    assert daily_main._persist_or_flag(save_json, "log.json", [1]) is True
    assert daily_main._RUN_STATE["partial_reasons"] == []


HEAD = json.dumps([{"id": "a"}, {"id": "b"}])


@pytest.mark.parametrize(
    "working, fragment",
    [
        ("[]", "shrank"),
        (json.dumps([{"id": "a"}]), "shrank"),
        (json.dumps([{"id": "a"}, {"id": "z"}]), "lost 1"),
        ("\x00\x00", "not a readable"),
        ('{"id": "a"}', "not a readable"),
    ],
)
def test_evidence_loss_names_each_way_of_losing_records(working, fragment):
    assert fragment in taste_sync.evidence_loss(HEAD, working)


@pytest.mark.parametrize(
    "head, working",
    [
        (HEAD, HEAD),
        (HEAD, json.dumps([{"id": "a"}, {"id": "b"}, {"id": "c"}])),
        (None, "[]"),
        ("{broken", "[]"),
    ],
)
def test_evidence_loss_allows_growth_and_a_missing_baseline(head, working):
    assert taste_sync.evidence_loss(head, working) is None


def _fake_git(monkeypatch, head_text):
    calls = []

    def run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[:2] == ["git", "show"]:
            return SimpleNamespace(returncode=0, stdout=head_text.encode())
        if cmd[:2] == ["git", "diff"]:
            return SimpleNamespace(returncode=1, stdout=b"")
        return SimpleNamespace(returncode=0, stdout=b"")

    monkeypatch.setattr(taste_sync.subprocess, "run", run)
    return calls


def _verbs(calls):
    return [c[1] for c in calls if c[0] == "git"]


def test_the_job_refuses_to_stage_commit_or_push_a_shrunk_store(monkeypatch):
    Path(taste_sync.EVIDENCE_PATH).write_text("[]", encoding="utf-8")
    calls = _fake_git(monkeypatch, HEAD)
    assert taste_sync.main() == taste_sync.EXIT_EVIDENCE_LOSS
    assert not {"add", "commit", "push"} & set(_verbs(calls))


def test_the_job_commits_and_pushes_a_store_that_grew(monkeypatch):
    grown = json.dumps([{"id": "a"}, {"id": "b"}, {"id": "c"}])
    Path(taste_sync.EVIDENCE_PATH).write_text(grown, encoding="utf-8")
    calls = _fake_git(monkeypatch, HEAD)
    assert taste_sync.main() == 0
    assert _verbs(calls)[-3:] == ["add", "commit", "push"]


def test_head_evidence_reads_the_committed_copy_not_the_working_file():
    def git(*args):
        subprocess.run(["git", *args], check=True, capture_output=True)

    git("init", "-q")
    Path(taste_sync.EVIDENCE_PATH).write_text(HEAD, encoding="utf-8")
    git("add", taste_sync.EVIDENCE_PATH)
    git("-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", "commit", "-qm", "x")
    Path(taste_sync.EVIDENCE_PATH).write_text("[]", encoding="utf-8")
    git("add", taste_sync.EVIDENCE_PATH)  # staged too, so the index is not a stand-in for HEAD
    assert json.loads(taste_sync.head_evidence()) == json.loads(HEAD)


def test_head_evidence_outside_a_repo_is_no_baseline(monkeypatch):
    monkeypatch.setenv("GIT_DIR", os.path.join(os.getcwd(), "not-a-repo"))
    assert taste_sync.head_evidence() is None


def test_the_scheduled_task_runs_the_guarded_script():
    script = (Path(__file__).parent / "register_daily_dropbox_taste_task.ps1").read_text(encoding="ascii")
    assert '-Argument "taste_sync.py"' in script
    assert "git', 'commit'" not in script
