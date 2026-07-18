"""Shared helpers for persisted project state and article identity."""

import hashlib
import json
import os
from datetime import date, timedelta
from urllib.parse import urlsplit, urlunsplit


def load_json(path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default if default is not None else []


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def normalize_url(url: str) -> str:
    """Normalize URLs enough to create stable article identifiers."""
    parsed = urlsplit((url or "").strip())
    path = parsed.path.rstrip("/") or "/"
    return urlunsplit((
        parsed.scheme.lower(),
        parsed.netloc.lower(),
        path,
        parsed.query,
        "",
    ))


def article_id_for(url: str, source: str = "") -> str:
    normalized = normalize_url(url)
    seed = f"{source.strip().casefold()}|{normalized}"
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16]


def exemplar_id_for(seed: str) -> str:
    return "ex_" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Cross-run delivered-article state
#
# The 7-day Gmail scan window (and persistent RSS feeds) re-surface the same
# candidates on consecutive days, so nothing stopped an already-delivered top
# pick from being selected + shipped again the next morning (verified
# 07-10 + 07-11). We persist the ids of recently delivered articles so the
# selector can skip them. The window is bounded on BOTH axes — a rolling day
# window AND a hard id cap — so the state file can never grow unbounded.
# ---------------------------------------------------------------------------

DELIVERED_STATE_PATH = "delivered_state.json"
DELIVERED_WINDOW_DAYS = 14
DELIVERED_MAX_IDS = 600


def load_delivered_state(path: str = DELIVERED_STATE_PATH) -> dict:
    """Load the rolling delivered-id state. Malformed/legacy files degrade to
    an empty ledger rather than raising."""
    data = load_json(path, {})
    if not isinstance(data, dict):
        return {"delivered": []}
    entries = data.get("delivered")
    if not isinstance(entries, list):
        entries = []
    clean = [
        {"id": e["id"], "date": str(e.get("date", ""))}
        for e in entries
        if isinstance(e, dict) and e.get("id")
    ]
    return {"delivered": clean}


def recently_delivered_ids(
    state: dict, today: str, window_days: int = DELIVERED_WINDOW_DAYS
) -> set:
    """Ids delivered within the last ``window_days`` (inclusive). An entry with
    an unparseable date is treated as recent (conservative: don't re-deliver)."""
    try:
        cutoff = date.fromisoformat(today[:10]) - timedelta(days=window_days)
    except ValueError:
        cutoff = None
    ids: set = set()
    for e in state.get("delivered", []):
        try:
            entry_date = date.fromisoformat(str(e.get("date", ""))[:10])
        except ValueError:
            ids.add(e["id"])
            continue
        if cutoff is None or entry_date >= cutoff:
            ids.add(e["id"])
    return ids


def record_delivered(
    state: dict,
    ids,
    today: str,
    window_days: int = DELIVERED_WINDOW_DAYS,
    max_ids: int = DELIVERED_MAX_IDS,
) -> dict:
    """Append today's delivered ids, then prune the ledger by BOTH the rolling
    day window and the hard id cap so it stays bounded. Returns the state."""
    entries = list(state.get("delivered", []))
    known = {e["id"] for e in entries}
    for _id in ids:
        if _id and _id not in known:
            entries.append({"id": _id, "date": today})
            known.add(_id)

    # Prune by day window.
    try:
        cutoff = date.fromisoformat(today[:10]) - timedelta(days=window_days)
    except ValueError:
        cutoff = None
    if cutoff is not None:
        kept = []
        for e in entries:
            try:
                entry_date = date.fromisoformat(str(e.get("date", ""))[:10])
            except ValueError:
                kept.append(e)  # keep undated rather than silently drop
                continue
            if entry_date >= cutoff:
                kept.append(e)
        entries = kept

    # Bound by id cap (keep the newest by date).
    if len(entries) > max_ids:
        entries.sort(key=lambda e: str(e.get("date", "")))
        entries = entries[-max_ids:]

    state["delivered"] = entries
    return state


def save_delivered_state(state: dict, path: str = DELIVERED_STATE_PATH) -> None:
    save_json(path, state)


def run_artifact_path(run_date: str) -> str:
    return os.path.join("artifacts", "runs", f"{run_date}.json")


def candidate_artifact_path(run_date: str) -> str:
    return os.path.join("artifacts", "candidates", f"{run_date}.json")


def triage_artifact_path(run_date: str) -> str:
    return os.path.join("artifacts", "triage", f"{run_date}.json")


def external_exemplars_path() -> str:
    return "external_exemplars.json"


def taste_evidence_path() -> str:
    return "taste_evidence.json"


def evidence_id_for(seed: str) -> str:
    return "ev_" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16]


def load_taste_evidence() -> list[dict]:
    return load_json(taste_evidence_path(), [])


def append_taste_evidence(records: list[dict]) -> int:
    """Append new evidence records, deduplicating by id. Returns count of new records added."""
    evidence = load_taste_evidence()
    existing_ids = {entry.get("id") for entry in evidence if isinstance(entry, dict)}
    added = 0
    for record in records:
        if record.get("id") not in existing_ids:
            evidence.append(record)
            existing_ids.add(record["id"])
            added += 1
    if added:
        save_json(taste_evidence_path(), evidence)
    return added


def _fix_wsl_path(path: str) -> str:
    """Convert WSL /mnt/c/... paths to Windows C:\\... paths."""
    if path.startswith("/mnt/c/"):
        return "C:\\" + path[7:].replace("/", "\\")
    return path


def migrate_to_taste_evidence() -> None:
    """One-time migration: merge external_exemplars.json + taste_submissions.json into taste_evidence.json."""
    if os.path.exists(taste_evidence_path()):
        return

    evidence = []

    for entry in load_json(external_exemplars_path(), []):
        if not isinstance(entry, dict):
            continue
        legacy_id = entry.get("id", "")
        seed = legacy_id.replace("ex_", "", 1) if legacy_id.startswith("ex_") else legacy_id
        evidence.append({
            "id": evidence_id_for(seed or entry.get("url", "") or entry.get("title", "")),
            "kind": "positive_exemplar",
            "source_channel": entry.get("source_channel", "unknown"),
            "title": entry.get("title", ""),
            "url": entry.get("url", ""),
            "local_path": _fix_wsl_path(entry.get("local_path", "")),
            "note": entry.get("note", ""),
            "score": None,
            "content_status": entry.get("content_status", "unfetched"),
            "metadata": {**entry.get("metadata", {}), "legacy_id": legacy_id},
            "created_at": entry.get("date_added", ""),
        })

    for entry in load_json("taste_submissions.json", []):
        if not isinstance(entry, dict):
            continue
        evidence.append({
            "id": evidence_id_for(f"github-issue|{entry.get('url', '')}"),
            "kind": "positive_exemplar",
            "source_channel": "github_issue",
            "title": entry.get("headline", ""),
            "url": entry.get("url", ""),
            "local_path": "",
            "note": entry.get("note", ""),
            "score": None,
            "content_status": "unfetched",
            "metadata": {"issue_number": entry.get("issue_number"), "legacy_source": "taste_submissions"},
            "created_at": f"{entry.get('date', '')}T00:00:00Z" if entry.get("date") else "",
        })

    save_json(taste_evidence_path(), evidence)
    print(f"Migrated {len(evidence)} records to {taste_evidence_path()}")


def load_run_artifact(run_date: str):
    return load_json(run_artifact_path(run_date), {})


def article_lookup_for_run(run_date: str) -> dict:
    artifact = load_run_artifact(run_date)
    articles = artifact.get("articles", []) if isinstance(artifact, dict) else []
    return {article.get("slot"): article for article in articles if isinstance(article, dict)}


def triage_lookup_for_run(run_date: str) -> dict:
    """Return triage candidates keyed by slot number (5+)."""
    artifact = load_json(triage_artifact_path(run_date), {})
    queue = artifact.get("triage_queue", []) if isinstance(artifact, dict) else []
    return {
        i + 5: candidate
        for i, candidate in enumerate(queue[:10])
        if isinstance(candidate, dict)
    }


def enrich_feedback_entry(run_date: str, slot: int, channel: str, score: int, note: str = "") -> dict:
    if slot <= 4:
        article = article_lookup_for_run(run_date).get(slot, {})
        return {
            "date": run_date,
            "slot": slot,
            "score": score,
            "note": note,
            "channel": channel,
            "article_id": article.get("article_id"),
            "headline": article.get("headline"),
            "url": article.get("url"),
            "article_source": article.get("source"),
        }
    # Slots 5-14 are triage candidates
    candidate = triage_lookup_for_run(run_date).get(slot, {})
    return {
        "date": run_date,
        "slot": slot,
        "score": score,
        "note": note,
        "channel": channel,
        "article_id": candidate.get("article_id") or article_id_for(candidate.get("primary_url", ""), candidate.get("source_name", "")),
        "headline": candidate.get("headline"),
        "url": candidate.get("primary_url"),
        "article_source": candidate.get("source_name"),
    }
