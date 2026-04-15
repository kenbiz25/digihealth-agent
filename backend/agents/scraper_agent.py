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

    await emit(f"Collected {len(all_raw)} raw results. Stratifying per country...")

    # ── Per-country bucketing ─────────────────────────────────────────────────
    # Each country gets its own raw-result bucket so no single country can
    # crowd out another within the same tier.
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

    # Per-country budgets: Tier 1 gets deepest individual coverage
    T1_BUDGET, T2_BUDGET, T3_BUDGET = 8, 5, 4

    stratified: list[dict] = []
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
            supp_tasks = []
            for c in all_missing:
                cq = COUNTRY_QUERIES.get(c, {})
                for q in cq.get("search", [f"digital health {c}"])[:2]:
                    supp_tasks.append((c, q, search_tavily(q, "news")))
                # Tier 3: also try general topic for broader hit
                if c in COUNTRIES_TIER3:
                    supp_tasks.append((c, f"{c} health technology", search_tavily(f"{c} health technology", "general")))

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
