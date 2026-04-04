"""RSS feed scanner for Daily Reads tier-2 candidate pipeline."""

import re
import time
from datetime import datetime, timedelta, timezone

import feedparser

RSS_FEEDS = [
    # ── Healthcare / Biotech (Slot 1) ────────────────────────────────────
    {
        "url": "https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/press-releases/rss.xml",
        "name": "FDA Press Releases",
        "category": "healthcare_daily",
        "priority": "high",
        "max_items": 10,
    },
    {
        "url": "https://www.biopharmadive.com/feeds/news/",
        "name": "BioPharma Dive",
        "category": "healthcare_daily",
        "priority": "normal",
        "max_items": 8,
    },
    {
        "url": "https://endpts.com/feed/",
        "name": "Endpoints News",
        "category": "healthcare_daily",
        "priority": "normal",
        "max_items": 8,
    },
    {
        "url": "https://www.statnews.com/feed/",
        "name": "STAT News",
        "category": "healthcare_daily",
        "priority": "normal",
        "max_items": 8,
    },
    {
        "url": "https://lifescivc.com/feed/",
        "name": "Life Sciences VC",
        "category": "healthcare_weekly",
        "priority": "high",
        "max_items": 5,
    },
    # ── Healthcare Services (managed care, hospitals, post-acute, SNFs) ──
    {
        "url": "https://www.beckershospitalreview.com/feed/",
        "name": "Becker's Hospital Review",
        "category": "healthcare_daily",
        "priority": "normal",
        "max_items": 8,
    },
    {
        "url": "https://www.beckerspayer.com/feed/",
        "name": "Becker's Payer Issues",
        "category": "healthcare_daily",
        "priority": "normal",
        "max_items": 8,
    },
    {
        "url": "https://www.fiercehealthcare.com/rss/xml",
        "name": "Fierce Healthcare",
        "category": "healthcare_daily",
        "priority": "normal",
        "max_items": 8,
    },
    {
        "url": "https://thehealthcareblog.com/feed/",
        "name": "The Health Care Blog",
        "category": "healthcare_weekly",
        "priority": "high",
        "max_items": 5,
    },
    {
        "url": "https://kffhealthnews.org/feed/",
        "name": "KFF Health News",
        "category": "healthcare_policy",
        "priority": "normal",
        "max_items": 8,
    },
    # ── Healthcare Policy / CMS ──────────────────────────────────────────
    {
        "url": "https://www.cms.gov/rss/31836",
        "name": "CMS Policy Updates",
        "category": "healthcare_policy",
        "priority": "high",
        "max_items": 10,
    },
    # ── Finance / Markets (Slot 2) ───────────────────────────────────────
    {
        "url": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000664",
        "name": "CNBC Finance",
        "category": "finance_macro",
        "priority": "normal",
        "max_items": 8,
    },
    {
        "url": "https://feeds.marketwatch.com/marketwatch/topstories/",
        "name": "MarketWatch",
        "category": "finance_macro",
        "priority": "normal",
        "max_items": 8,
    },
    {
        "url": "http://www.nytimes.com/services/xml/rss/nyt/Business.xml",
        "name": "NYT Business",
        "category": "finance_macro",
        "priority": "normal",
        "max_items": 8,
    },
    {
        "url": "https://dealbook.nytimes.com/feed/",
        "name": "DealBook",
        "category": "finance_macro",
        "priority": "normal",
        "max_items": 5,
    },
    {
        "url": "https://feeds2.feedburner.com/abnormalreturns",
        "name": "Abnormal Returns",
        "category": "finance_macro",
        "priority": "high",
        "max_items": 5,
    },
    {
        "url": "https://feeds.feedburner.com/TheBigPicture",
        "name": "The Big Picture",
        "category": "finance_macro",
        "priority": "normal",
        "max_items": 5,
    },
    {
        "url": "https://aswathdamodaran.blogspot.com/feeds/posts/default",
        "name": "Musings on Markets",
        "category": "finance_macro",
        "priority": "high",
        "max_items": 3,
    },
    {
        "url": "https://www.thereformedbroker.com/feed/",
        "name": "The Reformed Broker",
        "category": "finance_macro",
        "priority": "normal",
        "max_items": 5,
    },
    {
        "url": "https://feeds.feedburner.com/pehub/blog",
        "name": "PE Hub",
        "category": "finance_macro",
        "priority": "normal",
        "max_items": 5,
    },
    {
        "url": "http://www.economist.com/blogs/freeexchange/index.xml",
        "name": "Economist Free Exchange",
        "category": "finance_macro",
        "priority": "high",
        "max_items": 5,
    },
    {
        "url": "http://www.economist.com/blogs/graphicdetail/index.xml",
        "name": "Economist Graphic Detail",
        "category": "finance_macro",
        "priority": "normal",
        "max_items": 5,
    },
    {
        "url": "https://blogs.cfainstitute.org/investor/feed/atom/",
        "name": "CFA Enterprising Investor",
        "category": "finance_macro",
        "priority": "high",
        "max_items": 5,
    },
    {
        "url": "https://feeds.feedburner.com/marginalrevolution/feed",
        "name": "Marginal Revolution",
        "category": "finance_macro",
        "priority": "normal",
        "max_items": 5,
    },
    # ── Venture Capital / Deep Tech ──────────────────────────────────────
    {
        "url": "https://avc.com/feed/",
        "name": "AVC (Fred Wilson)",
        "category": "finance_macro",
        "priority": "high",
        "max_items": 3,
    },
    {
        "url": "http://robgo.org/feed/",
        "name": "ROBGO.ORG",
        "category": "finance_macro",
        "priority": "normal",
        "max_items": 3,
    },
    {
        "url": "https://venturebeat.com/feed/",
        "name": "VentureBeat",
        "category": "tech_ai",
        "priority": "normal",
        "max_items": 5,
    },
    # ── Tech / AI (Slot 3) ───────────────────────────────────────────────
    {
        "url": "http://export.arxiv.org/rss/cs.AI",
        "name": "arXiv cs.AI",
        "category": "tech_ai",
        "priority": "normal",
        "max_items": 5,
    },
    {
        "url": "https://arstechnica.com/ai/feed/",
        "name": "Ars Technica AI",
        "category": "tech_ai",
        "priority": "normal",
        "max_items": 8,
    },
    {
        "url": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
        "name": "The Verge AI",
        "category": "tech_ai",
        "priority": "normal",
        "max_items": 8,
    },
    {
        "url": "https://techcrunch.com/feed/",
        "name": "TechCrunch",
        "category": "tech_ai",
        "priority": "normal",
        "max_items": 8,
    },
    {
        "url": "https://feeds.wired.com/wired/index",
        "name": "Wired",
        "category": "tech_ai",
        "priority": "normal",
        "max_items": 5,
    },
    {
        "url": "http://www.nytimes.com/services/xml/rss/nyt/Technology.xml",
        "name": "NYT Technology",
        "category": "tech_ai",
        "priority": "normal",
        "max_items": 5,
    },
    {
        "url": "https://blog.google/technology/ai/rss/",
        "name": "Google AI Blog",
        "category": "tech_ai",
        "priority": "high",
        "max_items": 5,
    },
    # ── Wildcard / Curiosity (Slot 4) ────────────────────────────────────
    {
        "url": "https://nautil.us/feed/",
        "name": "Nautilus",
        "category": "broad_curious",
        "priority": "high",
        "max_items": 5,
    },
    {
        "url": "https://api.quantamagazine.org/feed/",
        "name": "Quanta Magazine",
        "category": "broad_curious",
        "priority": "high",
        "max_items": 5,
    },
    {
        "url": "https://lesswrong.com/.rss",
        "name": "Less Wrong",
        "category": "broad_curious",
        "priority": "normal",
        "max_items": 5,
    },
    {
        "url": "https://mathbabe.org/feed/",
        "name": "mathbabe",
        "category": "broad_curious",
        "priority": "normal",
        "max_items": 3,
    },
]

STRIP_HTML_RE = re.compile(r"<[^>]+>")
MAX_TOTAL_ITEMS = 60


def _entry_published_time(entry) -> datetime | None:
    """Extract a timezone-aware datetime from a feed entry."""
    for attr in ("published_parsed", "updated_parsed"):
        parsed = getattr(entry, attr, None)
        if parsed:
            try:
                return datetime(*parsed[:6], tzinfo=timezone.utc)
            except (TypeError, ValueError):
                continue
    return None


def _clean_summary(raw: str, limit: int = 300) -> str:
    text = STRIP_HTML_RE.sub("", raw or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def fetch_rss_feeds(hours_back: int = 26) -> list[dict]:
    """Fetch recent entries from all configured RSS feeds.

    Returns items in the same shape as tier2_scan() for seamless pipeline integration.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)
    seen_urls: set[str] = set()
    items: list[dict] = []

    for feed_config in RSS_FEEDS:
        feed_url = feed_config["url"]
        feed_name = feed_config["name"]
        max_items = feed_config.get("max_items", 10)

        try:
            parsed = feedparser.parse(feed_url)
        except Exception as exc:
            print(f"  RSS fetch failed for {feed_name}: {exc}")
            continue

        if parsed.bozo and not parsed.entries:
            print(f"  RSS parse error for {feed_name}: {parsed.bozo_exception}")
            continue

        count = 0
        for entry in parsed.entries:
            if count >= max_items:
                break

            link = (entry.get("link") or "").strip()
            if not link or link in seen_urls:
                continue

            published = _entry_published_time(entry)
            if published and published < cutoff:
                continue

            title = (entry.get("title") or "").strip()
            if not title:
                continue

            seen_urls.add(link)
            items.append({
                "source_name": feed_name,
                "subject": title,
                "snippet": _clean_summary(entry.get("summary", "")),
                "urls": [link],
                "tier": 2,
                "category": feed_config["category"],
                "priority": feed_config["priority"],
                "score": None,
            })
            count += 1

        if count:
            print(f"  {feed_name}: {count} items")

    # Cap total to avoid flooding the selector prompt
    if len(items) > MAX_TOTAL_ITEMS:
        items = items[:MAX_TOTAL_ITEMS]

    return items
