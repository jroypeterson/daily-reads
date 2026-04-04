"""Sync tickers.json from Coverage Manager coverage_universe_tickers.csv.

Builds an enriched ticker store with:
- Legacy flat buckets (healthcare, tech, other) for backward compat
- Company name → ticker lookup for headline matching
- Subsector grouping for richer signal tagging
"""

import csv
import json
import os
import re
import sys

COVERAGE_CSV = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "Coverage Manager", "coverage_universe_tickers.csv",
)
OUTPUT_PATH = "tickers.json"

SECTOR_TO_BUCKET = {
    "Biopharma": "healthcare",
    "MedTech": "healthcare",
    "Healthcare Services": "healthcare",
    "Healthcare Real Estate": "healthcare",
    "Life Science Tools": "healthcare",
    "Tech": "tech",
    "SaaS": "tech",
    "Fintech": "tech",
    "PA": "other",
    "Other": "other",
}


def load_coverage_csv(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def build_tickers(rows: list[dict]) -> dict:
    # Legacy flat buckets
    buckets: dict[str, list[str]] = {"healthcare": [], "tech": [], "other": []}
    # Company name → ticker mapping for headline matching
    company_lookup: dict[str, str] = {}
    # Subsector → ticker list
    subsectors: dict[str, list[str]] = {}
    # Full ticker detail for enrichment
    details: dict[str, dict] = {}

    for row in rows:
        ticker = (row.get("Ticker") or "").strip()
        if not ticker:
            continue

        sector_jp = (row.get("Sector (JP)") or "").strip()
        subsector_jp = (row.get("Subsector (JP)") or "").strip()
        company = (row.get("Company Name") or "").strip()
        country = (row.get("Country (HQ)") or "").strip()

        bucket = SECTOR_TO_BUCKET.get(sector_jp, "other")
        # Use just the base symbol (strip exchange suffixes for matching)
        base_ticker = ticker.split(".")[0] if "." in ticker else ticker
        base_ticker_upper = base_ticker.upper()

        if base_ticker_upper not in {t.upper() for t in buckets[bucket]}:
            buckets[bucket].append(base_ticker)

        # Company name lookup — use shortened forms for matching
        if company:
            # Store full name
            company_lookup[company.lower()] = ticker
            # Also store first word if it's long enough to be distinctive
            first_word = company.split()[0] if company.split() else ""
            if len(first_word) >= 4 and first_word.lower() not in ("the", "new", "inc", "corp"):
                company_lookup[first_word.lower()] = ticker

        if subsector_jp:
            subsectors.setdefault(subsector_jp, []).append(ticker)

        details[ticker] = {
            "sector": sector_jp,
            "subsector": subsector_jp,
            "company": company,
            "bucket": bucket,
            "country": country,
        }

    # Sort buckets
    for bucket in buckets:
        buckets[bucket].sort()

    return {
        **buckets,
        "company_lookup": company_lookup,
        "subsectors": subsectors,
        "details": details,
        "_source": "coverage_universe_tickers.csv",
        "_ticker_count": len(details),
    }


def main():
    csv_path = COVERAGE_CSV
    if len(sys.argv) > 1:
        csv_path = sys.argv[1]

    if not os.path.exists(csv_path):
        print(f"Coverage CSV not found: {csv_path}")
        sys.exit(1)

    rows = load_coverage_csv(csv_path)
    tickers = build_tickers(rows)

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(tickers, f, indent=2)

    print(f"Synced {tickers['_ticker_count']} tickers to {OUTPUT_PATH}")
    print(f"  healthcare: {len(tickers['healthcare'])}")
    print(f"  tech: {len(tickers['tech'])}")
    print(f"  other: {len(tickers['other'])}")
    print(f"  company names: {len(tickers['company_lookup'])}")
    print(f"  subsectors: {len(tickers['subsectors'])}")


if __name__ == "__main__":
    main()
