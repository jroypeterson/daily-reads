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


def test_it_degrades_to_sending_unchunked_when_the_package_is_missing(monkeypatch):
    """The digest going out matters more than the guard running."""
    monkeypatch.setattr(c, "_mod", None)
    monkeypatch.setattr(c, "_warned", False)
    monkeypatch.setattr(c, "_PKG_PARENT", c.Path("/nonexistent/slack_blocks"))
    # An earlier test in this session already put the REAL package directory on
    # sys.path and imported it, so patching _PKG_PARENT alone is not enough —
    # `import slack_blocks` would still succeed and the test would silently pass
    # for the wrong reason. Remove both the cached module and the path.
    saved_mod = sys.modules.pop("slack_blocks", None)
    real_parent = str((c.Path(__file__).resolve().parent.parent
                       / "_shared" / "slack_blocks"))
    saved_path = list(sys.path)
    sys.path[:] = [p for p in sys.path if p != real_parent]
    try:
        blocks = [sec(i) for i in range(137)]
        assert c.chunk(blocks) == [blocks]   # unchunked, but NOT dropped
        assert c.problems(blocks) == []      # no false alarm either
        assert c.to_text(blocks) == ""
    finally:
        sys.path[:] = saved_path
        if saved_mod is not None:
            sys.modules["slack_blocks"] = saved_mod


def test_text_fallback_is_available():
    assert "item 1" in c.to_text([sec(1)])
