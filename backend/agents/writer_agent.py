"""
Writer Agent - Produces one executive snapshot per target country.
Each snapshot covers the last 7 days and is designed to fit one PDF page.
"""
import asyncio
import json
from datetime import datetime
from typing import Any
from backend.config import AI_PROVIDER, WRITER_MODEL, TARGET_COUNTRIES, COUNTRIES_TIER1, COUNTRIES_TIER2, COUNTRIES_TIER3
from backend.agents.base_agent import get_ai_client, call_ai, parse_json_response


WRITER_SYSTEM = """You are a senior health intelligence analyst briefing C-suite executives.
Write in crisp, executive prose. Every sentence must earn its place.
Audience: Ministers, investors, NGO directors — people who make decisions, not read background.
Rules:
- Lead with impact, not context
- Use numbers and specifics whenever available
- Flag risks and opportunities explicitly
- Be direct: "This matters because..." not "It is worth noting that..."
"""

TIER_LABELS = {c: "Tier 1 — Priority" for c in COUNTRIES_TIER1}
TIER_LABELS.update({c: "Tier 2" for c in COUNTRIES_TIER2})
TIER_LABELS.update({c: "Tier 3" for c in COUNTRIES_TIER3})


def group_by_country(articles: list[dict]) -> dict[str, list]:
    """Group articles under each target country they mention."""
    by_country: dict[str, list] = {c: [] for c in TARGET_COUNTRIES}
    for article in articles:
        mentioned = article.get("countries_mentioned") or []
        placed = False
        for country in TARGET_COUNTRIES:   # iterate in priority order
            if country in mentioned:
                by_country[country].append(article)
                placed = True
        if not placed:
            # Try fuzzy match on title/content
            text = (article.get("title", "") + " " + article.get("raw_content", "")).lower()
            for country in TARGET_COUNTRIES:
                if country.lower() in text:
                    by_country[country].append(article)
    return by_country


async def run_writer(
    enriched_articles: list[dict],
    extra_instructions: str = "",
    run_id: str = "",
    websocket_callback=None,
    country_filter: str | None = None,
) -> dict[str, Any]:
    """
    Write one executive snapshot per country.
    Returns: { report: {...}, tokens_used: int }
    """
    async def emit(msg: str):
        if websocket_callback:
            await websocket_callback({"step": "writer", "message": msg})

    await emit(f"Organising {len(enriched_articles)} articles by country...")

    client = get_ai_client(AI_PROVIDER)
    date_str = datetime.utcnow().strftime("%B %d, %Y")
    period_end = datetime.utcnow()
    period_start = period_end.replace(day=max(1, period_end.day - 6))
    period_str = f"{period_start.strftime('%b %d')}–{period_end.strftime('%b %d, %Y')}"
    tokens_used = 0

    by_country = group_by_country(enriched_articles)

    # If running a single-country scan, only produce that country's snapshot
    countries_to_process = [country_filter] if (country_filter and country_filter in TARGET_COUNTRIES) else TARGET_COUNTRIES

    # ── Executive overview (all countries, one paragraph) ─────────────────
    await emit("Writing executive overview...")
    overview_slim = []
    for country in TARGET_COUNTRIES:
        arts = by_country[country]
        if arts:
            top = sorted(arts, key=lambda a: {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(a.get("impact_level", "low"), 3))
            overview_slim.append({
                "country": country,
                "tier": TIER_LABELS[country],
                "article_count": len(arts),
                "top_headline": (top[0].get("executive_headline") or top[0].get("title", ""))[:100],
                "top_impact": top[0].get("impact_level", "medium"),
            })

    overview_prompt = f"""Write a 120-word Executive Overview for a Digi-Health Brief covering {period_str}.
Countries with activity: {json.dumps(overview_slim, indent=2)}
{f'Focus: {extra_instructions}' if extra_instructions else ''}
Start: "This week's brief covers digital health developments across..."
Be punchy and executive. Numbers only where available from the data.
"""
    exec_summary, t = call_ai(client, WRITER_SYSTEM, overview_prompt, WRITER_MODEL, 400, AI_PROVIDER)
    tokens_used += t

    # ── One snapshot per country ───────────────────────────────────────────
    sections = []
    for idx, country in enumerate(countries_to_process):
        if idx > 0:
            await asyncio.sleep(20)

        arts = by_country[country]
        tier = TIER_LABELS[country]
        await emit(f"Writing {country} snapshot ({len(arts)} articles)...")

        if not arts:
            sections.append({
                "country": country,
                "tier": tier,
                "content": f"No new digital health developments captured for {country} in the last 7 days.",
                "article_count": 0,
                "impact_distribution": {"critical": 0, "high": 0, "medium": 0, "low": 0},
                "top_articles": [],
                "official_signals": [],
                "sentiment": "No signal",
                "recommended_actions": [],
            })
            continue

        # Sort by impact severity
        level_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        arts_sorted = sorted(arts, key=lambda a: level_order.get(a.get("impact_level", "low"), 3))

        # Impact distribution
        dist = {"critical": 0, "high": 0, "medium": 0, "low": 0}
        for a in arts:
            lvl = a.get("impact_level", "low")
            if lvl in dist:
                dist[lvl] += 1

        # Official signals
        officials = [a for a in arts if a.get("is_official")]
        # Social sentiment items
        sentiment_items = [a for a in arts if a.get("sentiment_signal") in ("positive", "negative", "mixed")]

        slim_arts = [
            {
                "title":              (a.get("executive_headline") or a.get("title", ""))[:120],
                "impact_level":       a.get("impact_level", "medium"),
                "impact_summary":     (a.get("impact_summary") or "")[:200],
                "recommended_action": a.get("recommended_action", ""),
                "source_name":        a.get("source_name", ""),
                "is_official":        a.get("is_official", False),
                "sentiment_signal":   a.get("sentiment_signal", "neutral"),
                "published_at":       a.get("published_at", ""),
            }
            for a in arts_sorted[:6]
        ]

        country_prompt = f"""Write a one-page executive country snapshot for {country} ({tier}).
Period: {period_str} | Articles: {len(arts)} | Distribution: {json.dumps(dist)}

Articles:
{json.dumps(slim_arts, indent=2)}

Write these sections in order — be concise, each bullet max 2 lines:

TOP HEADLINES ({min(len(arts), 5)} items, most impactful first):
For each: [IMPACT LEVEL] Headline — Source | → Recommended action

OFFICIAL SIGNALS & PRONOUNCEMENTS:
(From ministries/ministers/government bodies only. If none, write "No official signals this week.")

SOCIAL SENTIMENT:
(Summarise community/stakeholder tone in 1-2 sentences. Positive/negative/mixed.)

RECOMMENDED EXECUTIVE ACTIONS (max 2, critical/high only):
Numbered, each starting with an action verb.

{f'Additional lens: {extra_instructions}' if extra_instructions else ''}
"""
        content, t = call_ai(client, WRITER_SYSTEM, country_prompt, WRITER_MODEL, 800, AI_PROVIDER)
        tokens_used += t

        sections.append({
            "country": country,
            "tier": tier,
            "content": content,
            "article_count": len(arts),
            "impact_distribution": dist,
            "top_articles": arts_sorted[:5],
            "official_signals": [a.get("title", "") for a in officials[:3]],
            "sentiment": sentiment_items[0].get("sentiment_signal", "neutral") if sentiment_items else "neutral",
            "recommended_actions": [
                a.get("recommended_action", "")
                for a in arts_sorted if a.get("recommended_action") and a.get("impact_level") in ("critical", "high")
            ][:2],
        })

    await emit("Writing strategic outlook...")
    await asyncio.sleep(20)

    # ── Strategic outlook (cross-country) ─────────────────────────────────
    active_countries = [s["country"] for s in sections if s["article_count"] > 0]
    critical_count = sum(s["impact_distribution"]["critical"] for s in sections)
    high_count = sum(s["impact_distribution"]["high"] for s in sections)

    analysis_prompt = f"""Write a 150-word "Strategic Outlook" for the Digi-Health brief dated {date_str}.
Active countries this week: {', '.join(active_countries)}
Critical items: {critical_count} | High: {high_count}
Top headlines: {json.dumps([s['top_articles'][0].get('executive_headline','') if s['top_articles'] else '' for s in sections if s['article_count'] > 0][:6], indent=2)}

Include:
1. One cross-country macro trend
2. One risk or opportunity that needs executive attention
3. One forward-looking call to action

Write ONLY the outlook section, no headers:
"""
    analysis, t = call_ai(client, WRITER_SYSTEM, analysis_prompt, WRITER_MODEL, 500, AI_PROVIDER)
    tokens_used += t

    report = {
        "title": f"Digi-Health Brief — {period_str}",
        "date": date_str,
        "period": period_str,
        "run_id": run_id,
        "executive_summary": exec_summary,
        "sections": sections,          # one per country
        "strategic_analysis": analysis,
        "stats": {
            "total_articles": len(enriched_articles),
            "countries_active": len(active_countries),
            "critical": critical_count,
            "high": high_count,
        },
        "articles": enriched_articles,
    }

    await emit(f"Brief complete — {len(sections)} country snapshots written.")

    return {"report": report, "tokens_used": tokens_used}


async def apply_user_request(
    report: dict,
    user_request: str,
    websocket_callback=None,
) -> dict[str, Any]:
    async def emit(msg: str):
        if websocket_callback:
            await websocket_callback({"step": "writer", "message": f"[Request] {msg}"})

    await emit(f"Processing request: {user_request}")
    client = get_ai_client(AI_PROVIDER)

    request_prompt = f"""Modify this Digi-Health executive brief per the user request below.

REQUEST: {user_request}

Brief title: {report.get('title')}
Executive summary: {report.get('executive_summary', '')[:400]}
Countries covered: {[s.get('country') for s in report.get('sections', [])]}
Total articles: {len(report.get('articles', []))}

Return JSON: {{"modified_section": "...", "updated_content": "...", "explanation": "..."}}
"""
    response_text, tokens = call_ai(client, WRITER_SYSTEM, request_prompt, WRITER_MODEL, 1500, AI_PROVIDER)
    try:
        result = parse_json_response(response_text)
    except Exception:
        result = {"modified_section": "general", "updated_content": response_text, "explanation": "Request processed"}

    await emit(f"Done: {result.get('explanation', 'Request applied')}")
    return {"result": result, "tokens_used": tokens}
