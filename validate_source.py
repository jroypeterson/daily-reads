"""Validate and discover newsletter source addresses against Gmail.

Usage:
    # Discover the real sender address for a newsletter
    python validate_source.py "stratechery"
    python validate_source.py "morning brew"

    # Audit all active sources in sources.py against Gmail
    python validate_source.py --audit

    # Audit mode used by CI (outputs warnings, non-zero exit on stale sources)
    python validate_source.py --audit --ci
"""

import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from email.utils import parseaddr

from sources import SOURCES


def get_gmail_service():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    token_json = os.environ["GMAIL_OAUTH_JSON"]
    token_data = json.loads(token_json)
    creds = Credentials.from_authorized_user_info(token_data)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return build("gmail", "v1", credentials=creds)


def gmail_search(service, query: str, max_results: int = 20) -> list[dict]:
    """Search Gmail and return message headers."""
    resp = service.users().messages().list(
        userId="me", q=query, maxResults=max_results
    ).execute()
    messages = []
    for stub in resp.get("messages", []):
        msg = service.users().messages().get(
            userId="me", id=stub["id"], format="metadata",
            metadataHeaders=["From", "Subject", "Date"],
        ).execute()
        headers = {h["name"].lower(): h["value"] for h in msg["payload"]["headers"]}
        _, sender_email = parseaddr(headers.get("from", ""))
        messages.append({
            "from_raw": headers.get("from", ""),
            "sender_email": sender_email.lower(),
            "subject": headers.get("subject", ""),
            "date": headers.get("date", ""),
        })
    return messages


def discover(keyword: str):
    """Search Gmail for a keyword and show sender addresses found."""
    service = get_gmail_service()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y/%m/%d")
    query = f"after:{cutoff} {keyword}"
    print(f"Searching Gmail for: {query}\n")

    messages = gmail_search(service, query, max_results=30)
    if not messages:
        print("  No emails found. Check your spelling or look further back.")
        return

    # Tally sender addresses
    sender_counts = Counter()
    sender_examples = {}
    for msg in messages:
        addr = msg["sender_email"]
        sender_counts[addr] += 1
        if addr not in sender_examples:
            sender_examples[addr] = msg

    print(f"Found {len(messages)} emails. Sender addresses:\n")
    for addr, count in sender_counts.most_common():
        example = sender_examples[addr]
        in_sources = "  [ALREADY IN sources.py]" if addr in SOURCES else ""
        print(f"  {addr}  ({count} emails){in_sources}")
        print(f"    From: {example['from_raw']}")
        print(f"    Example: {example['subject']}")
        print()

    # Suggest what to add
    missing = [addr for addr in sender_counts if addr not in SOURCES]
    if missing:
        print("--- Addresses NOT in sources.py ---")
        for addr in missing:
            print(f"  {addr}")
        print("\nAdd the relevant address(es) to sources.py with the correct metadata.")
    else:
        print("All discovered addresses are already in sources.py.")


def audit(ci_mode: bool = False):
    """Check every source in sources.py against recent Gmail activity."""
    service = get_gmail_service()
    cutoff_7d = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y/%m/%d")
    cutoff_30d = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y/%m/%d")

    print(f"Auditing {len(SOURCES)} sources against Gmail...\n")

    ok = []
    stale = []
    dead = []

    for email_addr, source in SOURCES.items():
        name = source["name"]
        # Check last 7 days first
        query_7d = f"after:{cutoff_7d} from:{email_addr}"
        msgs_7d = gmail_search(service, query_7d, max_results=1)
        if msgs_7d:
            ok.append((name, email_addr, "recent"))
            continue

        # Fall back to 30 days
        query_30d = f"after:{cutoff_30d} from:{email_addr}"
        msgs_30d = gmail_search(service, query_30d, max_results=1)
        if msgs_30d:
            stale.append((name, email_addr, msgs_30d[0]["date"]))
        else:
            dead.append((name, email_addr))

    # Report
    print(f"OK ({len(ok)}):")
    for name, addr, _ in ok:
        print(f"  {name:30s} {addr}")

    if stale:
        print(f"\nSTALE — no email in 7 days, last seen within 30 ({len(stale)}):")
        for name, addr, last_date in stale:
            print(f"  {name:30s} {addr}")
            print(f"    Last seen: {last_date}")

    if dead:
        print(f"\nDEAD — no email in 30 days ({len(dead)}):")
        for name, addr in dead:
            print(f"  {name:30s} {addr}")
        print("\n  These may have wrong addresses or you may not be subscribed.")

    if ci_mode and (stale or dead):
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Validate newsletter sources against Gmail"
    )
    parser.add_argument(
        "keyword", nargs="?",
        help="Search term to discover sender addresses (e.g. 'stratechery')"
    )
    parser.add_argument(
        "--audit", action="store_true",
        help="Audit all sources in sources.py against recent Gmail"
    )
    parser.add_argument(
        "--ci", action="store_true",
        help="CI mode: exit non-zero if stale/dead sources found"
    )
    args = parser.parse_args()

    if args.audit:
        audit(ci_mode=args.ci)
    elif args.keyword:
        discover(args.keyword)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
