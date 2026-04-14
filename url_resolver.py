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

# Hosts whose URLs are click-tracking redirectors AND that we attempt to
# resolve with a single HTTP request. Only URLs on these hosts trigger a
# network call — everything else passes through untouched.
#
# NOT included (intentionally):
#   - marketing.biospace.com — HubSpot wraps tracking URLs in a JS
#     bot-detection landing page that blocks server-side resolution.
#     There is no <noscript>, meta-refresh, or canonical URL fallback;
#     defeating it would require a real headless browser. The Slack
#     chunker handles these long URLs downstream as a safety net.
#
# Note: email.mckinsey.com and link.theatlantic.com tokens frequently fail
# to resolve to the real article (token consumed / cookie-gated) and land
# on the publisher homepage or an ad-tracker. We still try to resolve them
# here, but the dead-end check below drops the URL so a broken link never
# ships in the digest.
# Explicit hosts we've confirmed are click-tracking redirectors. Kept for
# readability / debugging; the shape-based pattern below catches most new
# tracker subdomains automatically.
KNOWN_REDIRECTORS = re.compile(
    r"^("
    r"[a-z0-9]+\.ct\.sendgrid\.net"
    r"|email\.mckinsey\.com"
    r"|link\.theatlantic\.com"
    r"|qtx\.omeclk\.com"
    r"|links\.morningbrew\.com"
    r"|links\.message\.bloomberg\.com"
    r"|urldefense\.com"
    r")$",
    re.IGNORECASE,
)

# Shape-based tracker detection. Any URL whose subdomain looks like a
# click/email tracker gets resolution + dead-end checking, regardless of
# whether we've seen the host before. This is what makes the system
# self-healing for new newsletter platforms.
LIKELY_TRACKER_PATTERN = re.compile(
    r"^(links?|email|mail|trk|click|go|m|r|cl|e)\d*\.[a-z0-9-]+\.[a-z]{2,}$",
    re.IGNORECASE,
)

# Ad-tech tracker hosts — if a redirector resolves to one of these, the
# URL never leads to a readable article. Dropped.
DEAD_END_HOSTS = re.compile(
    r"^(www\.)?(p\.)?liadm\.com$|\.liadm\.com$",
    re.IGNORECASE,
)

REQUEST_TIMEOUT = 6
# Use a realistic browser UA — some tracking redirectors bot-sniff and
# return a 200 landing page to the bot UA instead of a 30x to the article.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)
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
    return bool(KNOWN_REDIRECTORS.match(host) or LIKELY_TRACKER_PATTERN.match(host))


def _is_dead_end(final_url: str) -> bool:
    """Return True if a resolved URL is a dead end. Two rules:
      1. Final host is a known ad-tracker (liadm.com family, etc.).
      2. Final path is empty or `/` — a redirector that lands on the bare
         publisher homepage has lost the article reference by definition.

    Rule 2 is intentionally generic: it catches McKinsey, Fierce, and any
    future publisher whose tokens get consumed/expire — no per-host config.
    """
    try:
        parsed = urlsplit(final_url)
    except Exception:
        return False
    host = parsed.netloc.lower()
    path = parsed.path or "/"
    if DEAD_END_HOSTS.search(host):
        return True
    if path in ("", "/"):
        return True
    return False


# Status codes that mean "URL is definitely broken". 401/403 are treated as
# OK because they're paywalls (Bloomberg, WSJ, FT) — the URL itself is valid
# and the user can access it with their subscription.
HARD_FAILURE_CODES = {404, 410}


def check_url_live(url: str, timeout: int = 3) -> bool:
    """Quick liveness probe used right before delivery.

    Returns False only for confident failures (404/410, DNS/connection
    errors). Timeouts, 5xx, and other ambiguous responses return True so
    bot-walled sites (STAT, BioSpace) aren't accidentally dropped — the
    user can still click through in their browser.
    """
    if not url or not url.startswith(("http://", "https://")):
        return False
    headers = {"User-Agent": USER_AGENT}
    try:
        resp = requests.head(url, allow_redirects=True, timeout=timeout, headers=headers)
        if resp.status_code == 405:  # Method Not Allowed — retry with GET
            resp = requests.get(
                url, allow_redirects=True, timeout=timeout, headers=headers, stream=True
            )
            resp.close()
        return resp.status_code not in HARD_FAILURE_CODES
    except requests.exceptions.Timeout:
        return True  # unknown — don't drop on bot-walled sites
    except requests.exceptions.ConnectionError:
        return False  # DNS fail / connection refused = broken
    except Exception:
        return True  # unknown error — conservative: keep the URL


def check_urls_live(urls: list[str], timeout: int = 3) -> dict[str, bool]:
    """Parallel liveness probe. Returns {url: is_live} for each input URL."""
    if not urls:
        return {}
    results: dict[str, bool] = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(check_url_live, u, timeout): u for u in urls}
        for fut in as_completed(futures):
            url = futures[fut]
            try:
                results[url] = fut.result()
            except Exception:
                results[url] = True
    return results


def _resolve_one(url: str) -> str:
    """Follow redirects on a single URL. Returns cleaned final URL, empty
    string if the redirector resolves to a dead end, or the original URL on
    transport failure."""
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
        if _is_dead_end(final):
            return ""
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
                # Empty string = dead-end (cached too, so we don't retry).
                cache[original] = final
        _save_cache(cache)
        changed = sum(
            1 for _, original in to_fetch
            if cache.get(original) and cache.get(original) != original
        )
        dead = sum(1 for _, original in to_fetch if cache.get(original) == "")
        print(
            f"url_resolver: resolved {changed}/{len(to_fetch)} redirector URLs"
            + (f" ({dead} dead-end dropped)" if dead else "")
        )

    # Drop dead-end URLs (empty strings) from the final list.
    return [u for u in resolved if u]
