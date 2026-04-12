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

# How many days back to search for articles — 1 = last 24 hrs (daily freshness guardrail)
SEARCH_LOOKBACK_DAYS = int(os.getenv("SEARCH_LOOKBACK_DAYS", "1"))

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

# === Search Queries (ordered by priority — Tier 1 first so they rank highest in raw results) ===
# Tier 1: Sierra Leone & Bangladesh — 4 queries each
SEARCH_QUERIES_TIER1 = [
    "digital health Sierra Leone",
    "telemedicine mHealth Sierra Leone healthcare",
    "Sierra Leone Ministry of Health health policy meeting",
    "Sierra Leone health technology funding plans",
    "digital health Bangladesh",
    "telemedicine mHealth Bangladesh healthcare",
    "Bangladesh Ministry of Health digital policy meeting",
    "Bangladesh health technology eHealth plans",
]

# Tier 2: Kenya, Rwanda, Ghana, India — 2 queries each
SEARCH_QUERIES_TIER2 = [
    "digital health Kenya telemedicine",
    "Kenya Ministry of Health health policy",
    "digital health Rwanda eHealth",
    "Rwanda health technology policy meeting",
    "digital health Ghana mHealth",
    "Ghana Ministry of Health health plans",
    "digital health India telemedicine AI",
    "India Ministry of Health digital health policy",
]

# Tier 3: Saudi Arabia, Tanzania, Bhutan — 2 queries each (general + news)
SEARCH_QUERIES_TIER3 = [
    "digital health Saudi Arabia eHealth telemedicine",
    "Saudi Arabia Vision 2030 health technology",
    "digital health Tanzania mHealth policy",
    "Tanzania health technology implementation",
    "digital health Bhutan eHealth healthcare",
    "Bhutan health technology policy",
]

# Combined — used by scraper (Tier 1 searched first)
SEARCH_QUERIES = SEARCH_QUERIES_TIER1 + SEARCH_QUERIES_TIER2 + SEARCH_QUERIES_TIER3

# Twitter/social queries — country-specific
TWITTER_QUERIES_TIER1 = [
    "digital health Sierra Leone",
    "health technology Bangladesh mHealth",
]
TWITTER_QUERIES_TIER2 = [
    "digital health Kenya Rwanda",
    "digital health Ghana India telemedicine",
]
TWITTER_QUERIES_TIER3 = [
    "digital health Saudi Arabia Tanzania Bhutan",
]
TWITTER_QUERIES = TWITTER_QUERIES_TIER1 + TWITTER_QUERIES_TIER2 + TWITTER_QUERIES_TIER3

# === Per-country query map (used for country-specific runs) ===
COUNTRY_QUERIES: dict[str, dict] = {
    "Sierra Leone": {
        "search":    ["digital health Sierra Leone", "Sierra Leone mHealth telemedicine healthcare", "Sierra Leone health technology implementation"],
        "official":  ["Sierra Leone Minister of Health digital health announcement", "MOHS Sierra Leone health policy pronouncement"],
        "moh_site":  "site:mohs.gov.sl",
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
        "moh_site":  "site:health.go.ke",
        "sentiment": "digital health Kenya community discussion",
    },
    "Rwanda": {
        "search":    ["digital health Rwanda", "Rwanda eHealth telemedicine implementation"],
        "official":  ["Rwanda Minister of Health digital health pronouncement", "Rwanda MOH digital health update"],
        "moh_site":  "site:moh.gov.rw",
        "sentiment": "digital health Rwanda community discussion",
    },
    "Ghana": {
        "search":    ["digital health Ghana", "Ghana mHealth health technology policy"],
        "official":  ["Ghana Minister of Health digital health announcement", "Ghana MOH health plans digital"],
        "moh_site":  "site:moh.gov.gh",
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
        "moh_site":  "site:mohcdgec.go.tz",
        "sentiment": "digital health Tanzania community discussion",
    },
    "Bhutan": {
        "search":    ["digital health Bhutan", "Bhutan eHealth healthcare technology"],
        "official":  ["Bhutan Ministry of Health digital health update", "Bhutan health minister digital"],
        "moh_site":  "site:health.gov.bt",
        "sentiment": "digital health Bhutan community discussion",
    },
}

# === Official pronouncement & social sentiment queries ===
# Tracks minister statements, MOH announcements, LinkedIn/Twitter discussions
OFFICIAL_QUERIES = [
    # Tier 1
    "Sierra Leone Minister of Health digital health announcement 2025 2026",
    "MOHS Sierra Leone health policy pronouncement implementation",
    "Bangladesh health minister digital health statement announcement",
    "DGHS Bangladesh eHealth mHealth implementation update",
    # Tier 2
    "Kenya Cabinet Secretary Health digital announcement",
    "Kenya MOH digital health policy tools launched",
    "Rwanda Minister of Health digital health pronouncement",
    "Ghana Minister of Health digital health announcement implementation",
    "India Ministry of Health digital health Ayushman policy update",
    # Tier 3
    "Saudi Arabia MOH digital health vision 2030 announcement",
    "Tanzania Minister of Health digital health update",
    "Bhutan Ministry of Health digital health update",
]

SENTIMENT_QUERIES = [
    # LinkedIn/social discussions — all tiers
    "site:linkedin.com Sierra Leone Bangladesh digital health",
    "site:linkedin.com Kenya Rwanda Ghana digital health discussion",
    "site:linkedin.com India digital health implementation discussion",
    "site:linkedin.com Saudi Arabia Tanzania Bhutan digital health",
    # Twitter/community discussions — all tiers
    "digital health Sierra Leone community reaction discussion",
    "digital health Bangladesh mHealth stakeholder sentiment",
    "digital health Kenya Rwanda Ghana stakeholder discussion",
    "digital health India telemedicine community sentiment",
    "digital health Saudi Arabia Tanzania Bhutan discussion",
]

# === Ministry of Health site-specific queries ===
MOH_SITE_QUERIES = [
    "site:mohs.gov.sl",                        # Sierra Leone MoH  (Tier 1)
    "site:mohfw.gov.bd digital health",        # Bangladesh MoH    (Tier 1)
    "site:health.go.ke",                       # Kenya MoH         (Tier 2)
    "site:moh.gov.rw",                         # Rwanda MoH        (Tier 2)
    "site:moh.gov.gh",                         # Ghana MoH         (Tier 2)
    "site:mohfw.gov.in digital health",        # India MoH         (Tier 2)
    "site:moh.gov.sa digital health",          # Saudi Arabia MoH  (Tier 3)
    "site:mohcdgec.go.tz",                     # Tanzania MoH      (Tier 3)
    "site:health.gov.bt",                      # Bhutan MoH        (Tier 3)
]

# === Agent Settings ===
MAX_ARTICLES_PER_RUN   = int(os.getenv("MAX_ARTICLES_PER_RUN", "20"))
MIN_VERIFICATION_SCORE = float(os.getenv("MIN_VERIFICATION_SCORE", "0.6"))
MAX_FOLLOW_UP_LINKS    = int(os.getenv("MAX_FOLLOW_UP_LINKS", "5"))
