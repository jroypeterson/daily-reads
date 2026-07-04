"""Reusable Readwise REST client — highlight export (v2 API).

Fetch-only module, deliberately free of any taste/preference logic so it can
be reused by other consumers (e.g. a future Anki card pipeline). The taste
mapping lives in process_readwise_exemplars.py.

API: GET https://readwise.io/api/v2/export/ returns highlights grouped by
source document ("book" in Readwise terms — covers articles, books, tweets,
podcasts; the `category` field distinguishes them). Supports incremental sync
via `updatedAfter` (ISO-8601) and pagination via `pageCursor`/`nextPageCursor`.

Auth: static personal token from https://readwise.io/access_token in the
READWISE_TOKEN env var, sent as header `Authorization: Token <token>` — the
same token main.py's deliver_reader uses for the v3 Reader push.

Rate limits: the export endpoint is limited (~20 req/min) and returns
429 + Retry-After when exceeded; _get_page honors it with bounded retries.
"""

import os
import time

import requests

EXPORT_URL = "https://readwise.io/api/v2/export/"
DEFAULT_TIMEOUT = 30
MAX_RETRIES_PER_PAGE = 3
MAX_RETRY_WAIT_SECONDS = 120


class ReadwiseError(Exception):
    """Readwise API request failed after retries."""


class ReadwiseAuthError(ReadwiseError):
    """Token missing/rejected (401/403)."""


def get_token() -> str | None:
    """Return the READWISE_TOKEN env var, or None if unset/blank."""
    token = (os.environ.get("READWISE_TOKEN") or "").strip()
    return token or None


def fetch_export(
    token: str,
    updated_after: str | None = None,
    max_pages: int = 20,
    request_fn=None,
    sleep_fn=time.sleep,
) -> list[dict]:
    """Fetch export records (one dict per source document, each carrying a
    nested `highlights` list).

    updated_after: ISO-8601 timestamp — only documents whose highlights were
    created/updated after this instant are returned (incremental sync).
    max_pages: hard bound on pagination; exceeding it raises ReadwiseError
    rather than silently returning a partial pull.
    request_fn/sleep_fn: injectable for tests.
    """
    if not token:
        raise ReadwiseAuthError("no Readwise token provided")
    request_fn = request_fn or requests.get
    headers = {"Authorization": f"Token {token}"}

    results: list[dict] = []
    cursor = None
    for _ in range(max_pages):
        params: dict = {}
        if updated_after:
            params["updatedAfter"] = updated_after
        if cursor:
            params["pageCursor"] = cursor
        page = _get_page(request_fn, headers, params, sleep_fn)
        results.extend(r for r in page.get("results", []) if isinstance(r, dict))
        cursor = page.get("nextPageCursor")
        if not cursor:
            return results
    raise ReadwiseError(
        f"Readwise export pagination did not terminate within {max_pages} pages "
        "— refusing to return a silently-partial pull"
    )


def _get_page(request_fn, headers: dict, params: dict, sleep_fn) -> dict:
    """GET one export page with retry/backoff on 429 (honoring Retry-After),
    5xx, and network errors. Raises ReadwiseAuthError on 401/403."""
    delay = 5
    last_error = "unknown"
    for attempt in range(MAX_RETRIES_PER_PAGE + 1):
        if attempt:
            sleep_fn(min(delay, MAX_RETRY_WAIT_SECONDS))
            delay *= 2
        try:
            resp = request_fn(EXPORT_URL, headers=headers, params=params, timeout=DEFAULT_TIMEOUT)
        except requests.RequestException as exc:
            last_error = f"network error: {exc}"
            continue

        if resp.status_code in (401, 403):
            raise ReadwiseAuthError(f"Readwise token rejected (HTTP {resp.status_code})")
        if resp.status_code == 429:
            try:
                retry_after = int(resp.headers.get("Retry-After", "") or 0)
            except (TypeError, ValueError):
                retry_after = 0
            delay = max(delay, retry_after or 30)
            last_error = f"rate limited (429, Retry-After={retry_after or 'n/a'})"
            continue
        if resp.status_code >= 500:
            last_error = f"server error (HTTP {resp.status_code})"
            continue
        if resp.status_code != 200:
            raise ReadwiseError(
                f"Readwise export failed: HTTP {resp.status_code} — {resp.text[:200]}"
            )
        try:
            return resp.json()
        except ValueError as exc:
            last_error = f"invalid JSON response: {exc}"
            continue

    raise ReadwiseError(
        f"Readwise export page failed after {MAX_RETRIES_PER_PAGE + 1} attempts — {last_error}"
    )
