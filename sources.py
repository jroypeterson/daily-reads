"""Master source list for Daily Reads newsletter scanning."""

SOURCES = {
    # === Healthcare Daily ===
    # NOTE: Endpoints News — no emails found in Gmail. Subscribed?
    # "noreply@mail.endpts.com": {
    #     "name": "Endpoints News",
    #     "email": "noreply@mail.endpts.com",
    #     "tier": 1,
    #     "category": "healthcare_daily",
    #     "frequency": "daily",
    #     "priority": "normal",
    # },
    "newsletter@statnews.com": {
        "name": "STAT News",
        "email": "newsletter@statnews.com",
        "tier": 1,
        "category": "healthcare_daily",
        "frequency": "daily",
        "priority": "normal",
    },
    "editors@go.fiercepharma.com": {
        "name": "Fierce Pharma",
        "email": "editors@go.fiercepharma.com",
        "tier": 1,
        "category": "healthcare_daily",
        "frequency": "daily",
        "priority": "normal",
    },
    "editors@go.fiercebiotech.com": {
        "name": "Fierce Biotech",
        "email": "editors@go.fiercebiotech.com",
        "tier": 1,
        "category": "healthcare_daily",
        "frequency": "daily",
        "priority": "normal",
    },
    # NOTE: BioPharma Dive — no emails found in Gmail. Subscribed?
    # "noreply@biopharmadive.com": {
    #     "name": "BioPharma Dive",
    #     "email": "noreply@biopharmadive.com",
    #     "tier": 1,
    #     "category": "healthcare_daily",
    #     "frequency": "daily",
    #     "priority": "normal",
    # },
    # NOTE: MedCity News — no emails found in Gmail. Subscribed?
    # "noreply@medcitynews.com": {
    #     "name": "MedCity News",
    #     "email": "noreply@medcitynews.com",
    #     "tier": 1,
    #     "category": "healthcare_daily",
    #     "frequency": "daily",
    #     "priority": "normal",
    # },
    "newsletters@biospace.com": {
        "name": "BioSpace",
        "email": "newsletters@biospace.com",
        "tier": 1,
        "category": "healthcare_daily",
        "frequency": "daily",
        "priority": "normal",
    },
    # === Healthcare Weekly / Periodic ===
    # NOTE: Timmerman Report — no emails found in Gmail. Subscribed?
    # "noreply@timmermanreport.com": {
    #     "name": "Timmerman Report",
    #     "email": "noreply@timmermanreport.com",
    #     "tier": 1,
    #     "category": "healthcare_weekly",
    #     "frequency": "weekly",
    #     "priority": "high",
    # },
    # NOTE: BioPharma Research Group — no emails found in Gmail. Subscribed?
    # "noreply@biopharmaresearchgroup.substack.com": {
    #     "name": "BioPharma Research Group",
    #     "email": "noreply@biopharmaresearchgroup.substack.com",
    #     "tier": 1,
    #     "category": "healthcare_weekly",
    #     "frequency": "weekly",
    #     "priority": "high",
    # },
    # NOTE: Readerm — no emails found in Gmail. Subscribed?
    # "noreply@readerm.substack.com": {
    #     "name": "Readerm",
    #     "email": "noreply@readerm.substack.com",
    #     "tier": 1,
    #     "category": "healthcare_weekly",
    #     "frequency": "weekly",
    #     "priority": "high",
    # },
    # === Healthcare Policy ===
    "kff@emails.kff.org": {
        "name": "KFF Health News",
        "email": "kff@emails.kff.org",
        "tier": 1,
        "category": "healthcare_policy",
        "frequency": "daily",
        "priority": "normal",
    },
    # === Finance / Macro ===
    "retailbrew@morningbrew.com": {
        "name": "Morning Brew",
        "email": "retailbrew@morningbrew.com",
        "tier": 1,
        "category": "finance_macro",
        "frequency": "daily",
        "priority": "normal",
    },
    "noreply@news.bloomberg.com": {
        "name": "Bloomberg",
        "email": "noreply@news.bloomberg.com",
        "tier": 1,
        "category": "finance_macro",
        "frequency": "daily",
        "priority": "normal",
    },
    # NOT a daily newsletter — this is Bloomberg's subscription/marketing stream
    # ("Welcome to Bloomberg.com", "Final Reminder: Save 60%"), which started at a
    # 2026-07-22 signup and went quiet on 07-24 when the promo ended. Declaring it
    # `daily` made the Source Audit fire a stale warning every single day (board #273,
    # identically on 08-01/02/03) for a source that is behaving exactly as expected.
    #
    # The audit is already cadence-aware; the bug was purely this declaration. The REAL
    # Bloomberg feed is `noreply@news.bloomberg.com` below, which is healthy — 40
    # messages in the 8 days to 2026-08-04, max gap 1 day, Money Stuff and the rest.
    # So #273's "broken subscription, re-subscribe" reading was wrong in both halves:
    # nothing is broken, and re-subscribing would have changed nothing.
    "subscriptions@message.bloomberg.com": {
        "name": "Bloomberg (subscription notices)",
        "email": "subscriptions@message.bloomberg.com",
        "tier": 1,
        "category": "finance_macro",
        "frequency": "monthly",
        "priority": "normal",
    },
    "access@interactive.wsj.com": {
        "name": "WSJ Newsletters",
        "email": "access@interactive.wsj.com",
        "tier": 1,
        "category": "finance_macro",
        "frequency": "daily",
        "priority": "normal",
    },
    # === Finance Weekly ===
    "email@stratechery.com": {
        "name": "Stratechery",
        "email": "email@stratechery.com",
        "tier": 1,
        "category": "finance_weekly",
        "frequency": "weekly",
        "priority": "high",
    },
    # === Tech / AI ===
    # NOTE: TheSequence — no emails found in Gmail. Subscribed?
    # "noreply@thesequence.substack.com": {
    #     "name": "TheSequence",
    #     "email": "noreply@thesequence.substack.com",
    #     "tier": 1,
    #     "category": "tech_ai",
    #     "frequency": "daily",
    #     "priority": "normal",
    # },
    # NOTE: Import AI — no emails found in Gmail. Subscribed?
    # "noreply@importai.substack.com": {
    #     "name": "Import AI",
    #     "email": "noreply@importai.substack.com",
    #     "tier": 1,
    #     "category": "tech_ai",
    #     "frequency": "weekly",
    #     "priority": "high",
    # },
    # NOTE: TLDR — no emails found in Gmail. Subscribed?
    # "noreply@tldrnewsletter.com": {
    #     "name": "TLDR",
    #     "email": "noreply@tldrnewsletter.com",
    #     "tier": 1,
    #     "category": "tech_ai",
    #     "frequency": "daily",
    #     "priority": "normal",
    # },
    # === Consulting ===
    "publishing@email.mckinsey.com": {
        "name": "McKinsey",
        "email": "publishing@email.mckinsey.com",
        "tier": 1,
        "category": "consulting",
        "frequency": "weekly",
        "priority": "high",
    },
    "bostonconsultinggroup@bcg.com": {
        "name": "BCG",
        "email": "bostonconsultinggroup@bcg.com",
        "tier": 1,
        "category": "consulting",
        "frequency": "weekly",
        "priority": "high",
    },
    # === Broad / Curiosity ===
    # NOTE: Nautilus — no emails found in Gmail. Subscribed?
    # "noreply@nautil.us": {
    #     "name": "Nautilus",
    #     "email": "noreply@nautil.us",
    #     "tier": 1,
    #     "category": "broad_curious",
    #     "frequency": "weekly",
    #     "priority": "high",
    # },
    "email@theatlantic.com": {
        "name": "The Atlantic",
        "email": "email@theatlantic.com",
        "tier": 1,
        "category": "broad_curious",
        "frequency": "daily",
        "priority": "normal",
    },
    "newsletters@theatlantic.com": {
        "name": "The Atlantic",
        "email": "newsletters@theatlantic.com",
        "tier": 1,
        "category": "broad_curious",
        "frequency": "daily",
        "priority": "normal",
    },
    # === Always Read (paid subscriptions) ===
    "mbideepdives@substack.com": {
        "name": "MBI",
        "email": "mbideepdives@substack.com",
        "tier": 1,
        "category": "finance_macro",
        "frequency": "weekly",
        "priority": "high",
        "always_read": True,
    },
    "info@scuttleblurb.com": {
        "name": "Scuttleblurb",
        "email": "info@scuttleblurb.com",
        "tier": 1,
        "category": "finance_macro",
        "frequency": "weekly",
        "priority": "high",
        "always_read": True,
    },
    "thetranscript@substack.com": {
        "name": "The Transcript",
        "email": "thetranscript@substack.com",
        "tier": 1,
        "category": "finance_macro",
        "frequency": "weekly",
        "priority": "high",
        "always_read": True,
    },
    "customerservice@valueinvestorinsight.com": {
        "name": "Value Investors Insight",
        "email": "customerservice@valueinvestorinsight.com",
        "tier": 1,
        "category": "finance_macro",
        "frequency": "monthly",
        "priority": "high",
        "always_read": True,
        # VII sends ~2x more marketing (partner promos, event upsells, podcast
        # cross-promos) than actual content. Whitelist the subject patterns
        # that correspond to real issues/bonuses so promos never reach the
        # digest. Update this list if VII introduces a new issue format.
        "subject_allow": [
            r"^Value Investor Insight New Issue",
            r"^Value Investor Insight Bonus",
            r"^New VII(\s|:)",
        ],
    },
    "aletteraday@substack.com": {
        "name": "A Letter a Day",
        "email": "aletteraday@substack.com",
        "tier": 1,
        "category": "finance_macro",
        "frequency": "daily",
        "priority": "high",
        "always_read": True,
    },
    # Apollo's Daily Spark (Torsten Slok). Added 2026-08-07 on JP's go, filling
    # the one gap the 2026-08-06 commentary audit found: 22 configured sources
    # and ZERO institutional market commentary — no sell-side summary, no
    # asset-manager letter, no bank economics.
    #
    # It was ALREADY ARRIVING and simply unregistered — 25 messages in a 90-day
    # window, so the digest has been ignoring it. Address discovered with
    # `validate_source.py "Slok"`, not guessed: the From header is
    # `Torsten Slok <agm@apollo.com>`, which no amount of reasoning about
    # apollo.com would have produced.
    "agm@apollo.com": {
        "name": "Apollo Daily Spark (Torsten Slok)",
        "email": "agm@apollo.com",
        "tier": 1,
        "category": "finance_macro",
        "frequency": "daily",
        "priority": "normal",
    },
    # Oaktree Insights (Howard Marks memos + the firm's market commentary).
    # JP subscribed 2026-08-07 and confirmed the double opt-in himself.
    #
    # ⚠ The address is INFERRED, not observed on a real issue — the only Oaktree
    # mail that exists so far is the subscription confirmation, from
    # `EmailNotifications@oaktreecapital.com`. That is an alert-SYSTEM address
    # ("Oaktree Email Alert Subscription"), not a one-off transactional sender,
    # so it is the right guess — but it IS a guess, which the Apollo entry above
    # deliberately is not.
    #
    # Safe to register on inference because being wrong is LOUD — but NOT via
    # the weekly report, which is the obvious wrong guess: `monthly` is in
    # `SLOW_CADENCES`, so `classify_missing_sources()` files it under "quiet
    # this week (normal)" every week and never alarms. The lane that catches a
    # genuinely wrong address is the cadence-aware
    # `python validate_source.py --audit`, where monthly means stale at 45 days
    # and **dead at 80**. So a bad address here surfaces in ~3 months, not
    # never — and not next week either. If it fires, re-run
    # `python validate_source.py "Oaktree"` and take the OBSERVED From header,
    # the way Apollo's was found.
    #
    # `monthly` is the closest value the vocabulary has; memos are genuinely
    # irregular (weeks to months apart), so a missed month is not a fault.
    "emailnotifications@oaktreecapital.com": {
        "name": "Oaktree Insights (Howard Marks)",
        "email": "EmailNotifications@oaktreecapital.com",
        "tier": 1,
        "category": "finance_macro",
        "frequency": "monthly",
        "priority": "normal",
    },
    "theprimer@biotechprimer.com": {
        "name": "Biotech Primer",
        "email": "theprimer@biotechprimer.com",
        "tier": 1,
        "category": "healthcare_weekly",
        "frequency": "weekly",
        "priority": "high",
        "always_read": True,
    },
    "msim.fund@morganstanley.com": {
        "name": "Consilient Observer",
        "email": "msim.fund@morganstanley.com",
        "tier": 1,
        "category": "finance_macro",
        "frequency": "monthly",
        "priority": "high",
        "always_read": True,
        # Morgan Stanley Investment Management's fund address sends the
        # Counterpoint Global Insights research (Mauboussin's Consilient
        # Observer series) AND generic fund marketing/factsheets. Whitelist
        # only the research banner so the must-read lane never fills with
        # fund promos (same pattern as the VII entry above).
        "subject_allow": [
            r"Consilient Observer",
            r"Counterpoint Global Insights",
        ],
    },
    # --- Journals (JP 2026-07-06 ask: flag 1-2 must-read articles per issue).
    # Health Affairs: no TOC subscription arrives yet — add its sender here
    # once subscribed (validate_source.py to confirm the address).
    "nejmtoc@n.nejm.org": {
        "name": "NEJM",
        "email": "nejmtoc@n.nejm.org",
        "tier": 1,
        "category": "journals",
        "frequency": "weekly",
        "priority": "high",
    },
    "webmaster@n.nejm.org": {
        "name": "NEJM Weekend Briefing",
        "email": "webmaster@n.nejm.org",
        "tier": 1,
        "category": "journals",
        "frequency": "weekly",
        "priority": "normal",
    },
}


def get_source(email_address: str) -> dict | None:
    """Look up a source by email address (case-insensitive)."""
    return SOURCES.get(email_address.lower())


def get_all_sender_emails() -> list[str]:
    """Return all tracked sender email addresses."""
    return list(SOURCES.keys())


def get_always_read_names() -> set[str]:
    """Return source names marked as always_read."""
    return {s["name"] for s in SOURCES.values() if s.get("always_read")}


def get_journal_source_names() -> set[str]:
    """Return source names in the journals category (NEJM, Health Affairs...)."""
    return {s["name"] for s in SOURCES.values() if s.get("category") == "journals"}
