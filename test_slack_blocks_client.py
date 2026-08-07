"""
Tests for the Block Kit ceiling shim (fleet board #268).

`_split_oversized_section_blocks` already handled Slack's 3000-chars-PER-SECTION
limit. Nothing handled the 50-blocks-PER-MESSAGE limit — a different ceiling with
the same opaque `invalid_blocks` error. The digest's block count scales with how
many articles were found, so the payload is biggest on the days worth reading.

The contract that matters most here is the DEGRADATION: if the shared package is
missing, the digest must still go out. A safety net that becomes a new single
point of failure is worse than the bug it catches.
"""

from __future__ import annotations

import sys

import slack_blocks_client as c


def sec(i=0):
    return {"type": "section", "text": {"type": "mrkdwn", "text": f"item {i}"}}


def test_an_oversized_payload_is_named_before_sending():
    problems = c.problems([sec(i) for i in range(137)])
    assert problems and "137 blocks" in problems[0]


def test_a_normal_payload_reports_nothing():
    assert c.problems([sec(i) for i in range(10)]) == []


def test_chunking_loses_no_blocks():
    blocks = [sec(i) for i in range(137)]
    chunks = c.chunk(blocks)
    assert [b for ch in chunks for b in ch] == blocks
    assert all(len(ch) <= 50 for ch in chunks)


def test_a_small_payload_is_one_message():
    """The common case must be byte-identical to the old behaviour."""
    blocks = [sec(i) for i in range(10)]
    assert c.chunk(blocks) == [blocks]


def test_the_guard_is_ACTIVE_without_the_shared_sibling(monkeypatch):
    """The CI condition, and the whole reason the guard was vendored.

    `actions/checkout@v5` fetches this repo only; `<workspace>/_shared/` is a
    Dropbox sibling that does not exist on the runner. The previous shim
    imported from there, so on every CI run the guard silently did nothing —
    `problems()` returned `[]` and `chunk()` returned the payload whole — while
    the fleet docs recorded this project as covered.

    Simulates the runner by removing any `_shared` path and the cached shared
    module, then asserts the guard still WORKS rather than still degrades.
    """
    monkeypatch.setattr(c, "_mod", None)
    monkeypatch.setattr(c, "_warned", False)
    saved_mod = sys.modules.pop("slack_blocks", None)
    saved_path = list(sys.path)
    sys.path[:] = [p for p in sys.path if "_shared" not in p]
    try:
        blocks = [sec(i) for i in range(137)]
        assert c.problems(blocks), "the 50-block ceiling must be REPORTED in CI"
        chunks = c.chunk(blocks)
        assert len(chunks) > 1, "137 blocks must be split, not sent whole"
        assert all(len(ch) <= 50 for ch in chunks)
        assert sum(len(ch) for ch in chunks) == 137, "split, never truncate"
        assert c.to_text(blocks), "text fallback must be available in CI too"
    finally:
        sys.path[:] = saved_path
        if saved_mod is not None:
            sys.modules["slack_blocks"] = saved_mod


def test_it_still_degrades_rather_than_gating_if_the_guard_cannot_load(monkeypatch):
    """The digest going out matters more than the guard running.

    Unchanged contract from the shim era: a safety net that becomes a new
    single point of failure is worse than the bug it catches. Only the failure
    mode is now genuinely exceptional — the module ships in this repo.
    """
    monkeypatch.setattr(c, "_mod", None)
    monkeypatch.setattr(c, "_warned", False)
    saved = sys.modules.pop("block_ceiling", None)
    sys.modules["block_ceiling"] = None   # force the import to raise
    try:
        blocks = [sec(i) for i in range(137)]
        assert c.chunk(blocks) == [blocks]   # unchunked, but NOT dropped
        assert c.problems(blocks) == []      # no false alarm either
        assert c.to_text(blocks) == ""
    finally:
        sys.modules.pop("block_ceiling", None)
        if saved is not None:
            sys.modules["block_ceiling"] = saved


def test_text_fallback_is_available():
    assert "item 1" in c.to_text([sec(1)])
