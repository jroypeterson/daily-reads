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
    "subscriptions@message.bloomberg.com": {
        "name": "Bloomberg",
        "email": "subscriptions@message.bloomberg.com",
        "tier": 1,
        "category": "finance_macro",
        "frequency": "daily",
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
    # === Always Read: Biotech notes (research-style, not marketing) ===
    "mattbiotech@substack.com": {
        "name": "Matt Gamber's Biotech Newsletter",
        "email": "mattbiotech@substack.com",
        "tier": 1,
        "category": "healthcare_weekly",
        "frequency": "weekly",
        "priority": "high",
        "always_read": True,
    },
    "decodingbio@substack.com": {
        "name": "Decoding Bio",
        "email": "decodingbio@substack.com",
        "tier": 1,
        "category": "healthcare_weekly",
        "frequency": "weekly",
        "priority": "high",
        "always_read": True,
    },
    "ideapharma@substack.com": {
        "name": "Asymmetric Learning (IdeaPharma)",
        "email": "ideapharma@substack.com",
        "tier": 1,
        "category": "healthcare_weekly",
        "frequency": "weekly",
        "priority": "high",
        "always_read": True,
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
