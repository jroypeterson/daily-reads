"""Health heartbeat poster for #status-reports.

Implements the health/v1 contract from HEALTH_REPORTING.md (§4.1, §7).
Every daily-reads run posts one short Block Kit message to Slack at end of run,
succeeded or failed.

Spec invariants enforced here:
- Block Kit only ({"text": ...} renders mrkdwn literally on the shared webhook)
- Long error tracebacks split at line boundaries to stay under Slack's 3000-char
  per-section limit
- On Slack POST failure: log full payload, write .health/last_run.json, raise
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import requests

WEBHOOK_ENV = "SLACK_WEBHOOK_STATUS_REPORTS"
TAG = "health/v1"
SLACK_SECTION_LIMIT = 3000
HEALTH_DIR = Path(".health")
FALLBACK_PATH = HEALTH_DIR / "last_run.json"
# Touched on every successful heartbeat post. Workflow's if:always()
# fallback step checks for this — if absent, main.py died before posting
# and the fallback step posts a generic error heartbeat.
SENTINEL_PATH = HEALTH_DIR / "posted"

Status = Literal["ok", "partial", "error"]


@dataclass
class Heartbeat:
    project: str
    status: Status
    cycle: str
    start_time: datetime
    end_time: datetime
    next_expected: str
    counters: list[str] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error_text: str = ""
    run_link: str = ""
    attempt: str = "1"


def _fmt_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _duration(start: datetime, end: datetime) -> str:
    secs = max(0, int((end - start).total_seconds()))
    if secs < 60:
        return f"{secs}s"
    mins, s = divmod(secs, 60)
    if mins < 60:
        return f"{mins}m" if s == 0 else f"{mins}m{s}s"
    h, m = divmod(mins, 60)
    return f"{h}h{m}m"


_STATUS_EMOJI = {"ok": ":white_check_mark:", "partial": ":warning:", "error": ":x:"}


def _build_blocks(hb: Heartbeat) -> tuple[list[dict], str]:
    emoji = _STATUS_EMOJI[hb.status]
    duration = _duration(hb.start_time, hb.end_time)

    header_lines = [
        f"{emoji} *{hb.project} — {hb.status}*  ·  {TAG}",
        f"cycle: {hb.cycle}  ·  attempt: {hb.attempt}",
        f"{_fmt_utc(hb.start_time)} → {_fmt_utc(hb.end_time)} ({duration})",
        f"next expected: {hb.next_expected}",
    ]
    body_parts: list[str] = ["\n".join(header_lines)]

    if hb.counters:
        body_parts.append("*Counters:* " + " · ".join(hb.counters))
    if hb.artifacts:
        body_parts.append("*Artifacts:*\n" + "\n".join(f"  • {a}" for a in hb.artifacts))
    if hb.warnings:
        body_parts.append("*Warnings:*\n" + "\n".join(f"  • {w}" for w in hb.warnings))

    main_text = "\n\n".join(body_parts)
    blocks = _split_long_section(main_text)

    if hb.status != "ok" and hb.error_text:
        err = hb.error_text.strip()
        err_block_text = f"*Error:*\n```\n{err}\n```"
        blocks.extend(_split_long_section(err_block_text))

    if hb.run_link:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": hb.run_link},
        })

    fallback = f"{hb.project} — {hb.status} ({hb.cycle})"
    return blocks, fallback


def _split_long_section(text: str) -> list[dict]:
    """Break text into section blocks under Slack's 3000-char per-section cap.

    Splits at line boundaries so code blocks stay readable.
    """
    if len(text) <= SLACK_SECTION_LIMIT:
        return [{"type": "section", "text": {"type": "mrkdwn", "text": text}}]

    chunks: list[str] = []
    current = ""
    for line in text.split("\n"):
        candidate = line if not current else current + "\n" + line
        if len(candidate) > SLACK_SECTION_LIMIT and current:
            chunks.append(current)
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)
    return [{"type": "section", "text": {"type": "mrkdwn", "text": c}} for c in chunks]


def _write_fallback(payload: dict) -> None:
    FALLBACK_PATH.parent.mkdir(parents=True, exist_ok=True)
    FALLBACK_PATH.write_text(
        json.dumps(payload, indent=2, default=str), encoding="utf-8"
    )


def post_health_to_slack(hb: Heartbeat) -> None:
    """Post a heartbeat. On Slack POST failure: log payload, write fallback,
    raise so CI surfaces a missing-heartbeat signal (per §4.7)."""
    blocks, fallback = _build_blocks(hb)
    payload = {"blocks": blocks, "text": fallback}

    print(f"\n[health/v1] {hb.project} {hb.status} cycle={hb.cycle} attempt={hb.attempt}")
    print(json.dumps(payload, indent=2, default=str))

    webhook_url = os.environ.get(WEBHOOK_ENV)
    if not webhook_url:
        _write_fallback(payload)
        raise RuntimeError(
            f"{WEBHOOK_ENV} not set — wrote payload to {FALLBACK_PATH}"
        )

    try:
        resp = requests.post(webhook_url, json=payload, timeout=10)
        resp.raise_for_status()
    except Exception as e:
        _write_fallback(payload)
        raise RuntimeError(
            f"Slack heartbeat POST failed: {e} — wrote payload to {FALLBACK_PATH}"
        ) from e

    HEALTH_DIR.mkdir(parents=True, exist_ok=True)
    SENTINEL_PATH.write_text(
        f"{hb.cycle} attempt={hb.attempt} status={hb.status}\n", encoding="utf-8"
    )
