"""Shared helpers for persisted project state and article identity."""

import hashlib
import json
import os
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
