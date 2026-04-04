"""Harvest taste submissions from GitHub Issues and rebuild taste profile."""

import os
import re
import sys
from datetime import datetime, timezone

import anthropic
import requests
from project_data import append_taste_evidence, evidence_id_for, load_taste_evidence
from preference_learning import update_learned_preferences

REPO = "jroypeterson/daily-reads"
API = "https://api.github.com"
TITLE_RE = re.compile(r"Taste:\s*(.+)", re.IGNORECASE)
URL_RE = re.compile(r"https?://\S+")



def harvest_issues(headers):
    """Fetch open taste issues, parse them, append to taste_evidence.json, close them."""
    resp = requests.get(
        f"{API}/repos/{REPO}/issues",
        headers=headers,
        params={"labels": "taste", "state": "open", "per_page": 100},
        timeout=15,
    )
    resp.raise_for_status()
    issues = resp.json()

    if not issues:
        print("No taste issues to process.")
        return 0

    new_records = []

    for issue in issues:
        title = issue.get("title", "")
        m = TITLE_RE.search(title)
        if not m:
            print(f"  Skipping issue #{issue['number']}: title didn't match pattern")
            continue

        headline = m.group(1).strip()
        body = issue.get("body") or ""

        # Extract article URL
        url_match = URL_RE.search(body)
        url = url_match.group(0) if url_match else ""

        # Extract optional note
        note = ""
        note_match = re.search(r"Why I liked it:\s*(.+)", body, re.IGNORECASE | re.DOTALL)
        if note_match:
            note = note_match.group(1).strip()

        if not url:
            print(f"  Skipping issue #{issue['number']}: no URL found in body")
        else:
            new_records.append({
                "id": evidence_id_for(f"github-issue|{url}"),
                "kind": "positive_exemplar",
                "source_channel": "github_issue",
                "title": headline,
                "url": url,
                "local_path": "",
                "note": note,
                "score": None,
                "content_status": "unfetched",
                "metadata": {"issue_number": issue["number"]},
                "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            })
            print(f"  Recorded: {headline}")

        # Close the issue
        requests.patch(
            f"{API}/repos/{REPO}/issues/{issue['number']}",
            headers=headers,
            json={"state": "closed"},
            timeout=10,
        )

    new_count = append_taste_evidence(new_records)
    print(f"Processed {new_count} new taste submission(s) from {len(issues)} issue(s).")
    return new_count


def rebuild_profile():
    """Use Claude with web_search to distill taste_profile.md from all evidence."""
    evidence = load_taste_evidence()
    exemplars = [e for e in evidence if e.get("kind") == "positive_exemplar"]
    if len(exemplars) < 3:
        print(f"Only {len(exemplars)} exemplar(s) — need 3+ to build profile. Skipping.")
        return

    # Load current profile for context
    current_profile = ""
    try:
        with open("taste_profile.md", "r") as f:
            current_profile = f.read()
    except FileNotFoundError:
        pass

    exemplar_text = ""
    for i, s in enumerate(exemplars, 1):
        exemplar_text += f"\n{i}. [{s.get('created_at', '')}] \"{s.get('title', '')}\"\n"
        if s.get("url"):
            exemplar_text += f"   URL: {s['url']}\n"
        if s.get("note"):
            exemplar_text += f"   Reader's note: {s['note']}\n"
        excerpt = s.get("metadata", {}).get("extracted_text_preview", "")
        if excerpt and not s.get("note"):
            exemplar_text += f"   Content excerpt: {excerpt[:300]}\n"

    prompt = f"""You are building a general-purpose content taste profile for a reader.

EXEMPLAR ARTICLES (articles the reader submitted as positive examples):
{exemplar_text}

CURRENT PROFILE (if any):
{current_profile}

INSTRUCTIONS:
1. Use web_search to read/understand each submitted article (search for the URL or headline).
2. Identify recurring themes, preferred depth/style, and valued qualities across all exemplars.
3. Write an updated taste_profile.md with two sections:

## Preference Summary
### Topics I Gravitate Toward
### Qualities I Value
### What I Tend to Skip
### Source & Style Affinities

## Exemplar Log
| # | Date | Headline | URL | Note | Themes |
(Include ALL exemplars with extracted themes)

CRITICAL: This profile must be GENERAL PURPOSE — do not reference daily-reads slots,
newsletter sources, or any specific curation system. This profile should be reusable
for any content curation context (articles, podcasts, videos, etc.).

Start the file with:
# Taste Profile
> General-purpose content preference model. Last updated: {datetime.now(timezone.utc).strftime('%Y-%m-%d')} ({len(exemplars)} exemplars)

Output ONLY the markdown content for taste_profile.md."""

    print("Calling Claude to rebuild taste profile...")
    client = anthropic.Anthropic()
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 10}],
        messages=[{"role": "user", "content": prompt}],
    )

    # Extract text from response
    profile_text = ""
    for block in response.content:
        if block.type == "text":
            profile_text += block.text

    if profile_text.strip():
        with open("taste_profile.md", "w", encoding="utf-8") as f:
            f.write(profile_text.strip() + "\n")
        print("taste_profile.md updated.")
    else:
        print("WARNING: No profile text generated by Claude.")


def main():
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("No GITHUB_TOKEN set — skipping taste processing")
        return

    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
    }

    new_count = harvest_issues(headers)

    # Only rebuild profile if we got new submissions
    if new_count > 0:
        rebuild_profile()

    update_learned_preferences()


if __name__ == "__main__":
    main()
