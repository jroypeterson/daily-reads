"""Master source list for Daily Reads newsletter scanning."""

SOURCES = {
    # === Healthcare Daily ===
    "noreply@mail.endpts.com": {
        "name": "Endpoints News",
        "email": "noreply@mail.endpts.com",
        "tier": 1,
        "category": "healthcare_daily",
        "frequency": "daily",
        "priority": "normal",
    },
    "newsletters@statnews.com": {
        "name": "STAT News",
        "email": "newsletters@statnews.com",
        "tier": 1,
        "category": "healthcare_daily",
        "frequency": "daily",
        "priority": "normal",
    },
    "news@fiercepharma.com": {
        "name": "Fierce Pharma",
        "email": "news@fiercepharma.com",
        "tier": 1,
        "category": "healthcare_daily",
        "frequency": "daily",
        "priority": "normal",
    },
    "news@fiercebiotech.com": {
        "name": "Fierce Biotech",
        "email": "news@fiercebiotech.com",
        "tier": 1,
        "category": "healthcare_daily",
        "frequency": "daily",
        "priority": "normal",
    },
    "noreply@biopharmadive.com": {
        "name": "BioPharma Dive",
        "email": "noreply@biopharmadive.com",
        "tier": 1,
        "category": "healthcare_daily",
        "frequency": "daily",
        "priority": "normal",
    },
    "noreply@medcitynews.com": {
        "name": "MedCity News",
        "email": "noreply@medcitynews.com",
        "tier": 1,
        "category": "healthcare_daily",
        "frequency": "daily",
        "priority": "normal",
    },
    "newsletters@biospace.com": {
        "name": "BioSpace",
        "email": "newsletters@biospace.com",
        "tier": 1,
        "category": "healthcare_daily",
        "frequency": "daily",
        "priority": "normal",
    },
    # === Healthcare Weekly / Periodic ===
    "noreply@timmermanreport.com": {
        "name": "Timmerman Report",
        "email": "noreply@timmermanreport.com",
        "tier": 1,
        "category": "healthcare_weekly",
        "frequency": "weekly",
        "priority": "high",
    },
    "noreply@biopharmaresearchgroup.substack.com": {
        "name": "BioPharma Research Group",
        "email": "noreply@biopharmaresearchgroup.substack.com",
        "tier": 1,
        "category": "healthcare_weekly",
        "frequency": "weekly",
        "priority": "high",
    },
    "noreply@readerm.substack.com": {
        "name": "Readerm",
        "email": "noreply@readerm.substack.com",
        "tier": 1,
        "category": "healthcare_weekly",
        "frequency": "weekly",
        "priority": "high",
    },
    # === Healthcare Policy ===
    "noreply@kff.org": {
        "name": "KFF Health News",
        "email": "noreply@kff.org",
        "tier": 1,
        "category": "healthcare_policy",
        "frequency": "daily",
        "priority": "normal",
    },
    # === Finance / Macro ===
    "noreply@morningbrew.com": {
        "name": "Morning Brew",
        "email": "noreply@morningbrew.com",
        "tier": 1,
        "category": "finance_macro",
        "frequency": "daily",
        "priority": "normal",
    },
    "noreply@bloombergbriefs.com": {
        "name": "Bloomberg Briefs",
        "email": "noreply@bloombergbriefs.com",
        "tier": 1,
        "category": "finance_macro",
        "frequency": "daily",
        "priority": "normal",
    },
    "newsletters@wsj.com": {
        "name": "WSJ Newsletters",
        "email": "newsletters@wsj.com",
        "tier": 1,
        "category": "finance_macro",
        "frequency": "daily",
        "priority": "normal",
    },
    # === Finance Weekly ===
    "noreply@stratechery.com": {
        "name": "Stratechery",
        "email": "noreply@stratechery.com",
        "tier": 1,
        "category": "finance_weekly",
        "frequency": "weekly",
        "priority": "high",
    },
    # === Tech / AI ===
    "noreply@thesequence.substack.com": {
        "name": "TheSequence",
        "email": "noreply@thesequence.substack.com",
        "tier": 1,
        "category": "tech_ai",
        "frequency": "daily",
        "priority": "normal",
    },
    "noreply@importai.substack.com": {
        "name": "Import AI",
        "email": "noreply@importai.substack.com",
        "tier": 1,
        "category": "tech_ai",
        "frequency": "weekly",
        "priority": "high",
    },
    "noreply@tldrnewsletter.com": {
        "name": "TLDR",
        "email": "noreply@tldrnewsletter.com",
        "tier": 1,
        "category": "tech_ai",
        "frequency": "daily",
        "priority": "normal",
    },
    # === Consulting ===
    "noreply@mckinsey.com": {
        "name": "McKinsey",
        "email": "noreply@mckinsey.com",
        "tier": 1,
        "category": "consulting",
        "frequency": "weekly",
        "priority": "high",
    },
    "noreply@bcg.com": {
        "name": "BCG",
        "email": "noreply@bcg.com",
        "tier": 1,
        "category": "consulting",
        "frequency": "weekly",
        "priority": "high",
    },
    # === Broad / Curiosity ===
    "noreply@nautil.us": {
        "name": "Nautilus",
        "email": "noreply@nautil.us",
        "tier": 1,
        "category": "broad_curious",
        "frequency": "weekly",
        "priority": "high",
    },
    "noreply@theatlantic.com": {
        "name": "The Atlantic",
        "email": "noreply@theatlantic.com",
        "tier": 1,
        "category": "broad_curious",
        "frequency": "daily",
        "priority": "normal",
    },
    # === Always Read (paid subscriptions) ===
    "noreply@maboroshi.substack.com": {
        "name": "MBI",
        "email": "noreply@maboroshi.substack.com",
        "tier": 1,
        "category": "finance_macro",
        "frequency": "weekly",
        "priority": "high",
        "always_read": True,
    },
    "noreply@scuttleblurb.substack.com": {
        "name": "Scuttleblurb",
        "email": "noreply@scuttleblurb.substack.com",
        "tier": 1,
        "category": "finance_macro",
        "frequency": "weekly",
        "priority": "high",
        "always_read": True,
    },
    "noreply@thetranscript.substack.com": {
        "name": "The Transcript",
        "email": "noreply@thetranscript.substack.com",
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
    "noreply@letteraday.substack.com": {
        "name": "A Letter a Day",
        "email": "noreply@letteraday.substack.com",
        "tier": 1,
        "category": "finance_macro",
        "frequency": "daily",
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
