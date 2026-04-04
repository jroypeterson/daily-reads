"""Summarize Daily Reads history from JSON artifacts."""

from collections import Counter
from pathlib import Path

from project_data import load_json


def list_artifact_files(subdir: str):
    path = Path("artifacts") / subdir
    if not path.exists():
        return []
    return sorted(p for p in path.glob("*.json") if p.is_file())


def summarize_run_artifacts():
    run_files = list_artifact_files("runs")
    if not run_files:
        return {
            "run_count": 0,
            "selected_articles": 0,
            "dates": [],
            "by_source": {},
            "by_slot": {},
        }

    by_source = Counter()
    by_slot = Counter()
    selected_articles = 0
    dates = []

    for path in run_files:
        artifact = load_json(str(path), {})
        dates.append(artifact.get("run_date") or path.stem)
        for article in artifact.get("articles", []):
            selected_articles += 1
            by_source[article.get("source", "Unknown")] += 1
            by_slot[str(article.get("slot", "?"))] += 1

    return {
        "run_count": len(run_files),
        "selected_articles": selected_articles,
        "dates": dates,
        "by_source": dict(by_source.most_common(10)),
        "by_slot": dict(sorted(by_slot.items())),
    }


def summarize_candidate_artifacts():
    candidate_files = list_artifact_files("candidates")
    if not candidate_files:
        return {
            "run_count": 0,
            "total_candidates": 0,
            "gmail_candidates": 0,
            "tier2_candidates": 0,
            "by_category": {},
        }

    by_category = Counter()
    total_candidates = 0
    gmail_candidates = 0
    tier2_candidates = 0

    for path in candidate_files:
        artifact = load_json(str(path), {})
        gmail = artifact.get("gmail_candidates", [])
        tier2 = artifact.get("tier2_candidates", [])
        gmail_candidates += len(gmail)
        tier2_candidates += len(tier2)
        total_candidates += len(gmail) + len(tier2)
        for candidate in gmail + tier2:
            by_category[candidate.get("category", "unknown")] += 1

    return {
        "run_count": len(candidate_files),
        "total_candidates": total_candidates,
        "gmail_candidates": gmail_candidates,
        "tier2_candidates": tier2_candidates,
        "by_category": dict(by_category.most_common(10)),
    }


def summarize_triage_artifacts():
    triage_files = list_artifact_files("triage")
    if not triage_files:
        return {
            "run_count": 0,
            "queued_candidates": 0,
            "top_sources": {},
        }

    queued_candidates = 0
    top_sources = Counter()
    for path in triage_files:
        artifact = load_json(str(path), {})
        queue = artifact.get("triage_queue", [])
        queued_candidates += len(queue)
        for candidate in queue:
            top_sources[candidate.get("source_name", "Unknown")] += 1

    return {
        "run_count": len(triage_files),
        "queued_candidates": queued_candidates,
        "top_sources": dict(top_sources.most_common(10)),
    }


def summarize_feedback():
    feedback = load_json("feedback_log.json", [])
    by_channel = Counter()
    by_score = Counter()
    article_feedback = 0

    for entry in feedback:
        by_channel[entry.get("channel") or entry.get("source") or "unknown"] += 1
        by_score[str(entry.get("score", "?"))] += 1
        if entry.get("article_id"):
            article_feedback += 1

    return {
        "feedback_entries": len(feedback),
        "article_linked_entries": article_feedback,
        "by_channel": dict(by_channel),
        "by_score": dict(sorted(by_score.items())),
    }


def summarize_retrospective():
    feedback = load_json("feedback_log.json", [])
    by_slot_scores = {}
    by_source_scores = {}
    miss_notes = Counter()

    for entry in feedback:
        score = entry.get("score")
        slot = entry.get("slot")
        source = entry.get("article_source") or entry.get("headline") or "Unknown"
        if isinstance(slot, int) and isinstance(score, int):
            by_slot_scores.setdefault(str(slot), []).append(score)
        if source and isinstance(score, int):
            by_source_scores.setdefault(source, []).append(score)
        if score == 1:
            note = (entry.get("note") or "").strip()
            if note:
                miss_notes[note] += 1

    def average_map(values_by_key: dict[str, list[int]]) -> dict[str, float]:
        return {
            key: round(sum(values) / len(values), 2)
            for key, values in values_by_key.items()
            if values
        }

    runs = summarize_run_artifacts()
    candidates = summarize_candidate_artifacts()
    selection_rate = 0.0
    if candidates["total_candidates"]:
        selection_rate = round(runs["selected_articles"] / candidates["total_candidates"], 3)

    return {
        "avg_score_by_slot": dict(sorted(average_map(by_slot_scores).items())),
        "avg_score_by_source": dict(
            sorted(
                average_map(by_source_scores).items(),
                key=lambda item: (-item[1], item[0]),
            )[:10]
        ),
        "common_miss_notes": dict(miss_notes.most_common(10)),
        "selection_rate": selection_rate,
    }


def summarize_preferences():
    prefs = load_json("learned_preferences.json", {})
    if not isinstance(prefs, dict):
        return {"updated_at": "unknown", "version": 0, "total_evidence": 0, "by_kind": {}, "topic_count": 0, "avoid_count": 0}
    if prefs.get("version") == 2:
        summary = prefs.get("evidence_summary", {})
        return {
            "updated_at": prefs.get("updated_at", "unknown"),
            "version": 2,
            "total_evidence": summary.get("total", 0),
            "by_kind": summary.get("by_kind", {}),
            "topic_count": len(prefs.get("topic_preferences", [])),
            "avoid_count": len(prefs.get("avoid_patterns", [])),
        }
    # v1 fallback
    evidence = prefs.get("evidence", {})
    return {
        "updated_at": prefs.get("updated_at", "unknown"),
        "version": 1,
        "total_evidence": evidence.get("feedback_entries", 0) + evidence.get("total_positive_exemplars", 0),
        "by_kind": {},
        "topic_count": 0,
        "avoid_count": 0,
    }


def summarize_criteria_state():
    state = load_json("criteria_update_state.json", {})
    if not isinstance(state, dict):
        return {"pending": None, "history_count": 0}
    pending = state.get("pending")
    return {
        "pending": pending.get("proposal_id") if isinstance(pending, dict) else None,
        "history_count": len(state.get("history", [])),
    }


def format_mapping(mapping: dict, empty_label: str) -> str:
    if not mapping:
        return empty_label
    return "\n".join(f"- {key}: {value}" for key, value in mapping.items())


def build_report() -> str:
    runs = summarize_run_artifacts()
    candidates = summarize_candidate_artifacts()
    triage = summarize_triage_artifacts()
    feedback = summarize_feedback()
    retrospective = summarize_retrospective()
    preferences = summarize_preferences()
    criteria = summarize_criteria_state()

    return f"""# Daily Reads History Report

## Runs
- Run artifacts: {runs['run_count']}
- Selected articles across runs: {runs['selected_articles']}
- Run dates: {', '.join(runs['dates']) if runs['dates'] else 'none yet'}

### Selected Sources
{format_mapping(runs['by_source'], '_No run artifacts yet._')}

### Selected Slots
{format_mapping(runs['by_slot'], '_No run artifacts yet._')}

## Candidates
- Candidate artifacts: {candidates['run_count']}
- Total candidates seen: {candidates['total_candidates']}
- Gmail candidates: {candidates['gmail_candidates']}
- Tier 2 candidates: {candidates['tier2_candidates']}

### Candidate Categories
{format_mapping(candidates['by_category'], '_No candidate artifacts yet._')}

## Triage
- Triage artifacts: {triage['run_count']}
- Queued candidates across runs: {triage['queued_candidates']}

### Triage Sources
{format_mapping(triage['top_sources'], '_No triage artifacts yet._')}

## Feedback
- Feedback entries: {feedback['feedback_entries']}
- Entries linked to article IDs: {feedback['article_linked_entries']}

### Feedback By Channel
{format_mapping(feedback['by_channel'], '_No feedback yet._')}

### Feedback By Score
{format_mapping(feedback['by_score'], '_No feedback yet._')}

## Retrospective
- Selection rate: {retrospective['selection_rate']}

### Average Score By Slot
{format_mapping(retrospective['avg_score_by_slot'], '_Not enough scored slot data yet._')}

### Average Score By Source
{format_mapping(retrospective['avg_score_by_source'], '_Not enough scored source data yet._')}

### Recurring Miss Notes
{format_mapping(retrospective['common_miss_notes'], '_No miss notes yet._')}

## Learned Preferences
- Last updated: {preferences['updated_at']}
- Version: {preferences['version']}
- Total evidence records: {preferences['total_evidence']}
- Evidence by kind: {', '.join(f'{k}={v}' for k, v in sorted(preferences['by_kind'].items())) or 'none'}
- Learned topic preferences: {preferences['topic_count']}
- Learned avoid patterns: {preferences['avoid_count']}

## Criteria Review
- Pending proposal: {criteria['pending'] or 'none'}
- Historical proposals tracked: {criteria['history_count']}
"""


def main():
    print(build_report())


if __name__ == "__main__":
    main()
