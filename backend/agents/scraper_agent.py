"""
Scraper Agent - Collects digital health Africa news from Twitter, LinkedIn, and the web.
Primary: Tavily API. Free fallback: Google News RSS + DuckDuckGo (no API key required).
"""
import asyncio
import httpx
import json
import re
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import Any
from backend.config import (
    TAVILY_API_KEY, TWITTER_BEARER_TOKEN, SERPER_API_KEY,
    SEARCH_QUERIES, SEARCH_QUERIES_TIER1, SEARCH_QUERIES_TIER2, SEARCH_QUERIES_TIER3,
    TWITTER_QUERIES, LINKEDIN_QUERIES, MOH_SITE_QUERIES, OFFICIAL_QUERIES, SENTIMENT_QUERIES, DONOR_QUERIES,
    MAX_ARTICLES_PER_RUN, AI_PROVIDER, SCRAPER_MODEL, SEARCH_LOOKBACK_DAYS,
    TARGET_COUNTRIES, COUNTRIES_TIER1, COUNTRIES_TIER2, COUNTRIES_TIER3,
    COUNTRY_QUERIES, EXCLUDED_URLS,
)

# Hard cap on Tavily calls per full run — keeps usage ≤50 searches/run
MAX_TAVILY_CALLS = 50

# Session-level flag: set True when Tavily returns 432 (quota exceeded)
_tavily_quota_exceeded = False

# Semaphore limits concurrent DuckDuckGo calls (DDG blocks high concurrency)
_ddg_semaphore: asyncio.Semaphore | None = None

from backend.agents.base_agent import get_ai_client, call_ai, parse_json_response


SYSTEM_PROMPT = """You are a news intelligence agent specializing in digital health for specific target countries.

TARGET COUNTRIES ONLY (discard everything else):
  Tier 1 — Sierra Leone, Bangladesh
  Tier 2 — Kenya, Rwanda, Ghana, India
  Tier 3 — Saudi Arabia, Tanzania, Bhutan

Your job is to extract structured news items from raw search results.
ONLY include items that are clearly about one or more of the target countries above.
Discard any item that does not mention a target country.

For each relevant news item extract:
- title: concise news headline
- url: source URL
- source: platform (twitter/linkedin/web/news)
- source_name: publication or account name
- published_at: date if available (ISO format)
- raw_content: key excerpt or summary of the content
- relevance_score: 0.0-1.0 (how relevant to digital health in a target country)
- is_africa_focused: true/false
- is_official: true if from a Ministry of Health, government body, or named senior official; false otherwise
- sentiment_signal: "positive" | "negative" | "neutral" | "mixed" — the tone of the item

SOURCE SCOPE — cast wide, do NOT limit to African publications:
- Global donors and funders reporting on target countries: USAID, Gates Foundation,
  Wellcome Trust, FCDO/DFID, Gavi, Global Fund, World Bank, AfDB, UNICEF, WHO, PEPFAR
- International health journals and think-tanks: The Lancet, BMJ, Health Affairs,
  GSMA Intelligence, PATH, PSI, JSI, Aga Khan Foundation, Jhpiego, MSF
- Government and intergovernmental sources: ministry sites, UN agencies, World Bank
- Tech/innovation press covering these countries: MedCity News, Health Tech World,
  TechCrunch Africa, Disrupt Africa, Quartz Africa, Rest of World
- LinkedIn posts, tweets, conference proceedings, donor press releases

Coverage scope — include ALL of:
- Digital health tools, apps, platforms, or infrastructure launched/implemented
- Telemedicine, mHealth, eHealth deployments and updates
- Ministry of Health plans, policies, meetings, or official announcements
- Government minister or senior official statements/pronouncements on healthcare
- Health funding, grants, partnerships, and procurement decisions (from any donor)
- AI/data in healthcare
- Donor reports, evaluations, and implementation updates mentioning target countries
- LinkedIn/Twitter community discussions, reactions, and sentiments about health developments
- Conference outcomes and stakeholder meetings

DEDUPLICATION RULE: If two or more items report the same announcement, event, or story (even from different websites), include ONLY the most informative version. One item per story — do not let the same news appear twice with different sources.

Return a JSON array of news items. If no relevant items found, return [].
"""


async def search_tavily(query: str, topic: str = "general", days: int | None = None) -> list[dict]:
    """Search using Tavily API. Detects quota exhaustion and sets session flag."""
    global _tavily_quota_exceeded
    if _tavily_quota_exceeded or not TAVILY_API_KEY:
        return []
    url = "https://api.tavily.com/search"
    payload = {
        "api_key": TAVILY_API_KEY,
        "query": query,
        "search_depth": "advanced",
        "include_answer": False,
        "include_raw_content": True,
        "max_results": 10,
        "topic": topic,
        "days": days if days is not None else SEARCH_LOOKBACK_DAYS,
        "exclude_domains": ["msn.com", "yahoo.com", "allafrica.com", "feedspot.com", "flipboard.com"],
    }
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            r = await client.post(url, json=payload)
            if r.status_code == 432:
                _tavily_quota_exceeded = True
                print("[Scraper] Tavily quota exceeded — switching to free search for this session")
                return []
            r.raise_for_status()
            return r.json().get("results", [])
        except Exception as e:
            print(f"[Scraper] Tavily error for '{query}': {e}")
            return []


async def search_google_news_rss(query: str, days: int | None = None) -> list[dict]:
    """Free: Google News RSS — no API key, concurrent-safe, best for news queries."""
    encoded = urllib.parse.quote(query)
    # tbs param: qdr:d3 = last 3 days, qdr:w = last week, qdr:m = last month
    tbs_map = {1: "qdr:d", 2: "qdr:d2", 3: "qdr:d3", 7: "qdr:w", 30: "qdr:m"}
    tbs = tbs_map.get(days or SEARCH_LOOKBACK_DAYS, "qdr:w")
    url = f"https://news.google.com/rss/search?q={encoded}&hl=en-US&gl=US&ceid=US:en&tbs={tbs}&num=10"
    headers = {"User-Agent": "Mozilla/5.0 (compatible; DigiHealthBot/1.0)"}
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        try:
            r = await client.get(url, headers=headers)
            r.raise_for_status()
            root = ET.fromstring(r.text)
            results = []
            for item in root.findall(".//item")[:10]:
                title = item.findtext("title") or ""
                link = item.findtext("link") or ""
                pub_date = item.findtext("pubDate") or ""
                source_el = item.find("source")
                source_name = (source_el.text if source_el is not None else "") or "Google News"
                description = re.sub(r"<[^>]+>", "", item.findtext("description") or "")
                if not link:
                    continue
                results.append({
                    "title": title,
                    "url": link,
                    "content": description,
                    "source": "news",
                    "source_name": source_name,
                    "published_date": pub_date,
                })
            return results
        except Exception as e:
            print(f"[Scraper] Google News RSS error for '{query}': {e}")
            return []


async def search_duckduckgo(query: str, days: int | None = None) -> list[dict]:
    """Free: DuckDuckGo — supports site: operators, best for web/LinkedIn/general queries."""
    global _ddg_semaphore
    if _ddg_semaphore is None:
        _ddg_semaphore = asyncio.Semaphore(3)
    async with _ddg_semaphore:
        try:
            from ddgs import DDGS
            loop = asyncio.get_event_loop()
            d = days or SEARCH_LOOKBACK_DAYS
            timelimit = "d" if d <= 1 else ("w" if d <= 7 else "m")
            raw = await loop.run_in_executor(None, lambda: list(DDGS().text(query, max_results=8, timelimit=timelimit)))
            return [
                {
                    "title": r.get("title", ""),
                    "url": r.get("href", ""),
                    "content": r.get("body", ""),
                    "source": "web",
                    "source_name": urllib.parse.urlparse(r.get("href", "")).netloc,
                    "published_date": "",
                }
                for r in raw if r.get("href")
            ]
        except Exception as e:
            print(f"[Scraper] DuckDuckGo error for '{query}': {e}")
            return []


async def search_web(query: str, topic: str = "general", days: int | None = None) -> list[dict]:
    """
    Unified search entry point.
    Uses Tavily when quota is available; auto-falls back to free alternatives:
      - topic='news' without site: → Google News RSS
      - topic='general' or site: query → DuckDuckGo
    """
    if TAVILY_API_KEY and not _tavily_quota_exceeded:
        return await search_tavily(query, topic, days=days)
    # Free fallback path
    if topic == "news" and "site:" not in query:
        return await search_google_news_rss(query, days=days)
    return await search_duckduckgo(query, days=days)


async def search_twitter_api(query: str) -> list[dict]:
    """Search Twitter/X using Bearer token (API v2)."""
    if not TWITTER_BEARER_TOKEN:
        return []
    url = "https://api.twitter.com/2/tweets/search/recent"
    params = {
        "query": f"{query} -is:retweet lang:en",
        "max_results": 20,
        "tweet.fields": "created_at,author_id,text,public_metrics,entities",
        "expansions": "author_id",
        "user.fields": "name,username,verified",
        "start_time": (datetime.utcnow() - timedelta(days=SEARCH_LOOKBACK_DAYS)).isoformat() + "Z",
    }
    headers = {"Authorization": f"Bearer {TWITTER_BEARER_TOKEN}"}
    async with httpx.AsyncClient(timeout=20) as client:
        try:
            r = await client.get(url, params=params, headers=headers)
            r.raise_for_status()
            data = r.json()
            tweets = data.get("data", [])
            users = {u["id"]: u for u in data.get("includes", {}).get("users", [])}
            results = []
            for t in tweets:
                user = users.get(t.get("author_id", ""), {})
                results.append({
                    "title": t["text"][:100],
                    "url": f"https://twitter.com/{user.get('username','_')}/status/{t['id']}",
                    "content": t["text"],
                    "source": "twitter",
                    "source_name": f"@{user.get('username', 'unknown')}",
                    "published_date": t.get("created_at", ""),
                })
            return results
        except Exception as e:
            print(f"[Scraper] Twitter API error: {e}")
            return []


async def search_serper(query: str) -> list[dict]:
    """Fallback: Google search via Serper API."""
    if not SERPER_API_KEY:
        return []
    url = "https://google.serper.dev/search"
    headers = {"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"}
    payload = {"q": query, "num": 10, "tbs": "qdr:d"}  # past 24 hours
    async with httpx.AsyncClient(timeout=20) as client:
        try:
            r = await client.post(url, headers=headers, json=payload)
            r.raise_for_status()
            data = r.json()
            results = []
            for item in data.get("organic", []):
                results.append({
                    "title": item.get("title", ""),
                    "url": item.get("link", ""),
                    "content": item.get("snippet", ""),
                    "source": "web",
                    "source_name": item.get("source", ""),
                    "published_date": item.get("date", ""),
                })
            return results
        except Exception as e:
            print(f"[Scraper] Serper error: {e}")
            return []


def deduplicate(articles: list[dict]) -> list[dict]:
    """Remove duplicate and excluded URLs."""
    seen_urls = set()
    unique = []
    for a in articles:
        url = a.get("url", "")
        if not url:
            continue
        if url in EXCLUDED_URLS:
            continue
        if url not in seen_urls:
            seen_urls.add(url)
            unique.append(a)
    return unique


async def run_scraper(run_id: str, websocket_callback=None, country_filter: str | None = None) -> dict[str, Any]:
    """
    Main scraper entry point.
    country_filter: if set, only searches for that specific country.
    Returns: { articles: [...], tokens_used: int, sources_searched: [...] }
    """
    async def emit(msg: str):
        if websocket_callback:
            await websocket_callback({"step": "scraper", "message": msg})

    scope = f"{country_filter} only" if country_filter else "all target countries"
    await emit(f"Starting news collection — scope: {scope}...")

    all_raw = []
    sources_searched = []
    search_tasks = []
    _base_tavily_count = 0  # updated after full-run query assembly

    if country_filter:
        # ── Country-specific deep scan: full 50-call budget, 3-day lookback ──
        # All resources focused on one country for maximum freshness and coverage.
        cq = COUNTRY_QUERIES.get(country_filter, {})
        if not cq:
            await emit(f"Unknown country filter '{country_filter}' — running full scan instead.")
            country_filter = None
        else:
            c = country_filter
            moh = cq.get("moh_site", "")
            # 15 orthogonal query angles — news/general matched to content type
            deep_plan: list[tuple[str, str, str]] = [
                ("country_news",      f"{c} digital health launched announced 2025 2026",            "news"),
                ("country_news",      f"{c} Ministry of Health digital technology announcement",      "news"),
                ("country_news",      f"{c} mHealth telemedicine implementation deployed rollout",    "news"),
                ("country_news",      f"{c} health technology funding grant awarded 2025",            "news"),
                ("country_news",      f"{c} eHealth digital health policy regulation update",         "news"),
                ("country_news",      f"{c} health information system data platform update",          "news"),
                ("country_news",      f"{c} digital health AI artificial intelligence healthcare",    "news"),
                ("country_news",      f"{c} health technology conference summit stakeholder 2025",    "news"),
                ("country_news",      f"{c} WHO UNICEF USAID digital health partnership 2025",       "news"),
                ("country_news",      f"{c} health minister digital technology statement 2025",       "news"),
                ("country_news",      f"{c} telemedicine community health workers mobile",            "news"),
                ("country_news",      f"{c} digital health app platform service launched",            "news"),
                ("official",          f"{c} Minister of Health digital health pronouncement 2025",   "news"),
                # Donor / global org intelligence
                ("donor",             f"USAID WHO UNICEF Gates {c} digital health 2025",             "news"),
                ("donor",             f"World Bank FCDO {c} health technology funding 2025",         "news"),
                ("donor",             f"PATH JSI Wellcome {c} digital health implementation 2025",   "news"),
                # Social / LinkedIn
                ("linkedin_country",  f"site:linkedin.com {c} digital health",                       "general"),
                ("sentiment_country", f"{c} digital health community discussion reaction 2025",       "general"),
            ]
            if moh:
                deep_plan.append(("moh_site", moh, "news"))
            # Cap at full budget
            deep_plan = deep_plan[:MAX_TAVILY_CALLS]
            _base_tavily_count = len(deep_plan)

            for src_type, q, topic in deep_plan:
                # 3-day lookback for single-country: get the very latest
                search_tasks.append((src_type, q, search_web(q, topic, days=3)))

            sources_searched.append(f"{c} deep scan — {len(deep_plan)} queries (3-day lookback)")
            sources_searched.append(f"MoH Site | Official | LinkedIn | Sentiment — {c}")

            if TWITTER_BEARER_TOKEN:
                search_tasks.append(("twitter_api", f"digital health {c}", search_twitter_api(f"digital health {c}")))
                sources_searched.append("Twitter/X API")

    if not country_filter:
        # ── Full run: tiered, single-topic-per-query, capped at MAX_TAVILY_CALLS ──
        tavily_plan: list[tuple[str, str, str]] = []  # (src_type, query, topic)

        # Tier 1 — news topic (24 h–7 day fresh news)
        for q in SEARCH_QUERIES_TIER1:
            tavily_plan.append(("tavily_t1", q, "news"))
        # Tier 2 — news topic
        for q in SEARCH_QUERIES_TIER2:
            tavily_plan.append(("tavily_t2", q, "news"))
        # Tier 3 — general topic (broader web; lower daily news volume)
        for q in SEARCH_QUERIES_TIER3:
            tavily_plan.append(("tavily_t3", q, "general"))
        # LinkedIn discussions — general topic
        for q in LINKEDIN_QUERIES:
            tavily_plan.append(("linkedin_tavily", q, "general"))
        # Ministry of Health sites — news topic
        for q in MOH_SITE_QUERIES:
            tavily_plan.append(("moh_site", q, "news"))
        # Official pronouncements — news topic
        for q in OFFICIAL_QUERIES:
            tavily_plan.append(("official", q, "news"))
        # Donor & global org updates — news topic
        for q in DONOR_QUERIES:
            tavily_plan.append(("donor", q, "news"))
        # Social sentiment — general topic
        for q in SENTIMENT_QUERIES:
            tavily_plan.append(("sentiment", q, "general"))

        # Enforce hard cap — trim to budget before firing any calls
        if len(tavily_plan) > MAX_TAVILY_CALLS:
            tavily_plan = tavily_plan[:MAX_TAVILY_CALLS]

        if TAVILY_API_KEY:
            for src_type, q, topic in tavily_plan:
                search_tasks.append((src_type, q, search_web(q, topic)))
            sources_searched.append(f"Tavily ({len(tavily_plan)} queries, ≤{MAX_TAVILY_CALLS} cap)")
            sources_searched.append(f"Ministry of Health Sites ({len(MOH_SITE_QUERIES)})")
            sources_searched.append("LinkedIn + Official + Sentiment (via Tavily)")
        elif SERPER_API_KEY:
            for q in SEARCH_QUERIES[:8]:
                search_tasks.append(("serper", q, search_serper(q)))
            for q in MOH_SITE_QUERIES:
                search_tasks.append(("moh_site_serper", q, search_serper(q)))
            sources_searched.append("Google Search (Serper)")

        if TWITTER_BEARER_TOKEN:
            for q in TWITTER_QUERIES:
                search_tasks.append(("twitter_api", q, search_twitter_api(q)))
            sources_searched.append("Twitter/X API")

        # Track how many Tavily calls were actually queued for supplemental budget
        _base_tavily_count = len(tavily_plan)

    await emit(f"Searching {len(search_tasks)} queries across {len(sources_searched)} sources...")

    # Execute all searches concurrently
    results = await asyncio.gather(*[t[2] for t in search_tasks], return_exceptions=True)
    for i, (src_type, query, _) in enumerate(search_tasks):
        result = results[i]
        if isinstance(result, Exception):
            print(f"[Scraper] Error in {src_type}: {result}")
            continue
        for item in result:
            item["_src_type"] = src_type
            item["_query"] = query
        all_raw.extend(result)

    # Strip excluded URLs before any processing
    all_raw = [r for r in all_raw if r.get("url", "") not in EXCLUDED_URLS]
    await emit(f"Collected {len(all_raw)} raw results (excluded URLs removed). Stratifying...")

    # ── Bucketing ────────────────────────────────────────────────────────────
    if country_filter:
        # Single-country deep scan: pass ALL results through — no tier capping
        # Deduplicate by URL then take up to 80 items for AI
        seen: set[str] = set()
        stratified: list[dict] = []
        for item in all_raw:
            url = item.get("url") or item.get("link") or ""
            if url and url not in seen:
                seen.add(url)
                stratified.append(item)
        await emit(f"Single-country deep scan: {len(stratified)} unique results for {country_filter}.")
    else:
        # Full run: per-country bucketing so no single country crowds others
        per_country: dict[str, list] = {c: [] for c in TARGET_COUNTRIES}
        official_raw:     list = []
        sentiment_raw:    list = []
        country_run_raw:  list = []
        other_raw:        list = []

        def _infer_country(query: str) -> str | None:
            q = query.lower()
            for c in TARGET_COUNTRIES:
                if c.lower() in q:
                    return c
            return None

        for i, (src_type, _query, _) in enumerate(search_tasks):
            result = results[i]
            if isinstance(result, Exception):
                continue
            for item in result:
                item["_src_type"] = src_type
                item["_query"] = _query
            if src_type in ("official", "moh_site", "moh_site_serper"):
                official_raw.extend(result)
            elif src_type in ("sentiment", "linkedin_tavily", "linkedin"):
                sentiment_raw.extend(result)
            elif "country" in src_type:
                country_run_raw.extend(result)
            else:
                c = _infer_country(_query)
                if c:
                    per_country[c].extend(result)
                else:
                    other_raw.extend(result)

        T1_BUDGET, T2_BUDGET, T3_BUDGET = 8, 5, 4
        stratified = []
        for c in COUNTRIES_TIER1:
            stratified.extend(per_country[c][:T1_BUDGET])
        for c in COUNTRIES_TIER2:
            stratified.extend(per_country[c][:T2_BUDGET])
        for c in COUNTRIES_TIER3:
            stratified.extend(per_country[c][:T3_BUDGET])
        stratified += official_raw[:8]
        stratified += sentiment_raw[:5]
        stratified += country_run_raw[:8]
        stratified += other_raw[:4]

    # Deduplicate within stratified set by URL
    seen_urls: set[str] = set()
    slim_input: list[dict] = []
    for r in stratified:
        url = r.get("url") or r.get("link") or ""
        if url and url in seen_urls:
            continue
        if url:
            seen_urls.add(url)
        slim_input.append(r)

    def slim_result(r: dict) -> dict:
        return {
            "title":          (r.get("title") or "")[:120],
            "url":            r.get("url") or r.get("link") or "",
            "snippet":        (r.get("content") or r.get("snippet") or "")[:200],
            "source":         r.get("source") or r.get("_src_type") or "web",
            "published_date": r.get("published_date") or r.get("date") or "",
        }

    # Log per-country raw counts so we can see distribution
    budget_log = " | ".join(
        f"{c}:{len(per_country[c])}"
        for c in TARGET_COUNTRIES if per_country[c]
    )
    slim_raw = [slim_result(r) for r in slim_input[:60]]

    # Early exit — no raw results means search API is exhausted or offline.
    # Skip Claude call entirely to avoid burning AI credits on nothing.
    if not slim_raw:
        await emit("WARNING: 0 raw results returned. Search API may be over quota or offline. Aborting — no AI credits used.")
        return {"articles": [], "tokens_used": 0, "sources_searched": sources_searched, "raw_count": 0}

    await emit(f"Per-country raw: {budget_log}. Sending {len(slim_raw)} items to AI...")

    client = get_ai_client(AI_PROVIDER)
    raw_text = json.dumps(slim_raw, indent=2)

    user_prompt = f"""Raw search results from web, news and social media.
Extract news items relevant to digital health in our target countries from the last {SEARCH_LOOKBACK_DAYS} days.
Today: {datetime.utcnow().strftime('%Y-%m-%d')}

Results:
{raw_text}

Return JSON array. Each item: {{title, url, source, source_name, published_at, raw_content, relevance_score, is_africa_focused, is_official, sentiment_signal}}
"""

    response_text, tokens = call_ai(
        client, SYSTEM_PROMPT, user_prompt,
        model_tier=SCRAPER_MODEL, max_tokens=4000, provider=AI_PROVIDER
    )

    try:
        articles = parse_json_response(response_text)
    except Exception as e:
        print(f"[Scraper] JSON parse error: {e}\nRaw: {response_text[:500]}")
        articles = []

    # Filter and deduplicate
    articles = [a for a in articles if isinstance(a, dict) and a.get("relevance_score", 0) >= 0.5]
    articles = deduplicate(articles)

    # ── Per-country gap check & guarantee ────────────────────────────────────
    # Check each individual country — not just each tier — and run targeted
    # supplemental searches for any country with zero articles.
    # Tier 3 uses a lower relevance threshold (0.3) since coverage is thinner.
    if not country_filter and TAVILY_API_KEY:

        def _articles_for_country(country: str, arts: list[dict]) -> list:
            out = []
            for a in arts:
                mentioned = a.get("countries_mentioned") or []
                if not mentioned:
                    text = (a.get("title", "") + " " + a.get("raw_content", "")).lower()
                    mentioned = [c for c in TARGET_COUNTRIES if c.lower() in text]
                if country in mentioned:
                    out.append(a)
            return out

        missing_t1 = [c for c in COUNTRIES_TIER1 if not _articles_for_country(c, articles)]
        missing_t2 = [c for c in COUNTRIES_TIER2 if not _articles_for_country(c, articles)]
        missing_t3 = [c for c in COUNTRIES_TIER3 if not _articles_for_country(c, articles)]
        all_missing = missing_t1 + missing_t2 + missing_t3

        if all_missing:
            await emit(f"Coverage gaps detected: {all_missing}. Running targeted supplemental searches...")
            supp_budget = max(0, MAX_TAVILY_CALLS - _base_tavily_count)
            supp_tasks = []
            for c in all_missing:
                if len(supp_tasks) >= supp_budget:
                    break
                cq = COUNTRY_QUERIES.get(c, {})
                for q in cq.get("search", [f"digital health {c}"])[:2]:
                    supp_tasks.append((c, q, search_web(q, "news")))
                # Tier 3: also try general topic for broader hit
                if c in COUNTRIES_TIER3 and len(supp_tasks) < supp_budget:
                    supp_tasks.append((c, f"{c} health technology 2025", search_web(f"{c} health technology 2025", "general")))

            await asyncio.sleep(12)
            supp_results = await asyncio.gather(*[t[2] for t in supp_tasks], return_exceptions=True)
            supp_raw: list[dict] = []
            for i, (c, q, _) in enumerate(supp_tasks):
                res = supp_results[i]
                if isinstance(res, Exception):
                    continue
                for item in res:
                    item["_src_type"] = "supp"
                    item["_query"] = q
                supp_raw.extend(res[:5])

            if supp_raw:
                supp_slim = [slim_result(r) for r in supp_raw[:25]]
                # Lower threshold hint for Tier 3 countries
                t3_hint = f" For Tier 3 countries ({', '.join(COUNTRIES_TIER3)}), accept relevance_score >= 0.3." if missing_t3 else ""
                supp_prompt = f"""Targeted supplemental search for countries with no coverage: {all_missing}.
Today: {datetime.utcnow().strftime('%Y-%m-%d')}
Results:
{json.dumps(supp_slim, indent=2)}
Return JSON array. Each item: {{title, url, source, source_name, published_at, raw_content, relevance_score, is_africa_focused, is_official, sentiment_signal}}
Include any item that mentions a target country even if digital health is indirect.{t3_hint}
"""
                await asyncio.sleep(15)
                supp_text, supp_tokens = call_ai(
                    client, SYSTEM_PROMPT, supp_prompt,
                    model_tier=SCRAPER_MODEL, max_tokens=2000, provider=AI_PROVIDER
                )
                tokens += supp_tokens
                try:
                    supp_articles = parse_json_response(supp_text)
                    # Tier 3 gets lower threshold; Tier 1/2 stay at 0.4
                    def _keep(a: dict) -> bool:
                        score = a.get("relevance_score", 0)
                        mentioned = a.get("countries_mentioned") or []
                        is_t3 = any(c in mentioned for c in COUNTRIES_TIER3)
                        return score >= (0.3 if is_t3 else 0.4)
                    supp_articles = [a for a in supp_articles if isinstance(a, dict) and _keep(a)]
                    articles.extend(supp_articles)
                    articles = deduplicate(articles)
                    await emit(f"Supplemental pass added {len(supp_articles)} articles. Gaps filled: {[c for c in all_missing if _articles_for_country(c, articles)]}")
                except Exception:
                    pass

    articles = articles[:MAX_ARTICLES_PER_RUN]
    await emit(f"Extracted {len(articles)} relevant articles after AI filtering.")

    return {
        "articles": articles,
        "tokens_used": tokens,
        "sources_searched": sources_searched,
        "raw_count": len(all_raw),
    }
