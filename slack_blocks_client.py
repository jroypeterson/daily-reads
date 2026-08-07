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

_mod = None
_warned = False


def _get():
    """Return the VENDORED guard. See `block_ceiling.py` for why it is vendored.

    This used to insert `<workspace>/_shared/slack_blocks` on `sys.path`. That
    import succeeds on JP's laptop and fails on **every GitHub Actions run** —
    `actions/checkout@v5` fetches this repo only, and `_shared/` is a Dropbox
    sibling. So in CI, which is where this lane actually posts on schedule,
    `_get()` returned None, `problems()` returned `[]` and `chunk()` handed the
    payload back whole: the ceiling guard was inert precisely where it was
    needed, while the fleet recorded this project as covered.

    Importing a module that ships inside this repo cannot do that.
    """
    global _mod, _warned
    if _mod is not None:
        return _mod
    try:
        import block_ceiling  # vendored, same directory

        _mod = block_ceiling
    except Exception as e:  # noqa: BLE001 — degrade loudly, never gate
        if not _warned:
            print(f"[WARN] vendored block_ceiling unavailable ({e}); "
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
