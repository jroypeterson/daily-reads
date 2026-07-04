"""Ingest Readwise ARTICLE highlights as positive taste exemplars.

An article JP took the trouble to highlight in Readwise is a strong positive
taste signal — stronger than a mere click. This step maps recent Readwise
highlights into `taste_evidence.json` as `kind="positive_exemplar"` records,
the exact shape written by the email/Dropbox/GitHub-issue intake paths, so it
slots into the existing loop with no ranker changes:

    process_readwise_exemplars.py  ──▶  taste_evidence.json
    preference_learning.update_learned_preferences()   (next workflow step;
        any new exemplar triggers a full Claude synthesis)
                                   ──▶  learned_preferences.json
    main.load_learned_preferences_summary()            (ranker prior)

Scope guard: only `category == "articles"` documents enter the article-taste
loop. Books/tweets/podcasts are intentionally excluded — the loop models
*article* taste, and the standing taste_profile.md prior was already seeded
from the full Readwise book library (see CLAUDE.md).

State: `readwise_state.json` persists the incremental `updatedAfter` cursor.
It is committed by the daily workflow so CI runs stay incremental. First run
looks back INITIAL_LOOKBACK_DAYS.

Failure mode: degrade loudly-but-gracefully. A missing/rejected token or API
failure prints a prominent warning AND posts a Block Kit alert to
#status-reports, then exits 0 so the digest still runs without fresh
exemplars. Fetching is done by the reusable readwise_client module.
"""

import os
from datetime import datetime, timedelta, timezone

import requests

from project_data import (
    append_taste_evidence,
    evidence_id_for,
    load_json,
    load_taste_evidence,
    save_json,
)
from readwise_client import ReadwiseAuthError, ReadwiseError, fetch_export, get_token

STATE_PATH = "readwise_state.json"
INITIAL_LOOKBACK_DAYS = 30
# Overlap re-applied to the saved cursor so runner/Readwise clock skew can't
# drop a highlight updated around fetch time; id-dedupe makes overlap harmless.
CURSOR_OVERLAP_MINUTES = 10
# Cap new exemplars per run so one enthusiastic highlighting binge (or the
# first 30-day backfill) doesn't flood the synthesis prompt. Overflow is NOT
# lost: the cursor only advances when nothing was truncated, so the remainder
# drains on subsequent daily runs.
MAX_NEW_EXEMPLARS_PER_RUN = 25
ARTICLE_CATEGORIES = {"articles"}
MAX_PREVIEW_CHARS = 1200  # matches process_exemplar_content.MAX_PREVIEW_CHARS
MAX_NOTE_CHARS = 500  # matches the email intake cap


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def load_state() -> dict:
    state = load_json(STATE_PATH, {})
    return state if isinstance(state, dict) else {}


def default_updated_after() -> str:
    return _iso(_now_utc() - timedelta(days=INITIAL_LOOKBACK_DAYS))


def alarm(message: str) -> None:
    """Loud degradation: print prominently + post to #status-reports."""
    print(f"WARNING: {message}")
    webhook = os.environ.get("SLACK_WEBHOOK_STATUS_REPORTS")
    if not webhook:
        print("  (no SLACK_WEBHOOK_STATUS_REPORTS set — warning is log-only)")
        return
    payload = {
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f":warning: *daily-reads / Readwise taste ingest* — {message}",
                },
            }
        ],
        "text": f"daily-reads Readwise taste ingest: {message}",
    }
    try:
        requests.post(webhook, json=payload, timeout=15).raise_for_status()
    except requests.RequestException as exc:
        print(f"  (Slack alert failed too: {exc})")


def _clean_highlights(doc: dict) -> list[dict]:
    highlights = [
        h
        for h in doc.get("highlights", [])
        if isinstance(h, dict) and (h.get("text") or "").strip() and not h.get("is_discard")
    ]
    highlights.sort(key=lambda h: h.get("highlighted_at") or "")
    return highlights


def build_exemplar(doc: dict, created_at: str) -> dict | None:
    """Map one Readwise export document (an article + its highlights) to a
    taste-evidence record. Returns None when it shouldn't enter the loop."""
    if (doc.get("category") or "").lower() not in ARTICLE_CATEGORIES:
        return None
    highlights = _clean_highlights(doc)
    if not highlights:
        return None

    preview = " […] ".join(" ".join(h["text"].split()) for h in highlights)[:MAX_PREVIEW_CHARS]
    notes = "; ".join(
        " ".join(h["note"].split())
        for h in highlights
        if (h.get("note") or "").strip()
    )[:MAX_NOTE_CHARS]
    url = (doc.get("source_url") or doc.get("unique_url") or "").strip()
    title = (doc.get("readable_title") or doc.get("title") or "(untitled)").strip()

    return {
        "id": evidence_id_for(f"readwise|{doc.get('user_book_id')}"),
        "kind": "positive_exemplar",
        "source_channel": "readwise",
        "title": title,
        "url": url,
        "local_path": "",
        "note": notes,
        "score": None,
        # Highlight text IS the reader-endorsed content — no re-fetch needed.
        "content_status": "extracted" if preview else "unfetched",
        "metadata": {
            "readwise_user_book_id": doc.get("user_book_id"),
            "readwise_category": doc.get("category"),
            "readwise_source": doc.get("source"),
            "author": doc.get("author") or "",
            "highlight_count": len(highlights),
            "latest_highlighted_at": highlights[-1].get("highlighted_at") or "",
            "extracted_text_preview": preview,
            "extracted_at": created_at,
        },
        "created_at": created_at,
    }


def ingest(token: str) -> dict:
    """Pull incremental Readwise highlights and append article exemplars.

    Returns a summary dict (for tests / logging). Raises ReadwiseError /
    ReadwiseAuthError upward — main() converts those to loud-but-graceful.
    """
    state = load_state()
    updated_after = state.get("updated_after") or default_updated_after()
    fetch_start = _now_utc()
    now_iso = _iso(fetch_start)

    print(f"Fetching Readwise highlights updated after {updated_after} ...")
    docs = fetch_export(token, updated_after=updated_after)
    print(f"  {len(docs)} updated document(s) returned")

    existing_ids = {
        e.get("id") for e in load_taste_evidence() if isinstance(e, dict)
    }
    candidates = []
    skipped_non_article = 0
    for doc in docs:
        record = build_exemplar(doc, now_iso)
        if record is None:
            skipped_non_article += 1
            continue
        if record["id"] in existing_ids:
            continue
        candidates.append(record)

    # Newest highlighting activity first; overflow drains on later runs.
    candidates.sort(
        key=lambda r: r["metadata"].get("latest_highlighted_at") or "", reverse=True
    )
    truncated = len(candidates) > MAX_NEW_EXEMPLARS_PER_RUN
    batch = candidates[:MAX_NEW_EXEMPLARS_PER_RUN]

    added = append_taste_evidence(batch)
    for record in batch:
        print(f"  Recorded exemplar: \"{record['title']}\" ({record['metadata']['highlight_count']} highlights)")

    if truncated:
        print(
            f"  NOTE: {len(candidates) - len(batch)} exemplar(s) over the per-run cap "
            f"({MAX_NEW_EXEMPLARS_PER_RUN}) — cursor NOT advanced; they drain next run."
        )
    else:
        cursor = _iso(fetch_start - timedelta(minutes=CURSOR_OVERLAP_MINUTES))
        state["updated_after"] = cursor
    state["last_run_at"] = now_iso
    state["last_run_added"] = added
    save_json(STATE_PATH, state)

    summary = {
        "docs": len(docs),
        "skipped_non_article": skipped_non_article,
        "new_exemplars": added,
        "truncated": truncated,
    }
    print(
        f"Readwise taste ingest: {added} new exemplar(s) "
        f"({skipped_non_article} non-article doc(s) kept out of the article-taste loop)."
    )
    return summary


def main():
    print("=" * 60)
    print("  READWISE TASTE EXEMPLARS")
    print("=" * 60)

    token = get_token()
    if not token:
        alarm(
            "READWISE_TOKEN not set — proceeding WITHOUT Readwise taste exemplars. "
            "Set the `READWISE_TOKEN` GitHub secret (token from "
            "https://readwise.io/access_token)."
        )
        return

    try:
        ingest(token)
    except ReadwiseAuthError:
        alarm(
            "Readwise token rejected (401/403) — taste ingest skipped. Mint a new "
            "token at https://readwise.io/access_token and update the "
            "`READWISE_TOKEN` GitHub secret (and `daily-reads/.env` locally)."
        )
    except ReadwiseError as exc:
        alarm(f"Readwise export failed — taste ingest skipped this run. {exc}")


if __name__ == "__main__":
    main()
