"""Resolve newsletter tracking-redirect URLs to their canonical destinations.

Some newsletter senders (e.g. BioSpace via HubSpot, Endpoints via SendGrid)
wrap every link in a click-tracking redirector. The wrapped URLs are 600+
chars and clutter every downstream surface — Slack, Pages, Gmail, TickTick.

This module follows redirects exactly once per URL, caches the result, and
returns the cleaned canonical URL. On any failure (timeout, non-2xx, network
error) it returns the original URL unchanged so the pipeline never breaks.
"""

from __future__ import annotations

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlsplit

import requests

from gmail_reader import clean_url

CACHE_PATH = "url_resolution_cache.json"

# Hosts whose URLs are click-tracking redirectors AND that resolve cleanly
# via a single HTTP request. Only URLs on these hosts trigger a network
# call — everything else passes through untouched.
#
# NOT included (intentionally):
#   - marketing.biospace.com — HubSpot wraps tracking URLs in a JS
#     bot-detection landing page that blocks server-side resolution.
#     There is no <noscript>, meta-refresh, or canonical URL fallback;
#     defeating it would require a real headless browser. The Slack
#     chunker handles these long URLs downstream as a safety net.
KNOWN_REDIRECTORS = re.compile(
    r"^[a-z0-9]+\.ct\.sendgrid\.net$",
    re.IGNORECASE,
)

REQUEST_TIMEOUT = 4
USER_AGENT = "Mozilla/5.0 (compatible; daily-reads-bot/1.0)"
MAX_WORKERS = 8


def _load_cache() -> dict[str, str]:
    if not os.path.exists(CACHE_PATH):
        return {}
    try:
        with open(CACHE_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_cache(cache: dict[str, str]) -> None:
    try:
        with open(CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2, sort_keys=True)
    except Exception as e:
        print(f"url_resolver: failed to save cache: {e}")


def is_redirector(url: str) -> bool:
    try:
        host = urlsplit(url).netloc
    except Exception:
        return False
    return bool(KNOWN_REDIRECTORS.match(host))


def _resolve_one(url: str) -> str:
    """Follow redirects on a single URL. Returns cleaned final URL or original on failure."""
    headers = {"User-Agent": USER_AGENT}
    try:
        # HEAD is cheaper but some redirectors only honor GET. Try HEAD first.
        resp = requests.head(url, allow_redirects=True, timeout=REQUEST_TIMEOUT, headers=headers)
        if resp.status_code >= 400 or not resp.url or resp.url == url:
            resp = requests.get(
                url, allow_redirects=True, timeout=REQUEST_TIMEOUT, headers=headers, stream=True
            )
            resp.close()
        final = resp.url or url
        if not final.startswith(("http://", "https://")):
            return url
        return clean_url(final)
    except Exception:
        return url


def resolve_urls(urls: list[str]) -> list[str]:
    """Resolve any redirector URLs in the list. Order is preserved.

    URLs not on known redirector hosts pass through untouched. Resolved URLs
    are cached on disk so a given tracking link is only fetched once across
    runs. Failures fall back to the original URL silently.
    """
    if not urls:
        return urls

    cache = _load_cache()
    to_fetch: list[tuple[int, str]] = []
    resolved: list[str] = list(urls)

    for i, url in enumerate(urls):
        if not is_redirector(url):
            continue
        cached = cache.get(url)
        if cached:
            resolved[i] = cached
            continue
        to_fetch.append((i, url))

    if to_fetch:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = {pool.submit(_resolve_one, url): (i, url) for i, url in to_fetch}
            for fut in as_completed(futures):
                i, original = futures[fut]
                final = fut.result()
                resolved[i] = final
                # Cache regardless of whether resolution actually changed the URL —
                # caching the no-op saves us from re-trying broken redirectors.
                cache[original] = final
        _save_cache(cache)
        changed = sum(1 for i, original in to_fetch if cache.get(original) != original)
        print(f"url_resolver: resolved {changed}/{len(to_fetch)} redirector URLs")

    return resolved
