"""Gmail API module for fetching newsletter emails."""

import base64
import json
import os
import re
from datetime import datetime, timedelta, timezone
from email.utils import parseaddr
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from sources import get_source, get_all_sender_emails

TRACKING_QUERY_PREFIXES = (
    "utm_",
    "fbclid",
    "gclid",
    "mc_",
    "mkt_",
    "oly_",
    "_hs",
    "vero_",
    "mbid",
    "cmpid",
)
NON_ARTICLE_PATH_PATTERNS = re.compile(
    r"/(unsubscribe|account|profile|preferences|settings|subscribe|login|signup|share|podcast|events?|jobs?|careers?|advertis|privacy|terms)(/|$)",
    re.IGNORECASE,
)
NON_ARTICLE_HOST_PATTERNS = re.compile(
    r"(mailchi\.mp|substack\.com/api/|lnkd\.in|twitter\.com/share|facebook\.com/sharer)",
    re.IGNORECASE,
)


def get_gmail_service():
    """Build Gmail API service from GMAIL_OAUTH_JSON env var."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    token_json = os.environ["GMAIL_OAUTH_JSON"]
    token_data = json.loads(token_json)
    creds = Credentials.from_authorized_user_info(token_data)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return build("gmail", "v1", credentials=creds)


def clean_url(url: str) -> str:
    """Strip fragments and common tracking params while preserving core article identity."""
    parsed = urlsplit((url or "").strip())
    query_items = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith(TRACKING_QUERY_PREFIXES)
    ]
    path = parsed.path.rstrip("/") or "/"
    return urlunsplit((
        parsed.scheme.lower(),
        parsed.netloc.lower(),
        path,
        urlencode(query_items, doseq=True),
        "",
    ))


def is_probable_article_url(url: str) -> bool:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"}:
        return False
    if NON_ARTICLE_HOST_PATTERNS.search(url):
        return False
    if NON_ARTICLE_PATH_PATTERNS.search(parsed.path):
        return False
    if parsed.path in {"", "/"}:
        return False
    return True


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
        if not href.startswith("http") or skip_patterns.search(href):
            continue
        cleaned = clean_url(href)
        if is_probable_article_url(cleaned) and cleaned not in urls:
            urls.append(cleaned)
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
