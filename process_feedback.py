"""Harvest feedback from GitHub Issues and append to feedback_log.json."""

import json
import os
import re
import sys

import requests

REPO = "jroypeterson/daily-reads"
API = "https://api.github.com"
TITLE_RE = re.compile(r"Feedback:\s*(\d{4}-\d{2}-\d{2})\s+slot(\d+)\s+score(\d+)", re.IGNORECASE)


def load_json(path, default=None):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default if default is not None else []


def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def main():
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("No GITHUB_TOKEN set — skipping feedback processing")
        return

    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
    }

    # Fetch open issues with the feedback label
    resp = requests.get(
        f"{API}/repos/{REPO}/issues",
        headers=headers,
        params={"labels": "feedback", "state": "open", "per_page": 100},
        timeout=15,
    )
    resp.raise_for_status()
    issues = resp.json()

    if not issues:
        print("No feedback issues to process.")
        return

    feedback = load_json("feedback_log.json", [])
    existing = {(e["date"], e["slot"], e.get("source", "")) for e in feedback}
    processed = 0

    for issue in issues:
        title = issue.get("title", "")
        m = TITLE_RE.search(title)
        if not m:
            print(f"  Skipping issue #{issue['number']}: title didn't match pattern")
            continue

        date, slot, score = m.group(1), int(m.group(2)), int(m.group(3))

        # Extract optional note from body
        body = issue.get("body") or ""
        note = ""
        note_match = re.search(r"Optional note:\s*(.+)", body, re.IGNORECASE)
        if note_match:
            note = note_match.group(1).strip()

        # Deduplicate by (date, slot, source)
        key = (date, slot, "github_issue")
        if key in existing:
            print(f"  Duplicate: {date} slot{slot} — skipping")
        else:
            entry = {
                "date": date,
                "slot": slot,
                "score": score,
                "note": note,
                "source": "github_issue",
            }
            feedback.append(entry)
            existing.add(key)
            processed += 1
            print(f"  Recorded: {date} slot{slot} score{score}")

        # Close the issue
        requests.patch(
            f"{API}/repos/{REPO}/issues/{issue['number']}",
            headers=headers,
            json={"state": "closed"},
            timeout=10,
        )

    save_json("feedback_log.json", feedback)
    print(f"Processed {processed} new feedback entries from {len(issues)} issue(s).")


if __name__ == "__main__":
    main()
