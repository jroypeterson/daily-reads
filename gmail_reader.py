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
        r"|click\.\w+\.com/unsub|view\.in\.browser|mailto:"
        # WSJ newsletter "view in browser" wrapper — returns the full email
        # HTML rather than an article. Not a skip by URL pattern elsewhere
        # because the host isn't obviously a view-in-browser host.
        r"|trk\.wsj\.com/view/"
        # Generic CampaignMonitor web-view URLs (WSJ's Ten Point uses these
        # inside Proofpoint). Path shape `/t/<token>/` at a *.cmail20.com or
        # *.createsend.com host is always the email's web copy, not an article.
        r"|cmail\d+\.com/t/"
        r"|createsend\d*\.com/t/)",
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

            # Match against sources
            source = get_source(sender_email)

            # Per-source subject whitelist: if a source specifies `subject_allow`,
            # drop any email whose subject doesn't match one of the patterns.
            # Used to filter marketing/promo emails from paid newsletters whose
            # real-content subjects follow a known shape (e.g. VII).
            if source and source.get("subject_allow"):
                patterns = source["subject_allow"]
                if not any(re.search(p, subject) for p in patterns):
                    continue

            # Extract HTML body for URL parsing
            html_body = _extract_body(msg["payload"])
            urls = extract_urls_from_html(html_body) if html_body else []
            # Resolve newsletter click-tracking redirector URLs (BioSpace,
            # SendGrid, etc.) to their canonical destinations. No-op for
            # URLs that aren't on known redirector hosts.
            if urls:
                from url_resolver import resolve_urls
                urls = resolve_urls(urls)
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


def _pick_substack_post_url(urls: list[str]) -> str | None:
    """Pick the canonical post URL from a Substack email's link list.

    Substack emails contain many wrapper/app-link/reaction URLs. The real post
    URL typically lives on the publication's domain and has a `/p/<slug>` path
    (or a custom-domain equivalent). Fall back to the first http(s) link that
    isn't an app-link/share URL.
    """
    fallback = None
    for url in urls:
        try:
            parsed = urlsplit(url)
        except ValueError:
            continue
        if parsed.scheme not in {"http", "https"}:
            continue
        host = parsed.netloc.lower()
        path = parsed.path
        if "app-link" in path or path.startswith("/api/") or "/action/" in path:
            continue
        if host.endswith("substack.com") and "/p/" in path:
            return url
        if host.endswith("substack.com") and path.startswith("/p/"):
            return url
        if not host.endswith("substack.com") and "/p/" in path:
            # custom-domain Substack post
            return url
        if fallback is None:
            fallback = url
    return fallback


def fetch_substack_emails(hours_back: int = 26) -> list[dict]:
    """Fetch all @substack.com emails in the window, regardless of sources.py.

    Used to render the daily digest's Substack section so the user can spot
    newsletters worth promoting to always_read.

    Returns list of dicts with keys: sender_name, sender_email, subject, url, date.
    """
    service = get_gmail_service()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)
    date_query = cutoff.strftime("%Y/%m/%d")
    query = f"after:{date_query} from:substack.com"

    results: list[dict] = []
    page_token = None
    while True:
        resp = service.users().messages().list(
            userId="me", q=query, maxResults=100, pageToken=page_token
        ).execute()

        for msg_stub in resp.get("messages", []):
            msg = service.users().messages().get(
                userId="me", id=msg_stub["id"], format="full"
            ).execute()
            headers = {h["name"].lower(): h["value"] for h in msg["payload"]["headers"]}
            sender_raw = headers.get("from", "")
            sender_name, sender_email = parseaddr(sender_raw)
            sender_email = sender_email.lower()
            if not sender_email.endswith("@substack.com"):
                continue

            subject = headers.get("subject", "(no subject)")
            date_str = headers.get("date", "")

            html_body = _extract_body(msg["payload"])
            urls = extract_urls_from_html(html_body) if html_body else []
            post_url = _pick_substack_post_url(urls) if urls else None

            results.append({
                "sender_name": sender_name or sender_email,
                "sender_email": sender_email,
                "subject": subject,
                "url": post_url or "",
                "date": date_str,
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
