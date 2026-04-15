"""Weekly health report for the Daily Reads pipeline.

Runs every Friday. Analyzes the past 7 days of artifacts, feedback,
and delivery logs to produce a summary report delivered via Gmail and Slack.

Usage:
    python weekly_report.py
"""

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from sources import SOURCES, get_always_read_names


ARTIFACTS_RUNS = Path("artifacts/runs")
ARTIFACTS_CANDIDATES = Path("artifacts/candidates")
FEEDBACK_LOG = Path("feedback_log.json")
TASTE_EVIDENCE = Path("taste_evidence.json")
VERIFICATION_LOG = Path("artifacts/verification_log.json")
URL_VALIDATION_LOG = Path("artifacts/url_validation_log.json")


def _load_json(path: Path, default=None):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default if default is not None else []


def _past_7_days() -> list[str]:
    today = datetime.now(timezone.utc).date()
    return [(today - timedelta(days=i)).isoformat() for i in range(7)]


def build_report() -> dict:
    """Collect all metrics for the weekly report."""
    dates = _past_7_days()
    report = {
        "period_start": dates[-1],
        "period_end": dates[0],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    # --- Source Health ---
    sources_seen = set()
    source_email_counts: dict[str, int] = {}
    total_gmail = 0
    total_tier2 = 0
    total_selected = 0
    days_with_runs = 0
    articles_per_day = []

    for date in dates:
        run_path = ARTIFACTS_RUNS / f"{date}.json"
        if not run_path.exists():
            continue
        run = _load_json(run_path, {})
        days_with_runs += 1
        counts = run.get("counts", {})
        total_gmail += counts.get("gmail_items", 0)
        total_tier2 += counts.get("tier2_items", 0)
        selected = counts.get("selected_articles", 0)
        total_selected += selected
        articles_per_day.append(selected)

        # Track which sources produced articles
        for article in run.get("articles", []):
            sources_seen.add(article.get("source", ""))

        # Also check candidates for source coverage + per-source email volume
        cand_path = ARTIFACTS_CANDIDATES / f"{date}.json"
        if cand_path.exists():
            cands = _load_json(cand_path, {})
            for c in cands.get("gmail_candidates", []):
                name = c.get("source_name", "")
                sources_seen.add(name)
                source_email_counts[name] = source_email_counts.get(name, 0) + 1

    all_source_names = {s["name"] for s in SOURCES.values()}
    always_read_names = get_always_read_names()
    # sources_seen is populated from both gmail candidates and tier2/RSS
    # items (FDA Press Releases, Hacker News, etc.), so the raw count
    # can exceed the configured total. Only count configured sources
    # against the total.
    active_configured = sources_seen & all_source_names
    missing_sources = sorted(all_source_names - sources_seen)
    missing_always_read = sorted(always_read_names - sources_seen)

    # Build the full source roster, grouped by category, sorted within each
    # group. One entry per unique source name (SOURCES may have multiple
    # sender emails mapping to the same display name, e.g. Bloomberg,
    # The Atlantic).
    roster_by_category: dict[str, list[dict]] = {}
    seen_names: set[str] = set()
    for meta in SOURCES.values():
        name = meta["name"]
        if name in seen_names:
            continue
        seen_names.add(name)
        category = meta.get("category", "other")
        roster_by_category.setdefault(category, []).append({
            "name": name,
            "category": category,
            "frequency": meta.get("frequency", ""),
            "always_read": bool(meta.get("always_read")),
            "active": name in sources_seen,
            "email_count": source_email_counts.get(name, 0),
        })
    for entries in roster_by_category.values():
        entries.sort(key=lambda e: (not e["always_read"], e["name"].lower()))
    # Stable order of categories for rendering
    category_order = [
        "healthcare_daily", "healthcare_weekly", "healthcare_policy",
        "finance_macro", "finance_weekly",
        "tech_ai", "consulting", "broad_curious",
    ]
    ordered_roster: list[tuple[str, list[dict]]] = []
    for cat in category_order:
        if cat in roster_by_category:
            ordered_roster.append((cat, roster_by_category.pop(cat)))
    for cat in sorted(roster_by_category):
        ordered_roster.append((cat, roster_by_category[cat]))

    report["source_health"] = {
        "active_sources": len(active_configured),
        "total_configured": len(all_source_names),
        "missing_sources": missing_sources,
        "missing_always_read": missing_always_read,
        "total_gmail_items": total_gmail,
        "total_tier2_items": total_tier2,
        "days_with_runs": days_with_runs,
        "roster": ordered_roster,
    }

    # --- Selection Quality ---
    verification = _load_json(VERIFICATION_LOG, [])
    week_verifications = [v for v in verification if v.get("date") in dates]

    verified_pass = sum(1 for v in week_verifications if v.get("passed"))
    verified_fail = sum(1 for v in week_verifications if not v.get("passed"))
    fail_reasons = [v.get("reason", "") for v in week_verifications if not v.get("passed")]

    # Extraction tier usage
    tier_counts = {"trafilatura": 0, "jina": 0, "tavily": 0, "snippet_fallback": 0}
    for v in week_verifications:
        tier = v.get("extraction_tier", "")
        if tier in tier_counts:
            tier_counts[tier] += 1

    report["selection_quality"] = {
        "total_selected": total_selected,
        "articles_per_day": articles_per_day,
        "avg_articles_per_day": round(total_selected / max(days_with_runs, 1), 1),
        "verified_pass": verified_pass,
        "verified_fail": verified_fail,
        "fail_reasons": fail_reasons[:10],
        "extraction_tiers": tier_counts,
    }

    # --- Feedback Loop ---
    feedback = _load_json(FEEDBACK_LOG, [])
    week_feedback = [f for f in feedback if f.get("date") in dates]
    scores = [f.get("score", 0) for f in week_feedback if f.get("score")]
    score_counts = {1: 0, 2: 0, 3: 0}
    for s in scores:
        if s in score_counts:
            score_counts[s] += 1

    avg_score = round(sum(scores) / max(len(scores), 1), 2) if scores else None

    # Prior week for comparison
    prior_dates = [(datetime.now(timezone.utc).date() - timedelta(days=i)).isoformat()
                   for i in range(7, 14)]
    prior_feedback = [f for f in feedback if f.get("date") in prior_dates]
    prior_scores = [f.get("score", 0) for f in prior_feedback if f.get("score")]
    prior_avg = round(sum(prior_scores) / max(len(prior_scores), 1), 2) if prior_scores else None

    # Taste exemplars
    taste = _load_json(TASTE_EVIDENCE, [])
    week_taste = [t for t in taste if t.get("created_at", "")[:10] in dates]
    new_exemplars = sum(1 for t in week_taste if t.get("kind") == "positive_exemplar")

    report["feedback"] = {
        "total_ratings": len(week_feedback),
        "score_counts": score_counts,
        "avg_score": avg_score,
        "prior_week_avg": prior_avg,
        "score_trend": _trend(avg_score, prior_avg),
        "new_taste_exemplars": new_exemplars,
    }

    # --- Always-Read Coverage ---
    always_read_delivered = {}
    for date in dates:
        run_path = ARTIFACTS_RUNS / f"{date}.json"
        if not run_path.exists():
            continue
        run = _load_json(run_path, {})
        for article in run.get("articles", []):
            src = article.get("source", "")
            if src in always_read_names:
                always_read_delivered.setdefault(src, []).append(date)

    report["always_read"] = {
        "delivered": {name: len(days) for name, days in always_read_delivered.items()},
        "missing": sorted(always_read_names - set(always_read_delivered.keys())),
    }

    # --- URL Validation ---
    url_log = _load_json(URL_VALIDATION_LOG, [])
    week_url = [entry for entry in url_log if entry.get("date") in dates]
    total_checked = sum(e.get("checked_slots", 0) for e in week_url)
    surface_totals = {
        "article_warnings": 0,
        "triage_dropped": 0,
        "always_read_dropped": 0,
        "substack_dropped": 0,
    }
    warned_by_source: dict[str, int] = {}
    for entry in week_url:
        broken = entry.get("broken", {})
        for key in surface_totals:
            surface_totals[key] += broken.get(key, 0)
        for warned in entry.get("warned_articles", []):
            src = warned.get("source", "") or "Unknown"
            warned_by_source[src] = warned_by_source.get(src, 0) + 1

    total_broken = sum(surface_totals.values())
    top_warned_sources = sorted(
        warned_by_source.items(), key=lambda kv: -kv[1]
    )[:5]
    report["url_validation"] = {
        "days_logged": len(week_url),
        "checked_slots": total_checked,
        "total_broken": total_broken,
        "surfaces": surface_totals,
        "top_warned_sources": top_warned_sources,
    }

    return report


def _trend(current, prior):
    if current is None or prior is None:
        return "no data"
    diff = current - prior
    if abs(diff) < 0.1:
        return "stable"
    return f"{'up' if diff > 0 else 'down'} {abs(diff):.1f}"


def format_report_text(report: dict) -> str:
    """Format the report as plain text."""
    lines = []
    lines.append(f"DAILY READS — WEEKLY HEALTH REPORT")
    lines.append(f"Period: {report['period_start']} to {report['period_end']}")
    lines.append("")

    # Source Health
    sh = report["source_health"]
    lines.append("SOURCE HEALTH")
    lines.append(f"  Active sources: {sh['active_sources']}/{sh['total_configured']}")
    lines.append(f"  Gmail items ingested: {sh['total_gmail_items']}")
    lines.append(f"  Tier 2 items ingested: {sh['total_tier2_items']}")
    lines.append(f"  Days with successful runs: {sh['days_with_runs']}/7")
    if sh["missing_sources"]:
        lines.append(f"  Missing sources: {', '.join(sh['missing_sources'])}")
    if sh["missing_always_read"]:
        lines.append(f"  MISSING ALWAYS-READ: {', '.join(sh['missing_always_read'])}")
    # Full source roster grouped by category
    roster = sh.get("roster", [])
    if roster:
        lines.append("")
        lines.append("  Sources scanned (by category):")
        for category, entries in roster:
            lines.append(f"    [{category}]")
            for entry in entries:
                marker = "★" if entry["always_read"] else ("•" if entry["active"] else "○")
                count = f" ({entry['email_count']} email{'s' if entry['email_count'] != 1 else ''})" if entry["active"] else " (no emails)"
                lines.append(f"      {marker} {entry['name']}{count}")
        lines.append("    Legend: ★ always-read · • active this week · ○ silent this week")
    lines.append("")

    # Selection Quality
    sq = report["selection_quality"]
    lines.append("SELECTION QUALITY")
    lines.append(f"  Articles delivered: {sq['total_selected']} ({sq['avg_articles_per_day']}/day avg)")
    lines.append(f"  Verification: {sq['verified_pass']} passed, {sq['verified_fail']} failed")
    tiers = sq["extraction_tiers"]
    lines.append(f"  Extraction: trafilatura={tiers['trafilatura']}, jina={tiers['jina']}, tavily={tiers['tavily']}, snippet={tiers['snippet_fallback']}")
    if sq["fail_reasons"]:
        lines.append(f"  Top fail reasons:")
        for reason in sq["fail_reasons"][:5]:
            lines.append(f"    - {reason[:80]}")
    lines.append("")

    # Feedback
    fb = report["feedback"]
    lines.append("FEEDBACK LOOP")
    lines.append(f"  Ratings received: {fb['total_ratings']}")
    sc = fb["score_counts"]
    lines.append(f"  Breakdown: {sc.get(3,0)} strong, {sc.get(2,0)} fine, {sc.get(1,0)} miss")
    if fb["avg_score"]:
        lines.append(f"  Avg score: {fb['avg_score']} (trend: {fb['score_trend']})")
    lines.append(f"  Taste exemplars submitted: {fb['new_taste_exemplars']}")
    lines.append("")

    # Always-Read
    ar = report["always_read"]
    lines.append("ALWAYS-READ COVERAGE")
    for name, count in ar["delivered"].items():
        lines.append(f"  {name}: delivered {count} days")
    if ar["missing"]:
        lines.append(f"  NOT DELIVERED: {', '.join(ar['missing'])}")
    elif not ar["delivered"]:
        lines.append("  No always-read articles delivered this week")
    lines.append("")

    # URL Validation
    uv = report.get("url_validation", {})
    lines.append("URL VALIDATION")
    lines.append(
        f"  Probed: {uv.get('checked_slots', 0)} slots across "
        f"{uv.get('days_logged', 0)}/7 days"
    )
    surf = uv.get("surfaces", {})
    lines.append(
        f"  Broken: {uv.get('total_broken', 0)} "
        f"(main warnings={surf.get('article_warnings', 0)}, "
        f"triage={surf.get('triage_dropped', 0)}, "
        f"always-read={surf.get('always_read_dropped', 0)}, "
        f"substack={surf.get('substack_dropped', 0)})"
    )
    if uv.get("top_warned_sources"):
        lines.append("  Sources shipping broken main-slot URLs:")
        for src, n in uv["top_warned_sources"]:
            lines.append(f"    - {src}: {n} day(s)")
    lines.append("")

    return "\n".join(lines)


def format_report_html(report: dict) -> str:
    """Format the report as HTML for Gmail."""
    sh = report["source_health"]
    sq = report["selection_quality"]
    fb = report["feedback"]
    ar = report["always_read"]
    tiers = sq["extraction_tiers"]
    sc = fb["score_counts"]

    missing_html = ""
    if sh["missing_sources"]:
        missing_html += f'<p style="color: #e94560;">Missing sources: {", ".join(sh["missing_sources"])}</p>'
    if sh["missing_always_read"]:
        missing_html += f'<p style="color: #e94560; font-weight: bold;">Missing always-read: {", ".join(sh["missing_always_read"])}</p>'

    roster_html = ""
    roster = sh.get("roster", [])
    if roster:
        category_blocks = []
        for category, entries in roster:
            rows = []
            for entry in entries:
                if entry["always_read"]:
                    marker = '<span style="color: #ff9800;">★</span>'
                    color = "#e0e0e0"
                elif entry["active"]:
                    marker = '<span style="color: #4caf50;">●</span>'
                    color = "#e0e0e0"
                else:
                    marker = '<span style="color: #666;">○</span>'
                    color = "#a8a8b3"
                count = f' <span style="color: #666; font-size: 12px;">· {entry["email_count"]} email{"s" if entry["email_count"] != 1 else ""}</span>' if entry["active"] else ' <span style="color: #666; font-size: 12px;">· silent</span>'
                rows.append(
                    f'<li style="color: {color}; font-size: 13px; list-style: none; padding: 2px 0;">'
                    f'{marker} {entry["name"]}{count}</li>'
                )
            category_blocks.append(
                f'<p style="color: #a8a8b3; font-size: 12px; margin: 8px 0 2px 0; text-transform: uppercase; letter-spacing: 0.5px;">{category}</p>'
                f'<ul style="margin: 0; padding-left: 12px;">{"".join(rows)}</ul>'
            )
        roster_html = (
            '<details style="margin-top: 12px;"><summary style="cursor: pointer; color: #0fbcf9; font-size: 13px;">Show all sources scanned</summary>'
            '<p style="color: #666; font-size: 11px; margin-top: 6px;">★ always-read · ● active this week · ○ silent this week</p>'
            + "".join(category_blocks)
            + '</details>'
        )

    fail_html = ""
    if sq["fail_reasons"]:
        items = "".join(f"<li>{r[:80]}</li>" for r in sq["fail_reasons"][:5])
        fail_html = f'<p style="margin-top: 8px;">Top fail reasons:</p><ul style="color: #a8a8b3; font-size: 13px;">{items}</ul>'

    ar_html = ""
    for name, count in ar["delivered"].items():
        ar_html += f"<p>{name}: delivered {count} days</p>"
    if ar["missing"]:
        ar_html += f'<p style="color: #e94560; font-weight: bold;">Not delivered: {", ".join(ar["missing"])}</p>'
    elif not ar["delivered"]:
        ar_html += '<p style="color: #e94560;">No always-read articles delivered this week</p>'

    score_trend = ""
    if fb["avg_score"]:
        trend_color = "#4caf50" if "up" in fb["score_trend"] else "#e94560" if "down" in fb["score_trend"] else "#a8a8b3"
        score_trend = f'<p>Avg score: <strong>{fb["avg_score"]}</strong> <span style="color: {trend_color};">({fb["score_trend"]})</span></p>'

    uv = report.get("url_validation", {})
    surf = uv.get("surfaces", {})
    uv_color = "#4caf50" if uv.get("total_broken", 0) == 0 else "#ff9800"
    uv_warned_html = ""
    if uv.get("top_warned_sources"):
        items = "".join(
            f"<li>{src}: {n} day(s)</li>" for src, n in uv["top_warned_sources"]
        )
        uv_warned_html = (
            '<p style="margin-top: 8px;">Sources shipping broken main-slot URLs:</p>'
            f'<ul style="color: #a8a8b3; font-size: 13px;">{items}</ul>'
        )

    return f"""<html><body style="background: #0f0f23; color: #e0e0e0; font-family: -apple-system, sans-serif; padding: 24px; max-width: 700px; margin: 0 auto;">
<h1 style="color: #e94560;">Weekly Health Report</h1>
<p style="color: #666;">{report["period_start"]} to {report["period_end"]}</p>

<div style="background: #16213e; border-radius: 8px; padding: 16px; margin: 16px 0; border-left: 4px solid #0fbcf9;">
  <h3 style="color: #0fbcf9; margin-top: 0;">Source Health</h3>
  <p>Active: <strong>{sh["active_sources"]}/{sh["total_configured"]}</strong> sources</p>
  <p>Gmail: {sh["total_gmail_items"]} items · Tier 2: {sh["total_tier2_items"]} items</p>
  <p>Successful runs: {sh["days_with_runs"]}/7 days</p>
  {missing_html}
  {roster_html}
</div>

<div style="background: #16213e; border-radius: 8px; padding: 16px; margin: 16px 0; border-left: 4px solid #4caf50;">
  <h3 style="color: #4caf50; margin-top: 0;">Selection Quality</h3>
  <p>Delivered: <strong>{sq["total_selected"]}</strong> articles ({sq["avg_articles_per_day"]}/day avg)</p>
  <p>Verification: {sq["verified_pass"]} passed, {sq["verified_fail"]} failed</p>
  <p>Extraction: trafilatura={tiers["trafilatura"]}, jina={tiers["jina"]}, tavily={tiers["tavily"]}, snippet={tiers["snippet_fallback"]}</p>
  {fail_html}
</div>

<div style="background: #16213e; border-radius: 8px; padding: 16px; margin: 16px 0; border-left: 4px solid #ff9800;">
  <h3 style="color: #ff9800; margin-top: 0;">Feedback Loop</h3>
  <p>Ratings: <strong>{fb["total_ratings"]}</strong> — {sc.get(3,0)} strong, {sc.get(2,0)} fine, {sc.get(1,0)} miss</p>
  {score_trend}
  <p>Taste exemplars submitted: {fb["new_taste_exemplars"]}</p>
</div>

<div style="background: #16213e; border-radius: 8px; padding: 16px; margin: 16px 0; border-left: 4px solid #e94560;">
  <h3 style="color: #e94560; margin-top: 0;">Always-Read Coverage</h3>
  {ar_html}
</div>

<div style="background: #16213e; border-radius: 8px; padding: 16px; margin: 16px 0; border-left: 4px solid {uv_color};">
  <h3 style="color: {uv_color}; margin-top: 0;">URL Validation</h3>
  <p>Probed: <strong>{uv.get("checked_slots", 0)}</strong> slots across {uv.get("days_logged", 0)}/7 days</p>
  <p>Broken: <strong>{uv.get("total_broken", 0)}</strong>
     (main warnings={surf.get("article_warnings", 0)},
      triage dropped={surf.get("triage_dropped", 0)},
      always-read dropped={surf.get("always_read_dropped", 0)},
      substack dropped={surf.get("substack_dropped", 0)})</p>
  {uv_warned_html}
</div>

</body></html>"""


def format_report_slack(report: dict) -> list[dict]:
    """Format the report as Slack blocks."""
    sh = report["source_health"]
    sq = report["selection_quality"]
    fb = report["feedback"]
    ar = report["always_read"]
    tiers = sq["extraction_tiers"]
    sc = fb["score_counts"]

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": "Weekly Health Report"}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": f"{report['period_start']} to {report['period_end']}"}]},
        {"type": "divider"},
    ]

    # Source Health
    source_text = (
        f"*Source Health*\n"
        f"Active: *{sh['active_sources']}/{sh['total_configured']}* sources\n"
        f"Gmail: {sh['total_gmail_items']} items · Tier 2: {sh['total_tier2_items']} items\n"
        f"Runs: {sh['days_with_runs']}/7 days"
    )
    if sh["missing_sources"]:
        source_text += f"\n:warning: Missing: {', '.join(sh['missing_sources'])}"
    if sh["missing_always_read"]:
        source_text += f"\n:rotating_light: Missing always-read: {', '.join(sh['missing_always_read'])}"
    blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": source_text}})

    # Full source roster, one Slack section per category. Skip if roster
    # is empty (shouldn't happen in practice).
    roster = sh.get("roster", [])
    if roster:
        roster_header = "*Sources scanned* — ⭐ always-read · ✅ active · ⚪ silent"
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": roster_header}})
        for category, entries in roster:
            lines = []
            for entry in entries:
                if entry["always_read"]:
                    marker = ":star:"
                elif entry["active"]:
                    marker = ":white_check_mark:"
                else:
                    marker = ":white_circle:"
                count = f" ({entry['email_count']})" if entry["active"] and entry["email_count"] else ""
                lines.append(f"{marker} {entry['name']}{count}")
            text = f"_{category}_\n" + "  ·  ".join(lines)
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": text[:2990]},
            })

    # Selection
    sel_text = (
        f"*Selection Quality*\n"
        f"Delivered: *{sq['total_selected']}* articles ({sq['avg_articles_per_day']}/day)\n"
        f"Verification: {sq['verified_pass']} passed, {sq['verified_fail']} failed\n"
        f"Extraction: trafilatura={tiers['trafilatura']}, jina={tiers['jina']}, tavily={tiers['tavily']}, snippet={tiers['snippet_fallback']}"
    )
    blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": sel_text}})

    # Feedback
    score_line = f"{sc.get(3,0)} strong, {sc.get(2,0)} fine, {sc.get(1,0)} miss"
    fb_text = f"*Feedback Loop*\nRatings: *{fb['total_ratings']}* — {score_line}"
    if fb["avg_score"]:
        fb_text += f"\nAvg: {fb['avg_score']} ({fb['score_trend']})"
    fb_text += f"\nTaste exemplars: {fb['new_taste_exemplars']}"
    blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": fb_text}})

    # Always-Read
    ar_lines = [f"{name}: {count} days" for name, count in ar["delivered"].items()]
    ar_text = "*Always-Read Coverage*\n" + ("\n".join(ar_lines) if ar_lines else "No always-read delivered")
    if ar["missing"]:
        ar_text += f"\n:rotating_light: Not delivered: {', '.join(ar['missing'])}"
    blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": ar_text}})

    # URL Validation
    uv = report.get("url_validation", {})
    surf = uv.get("surfaces", {})
    uv_lines = [
        "*URL Validation*",
        f"Probed: *{uv.get('checked_slots', 0)}* slots across {uv.get('days_logged', 0)}/7 days",
        (
            f"Broken: *{uv.get('total_broken', 0)}* "
            f"(main warnings={surf.get('article_warnings', 0)}, "
            f"triage={surf.get('triage_dropped', 0)}, "
            f"always-read={surf.get('always_read_dropped', 0)}, "
            f"substack={surf.get('substack_dropped', 0)})"
        ),
    ]
    if uv.get("top_warned_sources"):
        uv_lines.append(":warning: Sources shipping broken main-slot URLs:")
        for src, n in uv["top_warned_sources"]:
            uv_lines.append(f"  • {src}: {n} day(s)")
    blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(uv_lines)}})

    return blocks


def deliver_gmail(html: str, period: str):
    """Send the report via Gmail."""
    import base64
    from email.mime.text import MIMEText
    from gmail_reader import get_gmail_service

    service = get_gmail_service()
    msg = MIMEText(html, "html")
    msg["to"] = "jroypeterson@gmail.com"
    msg["subject"] = f"Daily Reads — Weekly Report ({period})"
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    service.users().messages().send(userId="me", body={"raw": raw}).execute()
    print("Weekly report sent via Gmail")


def deliver_slack(blocks: list[dict]):
    """Send the report via Slack."""
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook_url:
        print("No SLACK_WEBHOOK_URL — skipping Slack delivery")
        return
    resp = requests.post(webhook_url, json={"blocks": blocks}, timeout=10)
    if resp.ok:
        print("Weekly report sent via Slack")
    else:
        print(f"Slack delivery failed: {resp.status_code} — {resp.text[:200]}")


def main():
    print("Building weekly health report...")
    report = build_report()

    # Save raw report
    os.makedirs("artifacts", exist_ok=True)
    report_path = Path("artifacts") / f"weekly_report_{report['period_end']}.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Saved to {report_path}")

    # Print text version
    text = format_report_text(report)
    print("\n" + text)

    # Deliver
    try:
        html = format_report_html(report)
        deliver_gmail(html, f"{report['period_start']} to {report['period_end']}")
    except Exception as e:
        print(f"Gmail delivery failed: {e}")

    try:
        blocks = format_report_slack(report)
        deliver_slack(blocks)
    except Exception as e:
        print(f"Slack delivery failed: {e}")


if __name__ == "__main__":
    main()
