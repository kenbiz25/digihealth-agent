import os
from dotenv import load_dotenv

load_dotenv()

# === AI Model Configuration ===
AI_PROVIDER = os.getenv("AI_PROVIDER", "claude")  # "claude" or "openai"

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# Claude models (recommended)
CLAUDE_MODELS = {
    "fast":     "claude-haiku-4-5-20251001",     # Fast, cheap - good for scraping
    "balanced": "claude-sonnet-4-6",              # Best overall - recommended
    "powerful": "claude-opus-4-6",               # Most capable - use for verification
}

# OpenAI models (alternative)
OPENAI_MODELS = {
    "fast":     "gpt-4o-mini",
    "balanced": "gpt-4o",
    "powerful": "o1",
}

# Active model selection
SCRAPER_MODEL    = os.getenv("SCRAPER_MODEL", "balanced")    # claude model tier
VERIFIER_MODEL   = os.getenv("VERIFIER_MODEL", "powerful")   # needs deep reasoning
ENRICHER_MODEL   = os.getenv("ENRICHER_MODEL", "balanced")
IMPACT_MODEL     = os.getenv("IMPACT_MODEL", "balanced")     # executive impact classification
WRITER_MODEL     = os.getenv("WRITER_MODEL", "balanced")

# === Search / Scraping APIs ===
TAVILY_API_KEY        = os.getenv("TAVILY_API_KEY", "")        # Primary: web+social search
TWITTER_BEARER_TOKEN  = os.getenv("TWITTER_BEARER_TOKEN", "")  # Optional: direct Twitter API
SERPER_API_KEY        = os.getenv("SERPER_API_KEY", "")        # Optional: Google search

# === Scheduling ===
SCHEDULE_HOUR        = int(os.getenv("SCHEDULE_HOUR", "7"))
SCHEDULE_MINUTE      = int(os.getenv("SCHEDULE_MINUTE", "0"))
SCHEDULE_DAY_OF_WEEK = os.getenv("SCHEDULE_DAY_OF_WEEK", "mon")  # mon-sun, or "*" for daily
TIMEZONE             = os.getenv("TIMEZONE", "Africa/Nairobi")

# How many days back to search — default 7 to match weekly schedule (override via env for daily use)
SEARCH_LOOKBACK_DAYS = int(os.getenv("SEARCH_LOOKBACK_DAYS", "7"))

# === Email ===
EMAIL_ENABLED    = os.getenv("EMAIL_ENABLED", "false").lower() == "true"
SMTP_HOST        = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT        = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER        = os.getenv("SMTP_USER", "")
SMTP_PASSWORD    = os.getenv("SMTP_PASSWORD", "")
EMAIL_FROM       = os.getenv("EMAIL_FROM", "")
EMAIL_TO         = os.getenv("EMAIL_TO", "")  # comma-separated list

# === Database ===
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./digital_health_agent.db")

# === Output ===
PDF_OUTPUT_DIR = os.getenv("PDF_OUTPUT_DIR", "./reports")
os.makedirs(PDF_OUTPUT_DIR, exist_ok=True)

# === Target Countries (by scan priority) ===
# Tier 1 — deepest coverage
COUNTRIES_TIER1 = ["Sierra Leone", "Bangladesh"]
# Tier 2 — broad coverage
COUNTRIES_TIER2 = ["Kenya", "Rwanda", "Ghana", "India"]
# Tier 3 — surface coverage
COUNTRIES_TIER3 = ["Saudi Arabia", "Tanzania", "Bhutan"]

# All target countries (used for filtering/UI)
TARGET_COUNTRIES = COUNTRIES_TIER1 + COUNTRIES_TIER2 + COUNTRIES_TIER3

# === Search Queries — optimised for freshness, orthogonality, and 50-call budget ===
# Each tier uses a single Tavily topic (news / general) — no double-firing.
# Queries are year-anchored and action-oriented to surface new events, not evergreen docs.

# Tier 1: Sierra Leone & Bangladesh — 3 queries each → topic: "news"
# Angles are orthogonal: (1) broad fresh news, (2) official/ministry, (3) implementation/deployment
SEARCH_QUERIES_TIER1 = [
    "Sierra Leone digital health launched announced 2025",
    "Sierra Leone Ministry of Health technology policy announcement",
    "Sierra Leone mHealth community health workers deployed rollout",
    "Bangladesh digital health eHealth launched 2025",
    "Bangladesh DGHS Ministry of Health technology policy update",
    "Bangladesh telemedicine mHealth rural healthcare rollout",
]

# Tier 2: Kenya, Rwanda, Ghana, India — 2 queries each → topic: "news"
# One broad angle + one official/implementation angle per country
SEARCH_QUERIES_TIER2 = [
    "Kenya digital health Ministry implementation launched 2025",
    "Kenya NHIF mHealth telemedicine health technology update",
    "Rwanda eHealth digital health Ministry update 2025",
    "Rwanda health technology implementation policy announcement",
    "Ghana digital health Ministry launched announced 2025",
    "Ghana mHealth community health workers technology policy",
    "India Ayushman ABDM digital health launched 2025",
    "India MOHFW telemedicine NHP health technology update",
]

# Tier 3: Saudi Arabia, Tanzania, Bhutan — 1 query each → topic: "general"
# Single broad query per country; "general" topic casts wider net for lower-volume markets
SEARCH_QUERIES_TIER3 = [
    "Saudi Arabia digital health eHealth Ministry vision 2030 2025",
    "Tanzania digital health mHealth Ministry implementation update",
    "Bhutan eHealth digital health Ministry healthcare announced",
]

# Combined list (Tier 1 first for priority ordering)
SEARCH_QUERIES = SEARCH_QUERIES_TIER1 + SEARCH_QUERIES_TIER2 + SEARCH_QUERIES_TIER3

# Twitter/X API queries (if bearer token is set)
TWITTER_QUERIES = [
    "digital health Sierra Leone Bangladesh",
    "digital health Kenya Rwanda Ghana India telemedicine",
    "digital health Saudi Arabia Tanzania Bhutan",
]

# LinkedIn via Tavily — 3 combined → topic: "general"
LINKEDIN_QUERIES = [
    "site:linkedin.com digital health Sierra Leone Bangladesh 2025",
    "site:linkedin.com digital health Kenya Rwanda Ghana India",
    "site:linkedin.com digital health Saudi Arabia Tanzania Bhutan",
]

# === Per-country query map (used for country-specific runs) ===
COUNTRY_QUERIES: dict[str, dict] = {
    "Sierra Leone": {
        "search":    ["digital health Sierra Leone", "Sierra Leone mHealth telemedicine healthcare", "Sierra Leone health technology implementation"],
        "official":  ["Sierra Leone Minister of Health digital health announcement", "MOHS Sierra Leone health policy pronouncement"],
        "moh_site":  "site:mohs.gov.sl digital health",
        "sentiment": "digital health Sierra Leone community discussion sentiment",
    },
    "Bangladesh": {
        "search":    ["digital health Bangladesh", "Bangladesh telemedicine mHealth healthcare", "Bangladesh eHealth digital health tools"],
        "official":  ["Bangladesh health minister digital health statement announcement", "DGHS Bangladesh eHealth implementation update"],
        "moh_site":  "site:mohfw.gov.bd digital health",
        "sentiment": "digital health Bangladesh community discussion sentiment",
    },
    "Kenya": {
        "search":    ["digital health Kenya", "Kenya telemedicine mHealth policy"],
        "official":  ["Kenya Cabinet Secretary Health digital announcement", "Kenya MOH digital health tools launched"],
        "moh_site":  "site:health.go.ke digital health",
        "sentiment": "digital health Kenya community discussion",
    },
    "Rwanda": {
        "search":    ["digital health Rwanda", "Rwanda eHealth telemedicine implementation"],
        "official":  ["Rwanda Minister of Health digital health pronouncement", "Rwanda MOH digital health update"],
        "moh_site":  "site:moh.gov.rw digital health",
        "sentiment": "digital health Rwanda community discussion",
    },
    "Ghana": {
        "search":    ["digital health Ghana", "Ghana mHealth health technology policy"],
        "official":  ["Ghana Minister of Health digital health announcement", "Ghana MOH health plans digital"],
        "moh_site":  "site:moh.gov.gh digital health",
        "sentiment": "digital health Ghana community discussion",
    },
    "India": {
        "search":    ["digital health India telemedicine AI", "India Ministry of Health digital health Ayushman"],
        "official":  ["India Ministry of Health digital health policy update", "India MOHFW digital health announcement"],
        "moh_site":  "site:mohfw.gov.in digital health",
        "sentiment": "digital health India community discussion",
    },
    "Saudi Arabia": {
        "search":    ["digital health Saudi Arabia vision 2030", "Saudi Arabia eHealth telemedicine"],
        "official":  ["Saudi Arabia MOH digital health announcement", "Saudi health minister digital"],
        "moh_site":  "site:moh.gov.sa digital health",
        "sentiment": "digital health Saudi Arabia community discussion",
    },
    "Tanzania": {
        "search":    ["digital health Tanzania", "Tanzania mHealth health technology policy"],
        "official":  ["Tanzania Minister of Health digital health update", "Tanzania MOH digital health"],
        "moh_site":  "site:mohcdgec.go.tz digital health",
        "sentiment": "digital health Tanzania community discussion",
    },
    "Bhutan": {
        "search":    ["digital health Bhutan", "Bhutan eHealth healthcare technology"],
        "official":  ["Bhutan Ministry of Health digital health update", "Bhutan health minister digital"],
        "moh_site":  "site:health.gov.bt",
        "sentiment": "digital health Bhutan community discussion",
    },
}

# === Official pronouncement queries — 4 combined → topic: "news" ===
# One query bundles countries per tier to avoid per-country overhead
OFFICIAL_QUERIES = [
    "Sierra Leone Bangladesh Minister Health digital health announced 2025",
    "Kenya Rwanda Cabinet Secretary Health digital health launched 2025",
    "Ghana India Ministry Health digital health implementation announced 2025",
    "Saudi Arabia Tanzania Bhutan Ministry Health digital health update 2025",
]

# === Social sentiment queries — 3 combined → topic: "general" ===
SENTIMENT_QUERIES = [
    "digital health Sierra Leone Bangladesh stakeholder reaction discussion 2025",
    "digital health Kenya Rwanda Ghana India stakeholder discussion 2025",
    "digital health Saudi Arabia Tanzania Bhutan reaction discussion 2025",
]

# === Ministry of Health site queries — Tier 1 + Tier 2 only → topic: "news" ===
MOH_SITE_QUERIES = [
    "site:mohs.gov.sl digital health",       # Sierra Leone MoH  (Tier 1)
    "site:mohfw.gov.bd digital health",      # Bangladesh MoH    (Tier 1)
    "site:health.go.ke digital health",      # Kenya MoH         (Tier 2)
    "site:moh.gov.rw digital health",        # Rwanda MoH        (Tier 2)
    "site:moh.gov.gh digital health",        # Ghana MoH         (Tier 2)
    "site:mohfw.gov.in digital health",      # India MoH         (Tier 2)
]

# === Donor & global org queries — cast wide beyond local media → topic: "news" ===
# Donors often publish implementation updates, evaluations, and grant announcements
# that local media never cover. These are high-value signals for leadership.
DONOR_QUERIES = [
    "USAID digital health Sierra Leone Bangladesh Kenya Rwanda Ghana India 2025",
    "Gates Foundation Wellcome digital health Africa India Bangladesh 2025",
    "UNICEF WHO digital health Sierra Leone Bangladesh Kenya Rwanda 2025",
    "World Bank digital health Africa India implementation 2025",
    "FCDO PEPFAR Gavi digital health Africa 2025",
    "PATH JSI digital health Sierra Leone Bangladesh Ghana Kenya 2025",
]

# === URL Exclusion List ===
# Articles at these URLs will never be returned by the scraper.
# Add any URL that is outdated, already captured, or irrelevant.
EXCLUDED_URLS: set[str] = {
    # Sierra Leone — already captured / static docs
    "https://mohs.gov.sl/download/68/digital-health/18150/sierral-leone-digital-health-roadmap-2024-2026-2.pdf",
    "https://www.linkedin.com/posts/ricardpognon_sierra-leone-national-digital-health-roadmap-activity-7150702536637800448-mz-C/",
    "https://sierraleone.unfpa.org/en/news/dsti-unfpa-partner-digitize-sierra-leones-nursing-and-midwifery-council-membership",
    "https://thetimes-sierraleone.com/sierra-leone-launches-digital-platform-for-nurses-midwives/",
    "https://moice.gov.sl/dsti-unfpa-partner-to-digitize-sierra-leones-nursing-and-midwifery-council-membership/",
    "https://mohs.gov.sl/moh-launches-health-information-hub/",
    "https://sierraleone.un.org/en/308623-centralized-health-data-system-launched-sierra-leone",
    "https://un-dco.org/stories/transforming-health-systems-sierra-leone",
    "https://africapublicity.com/un-agencies-sierra-leones-ministry-of-health-sign-flagship-health-project-to-advance-universal-health-coverage/",
    "https://www.povertyactionlab.org/evaluation/digital-monitoring-and-health-service-provision-sierra-leone?lang=en",
    "https://www.linkedin.com/posts/erin-broekhuysen-39a61010_how-can-program-implementers-turn-research-activity-7310131565815083008-T9-o",
    # Bangladesh
    "https://hrm.dghs.gov.bd/public/facility-registry/reports",
    "https://www.gavi.org/partner-countries/south-east-asia/bangladesh",
    # Ghana
    "https://www.newsghana.com.gh/csir-insti-unveils-ai-tools-to-reshape-ghanas-agriculture-and-healthcare/",
    "https://www.ghanamma.com/2026/04/12/csir-insti-unveils-ai-tools-to-reshape-ghanas-agriculture-and-healthcare/",
    # Saudi Arabia
    "https://www.vision2030.gov.sa/en/explore/programs/health-sector-transformation-program",
    "https://healthcluster.co/telemedicine-in-ksa/",
    "https://www.grandviewresearch.com/industry-analysis/saudi-arabia-digital-health-market-report",
}

# === Agent Settings ===
MAX_ARTICLES_PER_RUN   = int(os.getenv("MAX_ARTICLES_PER_RUN", "20"))
MIN_VERIFICATION_SCORE = float(os.getenv("MIN_VERIFICATION_SCORE", "0.6"))
MAX_FOLLOW_UP_LINKS    = int(os.getenv("MAX_FOLLOW_UP_LINKS", "5"))
