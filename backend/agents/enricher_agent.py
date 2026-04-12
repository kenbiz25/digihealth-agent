"""
Enricher Agent - Finds follow-up reading links, related research, context articles
and categorizes news into themes.
"""
import asyncio
import httpx
import json
from typing import Any
from backend.config import TAVILY_API_KEY, SERPER_API_KEY, AI_PROVIDER, ENRICHER_MODEL, MAX_FOLLOW_UP_LINKS
from backend.agents.base_agent import get_ai_client, call_ai, parse_json_response


TARGET_COUNTRY_LIST = "Sierra Leone, Bangladesh, Kenya, Rwanda, Ghana, India, Saudi Arabia, Tanzania, Bhutan"

ENRICHER_SYSTEM = f"""You are a research enrichment agent for digital health intelligence.
Target countries ONLY: {TARGET_COUNTRY_LIST}

Your role is to:
1. Categorize each article into themes (e.g., telemedicine, mHealth, AI diagnostics, health data, policy, funding, infrastructure)
2. Generate smart follow-up reading recommendations
3. Add relevant context (key organizations, countries, impact)
4. Suggest related search terms for deeper investigation
5. Extract key metrics or statistics mentioned

For each article, return:
{{
  "url": "original article url",
  "category": "primary theme",
  "sub_categories": ["list", "of", "themes"],
  "key_organizations": ["WHO", "Ministry of Health", etc.],
  "countries_mentioned": ["Sierra Leone", "Bangladesh", etc. — only from the target country list],
  "key_metrics": ["50,000 patients served", etc.],
  "impact_summary": "one line on the impact/significance",
  "follow_up_links": [
    {{"title": "...", "url": "...", "why_relevant": "..."}}
  ],
  "tags": ["mhealth", "funding", etc.]
}}
"""


async def find_follow_up_articles(title: str, category: str) -> list[dict]:
    """Search for related deeper reading articles."""
    if not TAVILY_API_KEY:
        return []
    query = f"{category} digital health Africa research {title[:60]}"
    url = "https://api.tavily.com/search"
    payload = {
        "api_key": TAVILY_API_KEY,
        "query": query,
        "search_depth": "basic",
        "max_results": MAX_FOLLOW_UP_LINKS,
        "topic": "general",
    }
    async with httpx.AsyncClient(timeout=20) as client:
        try:
            r = await client.post(url, json=payload)
            r.raise_for_status()
            results = r.json().get("results", [])
            return [{"title": r.get("title"), "url": r.get("url")} for r in results]
        except Exception:
            return []


async def run_enricher(
    articles: list[dict],
    run_id: str,
    websocket_callback=None,
) -> dict[str, Any]:
    """
    Enrich articles with categories, context, and follow-up links.
    Returns: { enriched_articles: [...], tokens_used: int, categories: {...} }
    """
    async def emit(msg: str):
        if websocket_callback:
            await websocket_callback({"step": "enricher", "message": msg})

    await emit(f"Enriching {len(articles)} verified articles with context and follow-up links...")

    client = get_ai_client(AI_PROVIDER)
    tokens_used = 0
    all_enrichments = []

    # AI enrichment in batches (pause between batches to respect 10k TPM rate limit)
    batch_size = 5
    for i in range(0, len(articles), batch_size):
        if i > 0:
            await emit("Pausing 35s between batches to respect API rate limits...")
            await asyncio.sleep(35)
        batch = articles[i:i + batch_size]
        # Slim batch — only fields needed for categorisation, no raw_content bloat
        slim_batch = [
            {
                "url":          a.get("url", ""),
                "title":        (a.get("title") or "")[:120],
                "snippet":      (a.get("raw_content") or "")[:250],
                "source":       a.get("source", "web"),
                "source_name":  a.get("source_name", ""),
                "published_at": a.get("published_at", ""),
            }
            for a in batch
        ]
        user_prompt = f"""Enrich these digital health Africa news articles.
Categorize each, extract key info, and suggest {MAX_FOLLOW_UP_LINKS} follow-up reading links per article.

Articles:
{json.dumps(slim_batch, indent=2)}

Return a JSON array with enrichment for each article (same order).
"""
        response_text, tokens = call_ai(
            client, ENRICHER_SYSTEM, user_prompt,
            model_tier=ENRICHER_MODEL, max_tokens=2500, provider=AI_PROVIDER
        )
        tokens_used += tokens

        try:
            batch_enrichments = parse_json_response(response_text)
            all_enrichments.extend(batch_enrichments)
        except Exception as e:
            print(f"[Enricher] Parse error batch {i}: {e}")
            for a in batch:
                all_enrichments.append({
                    "url": a.get("url"),
                    "category": "General Digital Health",
                    "sub_categories": [],
                    "follow_up_links": [],
                    "tags": [],
                })

    # Fetch actual follow-up articles concurrently for top articles
    enrichment_map = {e.get("url"): e for e in all_enrichments if e.get("url")}

    follow_up_tasks = []
    for article in articles[:10]:  # Only top 10 to limit API calls
        url = article.get("url", "")
        enrichment = enrichment_map.get(url, {})
        category = enrichment.get("category", "digital health")
        title = article.get("title", "")
        follow_up_tasks.append(find_follow_up_articles(title, category))

    await emit("Searching for follow-up reading links...")
    follow_up_results = await asyncio.gather(*follow_up_tasks, return_exceptions=True)

    # Merge everything together
    enriched_articles = []
    categories_count = {}

    for i, article in enumerate(articles):
        url = article.get("url", "")
        enrichment = enrichment_map.get(url, {})

        # Add real follow-up links if found
        real_follow_ups = []
        if i < len(follow_up_results) and not isinstance(follow_up_results[i], Exception):
            real_follow_ups = follow_up_results[i]

        ai_follow_ups = enrichment.get("follow_up_links", [])
        all_follow_ups = (ai_follow_ups + real_follow_ups)[:MAX_FOLLOW_UP_LINKS]

        merged = {
            **article,
            "category": enrichment.get("category", "General Digital Health"),
            "sub_categories": enrichment.get("sub_categories", []),
            "key_organizations": enrichment.get("key_organizations", []),
            "countries_mentioned": enrichment.get("countries_mentioned", []),
            "key_metrics": enrichment.get("key_metrics", []),
            "impact_summary": enrichment.get("impact_summary", ""),
            "follow_up_links": all_follow_ups,
            "tags": enrichment.get("tags", []),
        }
        enriched_articles.append(merged)

        cat = enrichment.get("category", "Other")
        categories_count[cat] = categories_count.get(cat, 0) + 1

    await emit(f"Enrichment complete. {len(enriched_articles)} articles enriched across {len(categories_count)} categories.")

    return {
        "enriched_articles": enriched_articles,
        "tokens_used": tokens_used,
        "categories": categories_count,
    }
