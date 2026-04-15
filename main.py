"""Daily Reads — Main orchestration script."""

import json
import os
import re
import sys
from difflib import ndiff
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

import anthropic
import requests

from gmail_reader import fetch_newsletters, fetch_substack_emails
from url_resolver import check_urls_live
from project_data import (
    article_id_for,
    candidate_artifact_path,
    load_json,
    run_artifact_path,
    save_json,
    triage_artifact_path,
)
from sources import SOURCES, get_always_read_names

REPO = "jroypeterson/daily-reads"
CRITERIA_STATE_PATH = "criteria_update_state.json"
PROPOSED_CRITERIA_PATH = "selection_criteria_proposed.md"
CRITERIA_WEB_URL = f"https://github.com/{REPO}/blob/main/{PROPOSED_CRITERIA_PATH}"
LEARNED_PREFERENCES_JSON_PATH = "learned_preferences.json"
LEARNED_PREFERENCES_MD_PATH = "learned_preferences.md"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def section(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}\n")


def feedback_url(date: str, slot: int, score: int, headline: str) -> str:
    """Generate a pre-filled GitHub Issue URL for one-tap feedback."""
    truncated = headline[:80]
    title = f"Feedback: {date} slot{slot} score{score}"
    body = f"Article: {truncated}\n\nOptional note: "
    params = urlencode({"labels": "feedback", "title": title, "body": body})
    return f"https://github.com/{REPO}/issues/new?{params}"


def slack_mailto_feedback_url(date: str, slot: int, score: int) -> str:
    """Generate a mailto link that opens a prefilled feedback draft."""
    params = urlencode(
        {
            "subject": f"Daily Reads feedback {date}",
            "body": f"{slot} {score}",
        }
    )
    return f"mailto:jroypeterson@gmail.com?{params}"


def load_criteria_state() -> dict:
    state = load_json(CRITERIA_STATE_PATH, None)
    if not isinstance(state, dict):
        return {"pending": None, "history": []}
    state.setdefault("pending", None)
    state.setdefault("history", [])
    return state


def save_criteria_state(state: dict):
    save_json(CRITERIA_STATE_PATH, state)


def criteria_issue_url(action: str, proposal_id: str) -> str:
    title = f"Criteria Update: {action} {proposal_id}"
    if action == "modify":
        body = (
            f"Proposal ID: {proposal_id}\n\n"
            "Requested changes:\n"
        )
    else:
        body = (
            f"Proposal ID: {proposal_id}\n\n"
            f"Action: {action}\n"
        )
    params = urlencode({"labels": "criteria-update", "title": title, "body": body})
    return f"https://github.com/{REPO}/issues/new?{params}"


def send_gmail_html(subject: str, html: str):
    import base64
    from email.mime.text import MIMEText
    from gmail_reader import get_gmail_service

    service = get_gmail_service()
    msg = MIMEText(html, "html")
    msg["to"] = "jroypeterson@gmail.com"
    msg["subject"] = subject
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    service.users().messages().send(userId="me", body={"raw": raw}).execute()


def notify_criteria_update(proposal: dict):
    summary_items = proposal.get("summary", [])
    summary_html = "".join(f"<li>{item}</li>" for item in summary_items)
    summary_text = "\n".join(f"• {item}" for item in summary_items)
    diff_lines = proposal.get("diff_lines", [])
    diff_html = "".join(
        f"<li><code>{line}</code></li>"
        for line in diff_lines
    ) or "<li><code>No concrete line-level diff available.</code></li>"
    diff_text = "\n".join(f"• {line}" for line in diff_lines) or "• No concrete line-level diff available."
    accept_url = criteria_issue_url("accept", proposal["proposal_id"])
    reject_url = criteria_issue_url("reject", proposal["proposal_id"])
    modify_url = criteria_issue_url("modify", proposal["proposal_id"])

    subject = f"Criteria Update Proposed — {proposal['proposal_id']}"
    html = f"""<html><body style="font-family: -apple-system, sans-serif; max-width: 640px; margin: 0 auto; color: #222; padding: 20px;">
<h1>Criteria Update Proposed</h1>
<p><strong>Proposal ID:</strong> {proposal['proposal_id']}</p>
<p><strong>Trigger:</strong> {proposal.get('trigger', 'feedback threshold reached')}</p>
<p><strong>Summary of changes:</strong></p>
<ul>{summary_html}</ul>
<p><strong>Concrete diff highlights:</strong></p>
<ul>{diff_html}</ul>
<p><a href="{CRITERIA_WEB_URL}">Review proposed criteria file</a></p>
<p>
  <a href="{accept_url}">Accept</a>
  &nbsp;|&nbsp;
  <a href="{reject_url}">Reject</a>
  &nbsp;|&nbsp;
  <a href="{modify_url}">Request modifications</a>
</p>
</body></html>"""

    try:
        send_gmail_html(subject, html)
        print("Criteria update email notification sent")
    except Exception as e:
        print(f"Criteria update email notification failed: {e}")

    webhook_url = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook_url:
        print("No SLACK_WEBHOOK_URL set — skipping criteria Slack notification")
        return

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": "Criteria Update Proposed"}},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*Proposal ID:* {proposal['proposal_id']}\n"
                    f"*Trigger:* {proposal.get('trigger', 'feedback threshold reached')}\n\n"
                    f"{summary_text or 'No summary generated.'}\n\n"
                    f"*Diff highlights:*\n{diff_text}"
                ),
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"<{CRITERIA_WEB_URL}|Review proposed criteria>  "
                    f"<{accept_url}|Accept>  "
                    f"<{reject_url}|Reject>  "
                    f"<{modify_url}|Request modifications>"
                ),
            },
        },
    ]

    try:
        resp = requests.post(webhook_url, json={"blocks": blocks}, timeout=10)
        resp.raise_for_status()
        print("Criteria update Slack notification sent")
    except Exception as e:
        print(f"Criteria update Slack notification failed: {e}")


def load_learned_preferences_summary() -> str:
    prefs = load_json(LEARNED_PREFERENCES_JSON_PATH, {})
    if not isinstance(prefs, dict):
        return ""

    # v2 structured preferences
    if prefs.get("version") == 2:
        parts = []

        def render_section(prefs_list, label, direction_filter=None):
            items = prefs_list or []
            if direction_filter:
                items = [p for p in items if p.get("direction") == direction_filter]
            if not items:
                return
            by_strength = {}
            for p in items:
                strength = p.get("strength", "weak")
                by_strength.setdefault(strength, []).append(p)
            for strength in ("strong", "moderate", "weak"):
                group = by_strength.get(strength, [])
                if not group:
                    continue
                parts.append(f"{strength.upper()} {label}:")
                for p in group:
                    evidence_count = len(p.get("evidence_ids", []))
                    parts.append(f"- {p.get('name', '?')} ({evidence_count} evidence points)")

        render_section(prefs.get("topic_preferences"), "topic preferences", "positive")
        render_section(prefs.get("source_preferences"), "source preferences", "positive")
        render_section(prefs.get("style_preferences"), "style preferences", "positive")

        avoid = prefs.get("avoid_patterns", [])
        if avoid:
            parts.append("AVOID patterns:")
            for p in avoid:
                parts.append(f"- {p.get('name', '?')}")

        # Add recent exemplars from taste evidence for concrete examples
        from project_data import load_taste_evidence
        evidence = load_taste_evidence()
        positive = [e for e in evidence if e.get("kind") in ("positive_exemplar", "daily_rating_3")]
        positive.sort(key=lambda e: e.get("created_at", ""))
        for entry in positive[-3:]:
            line = f"Exemplar ({entry.get('source_channel', '?')}): \"{entry.get('title', 'Untitled')}\""
            if entry.get("note"):
                line += f" — {entry['note']}"
            elif entry.get("metadata", {}).get("extracted_text_preview"):
                line += f" — {entry['metadata']['extracted_text_preview'][:180]}"
            parts.append(line)

        misses = [e for e in evidence if e.get("kind") == "daily_rating_1"]
        misses.sort(key=lambda e: e.get("created_at", ""))
        for entry in misses[-2:]:
            line = f"Recent miss ({entry.get('source_channel', '?')}): \"{entry.get('title', 'Untitled')}\""
            if entry.get("note"):
                line += f" — {entry['note']}"
            parts.append(line)

        return "\n".join(parts)

    # v1 fallback
    narrative = prefs.get("narrative_summary", {})
    parts = []
    for key in ("topics", "qualities", "avoid", "sources"):
        value = str(narrative.get(key, "")).strip()
        if value and "Not enough data yet" not in value:
            parts.append(value)
    recent_examples = prefs.get("recent_examples", [])
    example_lines = []
    for example in recent_examples[:3]:
        headline = str(example.get("headline", "")).strip()
        source_channel = str(example.get("source_channel", "")).strip()
        note = str(example.get("note", "")).strip()
        excerpt = str(example.get("excerpt", "")).strip()
        if headline:
            line = f"Exemplar ({source_channel or 'unknown'}): {headline}"
            if note:
                line += f" — {note}"
            elif excerpt:
                line += f" — {excerpt[:180]}"
            example_lines.append(line)
    if example_lines:
        parts.append("Recent positive exemplars:\n" + "\n".join(example_lines))
    return "\n".join(parts)


def build_criteria_diff_lines(current: str, proposed: str, limit: int = 8) -> list[str]:
    """Summarize concrete added/removed lines between active and proposed criteria."""
    diff_lines = []
    for line in ndiff(current.splitlines(), proposed.splitlines()):
        if line.startswith("? "):
            continue
        if line.startswith("- ") or line.startswith("+ "):
            text = line[2:].strip()
            if not text:
                continue
            prefix = "Removed" if line.startswith("- ") else "Added"
            diff_lines.append(f"{prefix}: {text}")
        if len(diff_lines) >= limit:
            break
    return diff_lines


def normalize_candidate(candidate: dict, source_type: str, run_date: str, ordinal: int) -> dict:
    urls = candidate.get("urls") or []
    primary_url = urls[0] if urls else ""
    source_name = candidate.get("source_name", "Unknown")
    headline = candidate.get("subject") or candidate.get("snippet") or "(untitled)"
    candidate_id = article_id_for(
        primary_url or f"{source_type}:{source_name}:{headline}:{ordinal}",
        source_name,
    )
    return {
        "candidate_id": candidate_id,
        "run_date": run_date,
        "source_type": source_type,
        "source_name": source_name,
        "headline": headline,
        "snippet": candidate.get("snippet", ""),
        "primary_url": primary_url,
        "urls": urls[:5],
        "category": candidate.get("category", "unknown"),
        "priority": candidate.get("priority", "normal"),
        "tier": candidate.get("tier", 0),
        "score": candidate.get("score"),
        "sender_email": candidate.get("sender_email"),
        "sender": candidate.get("sender"),
        "published_at": candidate.get("date"),
    }


def extract_candidate_signals(candidate: dict, ticker_lookup: set[str],
                              company_lookup: dict[str, str] | None = None,
                              ticker_details: dict[str, dict] | None = None) -> list[str]:
    text = " ".join(
        str(candidate.get(field, ""))
        for field in ("headline", "snippet", "source_name", "category")
    )
    # Match ticker symbols
    tokens = set(re.findall(r"\b[A-Z]{2,6}\b", text.upper()))
    ticker_hits = sorted(token for token in tokens if token in ticker_lookup)[:3]

    # Match company names in headlines
    if company_lookup:
        text_lower = text.lower()
        for name, ticker in company_lookup.items():
            if len(name) >= 5 and name in text_lower:
                base = ticker.split(".")[0].upper()
                if base not in ticker_hits:
                    ticker_hits.append(base)
                    if len(ticker_hits) >= 5:
                        break

    signals = []
    if candidate.get("priority") == "high":
        signals.append("priority:high")
    if candidate.get("source_type") == "gmail":
        signals.append("source_type:gmail")
    if candidate.get("source_type") == "tier2":
        signals.append("source_type:tier2")
    if candidate.get("score"):
        signals.append(f"hn_score:{candidate['score']}")
    if candidate.get("category"):
        signals.append(f"category:{candidate['category']}")
    signals.extend(f"ticker:{ticker}" for ticker in ticker_hits)

    # Add subsector tags from matched tickers
    if ticker_details and ticker_hits:
        subsectors_seen = set()
        for ticker in ticker_hits:
            detail = ticker_details.get(ticker) or ticker_details.get(ticker.upper())
            if detail and detail.get("subsector") and detail["subsector"] not in subsectors_seen:
                signals.append(f"subsector:{detail['subsector']}")
                subsectors_seen.add(detail["subsector"])

    return signals


def build_structured_candidates(
    gmail_items: list[dict],
    tier2_items: list[dict],
    run_date: str,
    tickers: dict,
) -> tuple[list[dict], list[dict]]:
    ticker_lookup = {
        str(ticker).upper()
        for bucket in ("healthcare", "tech", "other")
        for ticker in tickers.get(bucket, [])
        if isinstance(ticker, str)
    }
    company_lookup = tickers.get("company_lookup") or {}
    ticker_details = tickers.get("details") or {}

    normalized_gmail = [
        normalize_candidate(item, "gmail", run_date, index)
        for index, item in enumerate(gmail_items, 1)
    ]
    normalized_tier2 = [
        normalize_candidate(item, "tier2", run_date, index)
        for index, item in enumerate(tier2_items, 1)
    ]

    for candidate in normalized_gmail + normalized_tier2:
        candidate["derived_signals"] = extract_candidate_signals(
            candidate, ticker_lookup, company_lookup, ticker_details,
        )

    return normalized_gmail, normalized_tier2


def score_candidate_for_triage(candidate: dict) -> int:
    score = 0
    if candidate.get("source_type") == "gmail":
        score += 3
    if candidate.get("priority") == "high":
        score += 2
    if candidate.get("tier") == 1:
        score += 2
    score += len([signal for signal in candidate.get("derived_signals", []) if signal.startswith("ticker:")]) * 2
    if candidate.get("score"):
        score += min(int(candidate["score"]) // 50, 3)
    return score


INTEREST_BUCKETS = {
    "healthcare": {"healthcare_daily", "healthcare_weekly", "healthcare_policy"},
    "finance_macro": {"finance_macro"},
    "tech_ai": {"tech_ai"},
    "broad_curious": {"broad_curious"},
}


def _category_to_bucket(category: str) -> str:
    for bucket, categories in INTEREST_BUCKETS.items():
        if category in categories:
            return bucket
    return "other"


def build_triage_queue(
    structured_gmail: list[dict],
    structured_tier2: list[dict],
    selected_articles: list[dict],
    limit: int = 10,
) -> list[dict]:
    selected_urls = {article.get("url") for article in selected_articles}
    always_read_names = get_always_read_names()
    scored = []
    for candidate in structured_gmail + structured_tier2:
        if candidate.get("primary_url") in selected_urls:
            continue
        if candidate.get("source_name", "") in always_read_names:
            continue
        # Skip candidates whose links were dropped as dead-end redirectors
        # (e.g. McKinsey/Atlantic tokens that resolve to publisher homepage
        # or ad-tracker). A "# → nowhere" link in the digest is worse than
        # omitting the candidate.
        if not candidate.get("primary_url"):
            continue
        scored.append({
            **candidate,
            "triage_score": score_candidate_for_triage(candidate),
        })

    scored.sort(
        key=lambda candidate: (
            -candidate.get("triage_score", 0),
            candidate.get("source_name", ""),
            candidate.get("headline", ""),
        )
    )

    # Ensure at least one candidate from each major interest bucket
    queue = []
    buckets_covered = set()
    # First pass: pick the top candidate per bucket
    for candidate in scored:
        bucket = _category_to_bucket(candidate.get("category", "unknown"))
        if bucket not in buckets_covered:
            queue.append(candidate)
            buckets_covered.add(bucket)
    # Second pass: fill remaining slots by score
    for candidate in scored:
        if len(queue) >= limit:
            break
        if candidate not in queue:
            queue.append(candidate)

    return queue[:limit]


def build_always_read(
    structured_gmail: list[dict],
    selected_articles: list[dict],
) -> list[dict]:
    """Extract candidates from always-read paid sources."""
    always_read_names = get_always_read_names()
    if not always_read_names:
        return []
    selected_urls = {a.get("url") for a in selected_articles}
    results = []
    for candidate in structured_gmail:
        source_name = candidate.get("source_name", "")
        if source_name not in always_read_names:
            continue
        if candidate.get("primary_url") in selected_urls:
            continue
        # Drop URL-less candidates (dead-end redirector) — see build_triage_queue.
        if not candidate.get("primary_url"):
            continue
        results.append(candidate)
    return results


def validate_delivery_urls(
    articles: list[dict],
    triage_queue: list[dict],
    always_read: list[dict],
    substack_items: list[dict],
) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    """Probe every URL that is about to ship. Drops broken URLs from
    triage/always_read/substack lists. For main-slot articles (which are
    load-bearing — dropping one would leave an empty slot), logs a loud
    warning but keeps the article so the digest still goes out.

    Uses `url_resolver.check_urls_live` which treats 404/410 and
    connection errors as broken but keeps 401/403/timeouts (paywalled or
    bot-walled sites that work fine in the user's browser).
    """
    section("DELIVERY URL VALIDATION")

    # Gather every URL we're about to ship, with its source surface.
    # (surface, index, url)
    urls_to_check: list[tuple[str, int, str]] = []
    for i, a in enumerate(articles):
        url = (a.get("url") or "").strip()
        if url:
            urls_to_check.append(("article", i, url))
    for i, c in enumerate(triage_queue):
        url = (c.get("primary_url") or "").strip()
        if url:
            urls_to_check.append(("triage", i, url))
    for i, c in enumerate(always_read):
        url = (c.get("primary_url") or "").strip()
        if url:
            urls_to_check.append(("always_read", i, url))
    for i, item in enumerate(substack_items):
        url = (item.get("url") or "").strip()
        if url:
            urls_to_check.append(("substack", i, url))

    unique_urls = list({url for _, _, url in urls_to_check})
    if not unique_urls:
        print("No URLs to validate.")
        return articles, triage_queue, always_read, substack_items

    print(f"Probing {len(unique_urls)} unique URLs across {len(urls_to_check)} slots...")
    liveness = check_urls_live(unique_urls, timeout=3)

    broken_articles: list[int] = []
    broken_triage: set[int] = set()
    broken_always_read: set[int] = set()
    broken_substack: set[int] = set()
    for surface, idx, url in urls_to_check:
        if liveness.get(url, True):
            continue
        if surface == "article":
            broken_articles.append(idx)
        elif surface == "triage":
            broken_triage.add(idx)
        elif surface == "always_read":
            broken_always_read.add(idx)
        elif surface == "substack":
            broken_substack.add(idx)

    for idx in broken_articles:
        a = articles[idx]
        print(
            f"  WARNING: main slot {a.get('slot', '?')} URL is broken — "
            f"shipping anyway to preserve slot. Headline: {a.get('headline', '')[:60]}"
        )
        print(f"    URL: {a.get('url', '')}")

    def _filter(items: list[dict], dropped: set[int], label: str) -> list[dict]:
        if not dropped:
            return items
        for idx in sorted(dropped):
            c = items[idx]
            headline = c.get("headline") or c.get("subject", "Untitled")
            print(f"  Dropping {label}: {headline[:60]} — URL failed liveness probe")
        return [c for i, c in enumerate(items) if i not in dropped]

    triage_queue = _filter(triage_queue, broken_triage, "triage")
    always_read = _filter(always_read, broken_always_read, "always-read")
    substack_items = _filter(substack_items, broken_substack, "substack")

    total_broken = (
        len(broken_articles) + len(broken_triage)
        + len(broken_always_read) + len(broken_substack)
    )
    if total_broken == 0:
        print("All URLs passed liveness check.")
    else:
        print(
            f"Summary: {total_broken} broken URL(s) detected "
            f"({len(broken_articles)} main warnings, "
            f"{len(broken_triage)} triage dropped, "
            f"{len(broken_always_read)} always-read dropped, "
            f"{len(broken_substack)} substack dropped)."
        )

    # Append this run's validation counts to the log so the Friday weekly
    # report can surface URL-health trends.
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    log_path = "artifacts/url_validation_log.json"
    log = load_json(log_path, [])
    log.append({
        "date": today,
        "checked_unique": len(unique_urls),
        "checked_slots": len(urls_to_check),
        "broken": {
            "article_warnings": len(broken_articles),
            "triage_dropped": len(broken_triage),
            "always_read_dropped": len(broken_always_read),
            "substack_dropped": len(broken_substack),
        },
        # Main-slot warnings keep their slot in the digest but we log detail
        # so the weekly report can name which sources are shipping broken URLs.
        "warned_articles": [
            {
                "source": articles[i].get("source", ""),
                "headline": (articles[i].get("headline") or "")[:120],
                "url": articles[i].get("url", ""),
            }
            for i in broken_articles
        ],
    })
    save_json(log_path, log)
    print(f"Logged validation stats to {log_path}")

    return articles, triage_queue, always_read, substack_items


def validate_selected_articles(articles: list[dict]) -> list[dict]:
    """Enforce structural rules before delivering a digest."""
    required_slots = {1, 2, 3}
    allowed_slots = {1, 2, 3, 4}
    required_fields = ("headline", "source", "url", "slot", "summary", "why_it_matters")

    validated = []
    seen_slots = set()
    seen_sources = set()

    for index, raw_article in enumerate(articles, 1):
        if not isinstance(raw_article, dict):
            print(f"  Rejecting article #{index}: not an object")
            continue

        article = {key: raw_article.get(key) for key in required_fields}
        missing = [field for field, value in article.items() if value in (None, "", [])]
        if missing:
            print(f"  Rejecting article #{index}: missing {', '.join(missing)}")
            continue

        try:
            slot = int(article["slot"])
        except (TypeError, ValueError):
            print(f"  Rejecting article #{index}: invalid slot {article['slot']!r}")
            continue

        if slot not in allowed_slots:
            print(f"  Rejecting article #{index}: slot {slot} is out of range")
            continue
        if slot in seen_slots:
            print(f"  Rejecting article #{index}: duplicate slot {slot}")
            continue

        source = str(article["source"]).strip()
        normalized_source = source.casefold()
        if normalized_source in seen_sources:
            print(f"  Rejecting article #{index}: duplicate source {source}")
            continue

        url = str(article["url"]).strip()
        if not re.match(r"^https?://", url):
            print(f"  Rejecting article #{index}: invalid URL {url!r}")
            continue

        signal_tags = raw_article.get("signal_tags", [])
        if not isinstance(signal_tags, list):
            signal_tags = [str(signal_tags)]

        validated.append({
            "article_id": article_id_for(url, source),
            "headline": str(article["headline"]).strip(),
            "source": source,
            "url": url,
            "slot": slot,
            "summary": str(article["summary"]).strip(),
            "why_it_matters": str(article["why_it_matters"]).strip(),
            "signal_tags": [str(tag).strip() for tag in signal_tags if str(tag).strip()],
            "reading_time": str(raw_article.get("reading_time", "N/A")).strip() or "N/A",
        })
        seen_slots.add(slot)
        seen_sources.add(normalized_source)

        if len(validated) == 4:
            break

    present_slots = {article["slot"] for article in validated}
    missing_required_slots = sorted(required_slots - present_slots)
    if missing_required_slots:
        print(
            "Validation failed: missing required slot(s): "
            + ", ".join(str(slot) for slot in missing_required_slots)
        )
        return []

    return sorted(validated, key=lambda article: article["slot"])


# ---------------------------------------------------------------------------
# [GMAIL SCAN]
# ---------------------------------------------------------------------------

def gmail_scan() -> list[dict]:
    section("GMAIL SCAN")
    try:
        items = fetch_newsletters(hours_back=26)
        print(f"Found {len(items)} newsletter emails")
        sources_found = set(i["source_name"] for i in items)
        for s in sorted(sources_found):
            count = sum(1 for i in items if i["source_name"] == s)
            print(f"  - {s}: {count} email(s)")
        return items
    except Exception as e:
        print(f"Gmail scan failed: {e}")
        print("Continuing with Tier 2 sources only...")
        return []


def substack_scan() -> list[dict]:
    section("SUBSTACK SCAN")
    try:
        items = fetch_substack_emails(hours_back=26)
        # Deduplicate by (sender_email, subject) — Substack occasionally
        # resends; keep the first we saw.
        seen: set[tuple[str, str]] = set()
        unique: list[dict] = []
        for item in items:
            key = (item.get("sender_email", ""), item.get("subject", ""))
            if key in seen:
                continue
            seen.add(key)
            unique.append(item)
        unique.sort(key=lambda i: i.get("sender_name", "").lower())
        print(f"Found {len(unique)} Substack email(s) in last 26h")
        for item in unique:
            print(f"  - {item.get('sender_name', '')}: {item.get('subject', '')}")
        return unique
    except Exception as e:
        print(f"Substack scan failed: {e}")
        return []


# ---------------------------------------------------------------------------
# [TIER2 SCAN]
# ---------------------------------------------------------------------------

def tier2_scan() -> list[dict]:
    section("TIER2 SCAN")
    items = []

    # Hacker News top stories
    print("Fetching Hacker News top stories...")
    try:
        resp = requests.get(
            "https://hacker-news.firebaseio.com/v0/topstories.json", timeout=10
        )
        top_ids = resp.json()[:30]
        for story_id in top_ids:
            story = requests.get(
                f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json",
                timeout=5,
            ).json()
            if story and story.get("url"):
                items.append({
                    "source_name": "Hacker News",
                    "subject": story.get("title", ""),
                    "snippet": story.get("title", ""),
                    "urls": [story["url"]],
                    "tier": 2,
                    "category": "tech_ai",
                    "priority": "normal",
                    "score": story.get("score", 0),
                })
        print(f"  Got {len(items)} HN stories")
    except Exception as e:
        print(f"  HN fetch failed: {e}")

    return items


def rss_scan() -> list[dict]:
    section("RSS SCAN")
    try:
        from rss_feeds import fetch_rss_feeds
        items = fetch_rss_feeds()
        print(f"  Got {len(items)} RSS items")
        return items
    except Exception as e:
        print(f"  RSS scan failed: {e}")
        return []


# ---------------------------------------------------------------------------
# [FEEDBACK CHECK]
# ---------------------------------------------------------------------------

def feedback_check() -> dict:
    section("FEEDBACK CHECK")
    feedback = load_json("feedback_log.json", [])
    result = {"low_scores": [], "should_rewrite": False}

    if not feedback:
        print("No feedback yet.")
        return result

    # Check yesterday's ratings
    today = datetime.now(timezone.utc).date()
    yesterday = today - timedelta(days=1)
    yesterday_entries = [
        f for f in feedback
        if f.get("date", "")[:10] == str(yesterday)
    ]
    low = [f for f in yesterday_entries if f.get("score", 2) == 1]
    if low:
        result["low_scores"] = low
        print(f"Found {len(low)} low-rated articles from yesterday")

    # Check if 7+ days of feedback → trigger rewrite
    unique_dates = set(f.get("date", "")[:10] for f in feedback)
    if len(unique_dates) >= 7:
        result["should_rewrite"] = True
        print("7+ days of feedback accumulated — will trigger criteria rewrite")
    else:
        print(f"{len(unique_dates)} day(s) of feedback so far (need 7 for rewrite)")

    return result


# ---------------------------------------------------------------------------
# [ARTICLE SELECTION]
# ---------------------------------------------------------------------------

def select_articles(
    gmail_items: list[dict],
    tier2_items: list[dict],
    feedback_info: dict,
) -> list[dict]:
    section("ARTICLE SELECTION")

    # Load selection criteria and tickers
    with open("selection_criteria.md", "r") as f:
        criteria = f.read()
    tickers = load_json("tickers.json", {})
    run_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    structured_gmail, structured_tier2 = build_structured_candidates(
        gmail_items,
        tier2_items,
        run_date,
        tickers,
    )

    taste_summary = load_learned_preferences_summary()

    def candidate_block(label: str, candidates: list[dict]) -> str:
        text = ""
        for index, item in enumerate(candidates, 1):
            text += f"\n--- {label} {index} ---\n"
            text += f"Candidate ID: {item['candidate_id']}\n"
            text += f"Source: {item['source_name']} ({item['category']})\n"
            text += f"Priority: {item['priority']}\n"
            text += f"Headline: {item['headline']}\n"
            text += f"Snippet: {item['snippet']}\n"
            text += f"Primary URL: {item['primary_url'] or 'N/A'}\n"
            text += f"Derived signals: {', '.join(item.get('derived_signals', [])) or 'none'}\n"
        return text

    newsletter_text = candidate_block("Gmail Candidate", structured_gmail)
    tier2_text = candidate_block("Tier2 Candidate", structured_tier2)

    feedback_context = ""
    if feedback_info.get("low_scores"):
        feedback_context = "\n\nFEEDBACK NOTE: Yesterday had low-rated articles. Patterns to avoid:\n"
        for f in feedback_info["low_scores"]:
            feedback_context += f"- Slot {f.get('slot')}: score {f.get('score')}, note: {f.get('note', 'N/A')}\n"

    taste_section = ""
    if taste_summary:
        taste_section = f"\nREADER TASTE PROFILE:\n{taste_summary}\n"

    system_prompt = f"""You are a daily article curator for an investor focused on healthcare/biotech,
with secondary interest in tech/AI and macro markets.

SELECTION CRITERIA:
{criteria}
{taste_section}
TICKER UNIVERSE ({len(tickers.get('healthcare', []))} healthcare, {len(tickers.get('tech', []))} tech, {len(tickers.get('other', []))} other):
Healthcare subsectors: {', '.join(sorted(s for s, t in (tickers.get('subsectors') or {}).items() if any(((tickers.get('details') or {}).get(tk) or {}).get('bucket') == 'healthcare' for tk in t))[:20])}
Company name matching enabled ({len(tickers.get('company_lookup', {}))} names).
Articles mentioning coverage universe tickers or companies get a signal boost.
{feedback_context}

Select your top 8 articles ranked by quality, so we have backups if some don't hold up on closer reading.
Use the structured candidate metadata first. Use the web_search tool only if you need to verify or supplement a candidate.

Return ONLY valid JSON — an array of 8 objects ranked best-first, with these keys:
headline, source, url, rank (1-8), summary, why_it_matters, signal_tags, reading_time (estimated minutes to read, e.g. "4 min")
"""

    user_content = f"""Today's date: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}

=== GMAIL NEWSLETTERS ===
{newsletter_text if newsletter_text else "(No Gmail newsletters found today)"}

=== TIER 2 SOURCES ===
{tier2_text if tier2_text else "(No Tier 2 items found)"}

Select your top 8 articles ranked by quality. Return JSON only."""

    print("Calling Claude for article shortlist (top 8)...")
    client = anthropic.Anthropic()

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        system=system_prompt,
        tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}],
        messages=[{"role": "user", "content": user_content}],
    )

    # Extract JSON from response
    shortlist = []
    for block in response.content:
        if block.type == "text":
            text = block.text.strip()
            json_match = re.search(r'\[.*\]', text, re.DOTALL)
            if json_match:
                try:
                    shortlist = json.loads(json_match.group())
                    break
                except json.JSONDecodeError:
                    pass

    if not shortlist:
        print("WARNING: Could not parse article shortlist from Claude response")
        print("Raw response blocks:")
        for block in response.content:
            if block.type == "text":
                print(block.text[:500])
        return []

    print(f"Shortlisted {len(shortlist)} candidates:")
    for a in shortlist:
        print(f"  #{a.get('rank', '?')}: {a.get('headline', '?')[:60]} ({a.get('source', '?')})")

    # --- VERIFICATION PASS: read each article and confirm it meets criteria ---
    articles = verify_shortlist(shortlist, criteria, taste_section, feedback_context, client)

    if not articles:
        print("WARNING: No articles passed verification")
        return []

    print(f"\nFinal {len(articles)} verified articles:")
    for a in articles:
        print(f"  Slot {a.get('slot')}: {a.get('headline', '?')[:60]}")
        print(f"    Source: {a.get('source')} | Signals: {a.get('signal_tags', [])}")

    return articles


def _fetch_with_trafilatura(url: str, timeout: int = 15) -> str | None:
    """Try to extract article text using trafilatura (local, free)."""
    import trafilatura

    try:
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            print(f"    Trafilatura: fetch returned nothing")
            return None
        text = trafilatura.extract(downloaded, include_comments=False, include_tables=False)
        if text and len(text) > 500:
            print(f"    Trafilatura: extracted {len(text)} chars")
            return text
        print(f"    Trafilatura: too little text ({len(text) if text else 0} chars)")
    except Exception as e:
        print(f"    Trafilatura failed: {e}")
    return None


def _fetch_with_jina(url: str) -> str | None:
    """Fall back to Jina Reader API (free, handles JS rendering)."""
    print(f"    Falling back to Jina Reader...")
    try:
        resp = requests.get(
            f"https://r.jina.ai/{url}",
            headers={"Accept": "text/plain"},
            timeout=30,
        )
        resp.raise_for_status()
        text = resp.text.strip()
        if text and len(text) > 500:
            print(f"    Jina Reader: extracted {len(text)} chars")
            return text
        print(f"    Jina Reader: too little text ({len(text)} chars)")
    except Exception as e:
        print(f"    Jina Reader failed: {e}")
    return None


def _fetch_with_tavily(url: str) -> str | None:
    """Last resort: Tavily extract API for the hardest pages."""
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        return None

    print(f"    Falling back to Tavily extract...")
    try:
        resp = requests.post(
            "https://api.tavily.com/extract",
            json={"urls": [url]},
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results", [])
        if results and results[0].get("raw_content"):
            text = results[0]["raw_content"]
            print(f"    Tavily: extracted {len(text)} chars")
            return text
    except Exception as e:
        print(f"    Tavily extract failed: {e}")
    return None


_PAYWALL_PATTERNS = re.compile(
    r"(are you a robot|captcha|subscribe to continue|sign in to read|"
    r"create a free account|this content is for subscribers|"
    r"please log in|paywall|access denied|unusual activity)",
    re.IGNORECASE,
)


def _is_paywall_stub(text: str) -> bool:
    """Detect paywall, captcha, or bot-wall pages masquerading as article text."""
    if len(text) < 1500 and _PAYWALL_PATTERNS.search(text):
        return True
    return False


def fetch_article_text(url: str, timeout: int = 15) -> tuple[str | None, str]:
    """Fetch article text with 3-tier fallback: trafilatura -> Jina -> Tavily.

    Returns (text, extraction_tier) where tier is one of:
    'trafilatura', 'jina', 'tavily', or 'none'.
    """
    text = _fetch_with_trafilatura(url, timeout)
    if text and not _is_paywall_stub(text):
        if len(text) > 6000:
            text = text[:6000] + "\n[...truncated]"
        return text, "trafilatura"

    text = _fetch_with_jina(url)
    if text and not _is_paywall_stub(text):
        if len(text) > 6000:
            text = text[:6000] + "\n[...truncated]"
        return text, "jina"

    text = _fetch_with_tavily(url)
    if text and not _is_paywall_stub(text):
        if len(text) > 6000:
            text = text[:6000] + "\n[...truncated]"
        return text, "tavily"

    if text and _is_paywall_stub(text):
        print(f"    Detected paywall/bot-wall stub — discarding")

    return None, "none"


def verify_shortlist(
    shortlist: list[dict],
    criteria: str,
    taste_section: str,
    feedback_context: str,
    client,
) -> list[dict]:
    """Read each shortlisted article and verify it meets selection criteria.

    Walks through the shortlist in rank order, fetches article content,
    and asks Claude to verify. Stops once 4 articles pass (or 3 if slot 4
    wildcard has no good candidate).
    """
    section("ARTICLE VERIFICATION")
    slot_labels = {1: "Healthcare/Biotech", 2: "Finance/Macro", 3: "Tech/AI", 4: "Wildcard"}
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    verified = []
    verification_log = []
    seen_sources = set()
    next_slot = 1

    for candidate in shortlist:
        if next_slot > 4:
            break

        url = (candidate.get("url") or "").strip()
        headline = candidate.get("headline", "Untitled")
        source = candidate.get("source", "Unknown")

        # Skip duplicate sources
        if source.casefold() in seen_sources:
            print(f"  Skipping {headline[:50]} — duplicate source {source}")
            continue

        if not url or not re.match(r"^https?://", url):
            print(f"  Skipping {headline[:50]} — invalid URL")
            continue

        print(f"\n  Reading #{candidate.get('rank', '?')}: {headline[:60]}")
        print(f"    URL: {url}")

        article_text, extraction_tier = fetch_article_text(url)
        snippet_only = False
        if not article_text:
            # Fall back to newsletter snippet for paywalled/unfetchable articles
            snippet = candidate.get("summary", "")
            why = candidate.get("why_it_matters", "")
            fallback = f"Headline: {headline}\nSource: {source}\nSummary: {snippet}\nWhy it matters: {why}"
            if len(snippet) > 50:
                print(f"    Could not fetch article — using newsletter snippet for lighter verification")
                article_text = fallback
                snippet_only = True
                extraction_tier = "snippet_fallback"
            else:
                print(f"    Could not extract article text and no snippet — skipping")
                verification_log.append({
                    "date": today, "headline": headline, "source": source,
                    "url": url, "extraction_tier": "none",
                    "passed": False, "reason": "Could not fetch and no snippet",
                })
                continue

        if not snippet_only:
            print(f"    Fetched {len(article_text)} chars via {extraction_tier}")

        # Ask Claude to verify this article
        snippet_caveat = ""
        if snippet_only:
            snippet_caveat = """
NOTE: The full article could not be fetched (likely paywalled). You are evaluating based on
the headline and newsletter summary only. Apply a lighter bar — accept if the topic and source
are strong and the summary suggests substantive content. Reject only if the topic clearly
doesn't fit the criteria or seems thin/generic based on what's available."""

        verify_prompt = f"""You are verifying whether an article meets selection criteria for a daily digest.{snippet_caveat}

SELECTION CRITERIA:
{criteria}
{taste_section}
{feedback_context}

TARGET SLOT: Slot {next_slot} — {slot_labels.get(next_slot, 'General')}

ARTICLE HEADLINE: {headline}
ARTICLE SOURCE: {source}
SHORTLIST SUMMARY: {candidate.get('summary', '')}
SHORTLIST WHY IT MATTERS: {candidate.get('why_it_matters', '')}

FULL ARTICLE TEXT:
{article_text}

Based on the actual article content (not just the headline), evaluate:
1. Does this article have real substance and depth, or is it thin/generic?
2. Does it match the selection criteria and the target slot theme?
3. Is the shortlist summary accurate to what the article actually says?

Return ONLY valid JSON with these keys:
- "pass": true or false
- "reason": one sentence explaining your verdict
- "summary": an accurate 2-3 sentence summary based on the actual content (rewrite if the original was inaccurate)
- "why_it_matters": why this matters for the reader, based on actual content
- "reading_time": estimated minutes to read (e.g. "4 min")
"""

        try:
            verify_resp = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1024,
                messages=[{"role": "user", "content": verify_prompt}],
            )
            verify_text = ""
            for block in verify_resp.content:
                if block.type == "text":
                    verify_text += block.text

            json_match = re.search(r'\{.*\}', verify_text, re.DOTALL)
            if not json_match:
                print(f"    Could not parse verification response — skipping")
                continue

            verdict = json.loads(json_match.group())
        except Exception as e:
            print(f"    Verification call failed: {e} — skipping")
            continue

        passed = bool(verdict.get("pass"))
        reason = verdict.get("reason", "")
        verification_log.append({
            "date": today, "headline": headline, "source": source,
            "url": url, "extraction_tier": extraction_tier,
            "passed": passed, "reason": reason,
        })

        if passed:
            print(f"    PASS: {reason}")
            verified.append({
                "article_id": article_id_for(url, source),
                "headline": headline.strip(),
                "source": source.strip(),
                "url": url,
                "slot": next_slot,
                "summary": verdict.get("summary", candidate.get("summary", "")).strip(),
                "why_it_matters": verdict.get("why_it_matters", candidate.get("why_it_matters", "")).strip(),
                "signal_tags": [str(t).strip() for t in candidate.get("signal_tags", []) if str(t).strip()],
                "reading_time": verdict.get("reading_time", candidate.get("reading_time", "N/A")),
            })
            seen_sources.add(source.casefold())
            next_slot += 1
        else:
            print(f"    FAIL: {reason}")

    # Persist verification log for weekly reporting
    log_path = Path("artifacts/verification_log.json")
    existing_log = []
    if log_path.exists():
        try:
            existing_log = json.loads(log_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    existing_log.extend(verification_log)
    os.makedirs("artifacts", exist_ok=True)
    log_path.write_text(json.dumps(existing_log, indent=2), encoding="utf-8")

    # Accept 3 articles if we couldn't fill the wildcard slot
    if len(verified) >= 3:
        return verified
    return verified


# ---------------------------------------------------------------------------
# [DELIVERY: GMAIL]
# ---------------------------------------------------------------------------

def deliver_gmail(articles: list[dict], triage_queue: list[dict] | None = None, always_read: list[dict] | None = None, substack_items: list[dict] | None = None):
    section("DELIVERY: GMAIL")
    try:
        import base64
        from email.mime.text import MIMEText
        from gmail_reader import get_gmail_service

        service = get_gmail_service()
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        slot_emojis = {1: "🧬", 2: "📊", 3: "🤖", 4: "🌀"}

        html = f"""<html><body style="font-family: -apple-system, sans-serif; max-width: 600px; margin: 0 auto; background: #1a1a2e; color: #eee; padding: 20px;">
<h1 style="color: #e94560;">📰 Daily Reads — {today}</h1>
"""
        for a in articles:
            slot = a.get("slot", 0)
            emoji = slot_emojis.get(slot, "📌")
            feedback_links = [
                ("👍", "Strong pick", 3),
                ("👌", "Fine", 2),
                ("👎", "Miss", 1),
            ]
            feedback_html = " ".join(
                (
                    f'<a href="{feedback_url(today, slot, score, a.get("headline", ""))}" '
                    'style="text-decoration: none; background: #1a1a40; border: 1px solid #333; '
                    'border-radius: 4px; padding: 4px 10px; color: #eee; font-size: 13px; '
                    'margin-right: 6px;">'
                    f"{icon} {label}</a>"
                )
                for icon, label, score in feedback_links
            )
            html += f"""
<div style="background: #16213e; border-radius: 8px; padding: 16px; margin: 16px 0; border-left: 4px solid #e94560;">
  <h2 style="margin: 0 0 8px 0;">{emoji} <a href="{a.get('url', '#')}" style="color: #0fbcf9; text-decoration: none;">{a.get('headline', 'Untitled')}</a></h2>
  <p style="color: #a8a8b3; margin: 4px 0; font-size: 13px;">{a.get('source', '')} · Slot {slot} · ⏱ {a.get('reading_time', 'N/A')} read</p>
  <p style="margin: 8px 0;">{a.get('summary', '')}</p>
  <p style="color: #e94560; font-style: italic; margin: 8px 0;">💡 {a.get('why_it_matters', '')}</p>
  <p style="margin: 8px 0;">{feedback_html}</p>
  <p style="color: #666; font-size: 11px;">Signals: {', '.join(a.get('signal_tags', []))} · ⏱ {a.get('reading_time', 'N/A')} read</p>
</div>
"""
        if triage_queue:
            html += """
<div style="background: #1a1a2e; border-top: 2px solid #333; margin-top: 24px; padding-top: 16px;">
  <h3 style="color: #a8a8b3; margin: 0 0 4px 0;">Also considered</h3>
  <p style="color: #666; font-size: 11px; margin: 0 0 12px 0;">Reply to rate: <span style="color: #0fbcf9;">[slot#] [score 1-3]</span> — e.g. <span style="color: #0fbcf9;">5 3</span> = slot 5, strong pick; <span style="color: #0fbcf9;">7 1 not relevant</span> = slot 7, miss</p>
"""
            for i, candidate in enumerate(triage_queue[:10]):
                slot_num = i + 5
                headline = candidate.get("headline", "Untitled")
                url = candidate.get("primary_url", "#")
                source = candidate.get("source_name", "")
                html += f'  <p style="margin: 6px 0; font-size: 13px;"><span style="color: #a8a8b3; font-size: 11px; margin-right: 6px;">#{slot_num}</span><a href="{url}" style="color: #0fbcf9; text-decoration: none;">{headline}</a> <span style="color: #666;">— {source}</span></p>\n'
            html += "</div>\n"

        if always_read:
            html += """
<div style="background: #1a1a2e; border-top: 2px solid #e94560; margin-top: 24px; padding-top: 16px;">
  <h3 style="color: #e94560; margin: 0 0 8px 0;">📖 Always read</h3>
"""
            for item in always_read:
                headline = item.get("headline", "Untitled")
                url = item.get("primary_url", "#")
                source = item.get("source_name", "")
                html += f'  <p style="margin: 6px 0; font-size: 13px;"><a href="{url}" style="color: #0fbcf9; text-decoration: none;">{headline}</a> <span style="color: #666;">— {source}</span></p>\n'
            html += "</div>\n"

        if substack_items:
            html += """
<div style="background: #1a1a2e; border-top: 2px solid #7c3aed; margin-top: 24px; padding-top: 16px;">
  <h3 style="color: #7c3aed; margin: 0 0 4px 0;">📨 Substack — today's inbox</h3>
  <p style="color: #666; font-size: 11px; margin: 0 0 12px 0;">All @substack.com emails from the last 26h. Use this to decide which to promote to always-read.</p>
"""
            for item in substack_items:
                subject = item.get("subject", "(no subject)")
                url = item.get("url") or "#"
                sender = item.get("sender_name", "")
                html += f'  <p style="margin: 6px 0; font-size: 13px;"><a href="{url}" style="color: #0fbcf9; text-decoration: none;">{subject}</a> <span style="color: #666;">— {sender}</span></p>\n'
            html += "</div>\n"

        html += """
<hr style="border-color: #333; margin: 24px 0;">
<p style="color: #a8a8b3; font-size: 12px;">💬 Reply to rate: <span style="color: #0fbcf9;">[slot#] [score 1-3]</span> — 3 = strong pick, 2 = fine, 1 = miss. e.g. <span style="color: #0fbcf9;">1 3</span> or <span style="color: #0fbcf9;">3 1 too generic</span></p>
<p style="color: #666; font-size: 12px;">Or rate at
<a href="https://jroypeterson.github.io/daily-reads" style="color: #0fbcf9;">jroypeterson.github.io/daily-reads</a>
&nbsp;·&nbsp;
<a href="https://github.com/jroypeterson/daily-reads/issues/new?labels=taste&title=Taste%3A+&body=Paste+URL+here%0A%0AWhy+I+liked+it%3A+" style="color: #0fbcf9;">📎 Submit an article</a></p>
<p style="color: #666; font-size: 12px;">📬 Found something great? Forward it to <a href="mailto:jroypeterson+taste@gmail.com" style="color: #0fbcf9;">jroypeterson+taste@gmail.com</a> to train my taste. Add "Why I liked it:" in the body for extra signal.</p>
</body></html>"""

        msg = MIMEText(html, "html")
        msg["to"] = "jroypeterson@gmail.com"
        msg["subject"] = f"📰 Daily Reads — {today}"
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()

        service.users().messages().send(
            userId="me", body={"raw": raw}
        ).execute()
        print("Email sent to jasonrpeterson@gmail.com")
    except Exception as e:
        print(f"Gmail delivery failed: {e}")


# ---------------------------------------------------------------------------
# [DELIVERY: SLACK]
# ---------------------------------------------------------------------------

def deliver_slack(articles: list[dict], triage_queue: list[dict] | None = None, always_read: list[dict] | None = None, substack_items: list[dict] | None = None):
    section("DELIVERY: SLACK")
    # The daily digest posts to its own #daily-reads channel when its
    # dedicated webhook is configured. Fall back to the general
    # SLACK_WEBHOOK_URL so a missing secret doesn't break delivery.
    webhook_url = (
        os.environ.get("SLACK_WEBHOOK_URL_DAILY_READS")
        or os.environ.get("SLACK_WEBHOOK_URL")
    )
    if not webhook_url:
        print("No Slack webhook set (checked SLACK_WEBHOOK_URL_DAILY_READS, SLACK_WEBHOOK_URL) — skipping Slack delivery")
        return

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    slot_emojis = {1: ":dna:", 2: ":chart_with_upwards_trend:", 3: ":robot_face:", 4: ":cyclone:"}

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": f"📰 Daily Reads — {today}"}},
        {"type": "divider"},
    ]

    for a in articles:
        slot = a.get("slot", 0)
        emoji = slot_emojis.get(slot, ":pushpin:")
        strong_url = slack_mailto_feedback_url(today, slot, 3)
        fine_url = slack_mailto_feedback_url(today, slot, 2)
        miss_url = slack_mailto_feedback_url(today, slot, 1)
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"{emoji} *<{a.get('url', '#')}|{a.get('headline', 'Untitled')}>*\n"
                    f"_{a.get('source', '')} · Slot {slot} · :timer_clock: {a.get('reading_time', 'N/A')} read_\n\n"
                    f"{a.get('summary', '')}\n\n"
                    f"💡 _{a.get('why_it_matters', '')}_\n\n"
                    f"<{strong_url}|:thumbsup: Strong pick>  "
                    f"<{fine_url}|:ok_hand: Fine>  "
                    f"<{miss_url}|:thumbsdown: Miss>"
                ),
            },
        })
        blocks.append({"type": "divider"})

    if triage_queue:
        # Slack section text is capped at 3000 chars. Tracking-redirect URLs
        # (e.g. BioSpace marketing links) can be 600+ chars each, so chunk
        # the list across multiple section blocks to stay under the limit.
        triage_lines = [
            f"`#{i + 5}` <{c.get('primary_url', '#')}|{c.get('headline', 'Untitled')}> — {c.get('source_name', '')}"
            for i, c in enumerate(triage_queue[:10])
        ]
        header = "*Also considered*\n_Reply to rate: `[slot#] [score 1-3]` — 3 = strong pick, 2 = fine, 1 = miss. e.g. `5 3` or `7 1 not relevant`_"
        SLACK_SECTION_LIMIT = 2500  # leave headroom under the 3000 cap
        chunks: list[str] = []
        current = header
        for line in triage_lines:
            candidate = current + "\n" + line
            if len(candidate) > SLACK_SECTION_LIMIT and current:
                chunks.append(current)
                current = line
            else:
                current = candidate
        if current:
            chunks.append(current)
        for chunk in chunks:
            blocks.append({
                "type": "section",
                # Hard cap at 2990 as a final safety net against any single
                # chunk that slipped past the limit (e.g. one line > limit).
                "text": {"type": "mrkdwn", "text": chunk[:2990]},
            })

    if always_read:
        always_lines = "\n".join(
            f"<{c.get('primary_url', '#')}|{c.get('headline', 'Untitled')}> — {c.get('source_name', '')}"
            for c in always_read
        )
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f":book: *Always read*\n{always_lines}",
            },
        })

    if substack_items:
        # Substack emails carry very long redirect URLs (~700 chars each),
        # so a handful of lines push a chunk near Slack's 3000-char section
        # limit. Use a tight limit, force a new chunk before each add if
        # the next line would exceed, and truncate any single line that
        # somehow exceeds the limit on its own.
        SLACK_SECTION_LIMIT = 2500

        def _truncate_line(s: str) -> str:
            if len(s) <= SLACK_SECTION_LIMIT:
                return s
            return s[: SLACK_SECTION_LIMIT - 4] + "...>"

        sub_lines = [
            _truncate_line(
                f"<{item.get('url') or '#'}|{item.get('subject', '(no subject)')}> — {item.get('sender_name', '')}"
            )
            for item in substack_items
        ]
        header = ":incoming_envelope: *Substack — today's inbox*\n_All @substack.com emails from the last 26h. Flag which to promote to always-read._"
        chunks: list[str] = []
        current = header
        for line in sub_lines:
            candidate = current + "\n" + line
            if len(candidate) > SLACK_SECTION_LIMIT and current:
                chunks.append(current)
                current = line
            else:
                current = candidate
        if current:
            chunks.append(current)
        for chunk in chunks:
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": chunk[:2990]},
            })

    blocks.append({
        "type": "context",
        "elements": [{
            "type": "mrkdwn",
            "text": ":mailbox_with_mail: Found something great? Forward it to `jroypeterson+taste@gmail.com` to train my taste. Add \"Why I liked it:\" for extra signal.",
        }],
    })

    try:
        resp = requests.post(webhook_url, json={"blocks": blocks}, timeout=10)
        if not resp.ok:
            # Slack returns useful detail in the body (e.g. invalid_blocks, no_text)
            print(f"Slack delivery failed (non-blocking): HTTP {resp.status_code} — body: {resp.text[:500]}")
            print(f"Payload had {len(blocks)} blocks")
        else:
            print("Slack message sent")
    except Exception as e:
        print(f"Slack delivery failed (non-blocking): {e}")


# ---------------------------------------------------------------------------
# [DELIVERY: PAGES]
# ---------------------------------------------------------------------------

def _pages_triage_html(triage_queue: list[dict] | None) -> str:
    if not triage_queue:
        return ""
    items = "\n".join(
        f'    <p style="margin: 6px 0; font-size: 14px;">'
        f'<span style="color: #a8a8b3; font-size: 12px; margin-right: 6px;">#{i + 5}</span>'
        f'<a href="{c.get("primary_url", "#")}" target="_blank" style="color: #0fbcf9; text-decoration: none;">{c.get("headline", "Untitled")}</a>'
        f' <span style="color: #666;">— {c.get("source_name", "")}</span></p>'
        for i, c in enumerate(triage_queue[:10])
    )
    return f"""  <div style="border-top: 2px solid #2a2a50; margin-top: 24px; padding-top: 16px;">
    <h3 style="color: #a8a8b3; margin-bottom: 4px;">Also considered</h3>
    <p style="color: #666; font-size: 12px; margin-bottom: 12px;">Reply to rate: <span style="color: #0fbcf9;">[slot#] [score 1-3]</span> — 3 = strong pick, 2 = fine, 1 = miss. e.g. <span style="color: #0fbcf9;">5 3</span> or <span style="color: #0fbcf9;">7 1 not relevant</span></p>
{items}
  </div>"""


def _pages_substack_html(substack_items: list[dict] | None) -> str:
    if not substack_items:
        return ""
    items = "\n".join(
        f'    <p style="margin: 6px 0; font-size: 14px;">'
        f'<a href="{item.get("url") or "#"}" target="_blank" style="color: #0fbcf9; text-decoration: none;">{item.get("subject", "(no subject)")}</a>'
        f' <span style="color: #666;">— {item.get("sender_name", "")}</span></p>'
        for item in substack_items
    )
    return f"""  <div style="border-top: 2px solid #7c3aed; margin-top: 24px; padding-top: 16px;">
    <h3 style="color: #7c3aed; margin-bottom: 4px;">📨 Substack — today's inbox</h3>
    <p style="color: #666; font-size: 12px; margin-bottom: 12px;">All @substack.com emails from the last 26h. Use this to decide which to promote to always-read.</p>
{items}
  </div>"""


def _pages_always_read_html(always_read: list[dict] | None) -> str:
    if not always_read:
        return ""
    items = "\n".join(
        f'    <p style="margin: 6px 0; font-size: 14px;">'
        f'<a href="{c.get("primary_url", "#")}" target="_blank" style="color: #0fbcf9; text-decoration: none;">{c.get("headline", "Untitled")}</a>'
        f' <span style="color: #666;">— {c.get("source_name", "")}</span></p>'
        for c in always_read
    )
    return f"""  <div style="border-top: 2px solid #e94560; margin-top: 24px; padding-top: 16px;">
    <h3 style="color: #e94560; margin-bottom: 8px;">📖 Always read</h3>
{items}
  </div>"""


def deliver_pages(articles: list[dict], triage_queue: list[dict] | None = None, always_read: list[dict] | None = None, substack_items: list[dict] | None = None):
    section("DELIVERY: PAGES")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    slot_emojis = {1: "🧬", 2: "📊", 3: "🤖", 4: "🌀"}

    cards_html = ""
    for a in articles:
        slot = a.get("slot", 0)
        emoji = slot_emojis.get(slot, "📌")
        tags = ", ".join(a.get("signal_tags", []))
        feedback_links = [
            ("👍 Strong", 3),
            ("👌 Fine", 2),
            ("👎 Miss", 1),
        ]
        feedback_html = " ".join(
            (
                f'<a class="fb-link" href="{slack_mailto_feedback_url(today, slot, score)}">'
                f"{label}</a>"
            )
            for label, score in feedback_links
        )
        cards_html += f"""
      <div class="card">
        <div class="card-header">
          <span class="slot-emoji">{emoji}</span>
          <span class="slot-label">Slot {slot}</span>
        </div>
        <h2><a href="{a.get('url', '#')}" target="_blank">{a.get('headline', 'Untitled')}</a></h2>
        <p class="meta">{a.get('source', '')} · {today} · ⏱ {a.get('reading_time', 'N/A')} read</p>
        <p class="summary">{a.get('summary', '')}</p>
        <p class="why">💡 {a.get('why_it_matters', '')}</p>
        <p class="tags">{tags}</p>
        <div class="feedback">
          {feedback_html}
        </div>
      </div>
"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Daily Reads — {today}</title>
  <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      background: #0f0f23; color: #e0e0e0; padding: 24px;
      max-width: 800px; margin: 0 auto;
    }}
    h1 {{ color: #e94560; margin-bottom: 8px; font-size: 28px; }}
    .updated {{ color: #666; font-size: 13px; margin-bottom: 24px; }}
    .card {{
      background: #16213e; border-radius: 12px; padding: 20px;
      margin-bottom: 20px; border-left: 4px solid #e94560;
      transition: transform 0.2s;
    }}
    .card:hover {{ transform: translateY(-2px); }}
    .card-header {{ display: flex; align-items: center; gap: 8px; margin-bottom: 12px; }}
    .slot-emoji {{ font-size: 24px; }}
    .slot-label {{ color: #a8a8b3; font-size: 12px; text-transform: uppercase; letter-spacing: 1px; }}
    .card h2 {{ font-size: 18px; margin-bottom: 8px; }}
    .card h2 a {{ color: #0fbcf9; text-decoration: none; }}
    .card h2 a:hover {{ text-decoration: underline; }}
    .meta {{ color: #a8a8b3; font-size: 13px; margin-bottom: 12px; }}
    .summary {{ line-height: 1.6; margin-bottom: 10px; }}
    .why {{ color: #e94560; font-style: italic; margin-bottom: 10px; }}
    .tags {{ color: #666; font-size: 12px; margin-bottom: 12px; }}
    .intro {{
      background: #151530; border: 1px solid #2a2a50; border-radius: 12px;
      padding: 16px; margin-bottom: 24px; line-height: 1.6;
    }}
    .intro p {{ margin-bottom: 10px; }}
    .intro a {{ color: #0fbcf9; text-decoration: none; }}
    .intro a:hover {{ text-decoration: underline; }}
    .feedback {{ display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }}
    .fb-link {{
      background: #1a1a40; border: 1px solid #333; border-radius: 6px;
      padding: 7px 12px; color: #eee; text-decoration: none; font-size: 13px;
      transition: background 0.2s;
    }}
    .fb-link:hover {{ background: #2a2a50; }}
    .empty {{ text-align: center; padding: 60px 20px; color: #666; }}
  </style>
</head>
<body>
  <h1>📰 Daily Reads</h1>
  <p class="updated">Last updated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}</p>
  <div class="intro">
    <p>Score from this page by opening a prefilled email draft. Use <strong>3 = Strong pick</strong>, <strong>2 = Fine</strong>, and <strong>1 = Miss</strong>. You can add a note before sending.</p>
    <p>For broader preference training, <a href="https://github.com/{REPO}/issues/new?labels=taste&title=Taste%3A+&body=Paste+URL+here%0A%0AWhy+I+liked+it%3A+">submit an article you liked</a> or forward it to <a href="mailto:jroypeterson+taste@gmail.com">jroypeterson+taste@gmail.com</a>. Add "Why I liked it:" for extra signal.</p>
  </div>

  <div id="cards">
{cards_html if cards_html else '    <div class="empty"><p>No articles selected today. Check back tomorrow!</p></div>'}
  </div>
{_pages_triage_html(triage_queue)}
{_pages_always_read_html(always_read)}
{_pages_substack_html(substack_items)}
</body>
</html>"""

    os.makedirs("docs", exist_ok=True)
    with open("docs/index.html", "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Updated docs/index.html with {len(articles)} articles")


# ---------------------------------------------------------------------------
# [DELIVERY: LOG]
# ---------------------------------------------------------------------------

def deliver_log(articles: list[dict]):
    section("DELIVERY: LOG")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    slot_emojis = {1: "🧬", 2: "📊", 3: "🤖", 4: "🌀"}

    print(f"Daily Reads — {today}")
    print("-" * 40)
    for a in articles:
        slot = a.get("slot", 0)
        emoji = slot_emojis.get(slot, "📌")
        print(f"\n{emoji} Slot {slot}: {a.get('headline', 'Untitled')}")
        print(f"   Source: {a.get('source', '')}")
        print(f"   Article ID: {a.get('article_id', '')}")
        print(f"   URL: {a.get('url', '')}")
        print(f"   {a.get('summary', '')}")
        print(f"   💡 {a.get('why_it_matters', '')}")
        print(f"   Signals: {', '.join(a.get('signal_tags', []))}")


def deliver_ticktick(articles: list[dict], always_read: list[dict] | None = None):
    section("DELIVERY: TICKTICK")
    access_token = os.environ.get("TICKTICK_ACCESS_TOKEN")
    list_id = os.environ.get("TICKTICK_LIST_DAILY_READS")
    if not access_token or not list_id:
        print("TickTick credentials not configured — skipping.")
        return

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    due_date = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000+0000")

    tasks = []
    for a in articles:
        url = a.get("url", "")
        headline = a.get("headline", "Untitled")
        slot = a.get("slot", "?")
        title = f"[{headline}]({url})" if url else headline
        summary = a.get("summary", "")
        why = a.get("why_it_matters", "")
        strong = slack_mailto_feedback_url(today, slot, 3)
        fine = slack_mailto_feedback_url(today, slot, 2)
        miss = slack_mailto_feedback_url(today, slot, 1)
        reading_time = a.get("reading_time", "N/A")
        desc = f"⏱ {reading_time} read · {a.get('source', '')}\n\n{summary}\n\nWhy it matters: {why}" if why else f"⏱ {reading_time} read · {a.get('source', '')}\n\n{summary}"
        desc += f"\n\nRate this pick: [Strong]({strong}) · [Fine]({fine}) · [Miss]({miss})"
        desc += "\n\n---\nFound something great? Forward it to jroypeterson+taste@gmail.com to train my taste."
        tasks.append({
            "title": title,
            "content": desc,
            "dueDate": due_date,
            "projectId": list_id,
        })

    for item in (always_read or []):
        headline = item.get("headline") or item.get("subject", "Untitled")
        url = item.get("primary_url", "")
        source = item.get("source_name", "")
        title = f"[{headline}]({url})" if url else headline
        tasks.append({
            "title": title,
            "content": f"Source: {source}",
            "dueDate": due_date,
            "projectId": list_id,
        })

    created = 0
    token_expired = False
    for task in tasks:
        resp = requests.post(
            "https://api.ticktick.com/open/v1/task",
            headers=headers,
            json=task,
        )
        if resp.status_code == 200:
            created += 1
            print(f"  ✓ {task['title']}")
        elif resp.status_code == 401:
            token_expired = True
            print(f"  ✗ 401 Unauthorized — TickTick token has expired.")
            break
        else:
            print(f"  ✗ Failed ({resp.status_code}): {task['title']}")
            print(f"    {resp.text}")

    if token_expired:
        print("\n⚠️ TickTick access token expired. Re-run the OAuth flow to get a new token.")
        slack_url = os.environ.get("SLACK_WEBHOOK_URL")
        if slack_url:
            requests.post(slack_url, json={
                "text": "⚠️ *TickTick token expired* — Daily Reads can't push to TickTick. "
                        "Re-run the OAuth flow at developer.ticktick.com to get a new access token, "
                        "then update the `TICKTICK_ACCESS_TOKEN` GitHub secret."
            })

    print(f"\nCreated {created}/{len(tasks)} tasks in TickTick.")


def deliver_triage_log(triage_queue: list[dict]):
    section("TRIAGE QUEUE")
    if not triage_queue:
        print("No extra candidates ranked today.")
        return

    for index, candidate in enumerate(triage_queue[:5], 1):
        print(
            f"{index}. [{candidate.get('triage_score', 0)}] "
            f"{candidate.get('headline', 'Untitled')} "
            f"({candidate.get('source_name', 'Unknown')})"
        )
        print(f"   URL: {candidate.get('primary_url', '')}")
        print(f"   Signals: {', '.join(candidate.get('derived_signals', []))}")


# ---------------------------------------------------------------------------
# [CRITERIA REWRITE]
# ---------------------------------------------------------------------------

def rewrite_criteria(feedback: list[dict]):
    """Generate a proposed criteria update and notify for review."""
    section("CRITERIA REWRITE")
    state = load_criteria_state()
    pending = state.get("pending")
    if pending and pending.get("status") == "pending":
        print(f"Pending criteria proposal already exists: {pending.get('proposal_id')}")
        return

    print("Generating proposed criteria update based on feedback...")

    with open("selection_criteria.md", "r") as f:
        current = f.read()

    prior_proposal = ""
    modification_note = ""
    revision = 1
    trigger = "7+ days of feedback accumulated"
    if pending and pending.get("status") == "modification_requested":
        revision = int(pending.get("revision", 1)) + 1
        modification_note = pending.get("modification_note", "").strip()
        trigger = "user requested modifications to prior proposal"
        try:
            with open(PROPOSED_CRITERIA_PATH, "r") as f:
                prior_proposal = f.read()
        except FileNotFoundError:
            prior_proposal = ""

    client = anthropic.Anthropic()
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        messages=[{
            "role": "user",
            "content": f"""You are refining article selection criteria for a daily newsletter digest.

Current criteria:
{current}

Accumulated feedback (each entry has date, slot, score 1-3, and optional note):
{json.dumps(feedback, indent=2)}

Current proposed criteria (if revising an earlier proposal):
{prior_proposal or "(none)"}

Requested modifications from the user:
{modification_note or "(none)"}

Analyze the feedback patterns:
- High scores (3): What patterns should be reinforced?
- Neutral scores (2): What patterns are acceptable but not distinctive?
- Low scores (1): What patterns should be reduced?

Return ONLY valid JSON with this schema:
{{
  "summary": ["short bullet 1", "short bullet 2", "short bullet 3"],
  "proposed_markdown": "# Article Selection Criteria\\n..."
}}

The markdown should keep the same general structure as the current criteria file.
The summary should be concise and describe the highest-impact changes."""
        }],
    )

    payload = None
    for block in response.content:
        if block.type != "text":
            continue
        text = block.text.strip()
        json_match = re.search(r"\{.*\}", text, re.DOTALL)
        if not json_match:
            continue
        try:
            payload = json.loads(json_match.group())
            break
        except json.JSONDecodeError:
            continue

    if not payload:
        print("WARNING: could not parse criteria proposal response")
        return

    proposed_markdown = str(payload.get("proposed_markdown", "")).strip()
    summary = payload.get("summary", [])
    if not proposed_markdown or not isinstance(summary, list):
        print("WARNING: criteria proposal response missing required fields")
        return
    diff_lines = build_criteria_diff_lines(current, proposed_markdown)

    with open(PROPOSED_CRITERIA_PATH, "w") as f:
        f.write(proposed_markdown + "\n")

    proposal_id = datetime.now(timezone.utc).strftime("%Y-%m-%d") + f"-r{revision}"
    if pending:
        state["history"].append({
            **pending,
            "resolved_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "resolution": "superseded" if pending.get("status") == "modification_requested" else pending.get("status"),
        })

    state["pending"] = {
        "proposal_id": proposal_id,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "status": "pending",
        "revision": revision,
        "trigger": trigger,
        "summary": [str(item).strip() for item in summary if str(item).strip()],
        "diff_lines": diff_lines,
        "modification_note": "",
    }
    save_criteria_state(state)
    print(f"Proposed criteria update saved to {PROPOSED_CRITERIA_PATH}")
    notify_criteria_update(state["pending"])


def save_run_artifact(
    run_date: str,
    gmail_items: list[dict],
    tier2_items: list[dict],
    articles: list[dict],
    feedback_info: dict,
):
    section("SAVE RUN ARTIFACT")
    artifact = {
        "run_date": run_date,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "counts": {
            "gmail_items": len(gmail_items),
            "tier2_items": len(tier2_items),
            "selected_articles": len(articles),
        },
        "feedback_summary": {
            "low_score_count": len(feedback_info.get("low_scores", [])),
            "should_rewrite": bool(feedback_info.get("should_rewrite")),
        },
        "articles": articles,
    }
    path = run_artifact_path(run_date)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    save_json(path, artifact)
    print(f"Saved run artifact to {path}")


def save_candidate_artifact(
    run_date: str,
    gmail_items: list[dict],
    tier2_items: list[dict],
    tickers: dict,
):
    section("SAVE CANDIDATE ARTIFACT")
    normalized_gmail, normalized_tier2 = build_structured_candidates(
        gmail_items,
        tier2_items,
        run_date,
        tickers,
    )
    artifact = {
        "run_date": run_date,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "counts": {
            "gmail_candidates": len(normalized_gmail),
            "tier2_candidates": len(normalized_tier2),
            "total_candidates": len(normalized_gmail) + len(normalized_tier2),
        },
        "gmail_candidates": normalized_gmail,
        "tier2_candidates": normalized_tier2,
    }
    path = candidate_artifact_path(run_date)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    save_json(path, artifact)
    print(f"Saved candidate artifact to {path}")


def save_triage_artifact(run_date: str, triage_queue: list[dict]):
    section("SAVE TRIAGE ARTIFACT")
    artifact = {
        "run_date": run_date,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "triage_queue": triage_queue,
    }
    path = triage_artifact_path(run_date)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    save_json(path, artifact)
    print(f"Saved triage artifact to {path}")


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("  📰 DAILY READS AGENT")
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 60)

    # Step 1: Gmail scan
    gmail_items = gmail_scan()

    # Step 2: Tier 2 sources
    tier2_items = tier2_scan()
    tier2_items.extend(rss_scan())

    # Step 3: Feedback check
    feedback_info = feedback_check()

    # Step 3b: Criteria rewrite if enough feedback
    if feedback_info["should_rewrite"]:
        all_feedback = load_json("feedback_log.json", [])
        rewrite_criteria(all_feedback)

    # Step 4: Article selection
    if not gmail_items and not tier2_items:
        print("\nNo items from any source. Exiting.")
        sys.exit(0)

    articles = select_articles(gmail_items, tier2_items, feedback_info)
    if not articles:
        print("\nFirst selection attempt failed validation — retrying...")
        articles = select_articles(gmail_items, tier2_items, feedback_info)
    if not articles:
        print("\nNo valid articles selected after 2 attempts. Exiting.")
        sys.exit(1)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    tickers = load_json("tickers.json", {})
    structured_gmail, structured_tier2 = build_structured_candidates(
        gmail_items,
        tier2_items,
        today,
        tickers,
    )
    triage_queue = build_triage_queue(structured_gmail, structured_tier2, articles)
    always_read = build_always_read(structured_gmail, articles)
    substack_items = substack_scan()
    save_candidate_artifact(today, gmail_items, tier2_items, tickers)
    save_run_artifact(today, gmail_items, tier2_items, articles, feedback_info)
    save_triage_artifact(today, triage_queue)

    # Step 4c: Pre-delivery URL liveness check — catch broken links before
    # they ship. Drops broken URLs from triage/always_read/substack and logs
    # warnings for main-slot articles (dropping those would leave empty slots).
    articles, triage_queue, always_read, substack_items = validate_delivery_urls(
        articles, triage_queue, always_read, substack_items
    )

    # Step 5: Deliver to all channels
    deliver_gmail(articles, triage_queue, always_read, substack_items)
    deliver_slack(articles, triage_queue, always_read, substack_items)
    deliver_pages(articles, triage_queue, always_read, substack_items)
    deliver_ticktick(articles, always_read)
    deliver_log(articles)
    deliver_triage_log(triage_queue)

    print(f"\n{'='*60}")
    print(f"  ✅ Daily Reads complete — {len(articles)} articles delivered")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
