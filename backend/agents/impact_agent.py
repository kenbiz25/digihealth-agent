"""
Impact Agent — Classifies articles by executive impact level and generates
action-oriented intelligence for senior health executives.
Pipeline position: Enricher → Impact → Writer
"""
import asyncio
import json
from typing import Any

from backend.config import AI_PROVIDER, IMPACT_MODEL
from backend.agents.base_agent import get_ai_client, call_ai, parse_json_response

IMPACT_LEVELS = ["critical", "high", "medium", "low"]

IMPACT_SYSTEM = """You are a strategic intelligence analyst briefing C-suite executives at Medtronic LABS.

=== MEDTRONIC LABS — STRATEGIC CONTEXT ===
Medtronic LABS is the impact arm of Medtronic focused on making healthcare more accessible and
affordable in emerging markets. Core priorities:

CLINICAL FOCUS (highest relevance):
  • NCD management — hypertension, diabetes, cardiac monitoring; community NCD programs
  • Maternal & newborn health — antenatal diagnostics, birth outcomes, obstetric technology
  • Primary care digital tools — community health workers, last-mile diagnostics
  • Point-of-care diagnostics — rapid tests, AI-assisted diagnosis, imaging at the facility edge

MARKET FOCUS (10 target countries, tiered by programme depth):
  • Tier 1 (deepest engagement): Sierra Leone, Bangladesh
  • Tier 2 (active programmes): Kenya, Rwanda, Ghana, India
  • Tier 3 (early/watch): Saudi Arabia, Tanzania, Bhutan, United States

STRATEGIC SIGNALS to elevate:
  • Government procurement or tender for devices/platforms in clinical focus areas → critical/high
  • Health insurance/UHC policy changes covering NCD or maternal care (NHIF, NHIS, Ayushman) → critical/high
  • Ministry of Health digital health plan or mandate in a Tier 1/2 country → critical/high
  • Named official announcement (minister, DG, CS) on digital health → high
  • Donor grant >$5M for health technology in target countries → high
  • Open calls for proposals (RFPs/CFPs) for digital health innovation → high
  • Competitor partnership or product launch in our clinical focus areas → high
  • Regulatory clearance (ICMR, PPB, SFDA, TMDA, FDA) for relevant devices → high
  • Academic/clinical evidence validating NCD or maternal digital interventions → medium
  • Pilot programmes, capacity-building, or system rollouts → medium
  • Conference announcements, opinion pieces, background reading → low

=== CLASSIFICATION RULES ===
- critical: Government mandate or regulation affecting operations; procurement/funding >$10M
  changing competitive landscape; active health crisis needing immediate digital response.
- high: Major Ministry of Health announcement; named official statement on digital health;
  competitor/partner move; open RFP/grant in our clinical focus areas; procurement decision
  in Tier 1/2 countries; UHC/insurance policy covering NCD/maternal care.
- medium: Research publication; pilot launch; capacity-building programme; informative
  but not operationally urgent in the next 2 weeks.
- low: Opinion, background, conference announcement, minor update.

=== RECOMMENDED ACTION FORMAT ===
Link the action to a Medtronic LABS function where possible:
  • "Brief the Kenya Market Access team on..."
  • "Engage the Ghana programme lead to explore..."
  • "Submit a comment on the draft policy for..."
  • "Monitor procurement tender — flag to BD team"
  • "Share with Clinical Affairs team — evidence supports..."

For each article return exactly this JSON object:
{
  "url": "<original url — required for merge>",
  "impact_level": "critical | high | medium | low",
  "impact_rationale": "<2-3 sentences: what happened, who is affected, why it matters for Medtronic LABS strategy this week>",
  "recommended_action": "<single imperative sentence starting with an action verb, naming the relevant team or function where applicable>",
  "executive_headline": "<max 15 words, Monday morning briefing card — punchy, concrete, no jargon>"
}

Return a JSON array of these objects, one per article, in the same order as the input.
"""


async def run_impact_agent(
    articles: list[dict],
    run_id: str,
    websocket_callback=None,
) -> dict[str, Any]:
    """
    Classify each enriched article by executive impact level.
    Returns: { classified_articles: [...], tokens_used: int, impact_summary: {...} }
    """
    async def emit(msg: str):
        if websocket_callback:
            await websocket_callback({"step": "impact", "message": msg})

    await emit(f"Classifying {len(articles)} articles by executive impact level...")

    client = get_ai_client(AI_PROVIDER)
    tokens_used = 0
    classifications: list[dict] = []

    batch_size = 5
    for i in range(0, len(articles), batch_size):
        if i > 0:
            await emit("Pausing between batches to respect rate limits...")
            await asyncio.sleep(35)

        batch = articles[i:i + batch_size]
        # Pass only the fields the agent needs — keep tokens lean
        slim_batch = [
            {
                "url": a.get("url"),
                "title": a.get("title"),
                "summary": a.get("summary") or a.get("impact_summary", ""),
                "category": a.get("category", ""),
                "countries_mentioned": a.get("countries_mentioned", []),
                "key_organizations": a.get("key_organizations", []),
                "key_metrics": a.get("key_metrics", []),
                "tags": a.get("tags", []),
            }
            for a in batch
        ]
        user_prompt = (
            f"Classify these {len(batch)} digital health articles by Medtronic LABS executive impact level.\n\n"
            f"Articles:\n{json.dumps(slim_batch, indent=2)}\n\n"
            "Return a JSON array with one classification object per article (same order)."
        )

        response_text, tokens = call_ai(
            client, IMPACT_SYSTEM, user_prompt,
            model_tier=IMPACT_MODEL, max_tokens=2000, provider=AI_PROVIDER,
        )
        tokens_used += tokens

        try:
            batch_results = parse_json_response(response_text)
            classifications.extend(batch_results)
        except Exception as e:
            print(f"[ImpactAgent] Parse error batch {i}: {e}")
            # Graceful fallback — mark as medium, don't crash the pipeline
            for a in batch:
                classifications.append({
                    "url": a.get("url"),
                    "impact_level": "medium",
                    "impact_rationale": "Automatic classification unavailable for this article.",
                    "recommended_action": "Review article manually.",
                    "executive_headline": (a.get("title") or "")[:80],
                })

    # Build lookup by URL for merge
    class_map = {c.get("url"): c for c in classifications if c.get("url")}

    # Sort order: critical first
    level_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    impact_counts = {lvl: 0 for lvl in IMPACT_LEVELS}
    classified_articles = []

    for article in articles:
        url = article.get("url", "")
        cls = class_map.get(url, {})
        level = cls.get("impact_level", "medium")
        if level not in IMPACT_LEVELS:
            level = "medium"
        impact_counts[level] += 1
        classified_articles.append({
            **article,
            "impact_level": level,
            "impact_rationale": cls.get("impact_rationale", ""),
            "recommended_action": cls.get("recommended_action", ""),
            "executive_headline": cls.get("executive_headline") or article.get("title", ""),
        })

    # Sort by severity — writer and PDF get priority-first ordering
    classified_articles.sort(key=lambda a: level_order.get(a.get("impact_level", "low"), 3))

    summary_msg = (
        f"Impact complete — "
        f"{impact_counts['critical']} critical, {impact_counts['high']} high, "
        f"{impact_counts['medium']} medium, {impact_counts['low']} low"
    )
    await emit(summary_msg)

    return {
        "classified_articles": classified_articles,
        "tokens_used": tokens_used,
        "impact_summary": impact_counts,
    }
