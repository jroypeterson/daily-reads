"""The workflow's state push survives another writer, and never loses or forces anything."""

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

import process_criteria_feedback
import publish_state


def _git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def _identify(repo):
    _git("config", "user.name", "t", cwd=repo)
    _git("config", "user.email", "t@t", cwd=repo)
    _git("config", "commit.gpgsign", "false", cwd=repo)


def _commit(repo, name, content, message="change"):
    (repo / name).write_text(content, encoding="utf-8")
    _git("add", name, cwd=repo)
    _git("commit", "-qm", message, cwd=repo)


@pytest.fixture
def repos(tmp_path, monkeypatch):
    """A bare origin, a depth-1 runner clone like Actions' default, and a second writer."""
    origin, seed = tmp_path / "origin.git", tmp_path / "seed"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    subprocess.run(["git", "clone", "-q", str(origin), str(seed)], check=True, capture_output=True)
    _git("checkout", "-q", "-B", "main", cwd=seed)
    _identify(seed)
    _commit(seed, "delivered_state.json", '{"delivered": []}\n', "seed")
    _commit(seed, "history.txt", "two\n", "second")
    _git("push", "-q", "origin", "main", cwd=seed)

    runner = tmp_path / "runner"
    url = origin.resolve().as_uri()
    subprocess.run(["git", "clone", "-q", "--depth", "1", url, str(runner)], check=True, capture_output=True)
    _identify(runner)
    monkeypatch.chdir(runner)
    monkeypatch.delenv("SLACK_WEBHOOK_STATUS_REPORTS", raising=False)
    monkeypatch.setenv("GITHUB_RUN_ID", "42")
    return SimpleNamespace(origin=origin, runner=runner, other=seed)


def _on_main(repo, name):
    return _git("show", f"main:{name}", cwd=repo.origin)


def _second_writer_pushes(repo, name, content):
    _commit(repo.other, name, content, "interactive push")
    _git("push", "-q", "origin", "main", cwd=repo.other)


def test_a_push_with_no_competition_lands(repos):
    _commit(repos.runner, "state.txt", "new\n")
    assert publish_state.main() == 0
    assert _on_main(repos, "state.txt") == "new"


def test_a_push_during_the_run_is_rebased_and_both_sides_land(repos):
    _commit(repos.runner, "state.txt", "new\n")
    _second_writer_pushes(repos, "code.py", "x = 1\n")
    assert publish_state.main() == 0
    assert _on_main(repos, "state.txt") == "new"
    assert _on_main(repos, "code.py") == "x = 1"


def test_a_conflict_saves_the_commit_to_a_rescue_branch_and_fails(repos, monkeypatch):
    alerts = []
    monkeypatch.setattr(publish_state, "alert", alerts.append)
    _commit(repos.runner, "delivered_state.json", '{"delivered": ["runner"]}\n')
    ours = _git("rev-parse", "HEAD", cwd=repos.runner)
    _second_writer_pushes(repos, "delivered_state.json", '{"delivered": ["other"]}\n')
    main_before = _git("rev-parse", "main", cwd=repos.origin)

    assert publish_state.main() == 1

    assert _git("rev-parse", "main", cwd=repos.origin) == main_before
    rescue = _git("for-each-ref", "--format=%(refname:short)", "refs/heads/rescue", cwd=repos.origin)
    assert rescue.startswith("rescue/daily-") and rescue.endswith("-42")
    assert _git("rev-parse", rescue, cwd=repos.origin) == ours
    assert not (repos.runner / ".git" / "rebase-merge").exists()
    assert len(alerts) == 1 and rescue in alerts[0]


def test_uncommitted_tracked_changes_do_not_block_the_rebase(repos):
    _commit(repos.runner, "state.txt", "new\n")
    (repos.runner / "delivered_state.json").write_text('{"delivered": ["unstaged"]}\n', encoding="utf-8")
    _second_writer_pushes(repos, "code.py", "x = 1\n")
    assert publish_state.main() == 0
    assert _on_main(repos, "code.py") == "x = 1"
    assert "unstaged" in (repos.runner / "delivered_state.json").read_text(encoding="utf-8")


def test_criteria_state_is_durable_after_a_race(repos):
    _second_writer_pushes(repos, "code.py", "x = 1\n")
    Path("criteria_update_state.json").write_text('{"pending": null}\n', encoding="utf-8")
    assert process_criteria_feedback.commit_durable_state(["criteria_update_state.json"], "criteria") is True
    assert json.loads(_on_main(repos, "criteria_update_state.json")) == {"pending": None}


def test_criteria_issue_stays_open_when_the_push_cannot_land(repos, monkeypatch):
    monkeypatch.setattr(process_criteria_feedback, "push_with_retry", lambda: False)
    Path("criteria_update_state.json").write_text('{"pending": null}\n', encoding="utf-8")
    assert process_criteria_feedback.commit_durable_state(["criteria_update_state.json"], "criteria") is False


def _scripted_git(monkeypatch, answers):
    calls = []

    def git(*args):
        calls.append(args)
        return answers(args)

    monkeypatch.setattr(publish_state, "_git", git)
    return calls


def test_retries_are_bounded_and_never_forced(monkeypatch):
    calls = _scripted_git(monkeypatch, lambda args: 1 if args[0] == "push" else 0)
    assert publish_state.push_with_retry() is False
    pushes = [c for c in calls if c[0] == "push"]
    assert len(pushes) == publish_state.MAX_ATTEMPTS
    assert not any("--force" in part for c in calls for part in c)


def test_invalid_json_after_a_clean_rebase_is_not_pushed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    calls = _scripted_git(monkeypatch, lambda args: 1 if args[0] == "push" else 0)
    Path("taste_evidence.json").write_text("[{", encoding="utf-8")
    assert publish_state.push_with_retry() is False
    assert len([c for c in calls if c[0] == "push"]) == 1


def test_a_failed_rescue_push_says_the_state_is_lost(monkeypatch):
    alerts = []
    monkeypatch.setattr(publish_state, "push_with_retry", lambda: False)
    monkeypatch.setattr(publish_state, "alert", alerts.append)
    _scripted_git(monkeypatch, lambda args: 1)
    assert publish_state.main() == 1
    assert "lost" in alerts[0]


def test_the_alert_posts_block_kit_and_survives_a_slack_failure(monkeypatch):
    import requests

    sent = []

    def post(url, json, timeout):
        sent.append(json)
        raise requests.ConnectionError("down")

    monkeypatch.setenv("SLACK_WEBHOOK_STATUS_REPORTS", "https://example.invalid/hook")
    monkeypatch.setattr(requests, "post", post)
    publish_state.alert("state did not land")
    assert sent[0]["blocks"][0]["type"] == "section"


def test_the_workflow_uses_the_publisher_and_serializes_runs():
    workflow = (Path(__file__).parent / ".github" / "workflows" / "daily.yml").read_text(encoding="utf-8")
    lines = [line.strip() for line in workflow.splitlines()]
    assert "python publish_state.py" in lines
    assert "git push" not in lines
    assert "group: daily-reads" in lines
    assert "cancel-in-progress: false" in lines
    assert any(line.startswith("fetch-depth: 0") for line in lines)
