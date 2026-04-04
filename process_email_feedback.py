"""Harvest feedback from email replies to Daily Reads digests.

Looks for replies to "Daily Reads" emails and parses simple feedback like:
  slot 1: 3
  slot 2: 1
  1 3
  3 1 too generic
  slot 3: okay
"""

import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

from gmail_reader import get_gmail_service
from project_data import append_taste_evidence, enrich_feedback_entry, evidence_id_for

FEEDBACK_RE = re.compile(
    r"^\s*(?:slot\s*)?(\d{1,2})[ \t]*[:\-]?[ \t]*(strong|great|good|fine|okay|ok|miss|bad|not useful|irrelevant|boring|1|2|3)(?:[ \t]*[,\-]?[ \t]*([^\n]+))?\s*$",
    re.IGNORECASE | re.MULTILINE,
)

SCORE_MAP = {
    "strong": 3,
    "great": 3,
    "good": 3,
    "3": 3,
    "fine": 2,
    "okay": 2,
    "ok": 2,
    "2": 2,
    "miss": 1,
    "bad": 1,
    "not useful": 1,
    "irrelevant": 1,
    "boring": 1,
    "1": 1,
}


def load_json(path, default=None):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default if default is not None else []


def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def extract_reply_text(payload):
    """Extract the reply portion of an email, stripping quoted content."""
    import base64

    text = ""
    if payload.get("mimeType") == "text/plain":
        data = payload.get("body", {}).get("data", "")
        if data:
            text = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
    for part in payload.get("parts", []):
        result = extract_reply_text(part)
        if result:
            text = result
            break

    if not text:
        return ""

    # Strip quoted reply (lines starting with > or "On ... wrote:")
    lines = []
    for line in text.split("\n"):
        if re.match(r"^On .+ wrote:", line):
            break
        if line.strip().startswith(">"):
            break
        lines.append(line)
    return "\n".join(lines).strip()


def main():
    print("=" * 60)
    print("  EMAIL FEEDBACK CHECK")
    print("=" * 60)

    try:
        service = get_gmail_service()
    except Exception as e:
        print(f"Gmail auth failed: {e}")
        return

    # Search for replies to Daily Reads emails in the last 48 hours
    cutoff = datetime.now(timezone.utc) - timedelta(hours=48)
    date_query = cutoff.strftime("%Y/%m/%d")
    query = f'after:{date_query} subject:"Daily Reads" in:inbox is:reply'

    try:
        resp = service.users().messages().list(
            userId="me", q=query, maxResults=20
        ).execute()
    except Exception as e:
        print(f"Gmail search failed: {e}")
        return

    messages = resp.get("messages", [])
    if not messages:
        print("No email feedback replies found.")
        return

    feedback = load_json("feedback_log.json", [])
    existing = {(e["date"], e["slot"], e.get("source", "")) for e in feedback}
    processed = 0

    for msg_stub in messages:
        msg = service.users().messages().get(
            userId="me", id=msg_stub["id"], format="full"
        ).execute()

        headers = {h["name"].lower(): h["value"] for h in msg["payload"]["headers"]}
        subject = headers.get("subject", "")

        # Extract date from subject like "Re: Daily Reads — 2026-03-25"
        date_match = re.search(r"(\d{4}-\d{2}-\d{2})", subject)
        if not date_match:
            continue
        digest_date = date_match.group(1)

        # Get the reply text
        reply_text = extract_reply_text(msg["payload"])
        if not reply_text:
            continue

        # Parse feedback lines
        for match in FEEDBACK_RE.finditer(reply_text):
            slot = int(match.group(1))
            rating = match.group(2).lower()
            note = (match.group(3) or "").strip()
            score = SCORE_MAP.get(rating, 3)

            if slot < 1 or slot > 14:
                continue

            key = (digest_date, slot, "email_reply")
            if key in existing:
                print(f"  Duplicate: {digest_date} slot{slot} — skipping")
                continue

            entry = enrich_feedback_entry(digest_date, slot, "email_reply", score, note)
            entry["source"] = "email_reply"
            feedback.append(entry)
            existing.add(key)
            processed += 1
            print(f"  Recorded: {digest_date} slot{slot} score{score} — {note or '(no note)'}")

    save_json("feedback_log.json", feedback)

    # Bridge score-1 and score-3 entries into taste evidence
    taste_records = []
    for entry in feedback:
        score = entry.get("score")
        if score not in (1, 3):
            continue
        taste_records.append({
            "id": evidence_id_for(f"feedback|{entry.get('date')}|{entry.get('slot')}|{entry.get('channel', '')}"),
            "kind": f"daily_rating_{score}",
            "source_channel": "daily_scoring",
            "title": entry.get("headline", ""),
            "url": entry.get("url", ""),
            "local_path": "",
            "note": entry.get("note", ""),
            "score": score,
            "content_status": "not_applicable",
            "metadata": {
                "article_id": entry.get("article_id"),
                "article_source": entry.get("article_source"),
                "slot": entry.get("slot"),
                "digest_date": entry.get("date"),
            },
            "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        })
    if taste_records:
        bridged = append_taste_evidence(taste_records)
        if bridged:
            print(f"Bridged {bridged} feedback entries to taste evidence.")

    print(f"Processed {processed} feedback entries from {len(messages)} reply email(s).")


if __name__ == "__main__":
    main()
