import os
from dotenv import load_dotenv

load_dotenv()

# =============================================================================
# AI MODEL CONFIGURATION
# =============================================================================

AI_PROVIDER = os.getenv("AI_PROVIDER", "claude")  # "claude" or "openai"

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY    = os.getenv("OPENAI_API_KEY", "")

CLAUDE_MODELS = {
    "fast":     "claude-haiku-4-5-20251001",   # scraping, dedup, tagging
    "balanced": "claude-sonnet-4-6",            # enrichment, impact scoring
    "powerful": "claude-opus-4-6",             # verification, final synthesis
}

OPENAI_MODELS = {
    "fast":     "gpt-4o-mini",
    "balanced": "gpt-4o",
    "powerful": "o1",
}

SCRAPER_MODEL  = os.getenv("SCRAPER_MODEL",  "balanced")
VERIFIER_MODEL = os.getenv("VERIFIER_MODEL", "powerful")
ENRICHER_MODEL = os.getenv("ENRICHER_MODEL", "balanced")
IMPACT_MODEL   = os.getenv("IMPACT_MODEL",   "balanced")
WRITER_MODEL   = os.getenv("WRITER_MODEL",   "balanced")

# =============================================================================
# SEARCH / SCRAPING APIS
# =============================================================================

TAVILY_API_KEY       = os.getenv("TAVILY_API_KEY", "")
TWITTER_BEARER_TOKEN = os.getenv("TWITTER_BEARER_TOKEN", "")
SERPER_API_KEY       = os.getenv("SERPER_API_KEY", "")
GITHUB_TOKEN         = os.getenv("GITHUB_TOKEN", "")           # NEW: GitHub API (60 req/hr unauth → 5000 auth)
UNPAYWALL_EMAIL      = os.getenv("UNPAYWALL_EMAIL", "keneth.kiplagat@medtroniclabs.org")

# =============================================================================
# SCHEDULING
# =============================================================================

SCHEDULE_HOUR        = int(os.getenv("SCHEDULE_HOUR", "7"))
SCHEDULE_MINUTE      = int(os.getenv("SCHEDULE_MINUTE", "0"))
SCHEDULE_DAY_OF_WEEK = os.getenv("SCHEDULE_DAY_OF_WEEK", "mon")
TIMEZONE             = os.getenv("TIMEZONE", "Africa/Nairobi")
SEARCH_LOOKBACK_DAYS = int(os.getenv("SEARCH_LOOKBACK_DAYS", "7"))

# =============================================================================
# EMAIL
# =============================================================================

EMAIL_ENABLED = os.getenv("EMAIL_ENABLED", "false").lower() == "true"
SMTP_HOST     = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT     = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER     = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
EMAIL_FROM    = os.getenv("EMAIL_FROM", "")
EMAIL_TO      = os.getenv("EMAIL_TO", "")

# =============================================================================
# DATABASE & OUTPUT
# =============================================================================

DATABASE_URL   = os.getenv("DATABASE_URL", "sqlite:///./digital_health_agent.db")
PDF_OUTPUT_DIR = os.getenv("PDF_OUTPUT_DIR", "./reports")
os.makedirs(PDF_OUTPUT_DIR, exist_ok=True)

# =============================================================================
# FIX 1 — AGENT LIMITS: raised from 20 → 100 so verification does the filtering
# FIX 2 — VERIFICATION: tightened score from 0.6 → 0.65 to reduce noise
# =============================================================================

MAX_ARTICLES_PER_RUN   = int(os.getenv("MAX_ARTICLES_PER_RUN",   "100"))   # was 20
MIN_VERIFICATION_SCORE = float(os.getenv("MIN_VERIFICATION_SCORE", "0.65")) # was 0.6
MAX_FOLLOW_UP_LINKS    = int(os.getenv("MAX_FOLLOW_UP_LINKS",    "5"))

# =============================================================================
# FIX 3 — URGENCY TIERING
# Primary classification is done by the enricher AI model (see enricher_agent.py).
# The keyword lists below serve as documentation / fallback heuristic only.
# URGENT articles bypass the weekly digest and trigger an immediate email push.
# =============================================================================

URGENCY_TIERS = {
    "URGENT": [
        "minister", "cabinet secretary", "policy signed", "law enacted",
        "tender deadline", "RFP closes", "call for proposals closes",
        "emergency", "launched today", "effective immediately",
        "breaking", "just announced", "press release",
    ],
    "STANDARD": [
        "implementation", "rollout", "pilot", "deployed", "award",
        "funding announced", "grant", "partnership", "MOU signed",
        "evaluation", "results", "published", "trial",
    ],
    "BACKGROUND": [
        "market report", "analysis", "overview", "strategy", "roadmap",
        "evergreen", "whitepaper", "explainer", "backgrounder",
    ],
}

URGENT_EMAIL_PUSH = os.getenv("URGENT_EMAIL_PUSH", "true").lower() == "true"

# =============================================================================
# TARGET COUNTRIES
# =============================================================================

COUNTRIES_TIER1 = ["Sierra Leone", "Bangladesh"]
COUNTRIES_TIER2 = ["Kenya", "Rwanda", "Ghana", "India"]
COUNTRIES_TIER3 = ["Saudi Arabia", "Tanzania", "Bhutan", "United States"]

TARGET_COUNTRIES = COUNTRIES_TIER1 + COUNTRIES_TIER2 + COUNTRIES_TIER3

# =============================================================================
# FIX 4 — YEAR ANCHORS: all queries now span 2025-2026 (was stuck on 2025)
# FIX 5 — QUERY LENGTH: shortened to 3-6 words for better search engine recall
# Orthogonal angles kept; overlapping variants removed.
# =============================================================================

# --- Query builder helpers (eliminates country × angle × year repetition) ---
_Y = "2025 2026"   # two-year lookback span


def _q(countries: list, angles: list, year: str = _Y) -> list:
    """Generate every country × angle pair to avoid hardcoded repetition."""
    return [f"{c} {a} {year}" for c in countries for a in angles]


_TIER1_COUNTRIES = ["Sierra Leone", "Bangladesh"]
_TIER2_COUNTRIES = ["Kenya", "Rwanda", "Ghana", "India"]

# Angles shared by every country in the tier
_BASE_ANGLES = ["digital health eHealth", "Ministry Health mHealth digital"]

# Country-specific extra angles (flagship programmes, acronyms)
_TIER1_EXTRA = [
    "Sierra Leone mHealth community workers 2025 2026",
    "Bangladesh DGHS telemedicine rural healthcare 2025 2026",
]
_TIER2_EXTRA = [
    "Kenya MOH telemedicine mHealth 2026",
    "Rwanda Ministry Health announcement 2025 2026",
    "Ghana mHealth community health workers 2026",
    "India ABDM MOHFW digital health 2026",
]

# --- Tier 1: Sierra Leone & Bangladesh ---
SEARCH_QUERIES_TIER1 = _q(_TIER1_COUNTRIES, _BASE_ANGLES, _Y) + _TIER1_EXTRA

# --- Tier 2: Kenya, Rwanda, Ghana, India ---
SEARCH_QUERIES_TIER2 = _q(_TIER2_COUNTRIES, _BASE_ANGLES, _Y) + _TIER2_EXTRA

# --- Tier 3: Saudi Arabia, Tanzania, Bhutan, US (unique angles kept manual) ---
# NOTE: do NOT mix country names in these queries — _infer_country() uses them
# to bucket results. A query mentioning "India" would steal US results.
SEARCH_QUERIES_TIER3 = [
    "Saudi Arabia digital health vision 2030 2026",
    "Tanzania digital health Ministry 2025 2026",
    "Bhutan eHealth Ministry healthcare 2025 2026",
    "United States digital health FDA CMS policy 2026",
    "United States USAID global health technology partnership 2026",
]

# =============================================================================
# FIX 6 — REAL-TIME & SPECIALIST NEWS SOURCES (new section)
# These were missed entirely in the original config.
# =============================================================================

REALTIME_NEWS_QUERIES = [
    # Specialist outlets
    "site:healthpolicywatch.net digital health Africa 2026",
    "site:ictworks.org digital health Africa 2026",
    "site:mhealthintelligence.com Africa India 2026",
    "site:statnews.com digital health Africa 2026",
    "site:devex.com digital health Africa India 2026",
    "site:apolitical.co digital health Africa 2026",
    "site:africahealthit.com digital health 2026",
    # WHO / UN press rooms
    "site:who.int digital health Africa 2025 2026",
    "site:afro.who.int digital health 2025 2026",
    "site:unicef.org digital health implementation 2026",
    "site:afdb.org digital health Africa 2026",
    # Global health media
    "site:globalhealth.org digital health Africa 2026",
    "site:thinkglobalhealth.org digital health Africa 2026",
]

# RSS feeds to poll on every run (fetched directly via requests, no search credit used)
MONITORED_RSS_FEEDS = [
    # WHO
    "https://www.who.int/rss-feeds/news-english.xml",
    "https://www.afro.who.int/rss.xml",
    # Specialist outlets
    "https://healthpolicywatch.net/feed/",
    "https://www.devex.com/news/rss.xml",
    "https://www.statnews.com/feed/",
    "https://ictworks.org/feed/",
    "https://mhealthintelligence.com/feed/",
    # Academic
    "https://www.thelancet.com/rssfeed/landig_current.xml",      # Lancet Digital Health
    "https://bmjopen.bmj.com/rss/current.xml",                   # BMJ Open
    "https://www.bmj.com/rss/ahead-of-print.xml",                # BMJ ahead of print
    "https://connect.medrxiv.org/medrxiv_xml.php?subject=Health_Informatics",  # medRxiv
    "https://www.ssrn.com/rss/ssrn-rss-globalhealth.xml",        # SSRN Global Health
    # Donor / implementer
    "https://www.gatesfoundation.org/ideas/rss",
    "https://wellcome.org/press-release/rss.xml",
]

# =============================================================================
# FIX 7 — GITHUB / OPEN SOURCE REPOSITORY MONITORING (new section)
# Release tags, README changes, and commit messages are leading indicators of
# country deployments — often 2-6 months ahead of any news coverage.
# Fetched via GitHub REST API (set GITHUB_TOKEN for 5000 req/hr).
# =============================================================================

GITHUB_REPOS_TO_WATCH = [
    # Global digital health platforms
    "dhis2/dhis2-core",                    # Release = new country-ready version
    "dhis2/dhis2-app-store",               # New country apps
    "opensrp/opensrp-client-core",         # OpenSRP — Kenya, Sierra Leone heavy
    "opensrp/fhircore",                    # FHIR-based CHW tools — Kenya
    "openmrs/openmrs-core",                # OpenMRS — Bangladesh, India, Ghana
    "medic/cht-core",                      # Community Health Toolkit — Sierra Leone, Kenya, Tanzania
    "onaio/onadata",                       # Ona Data — Kenya, Tanzania, Rwanda
    "onaio/kobocat",                       # KoBoToolbox — LMIC data collection
    "who-int/smart-guidelines",            # WHO SMART guidelines — policy signals
    "who-int/health-workforce",            # WHO health workforce digital tools
    "Digital-Square/global-goods-guidebook",  # Digital Square global goods
    # Country MoH / national systems
    "HealthIT-Uganda/openmrs-module-ugandaemr",  # mirrors Uganda; watch for similar MoH patterns
    "KENYA-MOH/dwapi",                     # Kenya MOH data warehouse API
    "I-TECH-UW/muzima-android",            # mUzima — Kenya, Zimbabwe
    "IntelliSOFT-Consulting/openmrs-module-kenyaemr",  # Kenya EMR
    # Standards & interoperability
    "hapifhir/hapi-fhir",                  # HAPI FHIR — country adoption via issues
    "hl7/fhir-ig-registry",                # HL7 IG Registry — new country IGs = rollout signal
    "openhie/openhim-core-js",             # OpenHIE mediator — LMIC HIE deployments
    # Indian national health stack
    "NHA-ABDM/ABDM-wrapper",              # India ABDM national health stack
    "NHA-ABDM/abdm-sdk",
    # Funding platforms / grant trackers (open data repos)
    "FCDO/aid-connect",                    # FCDO aid data (Sierra Leone, Kenya heavy)
    "worldbank/open-data",                 # World Bank open health data
]

# GitHub code search queries — surfaces country-specific implementation signals
# Use: GET https://api.github.com/search/code?q={query}
GITHUB_SEARCH_QUERIES = [
    "digital health Kenya implementation site:github.com",
    "mHealth Sierra Leone deploy site:github.com",
    "DHIS2 Rwanda configuration site:github.com",
    "OpenMRS Bangladesh install site:github.com",
    "CHT Sierra Leone community health site:github.com",
    "OpenSRP Kenya Ministry Health site:github.com",
    "ABDM India integration site:github.com",
    "digital health Ghana deployment site:github.com",
]

# GitHub topics to monitor for new repos/activity
GITHUB_TOPICS_TO_WATCH = [
    "digital-health-africa",
    "mhealth-kenya",
    "dhis2",
    "openmrs",
    "community-health-toolkit",
    "fhir-africa",
    "health-information-system",
    "opensrp",
    "ehealth-africa",
    "global-health",
]

# =============================================================================
# FIX 8 — DONOR & GRANT DATABASE MONITORING (expanded from original)
# =============================================================================

# Direct API endpoints — polled on every run, no search credit consumed
DONOR_API_ENDPOINTS = [
    # World Bank projects API — health sector, Africa + South Asia
    "https://api.worldbank.org/v2/projects?theme=Health&region=AFR&format=json&per_page=50",
    "https://api.worldbank.org/v2/projects?theme=Health&region=SAS&format=json&per_page=50",
    # FCDO Development Tracker — health sector code 12220
    "https://devtracker.fcdo.gov.uk/api/iati/activities/?sector=12220&format=json",
    # IATI Registry — major donors publishing health activity data
    "https://iati.cloud/api/activities/?sector_code=12220&format=json&ordering=-iati_updated&limit=50",
    # Global Fund grants API
    "https://data-service.theglobalfund.org/api/odata/v1/Grants?$filter=contains(ProgramArea,'Health')&$top=50",
]

# Monitored grant/tender URLs — fetched directly via Tavily extract on every run
MONITORED_GRANT_URLS = [
    # Original
    "https://simpler.grants.gov/opportunity/6e0f399b-6318-44be-8d17-12bc8d81708f",
    "https://projects.worldbank.org/en/projects-operations/procurement?srce=both",
    # New additions
    "https://devtracker.fcdo.gov.uk/projects?status=active&sector=12220",
    "https://www.theglobalfund.org/en/sourcing-management/procurement/health-products/",
    "https://ungm.org/Public/Notice",
    "https://gem.gov.in/",                          # India Government e-Marketplace
    "https://ppip.go.ke/",                          # Kenya Public Procurement Portal
    "https://www.devex.com/funding",
    "https://www.usaid.gov/work-usaid/find-a-funding-opportunity",
    "https://dec.usaid.gov/dec/home/Default.aspx",
    "https://3ieimpact.org/funding",                # 3ie open window grants
    "https://www.adb.org/projects/tenders/active",  # ADB tenders
    "https://www.afdb.org/en/projects-and-operations/procurement",
    "https://www.wellcome.org/grant-funding",
]

# Funding search queries (Tavily topic: "news")
FUNDING_QUERIES = [
    "digital health Africa NCD maternal grant 2025 2026",
    "RFP digital health LMIC primary care 2026",
    "Wellcome Trust health innovation Africa India 2026",
    "MasterCard Foundation digital health Africa grant 2026",
    "USAID Development Innovation Ventures digital health 2026",
    "NIH Fogarty digital health NCD Africa India 2026",
    "Gates Foundation global health grant Africa 2026",
    "FCDO digital health Africa award 2026",
    "3ie impact evaluation health technology grant 2026",
    "Grand Challenges Canada digital health Africa 2026",
]

# =============================================================================
# PROCUREMENT PORTAL QUERIES (expanded)
# =============================================================================

PROCUREMENT_PORTAL_QUERIES = [
    "site:projects.worldbank.org digital health Africa India 2025 2026",
    "site:ungm.org digital health Africa tender 2025 2026",
    "site:adb.org digital health procurement 2025 2026",
    "site:afdb.org digital health tender Africa 2025 2026",
    "site:devex.com digital health tender grant 2026",
    "site:dgmarket.com digital health Africa tender 2026",         # NEW
    "site:ppip.go.ke digital health Kenya 2026",                   # NEW: Kenya procurement
    "site:gem.gov.in health technology 2026",                      # NEW: India procurement
    "site:dec.usaid.gov digital health Africa 2026",               # NEW: USAID contracts
    "World Bank ADB AfDB digital health tender awarded 2025 2026",
]

# =============================================================================
# ACADEMIC & PRE-PRINT QUERIES (new section)
# =============================================================================

ACADEMIC_QUERIES = [
    "site:medrxiv.org digital health Africa implementation 2025 2026",
    "site:medrxiv.org mHealth LMIC Bangladesh Kenya 2025 2026",
    "site:ssrn.com digital health Africa India 2026",
    "site:researchsquare.com digital health Africa 2026",
    "Lancet Digital Health Africa implementation 2026",
    "BMJ Global Health digital health Kenya Rwanda Ghana 2026",
    "BMJ Open mHealth community health workers Africa 2026",
    "JMIR mHealth digital health Sierra Leone Bangladesh 2026",     # JMIR is LMIC-heavy
    "npj Digital Medicine Africa India implementation 2026",
]

# =============================================================================
# REGULATORY & STANDARDS QUERIES (expanded)
# =============================================================================

REGULATORY_QUERIES = [
    # Country regulatory bodies
    "ICMR India medical device digital health approval 2026",
    "Kenya PPB medical device registration 2026",
    "Ghana FDA medical device eHealth 2026",
    "Sierra Leone Pharmacy Board health technology 2026",
    "Bangladesh DGDA medical device approval 2026",
    "Saudi Arabia SFDA digital health clearance 2026",
    "Tanzania TMDA medical device eHealth 2026",
    "Rwanda medical device regulatory approval 2026",
    # International standards — leading indicators
    "HL7 FHIR implementation guide Africa 2026",                   # NEW: country FHIR adoption
    "ISO TC215 health informatics standard 2026",                  # NEW
    "IHE International Africa integration profile 2026",           # NEW
    "IMDRF medical device convergence LMIC 2026",                  # NEW
    "CE mark FDA clearance LMIC medical device 2026",
]

# =============================================================================
# OFFICIAL PRONOUNCEMENTS & MINISTRY MONITORING (expanded)
# =============================================================================

OFFICIALS_QUERIES = [
    '"Austin Demby" OR "Sierra Leone Ministry Health" digital 2025 2026',
    '"Aden Duale" OR "Patrick Amoth" Kenya Health digital 2025 2026',
    '"Sabin Nsanzimana" OR "Rwanda Minister Health" digital 2025 2026',
    '"Kwabena Mintah Akandoh" OR "Ghana Minister Health" digital 2025 2026',
    '"JP Nadda" OR "Apurva Chandra" India MOHFW digital 2025 2026',
    '"Mohamed Mchengerwa" OR "Tanzania Minister Health" digital 2025 2026',
    '"Fahad Al-Jalajel" OR "Saudi Arabia MOH" digital health 2026',
    '"Tandin Wangchuk" OR "Bhutan Ministry Health" digital 2026',
    '"Robert F Kennedy" OR "Martin Makary" FDA digital health 2026',
    # LinkedIn-specific (ministers post here before press releases)
    'site:linkedin.com "Sabin Nsanzimana" digital health 2026',
    'site:linkedin.com "Aden Duale" health Kenya 2026',
    'site:linkedin.com "Austin Demby" Sierra Leone health 2026',
]

# Ministry of Health official site queries
MOH_SITE_QUERIES = [
    "site:mohs.gov.sl digital health",
    "site:mohfw.gov.bd digital health",
    "site:health.go.ke digital health",
    "site:moh.gov.rw digital health",
    "site:moh.gov.gh digital health",
    "site:mohfw.gov.in digital health",
    "site:moh.gov.sa digital health",
    "site:mohcdgec.go.tz digital health",
    "site:health.gov.bt digital health",
    "site:hhs.gov digital health Africa India 2026",
]

OFFICIAL_QUERIES = [
    "Sierra Leone Bangladesh Minister Health digital 2025 2026",
    "Kenya Rwanda Cabinet Secretary Health digital 2025 2026",
    "Ghana India Ministry Health digital 2025 2026",
    "Saudi Arabia Tanzania Bhutan US digital health policy 2026",
]

# =============================================================================
# DONOR & GLOBAL ORG QUERIES (expanded)
# =============================================================================

DONOR_QUERIES = [
    "USAID digital health Sierra Leone Bangladesh Kenya Rwanda 2026",
    "Gates Foundation Wellcome digital health Africa India 2026",
    "UNICEF WHO digital health Sierra Leone Bangladesh Kenya 2026",
    "World Bank digital health Africa India implementation 2026",
    "FCDO digital health Africa 2026",                             # NEW: expanded FCDO
    "PEPFAR Gavi digital health Africa 2025 2026",
    "PATH JSI digital health Africa Bangladesh 2026",
    "CGIAR digital health agriculture Africa 2026",                # NEW
    "3ie impact evaluation digital health Africa 2026",            # NEW
    "Clinton Health Access Initiative digital health Africa 2026", # NEW
    "MSH Management Sciences Health digital Africa 2026",          # NEW
    "Aga Khan Foundation digital health Africa India 2026",        # NEW
]

# =============================================================================
# SOCIAL & COMMUNITY SIGNALS (expanded)
# =============================================================================

SENTIMENT_QUERIES = [
    "digital health Sierra Leone Bangladesh stakeholder 2025 2026",
    "digital health Kenya Rwanda Ghana India discussion 2026",
    "digital health Saudi Arabia Tanzania Bhutan US 2026",
]

# LinkedIn newsletters and Substack feeds from key implementers
MONITORED_SUBSTACK_FEEDS = [
    "https://digitalsquare.substack.com/feed",           # Digital Square
    "https://path.substack.com/feed",                    # PATH
    "https://onasubstack.substack.com/feed",             # Ona Data
    "https://mohfw.gov.in/rss.xml",                      # India MoH
]

# Twitter/X queries
TWITTER_QUERIES = [
    "digital health Sierra Leone Bangladesh",
    "digital health Kenya Rwanda Ghana India telemedicine",
    "digital health Saudi Arabia Tanzania Bhutan",
    "DHIS2 Africa implementation",                        # NEW
    "OpenSRP mHealth Africa deploy",                      # NEW
    "digital health policy Africa minister announcement", # NEW
]

# LinkedIn via Tavily (expanded from 3 → 9 queries)
LINKEDIN_QUERIES = [
    "site:linkedin.com digital health Sierra Leone 2026",
    "site:linkedin.com digital health Bangladesh 2026",
    "site:linkedin.com digital health Kenya 2026",
    "site:linkedin.com digital health Rwanda 2026",
    "site:linkedin.com digital health Ghana India 2026",
    "site:linkedin.com digital health Saudi Arabia Tanzania 2026",
    "site:linkedin.com DHIS2 implementation Africa 2026",
    "site:linkedin.com OpenSRP Africa deployment 2026",
    "site:linkedin.com digital health minister Africa announcement 2026",
]

# =============================================================================
# CONFERENCE & EVENT QUERIES (expanded)
# =============================================================================

CONFERENCE_QUERIES = [
    "AfDB Africa health digital summit 2025 2026",
    "GSMA MWC Africa mHealth announcement 2025 2026",
    "WHO Africa regional ministers digital health 2026",
    "eHealth Africa conference 2025 2026",
    "African Union health ministers digital communique 2026",
    "Global Digital Health Forum GDHF 2025 2026",
    "AeHIN Asia eHealth Bangladesh India 2025 2026",        # NEW: AeHIN
    "ITU Digital World health technology 2025 2026",        # NEW: ITU
    "Health Technology Forum Africa India 2026",
    "Africa Health exhibition Johannesburg 2026",           # NEW: Africa Health
    "Digital Health Summit Nairobi Kigali 2026",            # NEW: East Africa events
]

# =============================================================================
# BUDGET & FISCAL SIGNALS (expanded)
# =============================================================================

BUDGET_QUERIES = [
    "Ministry Health budget digital health Africa 2025 2026",
    "Kenya national health budget parliament 2025 2026",
    "India Union Budget health digital 2026",
    "Ghana health budget parliament 2025 2026",
    "Sierra Leone health budget allocation 2025 2026",
    "Bangladesh national health budget 2025 2026",
    "World Bank health loan disbursement Africa India 2026",
    "GAVI Global Fund disbursement health technology Africa 2026",
    "Rwanda MTEF health budget digital 2025 2026",
    "Saudi Arabia health budget Vision 2030 2026",
]

# =============================================================================
# CLINICAL DOMAIN — MEDTRONIC LABS FOCUS AREAS
# =============================================================================

CLINICAL_MEDTRONIC_QUERIES = [
    "maternal health digital diagnostics Africa India 2026",
    "NCD hypertension diabetes screening Africa India 2026",
    "cardiac care technology low resource settings 2026",
    "point of care diagnostics primary care Africa 2026",
    "community health worker NCD digital tool Africa 2026",
    "remote patient monitoring NCD Africa India 2026",
    "blood pressure hypertension mHealth Africa India 2026",
    "diabetes management digital tool Africa India 2026",
    "maternal mortality digital health Africa 2026",
    "primary healthcare digital tool Africa India 2026",
]

REIMBURSEMENT_NCD_QUERIES = [
    "NHIF Kenya NCD diabetes hypertension coverage 2026",
    "NHIS Ghana NCD insurance medical device 2026",
    "Ayushman Bharat NCD India diabetes cardiac 2026",
    "health insurance NCD medical device Africa 2026",
    "UHC NCD coverage medical device LMIC 2026",
    "hypertension diabetes insurance Africa India 2026",
]

# =============================================================================
# COMBINED MASTER QUERY LIST
# Ordered by priority — scraper processes in this sequence.
# =============================================================================

SEARCH_QUERIES = (
    SEARCH_QUERIES_TIER1
    + SEARCH_QUERIES_TIER2
    + SEARCH_QUERIES_TIER3
    + REALTIME_NEWS_QUERIES
    + ACADEMIC_QUERIES
    + OFFICIALS_QUERIES
    + MOH_SITE_QUERIES
    + OFFICIAL_QUERIES
    + DONOR_QUERIES
    + FUNDING_QUERIES
    + PROCUREMENT_PORTAL_QUERIES
    + REGULATORY_QUERIES
    + BUDGET_QUERIES
    + CLINICAL_MEDTRONIC_QUERIES
    + REIMBURSEMENT_NCD_QUERIES
    + CONFERENCE_QUERIES
    + SENTIMENT_QUERIES
    + LINKEDIN_QUERIES
)

# =============================================================================
# KEY MINISTRY OFFICIALS
# =============================================================================

KEY_OFFICIALS: dict[str, dict] = {
    "Sierra Leone": {
        "minister": "Austin Demby",
        "title":    "Minister of Health Sierra Leone",
        "dg":       "MOHS Sierra Leone Ministry of Health Sanitation",
    },
    "Bangladesh": {
        "minister": "Sardar Md. Sakhawat Hossain",
        "title":    "Minister of Health and Family Welfare Bangladesh",
        "dg":       "Prof. Pravath Chandra Biswas Director General DGHS Bangladesh",
    },
    "Kenya": {
        "minister": "Aden Duale",
        "title":    "Cabinet Secretary Health Kenya",
        "dg":       "Dr. Patrick Amoth Director General Health Kenya",
        "ps":       "Mary Muthoni Muriuki Principal Secretary Kenya Health",
    },
    "Rwanda": {
        "minister": "Sabin Nsanzimana",
        "title":    "Minister of Health Rwanda",
        "dg":       "Prof. Claude Mambo Muvunyi Director General Rwanda Biomedical Centre RBC",
    },
    "Ghana": {
        "minister": "Kwabena Mintah Akandoh",
        "title":    "Minister of Health Ghana",
        "dg":       "Prof. Samuel Kaba Akoriyea Director-General Ghana Health Service GHS",
    },
    "India": {
        "minister": "JP Nadda",
        "title":    "Union Minister Health and Family Welfare India",
        "dg":       "Apurva Chandra Secretary Ministry of Health Family Welfare MOHFW India",
    },
    "Saudi Arabia": {
        "minister": "Fahad Al-Jalajel",
        "title":    "Minister of Health Saudi Arabia",
        "dg":       "Dr. Hisham Aljadhey CEO Saudi Food Drug Authority SFDA",
    },
    "Tanzania": {
        "minister": "Mohamed Mchengerwa",
        "title":    "Minister of Health Tanzania",
        "dg":       "Dr. Seif Shekalaghe Permanent Secretary Tanzania Ministry Health",
    },
    "Bhutan": {
        "minister": "Tandin Wangchuk",
        "title":    "Minister of Health Bhutan",
        "dg":       "Kinga Jamphel Director General Department Health Services Bhutan",
    },
    "United States": {
        "minister": "Robert F Kennedy Jr",
        "title":    "HHS Secretary United States",
        "dg":       "Dr. Martin Makary FDA Commissioner United States",
    },
}

# =============================================================================
# PER-COUNTRY QUERY MAP (used for country-specific deep runs)
# =============================================================================

COUNTRY_QUERIES: dict[str, dict] = {
    "Sierra Leone": {
        "search":    ["Sierra Leone digital health 2026", "Sierra Leone mHealth telemedicine 2026", "Sierra Leone health technology 2025 2026"],
        "official":  ["Austin Demby digital health announcement", "MOHS Sierra Leone health policy 2026"],
        "moh_site":  "site:mohs.gov.sl digital health",
        "sentiment": "digital health Sierra Leone community discussion 2026",
        "github":    ["CHT Sierra Leone", "OpenSRP Sierra Leone", "DHIS2 Sierra Leone"],
        "academic":  "site:medrxiv.org Sierra Leone digital health",
        "procurement": "site:ppip.gov.sl digital health OR site:nppa.gov.sl digital health",
    },
    "Bangladesh": {
        "search":    ["Bangladesh digital health 2026", "Bangladesh telemedicine mHealth 2026", "Bangladesh eHealth tools 2025 2026"],
        "official":  ["Bangladesh health minister digital announcement 2026", "DGHS Bangladesh eHealth 2026"],
        "moh_site":  "site:mohfw.gov.bd digital health",
        "sentiment": "digital health Bangladesh discussion 2026",
        "github":    ["OpenMRS Bangladesh", "DHIS2 Bangladesh", "digital health Bangladesh"],
        "academic":  "site:medrxiv.org Bangladesh digital health",
        "procurement": "site:cptu.gov.bd digital health",
    },
    "Kenya": {
        "search":    ["Kenya digital health 2026", "Kenya telemedicine mHealth 2026"],
        "official":  ["Aden Duale digital health announcement 2026", "Kenya MOH digital launched 2026"],
        "moh_site":  "site:health.go.ke digital health",
        "sentiment": "digital health Kenya community discussion 2026",
        "github":    ["Kenya MOH DWAPI", "OpenSRP Kenya", "IntelliSOFT Kenya EMR", "DHIS2 Kenya"],
        "academic":  "site:medrxiv.org Kenya digital health",
        "procurement": "site:ppip.go.ke digital health",
    },
    "Rwanda": {
        "search":    ["Rwanda digital health 2026", "Rwanda eHealth telemedicine 2026"],
        "official":  ["Sabin Nsanzimana digital health 2026", "Rwanda MOH digital update 2026"],
        "moh_site":  "site:moh.gov.rw digital health",
        "sentiment": "digital health Rwanda discussion 2026",
        "github":    ["DHIS2 Rwanda", "OpenMRS Rwanda", "digital health Rwanda"],
        "academic":  "site:medrxiv.org Rwanda digital health",
        "procurement": "site:rppa.gov.rw digital health",
    },
    "Ghana": {
        "search":    ["Ghana digital health 2026", "Ghana mHealth health technology 2026"],
        "official":  ["Kwabena Mintah Akandoh digital health 2026", "Ghana MOH digital 2026"],
        "moh_site":  "site:moh.gov.gh digital health",
        "sentiment": "digital health Ghana discussion 2026",
        "github":    ["DHIS2 Ghana", "OpenMRS Ghana", "Ghana Health Service digital"],
        "academic":  "site:medrxiv.org Ghana digital health",
        "procurement": "site:ppa.gov.gh digital health",
    },
    "India": {
        "search":    ["India digital health telemedicine AI 2026", "India ABDM Ayushman digital 2026"],
        "official":  ["India Ministry Health digital policy 2026", "MOHFW digital announcement 2026"],
        "moh_site":  "site:mohfw.gov.in digital health",
        "sentiment": "digital health India discussion 2026",
        "github":    ["NHA-ABDM", "OpenMRS India", "DHIS2 India", "eSanjeevani India"],
        "academic":  "site:medrxiv.org India digital health",
        "procurement": "site:gem.gov.in health technology",
    },
    "Saudi Arabia": {
        "search":    ["Saudi Arabia digital health 2026", "Saudi Arabia eHealth telemedicine 2026"],
        "official":  ["Fahad Al-Jalajel MOH digital 2026", "Saudi health minister digital 2026"],
        "moh_site":  "site:moh.gov.sa digital health",
        "sentiment": "digital health Saudi Arabia discussion 2026",
        "github":    ["Saudi Arabia digital health", "SFDA digital health"],
        "academic":  "site:medrxiv.org Saudi Arabia digital health",
        "procurement": "site:moh.gov.sa procurement digital health",
    },
    "Tanzania": {
        "search":    ["Tanzania digital health 2026", "Tanzania mHealth technology 2026"],
        "official":  ["Mohamed Mchengerwa digital health 2026", "Tanzania MOH digital 2026"],
        "moh_site":  "site:mohcdgec.go.tz digital health",
        "sentiment": "digital health Tanzania discussion 2026",
        "github":    ["DHIS2 Tanzania", "OpenMRS Tanzania", "CHT Tanzania"],
        "academic":  "site:medrxiv.org Tanzania digital health",
        "procurement": "site:ppra.go.tz digital health",
    },
    "Bhutan": {
        "search":    ["Bhutan digital health 2026", "Bhutan eHealth healthcare 2025 2026"],
        "official":  ["Tandin Wangchuk Ministry Health digital 2026", "Bhutan MOH digital 2026"],
        "moh_site":  "site:health.gov.bt",
        "sentiment": "digital health Bhutan discussion 2026",
        "github":    ["Bhutan digital health", "DHIS2 Bhutan"],
        "academic":  "site:medrxiv.org Bhutan digital health",
        "procurement": "site:gpms.gov.bt digital health",
    },
    "United States": {
        "search":    ["US digital health FDA AI 2026", "US digital health Africa India partnership 2026"],
        "official":  ["HHS FDA digital health policy 2026", "CMS digital health reimbursement 2026"],
        "moh_site":  "site:hhs.gov digital health",
        "sentiment": "digital health United States innovation 2026",
        "github":    ["FDA digital health", "NIH digital health Africa", "USAID health technology"],
        "academic":  "site:medrxiv.org US digital health FDA 2026",
        "procurement": "site:sam.gov digital health Africa",
    },
}

