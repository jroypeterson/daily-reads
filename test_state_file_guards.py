"""#685: an unreadable state file must never be replaced by a default."""

import inspect
import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

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
    assert module.load_json_strict is project_data.load_json_strict
    assert module.save_json is project_data.save_json


def test_a_corrupt_feedback_log_closes_no_github_issue(monkeypatch):
    Path("feedback_log.json").write_bytes(b"{broken")
    issue = {"number": 7, "title": "Feedback: 2026-11-01 slot1 score3", "body": ""}
    closed = []
    monkeypatch.setenv("GITHUB_TOKEN", "x")
    monkeypatch.setattr(
        process_feedback.requests,
        "get",
        lambda *a, **k: SimpleNamespace(raise_for_status=lambda: None, json=lambda: [issue]),
    )
    monkeypatch.setattr(process_feedback.requests, "patch", lambda *a, **k: closed.append(a))
    with pytest.raises(UnreadableStateFile):
        process_feedback.main()
    assert closed == []
    assert Path("feedback_log.json").read_bytes() == b"{broken"


def test_a_corrupt_feedback_log_stops_email_feedback_before_reading_mail(monkeypatch):
    Path("feedback_log.json").write_bytes(b"{broken")
    service = MagicMock()
    messages = service.users.return_value.messages.return_value
    messages.list.return_value.execute.return_value = {"messages": [{"id": "1"}]}
    monkeypatch.setattr(process_email_feedback, "get_gmail_service", lambda: service)
    with pytest.raises(UnreadableStateFile):
        process_email_feedback.main()
    messages.get.assert_not_called()


def test_an_unreadable_ledger_skips_the_reader_push_and_marks_the_run_partial(monkeypatch):
    monkeypatch.setitem(daily_main._RUN_STATE, "partial_reasons", [])
    pushed = []
    monkeypatch.setattr(daily_main, "deliver_reader", lambda *a, **k: pushed.append(a))
    Path(project_data.DELIVERED_STATE_PATH).write_bytes(b"{broken")
    state = project_data.load_delivered_state()
    assert daily_main._deliver_reader_if_ledger_readable([], [], state, "2026-11-09") is False
    assert pushed == []
    assert "Reader push skipped" in daily_main._RUN_STATE["partial_reasons"][0]


def test_a_readable_ledger_pushes_to_reader(monkeypatch):
    monkeypatch.setitem(daily_main._RUN_STATE, "partial_reasons", [])
    pushed = []
    monkeypatch.setattr(daily_main, "deliver_reader", lambda *a, **k: pushed.append((a, k)))
    state = project_data.load_delivered_state()
    assert daily_main._deliver_reader_if_ledger_readable([], [], state, "2026-11-09") is True
    assert pushed == [(([], []), {"state": state, "today": "2026-11-09"})]
    assert daily_main._RUN_STATE["partial_reasons"] == []


def test_main_reaches_reader_only_through_the_ledger_check():
    source = inspect.getsource(daily_main.main)
    assert "_deliver_reader_if_ledger_readable(" in source
    assert "deliver_reader(articles" not in source.replace("_deliver_reader_if_ledger_readable", "")


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


def _fake_git(monkeypatch, head_text, failing=()):
    calls = []

    def run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[:2] == ["git", "show"]:
            return SimpleNamespace(returncode=0, stdout=head_text.encode())
        if cmd[:2] == ["git", "diff"]:
            return SimpleNamespace(returncode=1, stdout=b"")
        if cmd[:2] == ["git", "rev-list"]:
            return SimpleNamespace(returncode=0, stdout=b"1\n")
        if cmd[:2] == ["git", "log"]:
            return SimpleNamespace(returncode=0, stdout=taste_sync.COMMIT_MESSAGE.encode())
        if cmd[0] == "git" and cmd[1] in failing:
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
    assert [v for v in _verbs(calls) if v in ("add", "commit", "push")] == ["add", "commit", "push"]


GROWN = json.dumps([{"id": "a"}, {"id": "b"}, {"id": "c"}])


@pytest.mark.parametrize("verb", ["add", "commit", "push"])
def test_a_failed_git_step_fails_the_job_and_stops_the_steps_after_it(monkeypatch, verb):
    Path(taste_sync.EVIDENCE_PATH).write_text(GROWN, encoding="utf-8")
    calls = _fake_git(monkeypatch, HEAD, failing=(verb,))
    assert taste_sync.main() != 0
    order = ["add", "commit", "push"]
    assert not set(order[order.index(verb) + 1:]) & set(_verbs(calls))


@pytest.fixture
def git_clone(tmp_path, monkeypatch):
    """A real clone of a throwaway bare origin, with HEAD holding two evidence records."""
    monkeypatch.setattr(taste_sync, "INGEST_STEPS", [])
    origin, clone = tmp_path / "origin.git", tmp_path / "clone"

    def git(*args, cwd=clone):
        return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()

    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    subprocess.run(["git", "clone", "-q", str(origin), str(clone)], check=True, capture_output=True)
    git("checkout", "-q", "-B", "main")
    git("config", "user.name", "t")
    git("config", "user.email", "t@t")
    git("config", "commit.gpgsign", "false")
    for name in taste_sync.TRACKED_PATHS:
        (clone / name).write_text(HEAD if name == taste_sync.EVIDENCE_PATH else "{}", encoding="utf-8")
    git("add", ".")
    git("commit", "-qm", "seed")
    git("push", "-q", "origin", "main")
    monkeypatch.chdir(clone)
    return SimpleNamespace(git=git, origin=origin, clone=clone)


def _origin_evidence(repo):
    return json.loads(repo.git("show", f"main:{taste_sync.EVIDENCE_PATH}", cwd=repo.origin))


def test_real_git_a_change_left_staged_is_committed_and_pushed(git_clone):
    Path(taste_sync.EVIDENCE_PATH).write_text(GROWN, encoding="utf-8")
    git_clone.git("add", taste_sync.EVIDENCE_PATH)
    assert taste_sync.main() == 0
    assert len(_origin_evidence(git_clone)) == 3


def test_real_git_a_failed_push_fails_the_job_and_the_next_run_delivers_it(git_clone):
    Path(taste_sync.EVIDENCE_PATH).write_text(GROWN, encoding="utf-8")
    good_url = git_clone.git("remote", "get-url", "origin")
    git_clone.git("remote", "set-url", "--push", "origin", str(git_clone.clone.parent / "missing.git"))
    assert taste_sync.main() != 0
    assert len(_origin_evidence(git_clone)) == 2
    git_clone.git("remote", "set-url", "--push", "origin", good_url)
    assert taste_sync.main() == 0
    assert len(_origin_evidence(git_clone)) == 3


def test_real_git_a_commit_by_someone_else_is_never_pushed(git_clone):
    Path("other.txt").write_text("x", encoding="utf-8")
    git_clone.git("add", "other.txt")
    git_clone.git("commit", "-qm", "another session's work")
    assert taste_sync.main() == 0
    assert git_clone.git("rev-parse", "main", cwd=git_clone.origin) != git_clone.git("rev-parse", "HEAD")


def test_real_git_a_shrink_is_refused_and_origin_is_untouched(git_clone):
    Path(taste_sync.EVIDENCE_PATH).write_text("[]", encoding="utf-8")
    assert taste_sync.main() == taste_sync.EXIT_EVIDENCE_LOSS
    assert len(_origin_evidence(git_clone)) == 2


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
