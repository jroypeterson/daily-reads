"""Build structured learned preferences from unified taste evidence."""

import json
import os
import re
from datetime import datetime, timezone

import requests

from project_data import load_json, load_taste_evidence, save_json, taste_evidence_path

LEARNED_PREFERENCES_JSON_PATH = "learned_preferences.json"
LEARNED_PREFERENCES_MD_PATH = "learned_preferences.md"
TASTE_PROFILE_PATH = "taste_profile.md"

STRENGTH_THRESHOLDS = {"strong": 3, "moderate": 2, "weak": 1}


def _evidence_summary(evidence: list[dict]) -> dict:
    by_kind = {}
    by_channel = {}
    for entry in evidence:
        kind = entry.get("kind", "unknown")
        by_kind[kind] = by_kind.get(kind, 0) + 1
        channel = entry.get("source_channel", "unknown")
        by_channel[channel] = by_channel.get(channel, 0) + 1
    return {"total": len(evidence), "by_kind": by_kind, "by_channel": by_channel}


def _strength_for(positive_count: int, negative_count: int) -> str:
    net = positive_count - negative_count
    if net >= STRENGTH_THRESHOLDS["strong"]:
        return "strong"
    if net >= STRENGTH_THRESHOLDS["moderate"]:
        return "moderate"
    if net >= STRENGTH_THRESHOLDS["weak"]:
        return "weak"
    return "weak"


def fast_update_preferences() -> dict:
    """Lightweight preference recomputation without calling Claude.

    Updates evidence counts and adjusts strength levels on existing preferences.
    Cannot discover new topics/sources/styles — only reinforces or weakens existing ones.
    """
    evidence = load_taste_evidence()
    current = load_json(LEARNED_PREFERENCES_JSON_PATH, {})

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    summary = _evidence_summary(evidence)

    # If there are no existing v2 preferences, build a minimal shell
    if current.get("version") != 2:
        return {
            "version": 2,
            "updated_at": now,
            "topic_preferences": [],
            "source_preferences": [],
            "style_preferences": [],
            "avoid_patterns": [],
            "evidence_summary": summary,
            "score_scale": {"1": "Miss", "2": "Fine", "3": "Strong pick"},
        }

    # Update evidence summary
    current["evidence_summary"] = summary
    current["updated_at"] = now

    # Adjust existing preference strengths based on evidence
    for pref_list_key in ("topic_preferences", "source_preferences", "style_preferences"):
        for pref in current.get(pref_list_key, []):
            name_lower = pref.get("name", "").lower()
            if not name_lower:
                continue
            positive = 0
            negative = 0
            matched_ids = []
            for entry in evidence:
                title = (entry.get("title") or "").lower()
                note = (entry.get("note") or "").lower()
                if name_lower not in title and name_lower not in note:
                    continue
                matched_ids.append(entry.get("id"))
                kind = entry.get("kind", "")
                if kind in ("positive_exemplar", "daily_rating_3"):
                    positive += 1
                elif kind == "daily_rating_1":
                    negative += 1
            if matched_ids:
                pref["strength"] = _strength_for(positive, negative)
                pref["evidence_ids"] = matched_ids
                pref["last_updated"] = now

    # Same for avoid patterns
    for pref in current.get("avoid_patterns", []):
        name_lower = pref.get("name", "").lower()
        if not name_lower:
            continue
        matched_ids = []
        for entry in evidence:
            title = (entry.get("title") or "").lower()
            note = (entry.get("note") or "").lower()
            if name_lower in title or name_lower in note:
                matched_ids.append(entry.get("id"))
        if matched_ids:
            pref["evidence_ids"] = matched_ids
            pref["last_updated"] = now

    return current


def synthesize_preferences() -> dict:
    """Use Claude to derive structured preferences from all taste evidence.

    This is the slow path — called when new exemplars arrive or enough new ratings accumulate.
    """
    evidence = load_taste_evidence()
    current = load_json(LEARNED_PREFERENCES_JSON_PATH, {})
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Build evidence text for Claude
    positive_exemplars = [e for e in evidence if e.get("kind") == "positive_exemplar"]
    strong_picks = [e for e in evidence if e.get("kind") == "daily_rating_3"]
    misses = [e for e in evidence if e.get("kind") == "daily_rating_1"]

    def format_evidence_block(entries: list[dict], label: str) -> str:
        if not entries:
            return f"\n{label}: (none yet)\n"
        lines = [f"\n{label}:"]
        for e in entries:
            line = f"- [{e.get('source_channel', '?')}] \"{e.get('title', 'Untitled')}\""
            if e.get("note"):
                line += f" — {e['note']}"
            excerpt = e.get("metadata", {}).get("extracted_text_preview", "")
            if excerpt and not e.get("note"):
                line += f" — excerpt: {excerpt[:200]}"
            lines.append(line)
        return "\n".join(lines)

    evidence_text = ""
    evidence_text += format_evidence_block(positive_exemplars, "POSITIVE EXEMPLARS (reader submitted these as examples of what they want)")
    evidence_text += format_evidence_block(strong_picks, "STRONG PICKS (articles rated 3/3 in daily digest)")
    evidence_text += format_evidence_block(misses, "MISSES (articles rated 1/3 in daily digest)")

    current_prefs_text = ""
    if current.get("version") == 2:
        current_prefs_text = f"\nCURRENT PREFERENCES (update these, don't start from scratch):\n{json.dumps({k: current.get(k) for k in ('topic_preferences', 'source_preferences', 'style_preferences', 'avoid_patterns')}, indent=2)}\n"

    prompt = f"""You are analyzing reading taste evidence to derive structured content preferences for an investor-oriented reader.

{evidence_text}
{current_prefs_text}
INSTRUCTIONS:
1. If URLs are provided, use web_search to understand the articles' content and themes.
2. Identify patterns across all evidence: topics, sources, writing styles, and things to avoid.
3. Return a JSON object with this exact structure:

{{
  "topic_preferences": [
    {{"name": "short descriptive name", "strength": "strong|moderate|weak", "direction": "positive", "evidence_ids": ["ev_..."]}}
  ],
  "source_preferences": [
    {{"name": "source or publication type", "strength": "strong|moderate|weak", "direction": "positive", "evidence_ids": ["ev_..."]}}
  ],
  "style_preferences": [
    {{"name": "writing style quality", "strength": "strong|moderate|weak", "direction": "positive", "evidence_ids": ["ev_..."]}}
  ],
  "avoid_patterns": [
    {{"name": "pattern to avoid", "strength": "strong|moderate|weak", "direction": "negative", "evidence_ids": ["ev_..."]}}
  ]
}}

RULES:
- Use evidence_ids from the evidence records (ev_... format) to link preferences to evidence
- strength should reflect how much evidence supports this preference
- Keep names concise (2-5 words)
- Only include preferences with actual evidence — do not speculate
- For avoid_patterns, derive from misses and negative signals only
- Output ONLY valid JSON, no markdown fencing, no explanation"""

    try:
        import anthropic
        client = anthropic.Anthropic()
        print("Calling Claude to synthesize preferences...")
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 10}],
            messages=[{"role": "user", "content": prompt}],
        )

        # Extract JSON from response
        response_text = ""
        for block in response.content:
            if block.type == "text":
                response_text += block.text

        # Parse JSON — handle markdown fencing if Claude adds it despite instructions
        response_text = response_text.strip()
        if response_text.startswith("```"):
            response_text = re.sub(r"^```\w*\n?", "", response_text)
            response_text = re.sub(r"\n?```$", "", response_text)

        structured = json.loads(response_text)

        return {
            "version": 2,
            "updated_at": now,
            "topic_preferences": structured.get("topic_preferences", []),
            "source_preferences": structured.get("source_preferences", []),
            "style_preferences": structured.get("style_preferences", []),
            "avoid_patterns": structured.get("avoid_patterns", []),
            "evidence_summary": _evidence_summary(evidence),
            "score_scale": {"1": "Miss", "2": "Fine", "3": "Strong pick"},
            "last_synthesis": now,
        }

    except Exception as exc:
        print(f"Claude synthesis failed: {exc} — falling back to fast update")
        return fast_update_preferences()


def _needs_synthesis(evidence: list[dict], current: dict) -> bool:
    """Check if we should trigger a full Claude synthesis."""
    last_synthesis = current.get("last_synthesis", "")

    # New exemplars since last synthesis
    exemplars_after = sum(
        1 for e in evidence
        if e.get("kind") == "positive_exemplar" and e.get("created_at", "") > last_synthesis
    )
    if exemplars_after > 0:
        return True

    # 5+ new daily ratings since last synthesis
    ratings_after = sum(
        1 for e in evidence
        if e.get("kind", "").startswith("daily_rating_") and e.get("created_at", "") > last_synthesis
    )
    if ratings_after >= 5:
        return True

    return False


def render_preferences_markdown(preferences: dict) -> str:
    summary = preferences.get("evidence_summary", {})
    by_kind = summary.get("by_kind", {})
    by_channel = summary.get("by_channel", {})

    channel_lines = "\n".join(
        f"- {channel}: {count}"
        for channel, count in sorted(by_channel.items())
    ) or "_No evidence channels recorded yet._"

    def render_pref_list(prefs: list[dict], label: str) -> str:
        if not prefs:
            return f"_{label}: No data yet._"
        lines = []
        for p in prefs:
            name = p.get("name", "unnamed")
            strength = p.get("strength", "?")
            direction = p.get("direction", "positive")
            evidence_count = len(p.get("evidence_ids", []))
            lines.append(f"- **{name}** [{strength}, {direction}] ({evidence_count} evidence points)")
        return "\n".join(lines)

    return f"""# Learned Preferences
> Structured preference model. Last updated: {preferences.get('updated_at', 'unknown')}

## Evidence Snapshot
- Total evidence records: {summary.get('total', 0)}
- By kind: {', '.join(f'{k}={v}' for k, v in sorted(by_kind.items())) or 'none'}

### Evidence Channels
{channel_lines}

## Topic Preferences
{render_pref_list(preferences.get('topic_preferences', []), 'Topics')}

## Source Preferences
{render_pref_list(preferences.get('source_preferences', []), 'Sources')}

## Style Preferences
{render_pref_list(preferences.get('style_preferences', []), 'Styles')}

## Avoid Patterns
{render_pref_list(preferences.get('avoid_patterns', []), 'Avoid')}
"""


def _summarize_changes(old: dict, new: dict) -> list[str]:
    """Produce human-readable bullet points describing what changed between two preference snapshots."""
    lines = []

    def names(prefs, key):
        return {p.get("name") for p in prefs.get(key, []) if p.get("name")}

    for key, label in [
        ("topic_preferences", "topic"),
        ("source_preferences", "source"),
        ("style_preferences", "style"),
    ]:
        old_names = names(old, key)
        new_names = names(new, key)
        for name in sorted(new_names - old_names):
            pref = next((p for p in new.get(key, []) if p.get("name") == name), {})
            lines.append(f"New {label} preference: **{name}** [{pref.get('strength', '?')}]")
        for name in sorted(old_names - new_names):
            lines.append(f"Removed {label} preference: {name}")
        for name in sorted(old_names & new_names):
            old_p = next((p for p in old.get(key, []) if p.get("name") == name), {})
            new_p = next((p for p in new.get(key, []) if p.get("name") == name), {})
            if old_p.get("strength") != new_p.get("strength"):
                lines.append(f"{label.title()} **{name}**: {old_p.get('strength')} → {new_p.get('strength')}")

    old_avoid = names(old, "avoid_patterns")
    new_avoid = names(new, "avoid_patterns")
    for name in sorted(new_avoid - old_avoid):
        lines.append(f"New avoid pattern: **{name}**")
    for name in sorted(old_avoid - new_avoid):
        lines.append(f"Removed avoid pattern: {name}")

    if not lines:
        lines.append("Preferences refreshed (no structural changes)")

    return lines


def _notify_synthesis(changes: list[str], preferences: dict):
    """Send email and Slack notifications after a taste synthesis."""
    summary = preferences.get("evidence_summary", {})
    change_text = "\n".join(f"• {line}" for line in changes)
    change_html = "".join(f"<li>{line}</li>" for line in changes)

    subject = f"Taste Preferences Updated — {datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
    html = f"""<html><body style="font-family: -apple-system, sans-serif; max-width: 640px; margin: 0 auto; color: #222; padding: 20px;">
<h1>Taste Preferences Updated</h1>
<p>A synthesis run analyzed your taste evidence and updated learned preferences.</p>
<p><strong>Evidence:</strong> {summary.get('total', 0)} records</p>
<p><strong>Changes:</strong></p>
<ul>{change_html}</ul>
<p>Review the full preference state in <code>learned_preferences.md</code> or the repo.</p>
</body></html>"""

    # Email
    try:
        import base64
        from email.mime.text import MIMEText
        from gmail_reader import get_gmail_service

        service = get_gmail_service()
        msg = MIMEText(html, "html")
        msg["to"] = "jroypeterson@gmail.com"
        msg["subject"] = subject
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        service.users().messages().send(userId="me", body={"raw": raw}).execute()
        print("Taste synthesis email notification sent")
    except Exception as e:
        print(f"Taste synthesis email notification failed: {e}")

    # Slack
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook_url:
        print("No SLACK_WEBHOOK_URL set — skipping taste synthesis Slack notification")
        return

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": "Taste Preferences Updated"}},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*Evidence:* {summary.get('total', 0)} records\n\n"
                    f"*Changes:*\n{change_text}"
                ),
            },
        },
    ]

    try:
        resp = requests.post(webhook_url, json={"blocks": blocks}, timeout=10)
        resp.raise_for_status()
        print("Taste synthesis Slack notification sent")
    except Exception as e:
        print(f"Taste synthesis Slack notification failed: {e}")


def update_learned_preferences():
    """Main entry point: decide between fast update and full synthesis, then write artifacts."""
    evidence = load_taste_evidence()
    current = load_json(LEARNED_PREFERENCES_JSON_PATH, {})
    did_synthesize = False

    if _needs_synthesis(evidence, current) and os.environ.get("ANTHROPIC_API_KEY"):
        preferences = synthesize_preferences()
        did_synthesize = True
    else:
        preferences = fast_update_preferences()

    save_json(LEARNED_PREFERENCES_JSON_PATH, preferences)
    with open(LEARNED_PREFERENCES_MD_PATH, "w", encoding="utf-8") as f:
        f.write(render_preferences_markdown(preferences).strip() + "\n")
    print("learned_preferences.json and learned_preferences.md updated.")

    if did_synthesize:
        changes = _summarize_changes(current, preferences)
        _notify_synthesis(changes, preferences)


if __name__ == "__main__":
    update_learned_preferences()
