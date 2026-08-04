"""Thin shim to the shared fleet-wide Block Kit ceiling guard.

The logic lives ONCE in `<workspace>/_shared/slack_blocks` (a sibling of this repo).
This file only finds + imports it and degrades loudly when it is missing.

**The degradation is the important part.** A missing guard must never stop a digest
going out — that would turn a safety net into a new single point of failure, which is
strictly worse than the ceiling bug it exists to catch. So `chunk()` falls back to
"send it as one message, exactly as before" and warns once.

Why this project needs it: `main.py` already calls `_split_oversized_section_blocks`,
which handles Slack's 3000-chars-per-section limit — but nothing checks the
**50-blocks-per-message** limit, which is a different ceiling with the same opaque
`invalid_blocks` error. The digest's block count scales with how many articles were
found, so the payload is largest exactly on the days worth reading. The existing error
handler already prints `(had N blocks)`, which is the tell that this has bitten before.
"""
from __future__ import annotations

import sys
from pathlib import Path

_WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
_PKG_PARENT = _WORKSPACE_ROOT / "_shared" / "slack_blocks"

_mod = None
_warned = False


def _get():
    """Import the shared package once; warn (once) and return None if absent."""
    global _mod, _warned
    if _mod is not None:
        return _mod
    try:
        if str(_PKG_PARENT) not in sys.path:
            sys.path.insert(0, str(_PKG_PARENT))
        import slack_blocks  # type: ignore

        _mod = slack_blocks
    except Exception as e:  # noqa: BLE001 — degrade loudly, never gate
        if not _warned:
            print(f"[WARN] shared slack_blocks unavailable ({e}); "
                  f"posting unchunked (Slack may reject >50 blocks)", file=sys.stderr)
            _warned = True
    return _mod


def problems(blocks: list[dict]) -> list[str]:
    """Every Block Kit ceiling this payload breaks. Empty list when fine or unavailable."""
    mod = _get()
    if mod is None:
        return []
    try:
        return mod.validate_blocks(blocks)
    except Exception as e:  # noqa: BLE001
        print(f"[WARN] slack_blocks.validate_blocks failed ({e})", file=sys.stderr)
        return []


def chunk(blocks: list[dict]) -> list[list[dict]]:
    """Split into postable messages. Always returns at least one chunk."""
    mod = _get()
    if mod is None:
        return [blocks]
    try:
        return mod.chunk_blocks(blocks)
    except Exception as e:  # noqa: BLE001
        print(f"[WARN] slack_blocks.chunk_blocks failed ({e}); posting unchunked",
              file=sys.stderr)
        return [blocks]


def to_text(blocks: list[dict]) -> str:
    """Flatten to plain text for a last-resort post. '' when unavailable."""
    mod = _get()
    if mod is None:
        return ""
    try:
        return mod.render_blocks_to_text(blocks)
    except Exception:  # noqa: BLE001
        return ""
