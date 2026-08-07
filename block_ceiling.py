"""Slack Block Kit ceiling guard — VENDORED, deliberately, not a shim to `_shared/`.

This project's digest posts from **GitHub Actions** (`.github/workflows/daily.yml`),
and `<workspace>/_shared/` is a Dropbox sibling that `actions/checkout@v5` does not
fetch. The previous `slack_blocks_client.py` shim inserted `_shared/slack_blocks` on
`sys.path` and imported from there — which works on JP's laptop and **fails on every
CI run**, where `_get()` returned None, `problems()` returned `[]`, and the payload
went out unchunked. The guard was inert in the only place this lane actually posts on
schedule, while the fleet docs recorded daily-reads as covered.

That is the failure this fleet has already paid for once, and the reason the standing
rule is *vendor, don't shim, for CI projects*. `forensic_triage/block_ceiling.py` is
the same decision for the same reason.

WHY THIS LANE NEEDS IT. `main.py` already handles Slack's 3000-chars-per-section limit
via `_split_oversized_section_blocks`, but nothing checked the **50-blocks-per-message**
ceiling — a different limit behind the same opaque `invalid_blocks` rejection. The
digest's block count scales with how many articles were found, so the payload is
largest exactly on the days worth reading.

Canonical implementation + tests: `<workspace>/_shared/slack_blocks/`. If the ceilings
change, fix that copy first; this one is a follower.
"""
from __future__ import annotations

__all__ = [
    "MAX_BLOCKS",
    "MAX_SECTION_CHARS",
    "MAX_HEADER_CHARS",
    "MAX_CONTEXT_ELEMENTS",
    "MAX_TEXT_CHARS",
    "validate_blocks",
    "chunk_blocks",
    "render_blocks_to_text",
    "safe_payloads",
]

__version__ = "1.0.0"

MAX_BLOCKS = 50           # blocks per message — the one that actually bit us
MAX_SECTION_CHARS = 3000  # section text, and each context element
MAX_HEADER_CHARS = 150    # header text
MAX_CONTEXT_ELEMENTS = 10  # elements[] per context block
MAX_TEXT_CHARS = 40000    # top-level `text` (the plain-text fallback)


def validate_blocks(blocks: list[dict]) -> list[str]:
    """Return every Block Kit limit this payload breaks. Empty list == valid.

    Checks the count ceiling first because that is the one that is invisible in any
    single block: every block can be individually legal and the message still rejected.
    """
    problems: list[str] = []

    if not isinstance(blocks, list):
        return [f"payload is {type(blocks).__name__}, expected a list of blocks"]
    if not blocks:
        return ["payload has zero blocks"]
    if len(blocks) > MAX_BLOCKS:
        problems.append(
            f"{len(blocks)} blocks exceeds Slack's limit of {MAX_BLOCKS} per message")

    for i, b in enumerate(blocks):
        if not isinstance(b, dict):
            problems.append(f"block {i}: {type(b).__name__}, expected a dict")
            continue
        btype = b.get("type")
        if not btype:
            problems.append(f"block {i}: missing 'type'")
            continue

        if btype == "section":
            # A section is legal with `fields` and no `text`, so only complain about
            # missing/empty text when there are no fields either.
            txt = (b.get("text") or {}).get("text", "")
            fields = b.get("fields") or []
            if len(txt) > MAX_SECTION_CHARS:
                problems.append(
                    f"block {i} (section): {len(txt)} chars exceeds {MAX_SECTION_CHARS}")
            if not txt.strip() and not fields:
                problems.append(f"block {i} (section): empty text and no fields")
            for j, fl in enumerate(fields):
                ft = (fl or {}).get("text", "")
                if len(ft) > MAX_SECTION_CHARS:
                    problems.append(
                        f"block {i} field {j} (section): {len(ft)} chars "
                        f"exceeds {MAX_SECTION_CHARS}")

        elif btype == "context":
            els = b.get("elements")
            if not els:
                # The single most common Block Kit mistake in this fleet, and Slack
                # rejects the WHOLE message for it.
                problems.append(f"block {i} (context): missing or empty elements[]")
            else:
                if len(els) > MAX_CONTEXT_ELEMENTS:
                    problems.append(
                        f"block {i} (context): {len(els)} elements exceeds "
                        f"{MAX_CONTEXT_ELEMENTS}")
                for j, el in enumerate(els):
                    t = (el or {}).get("text", "")
                    if len(t) > MAX_SECTION_CHARS:
                        problems.append(
                            f"block {i} element {j} (context): {len(t)} chars "
                            f"exceeds {MAX_SECTION_CHARS}")
                    if not t.strip():
                        problems.append(f"block {i} element {j} (context): empty text")

        elif btype == "header":
            txt = (b.get("text") or {}).get("text", "")
            if len(txt) > MAX_HEADER_CHARS:
                problems.append(
                    f"block {i} (header): {len(txt)} chars exceeds {MAX_HEADER_CHARS}")
            if not txt.strip():
                problems.append(f"block {i} (header): empty text")

    return problems


def chunk_blocks(blocks: list[dict], *, max_blocks: int = MAX_BLOCKS) -> list[list[dict]]:
    """Split into messages of at most `max_blocks`, preferring a divider as the seam.

    Splitting rather than truncating is the whole point. Backing up to the last divider
    in the window keeps a table from being cut mid-way; the search floor is the halfway
    point so a divider-sparse payload still makes progress instead of emitting many tiny
    chunks (or, worse, looping forever on a zero-length advance).
    """
    if max_blocks < 1:
        raise ValueError("max_blocks must be >= 1")
    if len(blocks) <= max_blocks:
        return [list(blocks)]

    out: list[list[dict]] = []
    i = 0
    n = len(blocks)
    while i < n:
        end = min(i + max_blocks, n)
        if end < n:
            floor = i + max_blocks // 2
            seam = next((j for j in range(end - 1, floor, -1)
                         if isinstance(blocks[j], dict)
                         and blocks[j].get("type") == "divider"), None)
            if seam is not None:
                end = seam + 1
        out.append(blocks[i:end])
        i = end
    return out


def render_blocks_to_text(blocks: list[dict]) -> str:
    """Flatten Block Kit to plain markdown-ish text for the last-resort fallback.

    Sections keep their mrkdwn (code fences survive), dividers become a rule, context
    elements become quote lines, headers become bold lines.
    """
    parts: list[str] = []
    for b in blocks:
        if not isinstance(b, dict):
            continue
        btype = b.get("type")
        if btype == "divider":
            parts.append("---")
        elif btype == "header":
            t = (b.get("text") or {}).get("text", "")
            if t:
                parts.append(f"*{t}*")
        elif btype == "section":
            t = (b.get("text") or {}).get("text", "")
            if t:
                parts.append(t)
            for fl in b.get("fields") or []:
                ft = (fl or {}).get("text", "")
                if ft:
                    parts.append(ft)
        elif btype == "context":
            for el in b.get("elements") or []:
                t = (el or {}).get("text", "")
                if t:
                    parts.append("> " + t)
    return "\n\n".join(p for p in parts if p) + "\n"


def safe_payloads(blocks: list[dict], fallback_text: str,
                  *, max_blocks: int = MAX_BLOCKS) -> list[dict]:
    """Ready-to-POST payload(s) for `blocks`, split if needed.

    Every payload carries a `text` — Slack uses it for notifications and accessibility,
    and it is what survives if the blocks are rejected. Continuation messages are
    labelled so a reader can tell a 3-part digest from three unrelated posts.
    """
    chunks = chunk_blocks(blocks, max_blocks=max_blocks)
    total = len(chunks)
    payloads = []
    for n, chunk in enumerate(chunks, 1):
        # The FIRST message is not a continuation of anything — labelling it "cont. 1/3"
        # reads as a missing part 0 and makes the reader hunt for a post that never existed.
        text = fallback_text if n == 1 else f"{fallback_text} (cont. {n}/{total})"
        payloads.append({"blocks": chunk, "text": text[:MAX_TEXT_CHARS]})
    return payloads
