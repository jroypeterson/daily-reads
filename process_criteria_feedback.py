"""Process accept/reject/modify decisions for staged criteria proposals."""

import os
import re
from datetime import datetime, timezone

import requests

from main import (
    CRITERIA_STATE_PATH,
    PROPOSED_CRITERIA_PATH,
    REPO,
    load_criteria_state,
    save_criteria_state,
)

API = "https://api.github.com"
TITLE_RE = re.compile(r"Criteria Update:\s*(accept|reject|modify)\s+(.+)", re.IGNORECASE)


def append_history(state: dict, pending: dict, resolution: str, note: str = ""):
    state.setdefault("history", []).append({
        **pending,
        "resolved_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "resolution": resolution,
        "resolution_note": note,
    })


def apply_proposal():
    with open(PROPOSED_CRITERIA_PATH, "r") as f:
        proposed = f.read()
    with open("selection_criteria.md", "w") as f:
        f.write(proposed)


def main():
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("No GITHUB_TOKEN set — skipping criteria decision processing")
        return

    state = load_criteria_state()
    pending = state.get("pending")
    if not pending:
        print("No pending criteria proposal.")
        return

    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
    }

    resp = requests.get(
        f"{API}/repos/{REPO}/issues",
        headers=headers,
        params={"labels": "criteria-update", "state": "open", "per_page": 100},
        timeout=15,
    )
    resp.raise_for_status()
    issues = resp.json()
    if not issues:
        print("No criteria decision issues to process.")
        return

    processed = 0
    for issue in issues:
        match = TITLE_RE.search(issue.get("title", ""))
        if not match:
            continue

        action = match.group(1).lower()
        proposal_id = match.group(2).strip()
        if proposal_id != pending.get("proposal_id"):
            print(f"  Skipping issue #{issue['number']}: not for current proposal")
            continue

        body = issue.get("body") or ""
        note = ""
        note_match = re.search(r"Requested changes:\s*(.+)", body, re.IGNORECASE | re.DOTALL)
        if note_match:
            note = note_match.group(1).strip()

        if action == "accept":
            apply_proposal()
            append_history(state, pending, "accepted")
            state["pending"] = None
            print(f"  Accepted proposal {proposal_id}")
        elif action == "reject":
            append_history(state, pending, "rejected")
            state["pending"] = None
            print(f"  Rejected proposal {proposal_id}")
        elif action == "modify":
            pending["status"] = "modification_requested"
            pending["modification_note"] = note
            pending["requested_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            state["pending"] = pending
            print(f"  Modification requested for {proposal_id}")

        save_criteria_state(state)
        requests.patch(
            f"{API}/repos/{REPO}/issues/{issue['number']}",
            headers=headers,
            json={"state": "closed"},
            timeout=10,
        )
        processed += 1

    print(f"Processed {processed} criteria decision issue(s).")


if __name__ == "__main__":
    main()
