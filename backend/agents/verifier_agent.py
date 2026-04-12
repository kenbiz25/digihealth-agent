"""
Verifier Agent - Triangulates news: cross-references multiple sources,
checks for factual consistency, assigns a confidence score.
"""
import asyncio
import httpx
import json
from typing import Any
from backend.config import TAVILY_API_KEY, AI_PROVIDER, VERIFIER_MODEL, MIN_VERIFICATION_SCORE
from backend.agents.base_agent import get_ai_client, call_ai, parse_json_response


VERIFICATION_SYSTEM = """You are a rigorous fact-checking and news verification agent.
Target countries: Sierra Leone, Bangladesh, Kenya, Rwanda, Ghana, India, Saudi Arabia, Tanzania, Bhutan.

Your task is to evaluate each news article and verify it by:
1. CROSS-REFERENCING: Does this news appear in multiple credible sources?
2. RECENCY CHECK: Is this genuinely recent (not recycled old news)?
3. SOURCE CREDIBILITY: Is the source reputable (known health orgs, major media, verified accounts)?
4. CONTENT CONSISTENCY: Are the facts internally consistent? No obvious errors or contradictions?
5. COUNTRY SPECIFICITY: Is it genuinely about one of the target countries (not a tangential mention)?
6. CLAIM VERIFICATION: Are specific claims (statistics, events, organizations) verifiable?

Scoring:
- 0.9-1.0: Verified, multiple credible sources, high confidence
- 0.7-0.8: Likely true, credible source, limited cross-reference
- 0.5-0.6: Uncertain, single source, some credibility concerns
- 0.3-0.4: Questionable, source issues or contradictions found
- 0.0-0.2: Likely false, misinformation signals detected

Return JSON array. Each item: {
  "url": "...",
  "verification_score": 0.0-1.0,
  "verified": true/false,
  "verification_notes": "Brief explanation of score",
  "credibility_flags": ["list", "of", "issues"],
  "supporting_sources": ["urls that corroborate this"],
  "key_facts": ["list of key verifiable facts in this article"]
}
"""


async def fetch_corroborating_sources(article_title: str) -> list[dict]:
    """Search for other sources covering the same story."""
    if not TAVILY_API_KEY:
        return []
    query = f"{article_title[:100]} Africa health"
    url = "https://api.tavily.com/search"
    payload = {
        "api_key": TAVILY_API_KEY,
        "query": query,
        "search_depth": "basic",
        "max_results": 5,
        "days": 7,
    }
    async with httpx.AsyncClient(timeout=20) as client:
        try:
            r = await client.post(url, json=payload)
            r.raise_for_status()
            return r.json().get("results", [])
        except Exception:
            return []


async def run_verifier(
    articles: list[dict],
    run_id: str,
    websocket_callback=None,
) -> dict[str, Any]:
    """
    Verify each article for credibility and accuracy.
    Returns: { verified_articles: [...], tokens_used: int, rejected_count: int }
    """
    async def emit(msg: str):
        if websocket_callback:
            await websocket_callback({"step": "verifier", "message": msg})

    await emit(f"Verifying {len(articles)} articles for accuracy and credibility...")

    # Fetch corroborating sources for top articles concurrently
    corroboration_tasks = [
        fetch_corroborating_sources(a.get("title", ""))
        for a in articles[:15]
    ]
    corroboration_results = await asyncio.gather(*corroboration_tasks, return_exceptions=True)

    # Build slim article list for verification — drop raw_content to save tokens
    def slim_article(article: dict, corroborating: list) -> dict:
        return {
            "url":     article.get("url", ""),
            "title":   (article.get("title") or "")[:120],
            "snippet": (article.get("raw_content") or "")[:300],
            "source":  article.get("source", "web"),
            "source_name": article.get("source_name", ""),
            "published_at": article.get("published_at", ""),
            "corroborating_sources": [
                {"title": s.get("title", "")[:80], "url": s.get("url", "")}
                for s in corroborating[:3]
            ],
        }

    articles_for_verification = []
    for i, article in enumerate(articles):
        corr = []
        if i < len(corroboration_results) and not isinstance(corroboration_results[i], Exception):
            corr = corroboration_results[i]
        articles_for_verification.append(slim_article(article, corr))

    await emit("Cross-referencing sources and running AI verification...")

    client = get_ai_client(AI_PROVIDER)
    tokens_used = 0
    all_verifications = []

    # Process in batches of 5 to avoid token limits; pause between batches
    batch_size = 5
    for i in range(0, len(articles_for_verification), batch_size):
        if i > 0:
            await emit("Pausing 35s between batches to respect API rate limits...")
            await asyncio.sleep(35)
        batch = articles_for_verification[i:i + batch_size]
        user_prompt = f"""Verify these {len(batch)} digital health Africa news articles.
For each, check source credibility, cross-reference the corroborating sources provided, and assign a verification score.

Articles to verify:
{json.dumps(batch, indent=2)}

Return a JSON array with one verification result per article (same order).
"""
        response_text, tokens = call_ai(
            client, VERIFICATION_SYSTEM, user_prompt,
            model_tier=VERIFIER_MODEL, max_tokens=2000, provider=AI_PROVIDER
        )
        tokens_used += tokens

        try:
            batch_verifications = parse_json_response(response_text)
            all_verifications.extend(batch_verifications)
        except Exception as e:
            print(f"[Verifier] Parse error batch {i}: {e}")
            # Add default low-confidence result for failed batch
            for a in batch:
                all_verifications.append({
                    "url": a.get("url"),
                    "verification_score": 0.5,
                    "verified": True,
                    "verification_notes": "Auto-verification failed, manual review needed",
                    "credibility_flags": ["verification_error"],
                    "supporting_sources": [],
                    "key_facts": [],
                })

    # Merge verification results back into articles
    verification_map = {v.get("url"): v for v in all_verifications if v.get("url")}

    verified_articles = []
    rejected = []
    for article in articles:
        url = article.get("url", "")
        verification = verification_map.get(url, {})

        score = verification.get("verification_score", 0.5)
        article["verification_score"] = score
        article["verified"] = score >= MIN_VERIFICATION_SCORE
        article["verification_notes"] = verification.get("verification_notes", "")
        article["credibility_flags"] = verification.get("credibility_flags", [])
        article["supporting_sources"] = verification.get("supporting_sources", [])
        article["key_facts"] = verification.get("key_facts", [])

        if article["verified"]:
            verified_articles.append(article)
        else:
            rejected.append(article)

    await emit(
        f"Verification complete: {len(verified_articles)} passed, "
        f"{len(rejected)} rejected (score below {MIN_VERIFICATION_SCORE})."
    )

    return {
        "verified_articles": verified_articles,
        "rejected_articles": rejected,
        "tokens_used": tokens_used,
        "rejected_count": len(rejected),
    }
