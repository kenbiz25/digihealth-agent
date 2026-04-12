"""
Scraper Agent - Collects digital health Africa news from Twitter, LinkedIn, and the web.
Uses Tavily for broad web/social search + optional Twitter API v2.
"""
import asyncio
import httpx
import json
from datetime import datetime, timedelta
from typing import Any
from backend.config import (
    TAVILY_API_KEY, TWITTER_BEARER_TOKEN, SERPER_API_KEY,
    SEARCH_QUERIES, SEARCH_QUERIES_TIER1, SEARCH_QUERIES_TIER2, SEARCH_QUERIES_TIER3,
    TWITTER_QUERIES, MOH_SITE_QUERIES, OFFICIAL_QUERIES, SENTIMENT_QUERIES,
    MAX_ARTICLES_PER_RUN, AI_PROVIDER, SCRAPER_MODEL, SEARCH_LOOKBACK_DAYS,
    TARGET_COUNTRIES,
)
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

Coverage scope — include ALL of:
- Digital health tools, apps, platforms, or infrastructure launched/implemented
- Telemedicine, mHealth, eHealth deployments and updates
- Ministry of Health plans, policies, meetings, or official announcements
- Government minister or senior official statements/pronouncements on healthcare
- Health funding, grants, partnerships, and procurement decisions
- AI/data in healthcare
- LinkedIn/Twitter community discussions, reactions, and sentiments about health developments
- Conference outcomes and stakeholder meetings

Return a JSON array of news items. If no relevant items found, return [].
"""


async def search_tavily(query: str, topic: str = "general") -> list[dict]:
    """Search using Tavily API - supports web + social content."""
    if not TAVILY_API_KEY:
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
        "days": SEARCH_LOOKBACK_DAYS,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            r = await client.post(url, json=payload)
            r.raise_for_status()
            data = r.json()
            return data.get("results", [])
        except Exception as e:
            print(f"[Scraper] Tavily error for '{query}': {e}")
            return []


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
    """Remove duplicate URLs."""
    seen_urls = set()
    unique = []
    for a in articles:
        url = a.get("url", "")
        if url and url not in seen_urls:
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

    if country_filter:
        # ── Country-specific run: use per-country query map ─────────────────
        cq = COUNTRY_QUERIES.get(country_filter, {})
        if not cq:
            await emit(f"Unknown country filter '{country_filter}' — running full scan instead.")
            country_filter = None
        else:
            if TAVILY_API_KEY:
                for q in cq.get("search", []):
                    search_tasks.append(("tavily_country_general", q, search_tavily(q, "general")))
                    search_tasks.append(("tavily_country_news",    q, search_tavily(q, "news")))
                moh = cq.get("moh_site", "")
                if moh:
                    search_tasks.append(("moh_site", moh, search_tavily(moh, "news")))
                for q in cq.get("official", []):
                    search_tasks.append(("official", q, search_tavily(q, "news")))
                sent = cq.get("sentiment", "")
                if sent:
                    search_tasks.append(("sentiment", sent, search_tavily(sent, "general")))
                    search_tasks.append(("linkedin", f"site:linkedin.com {sent}", search_tavily(f"site:linkedin.com digital health {country_filter}", "general")))
                sources_searched.append(f"Tavily — {country_filter} focused")
                sources_searched.append(f"MoH Site — {country_filter}")
                sources_searched.append(f"Officials — {country_filter}")
            if TWITTER_BEARER_TOKEN:
                search_tasks.append(("twitter_api", f"digital health {country_filter}", search_twitter_api(f"digital health {country_filter}")))
                sources_searched.append("Twitter/X API")
            if SERPER_API_KEY and not TAVILY_API_KEY:
                for q in cq.get("search", []):
                    search_tasks.append(("serper", q, search_serper(q)))
                sources_searched.append("Google Search (Serper)")

    if not country_filter:
        # ── Full run: all countries, tiered priority ────────────────────────
        if TAVILY_API_KEY:
            for q in SEARCH_QUERIES_TIER1:
                search_tasks.append(("tavily_t1_general", q, search_tavily(q, "general")))
                search_tasks.append(("tavily_t1_news",    q, search_tavily(q, "news")))
            for q in SEARCH_QUERIES_TIER2:
                search_tasks.append(("tavily_t2_general", q, search_tavily(q, "general")))
                search_tasks.append(("tavily_t2_news",    q, search_tavily(q, "news")))
            for q in SEARCH_QUERIES_TIER3:
                search_tasks.append(("tavily_t3_general", q, search_tavily(q, "general")))
                search_tasks.append(("tavily_t3_news",    q, search_tavily(q, "news")))
            sources_searched.append("Tavily Web Search")

        if TWITTER_BEARER_TOKEN:
            for q in TWITTER_QUERIES:
                search_tasks.append(("twitter_api", q, search_twitter_api(q)))
            sources_searched.append("Twitter/X API")

        if TAVILY_API_KEY:
            linkedin_queries = [
                "site:linkedin.com digital health Sierra Leone Bangladesh",
                "site:linkedin.com digital health Kenya Rwanda Ghana India",
            ]
            for q in linkedin_queries:
                search_tasks.append(("linkedin_tavily", q, search_tavily(q)))
            sources_searched.append("LinkedIn (via Tavily)")
            for q in MOH_SITE_QUERIES:
                search_tasks.append(("moh_site", q, search_tavily(q, "news")))
            sources_searched.append(f"Ministry of Health Sites ({len(MOH_SITE_QUERIES)} countries)")
            for q in OFFICIAL_QUERIES:
                search_tasks.append(("official", q, search_tavily(q, "news")))
            sources_searched.append("Official/Ministry Pronouncements")
            for q in SENTIMENT_QUERIES:
                search_tasks.append(("sentiment", q, search_tavily(q, "general")))
            sources_searched.append("Social Sentiment (LinkedIn/Twitter)")
        elif SERPER_API_KEY:
            for q in MOH_SITE_QUERIES:
                search_tasks.append(("moh_site_serper", q, search_serper(q)))
            sources_searched.append("Ministry of Health Sites via Serper")

        if SERPER_API_KEY and not TAVILY_API_KEY:
            for q in SEARCH_QUERIES[:6]:
                search_tasks.append(("serper", q, search_serper(q)))
            sources_searched.append("Google Search (Serper)")

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

    await emit(f"Collected {len(all_raw)} raw results. Stratifying by tier...")

    # ── Stratified sampling: bucket by tier so every tier gets AI budget ──────
    # Without this, Tier 1's high query volume would fill the [:N] slice
    # and Tier 3 / official / sentiment articles would never reach Claude.
    tier1_raw, tier2_raw, tier3_raw, official_raw, sentiment_raw, country_raw, other_raw = (
        [], [], [], [], [], [], []
    )
    for i, (src_type, _query, _) in enumerate(search_tasks):
        result = results[i]
        if isinstance(result, Exception):
            continue
        for item in result:
            item["_src_type"] = src_type
            item["_query"] = _query
        if "t1" in src_type:
            tier1_raw.extend(result)
        elif "t2" in src_type:
            tier2_raw.extend(result)
        elif "t3" in src_type:
            tier3_raw.extend(result)
        elif src_type in ("official", "moh_site", "moh_site_serper"):
            official_raw.extend(result)
        elif src_type in ("sentiment", "linkedin_tavily", "linkedin"):
            sentiment_raw.extend(result)
        elif "country" in src_type:
            country_raw.extend(result)
        else:
            other_raw.extend(result)

    # Budget allocation: keep each bucket proportional to priority but ensure lower tiers are represented
    stratified = (
        tier1_raw[:15]    +   # Tier 1 — deepest (Sierra Leone, Bangladesh)
        tier2_raw[:12]    +   # Tier 2 — broad (Kenya, Rwanda, Ghana, India)
        tier3_raw[:10]    +   # Tier 3 — always included (Saudi Arabia, Tanzania, Bhutan)
        official_raw[:8]  +   # Official signals — always prioritised
        sentiment_raw[:5] +   # Social sentiment
        country_raw[:8]   +   # Country-specific run queries
        other_raw[:5]         # Twitter / other
    )
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

    slim_raw = [slim_result(r) for r in slim_input[:55]]
    await emit(f"Stratified to {len(slim_raw)} items (T1:{len(tier1_raw[:15])} T2:{len(tier2_raw[:12])} T3:{len(tier3_raw[:10])} Off:{len(official_raw[:8])} Sent:{len(sentiment_raw[:5])}). Running AI extraction...")

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

    # ── Adaptive redistribution: if higher tiers have no articles, supplement lower tiers ──
    if not country_filter:
        tier1_countries = {"Sierra Leone", "Bangladesh"}
        tier2_countries = {"Kenya", "Rwanda", "Ghana", "India"}
        tier3_countries = {"Saudi Arabia", "Tanzania", "Bhutan"}

        def countries_covered(arts: list[dict], target: set) -> set:
            covered = set()
            for a in arts:
                mentioned = a.get("countries_mentioned") or []
                if not mentioned:
                    text = (a.get("title", "") + " " + a.get("raw_content", "")).lower()
                    mentioned = [c for c in TARGET_COUNTRIES if c.lower() in text]
                covered.update(set(mentioned) & target)
            return covered

        t1_covered = countries_covered(articles, tier1_countries)
        t2_covered = countries_covered(articles, tier2_countries)
        t3_covered = countries_covered(articles, tier3_countries)

        # Supplement tiers with zero coverage using extra targeted searches
        supplemental_tasks = []
        if not t1_covered and TAVILY_API_KEY:
            await emit("Tier 1 has no articles — running supplemental Tier 1 searches...")
            for q in SEARCH_QUERIES_TIER1[:4]:
                supplemental_tasks.append(("supp_t1", q, search_tavily(q, "news")))
        if not t2_covered and TAVILY_API_KEY:
            await emit("Tier 2 has no articles — redistributing tokens to Tier 2...")
            for q in SEARCH_QUERIES_TIER2[:4]:
                supplemental_tasks.append(("supp_t2", q, search_tavily(q, "news")))
        if not t3_covered and TAVILY_API_KEY:
            await emit("Tier 3 has no articles — supplementing Tier 3 queries...")
            for q in SEARCH_QUERIES_TIER3[:4]:
                supplemental_tasks.append(("supp_t3", q, search_tavily(q, "news")))

        if supplemental_tasks:
            supp_results = await asyncio.gather(*[t[2] for t in supplemental_tasks], return_exceptions=True)
            supp_raw = []
            for i, (src_type, _q, _) in enumerate(supplemental_tasks):
                res = supp_results[i]
                if isinstance(res, Exception):
                    continue
                for item in res:
                    item["_src_type"] = src_type
                supp_raw.extend(res)

            if supp_raw:
                supp_slim = [slim_result(r) for r in supp_raw[:20]]
                supp_prompt = f"""Supplemental search results for target countries with no coverage.
Today: {datetime.utcnow().strftime('%Y-%m-%d')}
Results:
{json.dumps(supp_slim, indent=2)}
Return JSON array. Each item: {{title, url, source, source_name, published_at, raw_content, relevance_score, is_africa_focused, is_official, sentiment_signal}}
"""
                await asyncio.sleep(15)  # short pause before second AI call
                supp_text, supp_tokens = call_ai(
                    client, SYSTEM_PROMPT, supp_prompt,
                    model_tier=SCRAPER_MODEL, max_tokens=2000, provider=AI_PROVIDER
                )
                tokens += supp_tokens
                try:
                    supp_articles = parse_json_response(supp_text)
                    supp_articles = [a for a in supp_articles if isinstance(a, dict) and a.get("relevance_score", 0) >= 0.5]
                    articles.extend(supp_articles)
                    articles = deduplicate(articles)
                    await emit(f"Supplemental extraction added {len(supp_articles)} more articles.")
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
