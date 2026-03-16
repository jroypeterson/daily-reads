"""Gmail API module for fetching newsletter emails."""

import base64
import json
import os
import re
from datetime import datetime, timedelta, timezone
from email.utils import parseaddr

from bs4 import BeautifulSoup
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from sources import get_source, get_all_sender_emails


def get_gmail_service():
    """Build Gmail API service from GMAIL_OAUTH_JSON env var."""
    token_json = os.environ["GMAIL_OAUTH_JSON"]
    token_data = json.loads(token_json)
    creds = Credentials.from_authorized_user_info(token_data)
    return build("gmail", "v1", credentials=creds)


def extract_urls_from_html(html: str) -> list[str]:
    """Extract article URLs from HTML email body."""
    soup = BeautifulSoup(html, "html.parser")
    urls = []
    skip_patterns = re.compile(
        r"(unsubscribe|manage.preferences|email-preferences|list-manage|mailchimp"
        r"|click\.\w+\.com/unsub|view\.in\.browser|mailto:)",
        re.IGNORECASE,
    )
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith("http") and not skip_patterns.search(href):
            if href not in urls:
                urls.append(href)
    return urls


def fetch_newsletters(hours_back: int = 26) -> list[dict]:
    """Fetch newsletter emails from the last N hours.

    Returns list of dicts with keys:
        sender, sender_email, subject, snippet, date, urls,
        source_name, tier, category, priority
    """
    service = get_gmail_service()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)
    date_query = cutoff.strftime("%Y/%m/%d")

    # Build OR query for all tracked senders
    sender_emails = get_all_sender_emails()
    from_clauses = " OR ".join(f"from:{e}" for e in sender_emails)
    query = f"after:{date_query} ({from_clauses})"

    results = []
    page_token = None

    while True:
        resp = service.users().messages().list(
            userId="me", q=query, maxResults=100, pageToken=page_token
        ).execute()

        messages = resp.get("messages", [])
        for msg_stub in messages:
            msg = service.users().messages().get(
                userId="me", id=msg_stub["id"], format="full"
            ).execute()

            headers = {h["name"].lower(): h["value"] for h in msg["payload"]["headers"]}
            sender_raw = headers.get("from", "")
            _, sender_email = parseaddr(sender_raw)
            sender_email = sender_email.lower()

            subject = headers.get("subject", "(no subject)")
            date_str = headers.get("date", "")
            snippet = msg.get("snippet", "")

            # Extract HTML body for URL parsing
            html_body = _extract_body(msg["payload"])
            urls = extract_urls_from_html(html_body) if html_body else []

            # Match against sources
            source = get_source(sender_email)
            results.append({
                "sender": sender_raw,
                "sender_email": sender_email,
                "subject": subject,
                "snippet": snippet,
                "date": date_str,
                "urls": urls[:20],  # cap to avoid noise
                "source_name": source["name"] if source else "Unknown",
                "tier": source["tier"] if source else 0,
                "category": source["category"] if source else "unknown",
                "priority": source["priority"] if source else "normal",
            })

        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    return results


def _extract_body(payload: dict) -> str | None:
    """Recursively extract HTML body from Gmail payload."""
    if payload.get("mimeType") == "text/html":
        data = payload.get("body", {}).get("data", "")
        if data:
            return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")

    for part in payload.get("parts", []):
        result = _extract_body(part)
        if result:
            return result
    return None
