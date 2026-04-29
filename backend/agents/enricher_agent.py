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


TARGET_COUNTRY_LIST = "Sierra Leone, Bangladesh, Kenya, Rwanda, Ghana, India, Saudi Arabia, Tanzania, Bhutan, United States"
_ALL_COUNTRIES = ["Sierra Leone", "Bangladesh", "Kenya", "Rwanda", "Ghana", "India", "Saudi Arabia", "Tanzania", "Bhutan", "United States"]

ENRICHER_SYSTEM = f"""You are a research enrichment agent for Medtronic LABS digital health intelligence.
Target countries ONLY: {TARGET_COUNTRY_LIST}

Your role is to:
1. Categorize each article into a PRIMARY CATEGORY and sub-categories using the taxonomy below.
2. Generate smart follow-up reading recommendations.
3. Add relevant context (key organizations, countries, impact).
4. Extract key metrics or statistics mentioned.
5. Flag if this story appears to be a continuation of a developing story (see field: is_continuation_story).

--- PRIMARY CATEGORY TAXONOMY ---
Use EXACTLY one of the following primary categories:

Clinical — Medtronic LABS Focus:
  "NCD Management"         — hypertension, diabetes, cardiac monitoring, NCD programs
  "Maternal Health Tech"   — maternal mortality, antenatal care, birth outcomes, obstetric care
  "Primary Care Digital"   — community health workers, last-mile diagnostics, primary care tools
  "Point of Care Dx"       — rapid diagnostics, POC testing, imaging, AI-assisted diagnosis

Health System Infrastructure:
  "Digital Health Platform" — EHR, HMIS, health data systems, interoperability
  "Telemedicine / mHealth"  — teleconsultation, mHealth apps, remote care
  "Health Data & AI"        — AI/ML in diagnostics, data analytics, predictive health
  "Infrastructure & Connectivity" — device connectivity, rural network, power solutions

Policy & Governance:
  "Health Policy"           — government plans, ministerial announcements, national strategies
  "Regulation & Approval"   — medical device registration, regulatory clearance, ICMR, SFDA, PPB, TMDA
  "UHC & Insurance"         — universal health coverage, NHIF/NHIS, NCD reimbursement, tariff updates

Market & Investment:
  "Funding & Grants"        — donor disbursements, grants, health funding awards
  "Budget & Fiscal"         — ministry health budgets, parliamentary votes, fiscal year allocations
  "Procurement & Tender"    — medical supply procurement, device tenders, government contracts
  "Partnership & M&A"       — commercial partnerships, joint ventures, acquisitions

Events & Community:
  "Conference Outcomes"     — summit declarations, conference communiqués, forum outcomes (AfDB, GSMA, WHO regional)
  "Community Discussion"    — stakeholder sentiment, professional community reaction, social signal
  "Research & Evidence"     — published studies, clinical trials, evaluation reports, RCTs

Fallback (use only if none above fit):
  "General Digital Health"

--- URGENCY TIER ---
Classify each article into exactly one tier:
  "URGENT"     — time-sensitive; action needed within days.
                 Examples: minister signs policy TODAY, tender deadline THIS WEEK,
                 emergency declaration, RFP/call for proposals closes soon,
                 breaking announcement, press release just issued.
  "STANDARD"   — important but not time-critical; worth Monday morning briefing.
                 Examples: funding announced, pilot launched, MOU signed,
                 grant awarded, evaluation results published, new partnership.
  "BACKGROUND" — context / evergreen; useful for strategic reference.
                 Examples: market report, sector analysis, strategy overview,
                 whitepaper, explainer, conference proceedings summary.

For each article, return:
{{
  "url": "original article url",
  "category": "primary category from taxonomy above",
  "sub_categories": ["up to 3 secondary themes"],
  "key_organizations": ["WHO", "Ministry of Health", "Medtronic", etc.],
  "primary_country": "single country this article is CHIEFLY about, or null for genuinely global pieces",
  "countries_mentioned": ["countries this article is PRIMARILY reporting on — EXCLUDE countries mentioned only as comparisons, examples, or global context; max 2 entries; ONLY from the target country list"],
  "key_metrics": ["50,000 patients served", "$2M grant", etc.],
  "impact_summary": "one sentence on significance for Medtronic LABS strategy",
  "urgency_tier": "URGENT | STANDARD | BACKGROUND",
  "is_continuation_story": true/false,
  "follow_up_links": [
    {{"title": "...", "url": "...", "why_relevant": "..."}}
  ],
  "tags": ["ncd", "maternal-health", "regulation", "funding", etc.]
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


def _story_overlap(title_a: str, title_b: str) -> int:
    """Count meaningful word overlap between two titles (words >4 chars)."""
    words_a = {w.lower() for w in title_a.split() if len(w) > 4}
    words_b = {w.lower() for w in title_b.split() if len(w) > 4}
    return len(words_a & words_b)


async def run_enricher(
    articles: list[dict],
    run_id: str,
    websocket_callback=None,
    recent_article_titles: list[str] | None = None,
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

    # Build past-article title set for continuity matching (Gap 10)
    past_titles: list[str] = recent_article_titles or []

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

        ai_countries = set(enrichment.get("countries_mentioned") or [])
        scraper_countries = set(article.get("countries_mentioned") or [])
        full_text = " ".join(filter(None, [
            article.get("title", ""),
            article.get("raw_content", ""),
            article.get("source_name", ""),
        ])).lower()
        text_scan_countries = {c for c in _ALL_COUNTRIES if c.lower() in full_text}
        final_countries = list(ai_countries | text_scan_countries | scraper_countries)

        # Thematic continuity: check overlap with past article titles (Gap 10)
        current_title = article.get("title", "")
        continuation_of = ""
        is_continuation = enrichment.get("is_continuation_story", False)
        if not is_continuation and past_titles:
            for past_title in past_titles:
                if _story_overlap(current_title, past_title) >= 3:
                    is_continuation = True
                    continuation_of = past_title[:100]
                    break

        merged = {
            **article,
            "category": enrichment.get("category", "General Digital Health"),
            "sub_categories": enrichment.get("sub_categories", []),
            "key_organizations": enrichment.get("key_organizations", []),
            "primary_country": enrichment.get("primary_country") or "",
            "countries_mentioned": final_countries,
            "key_metrics": enrichment.get("key_metrics", []),
            "impact_summary": enrichment.get("impact_summary", ""),
            "urgency_tier": enrichment.get("urgency_tier", "STANDARD"),
            "follow_up_links": all_follow_ups,
            "tags": enrichment.get("tags", []),
            "is_continuation_story": is_continuation,
            "continuation_of": continuation_of,
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
