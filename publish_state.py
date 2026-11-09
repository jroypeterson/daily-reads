"""Push this repository's state commits without losing a race to another writer.

The daily workflow closes issues and delivers the digest before its last step pushes
the state recording them. Anything pushed to main during those minutes used to get that
final push rejected, and the state was discarded with the runner.

A rejected push is rebased onto the new main and retried. It is never forced. If the
rebase conflicts, or retries run out, the commit goes to a rescue branch so it outlives
the runner, and #status-reports is told: the digest's own heartbeat has already been
posted by then, so this alert is the only signal that state did not land.
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone

MAX_ATTEMPTS = 3
STATE_JSON_FILES = [
    "delivered_state.json",
    "feedback_log.json",
    "taste_evidence.json",
    "readwise_state.json",
    "learned_preferences.json",
    "criteria_update_state.json",
]


def _git(*args: str) -> int:
    return subprocess.run(["git", *args]).returncode


def state_files_parse() -> bool:
    """A rebase that merges cleanly as text can still leave invalid JSON."""
    for path in STATE_JSON_FILES:
        if not os.path.exists(path):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                json.load(f)
        except (ValueError, UnicodeDecodeError) as exc:
            print(f"{path} is not valid JSON after the rebase: {exc}")
            return False
    return True


def push_with_retry() -> bool:
    """Push HEAD to main, rebasing on rejection. True only once main holds the commit."""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        if _git("push", "origin", "HEAD:main") == 0:
            return True
        print(f"Push rejected (attempt {attempt} of {MAX_ATTEMPTS}).")
        if attempt == MAX_ATTEMPTS or _git("fetch", "origin", "main") != 0:
            return False
        if _git("rebase", "--autostash", "FETCH_HEAD") != 0:
            _git("rebase", "--abort")
            return False
        if not state_files_parse():
            return False
    return False


def alert(message: str) -> None:
    webhook = os.environ.get("SLACK_WEBHOOK_STATUS_REPORTS")
    print(f"ALERT: {message}")
    if not webhook:
        return
    import requests

    payload = {
        "text": message,
        "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": f":x: *daily-reads*: {message}"}}],
    }
    try:
        requests.post(webhook, json=payload, timeout=15).raise_for_status()
    except requests.RequestException as exc:
        print(f"Slack alert failed: {exc}")


def main() -> int:
    if push_with_retry():
        return 0
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    branch = f"rescue/daily-{stamp}-{os.environ.get('GITHUB_RUN_ID', 'local')}"
    if _git("push", "origin", f"HEAD:refs/heads/{branch}") == 0:
        alert(f"state did not reach main. It is saved on `{branch}` and must be merged before the next run.")
    else:
        alert("state did not reach main and the rescue branch push also failed. This run's state is lost.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
