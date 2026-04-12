"""
Orchestrator - Coordinates all agents in sequence and manages the full pipeline.
Pipeline: Scraper -> Verifier -> Enricher -> Writer -> PDF -> Email
"""
import asyncio
import uuid
from datetime import datetime, timedelta
from typing import Callable, Any
from sqlalchemy.orm import Session

from backend.database import AgentRun, AgentStep, NewsArticle, SessionLocal
from backend.agents.scraper_agent import run_scraper
from backend.agents.verifier_agent import run_verifier
from backend.agents.enricher_agent import run_enricher
from backend.agents.impact_agent import run_impact_agent
from backend.agents.writer_agent import run_writer
from backend.services.pdf_service import generate_pdf
from backend.services.email_service import send_email
from backend.config import AI_PROVIDER, EMAIL_ENABLED


PIPELINE_STEPS = [
    "scraper",
    "verifier",
    "enricher",
    "impact",
    "writer",
    "pdf_generator",
    "email_sender",
]


def create_run(db: Session, trigger: str = "scheduled") -> AgentRun:
    run = AgentRun(
        run_id=str(uuid.uuid4()),
        status="running",
        trigger=trigger,
        started_at=datetime.utcnow(),
        ai_provider=AI_PROVIDER,
    )
    db.add(run)
    # Create pending steps
    for step in PIPELINE_STEPS:
        db.add(AgentStep(run_id=run.run_id, step_name=step, status="pending"))
    db.commit()
    db.refresh(run)
    return run


def update_step(db: Session, run_id: str, step_name: str, status: str, output=None, error=None, tokens=0):
    step = db.query(AgentStep).filter(
        AgentStep.run_id == run_id, AgentStep.step_name == step_name
    ).first()
    if step:
        step.status = status
        step.output = output or {}
        step.error_msg = error
        step.tokens_used = tokens
        if status == "running":
            step.started_at = datetime.utcnow()
        elif status in ("completed", "failed"):
            step.finished_at = datetime.utcnow()
        db.commit()


def save_articles(db: Session, run_id: str, articles: list[dict]):
    """Insert new articles or update existing ones (upsert by run_id+url)."""
    existing = {
        a.url: a for a in db.query(NewsArticle).filter(NewsArticle.run_id == run_id).all()
    }
    for a in articles:
        url = a.get("url", "")
        if url in existing:
            rec = existing[url]
            rec.title              = a.get("title", rec.title)
            rec.source             = a.get("source", rec.source)
            rec.source_name        = a.get("source_name", rec.source_name)
            rec.published_at       = a.get("published_at", rec.published_at)
            rec.raw_content        = a.get("raw_content", rec.raw_content)
            rec.summary            = a.get("impact_summary", rec.summary) or a.get("summary", rec.summary)
            rec.verification_score = a.get("verification_score", rec.verification_score)
            rec.verified           = a.get("verified", rec.verified)
            rec.verification_notes = a.get("verification_notes", rec.verification_notes)
            rec.follow_up_links     = a.get("follow_up_links", rec.follow_up_links)
            rec.countries_mentioned = a.get("countries_mentioned", rec.countries_mentioned)
            rec.impact_level        = a.get("impact_level", rec.impact_level)
            rec.impact_rationale    = a.get("impact_rationale", rec.impact_rationale)
            rec.recommended_action  = a.get("recommended_action", rec.recommended_action)
            rec.executive_headline  = a.get("executive_headline", rec.executive_headline)
            rec.sentiment_signal    = a.get("sentiment_signal", rec.sentiment_signal)
            rec.is_official         = a.get("is_official", rec.is_official)
        else:
            db.add(NewsArticle(
                run_id=run_id,
                title=a.get("title", ""),
                url=url,
                source=a.get("source", "web"),
                source_name=a.get("source_name", ""),
                published_at=a.get("published_at", ""),
                raw_content=a.get("raw_content", ""),
                summary=a.get("impact_summary", "") or a.get("summary", ""),
                verification_score=a.get("verification_score", 0.0),
                verified=a.get("verified", False),
                verification_notes=a.get("verification_notes", ""),
                follow_up_links=a.get("follow_up_links", []),
                countries_mentioned=a.get("countries_mentioned", []),
                impact_level=a.get("impact_level"),
                impact_rationale=a.get("impact_rationale"),
                recommended_action=a.get("recommended_action"),
                executive_headline=a.get("executive_headline"),
                sentiment_signal=a.get("sentiment_signal"),
                is_official=a.get("is_official", False),
            ))
    db.commit()


async def run_pipeline(
    run_id: str | None = None,
    trigger: str = "scheduled",
    extra_instructions: str = "",
    country_filter: str | None = None,
    websocket_callback: Callable | None = None,
    db: Session | None = None,
) -> dict[str, Any]:
    """
    Execute the full agent pipeline.
    Returns the final report dict and pipeline stats.
    """
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True

    async def emit(data: dict):
        if websocket_callback:
            await websocket_callback(data)

    # Create or reuse run record
    if run_id is None:
        run = create_run(db, trigger)
        run_id = run.run_id
    else:
        run = db.query(AgentRun).filter(AgentRun.run_id == run_id).first()

    total_tokens = 0
    report = None
    pdf_path = None

    try:
        scope_label = f" [{country_filter} only]" if country_filter else ""
        await emit({"step": "pipeline", "message": f"Pipeline started{scope_label} (run_id: {run_id})", "run_id": run_id})

        # ─── STEP 1: SCRAPER ─────────────────────────────────────────
        update_step(db, run_id, "scraper", "running")
        scrape_msg = f"Collecting news for {country_filter}..." if country_filter else "Collecting news from social media and web..."
        await emit({"step": "scraper", "status": "running", "message": scrape_msg})

        scraper_result = await run_scraper(run_id, websocket_callback, country_filter=country_filter)
        articles = scraper_result["articles"]
        total_tokens += scraper_result["tokens_used"]

        # ── Cross-run duplicate guard ─────────────────────────────────
        # Fetch every URL already stored in the DB (any previous run)
        existing_urls: set[str] = {
            row.url for row in db.query(NewsArticle.url).filter(
                NewsArticle.run_id != run_id,
                NewsArticle.url.isnot(None),
            ).all()
        }
        new_articles = [a for a in articles if a.get("url", "") not in existing_urls]
        duplicate_count = len(articles) - len(new_articles)

        save_articles(db, run_id, new_articles)   # live: show new articles immediately
        update_step(db, run_id, "scraper", "completed",
                    output={
                        "article_count": len(new_articles),
                        "duplicates_skipped": duplicate_count,
                        "sources": scraper_result["sources_searched"],
                    },
                    tokens=scraper_result["tokens_used"])
        dup_msg = f" ({duplicate_count} already captured in a previous run — skipped)" if duplicate_count else ""
        await emit({"step": "scraper", "status": "completed",
                    "message": f"Collected {len(new_articles)} new articles{dup_msg}",
                    "data": {
                        "count": len(new_articles),
                        "duplicates_skipped": duplicate_count,
                        "sources": scraper_result["sources_searched"],
                    }})
        await emit({"step": "articles_updated", "message": "Articles updated"})

        articles = new_articles   # only fresh articles continue through the pipeline

        if not articles:
            raise ValueError(
                f"No new articles found (scraped {len(scraper_result['articles'])}, "
                f"all {duplicate_count} already captured). "
                "Check API keys, search configuration, or wait for new content."
            )

        # ─── STEP 2: VERIFIER ────────────────────────────────────────
        update_step(db, run_id, "verifier", "running")
        await emit({"step": "verifier", "status": "running", "message": "Verifying and fact-checking articles..."})

        verifier_result = await run_verifier(articles, run_id, websocket_callback)
        verified_articles = verifier_result["verified_articles"]
        total_tokens += verifier_result["tokens_used"]

        save_articles(db, run_id, verified_articles)   # live: update with verification scores
        update_step(db, run_id, "verifier", "completed",
                    output={"verified": len(verified_articles), "rejected": verifier_result["rejected_count"]},
                    tokens=verifier_result["tokens_used"])
        await emit({"step": "verifier", "status": "completed",
                    "message": f"{len(verified_articles)} verified, {verifier_result['rejected_count']} rejected",
                    "data": {"verified": len(verified_articles), "rejected": verifier_result["rejected_count"]}})
        await emit({"step": "articles_updated", "message": "Articles updated with verification scores"})

        if not verified_articles:
            raise ValueError("No articles passed verification. Lowering MIN_VERIFICATION_SCORE may help.")

        # ─── STEP 3: ENRICHER ────────────────────────────────────────
        update_step(db, run_id, "enricher", "running")
        await emit({"step": "enricher", "status": "running", "message": "Enriching articles with context and follow-up links..."})

        enricher_result = await run_enricher(verified_articles, run_id, websocket_callback)
        enriched_articles = enricher_result["enriched_articles"]
        total_tokens += enricher_result["tokens_used"]
        save_articles(db, run_id, enriched_articles)

        update_step(db, run_id, "enricher", "completed",
                    output={"categories": enricher_result["categories"]},
                    tokens=enricher_result["tokens_used"])
        await emit({"step": "enricher", "status": "completed",
                    "message": f"Articles enriched across {len(enricher_result['categories'])} categories",
                    "data": {"categories": enricher_result["categories"]}})
        await emit({"step": "articles_updated", "message": "Articles updated with enrichment"})

        # Inter-agent pause: let token-per-minute window reset before impact agent
        await emit({"step": "impact", "status": "pending", "message": "Cooling down 45s before impact classification..."})
        await asyncio.sleep(45)

        # ─── STEP 4: IMPACT CLASSIFIER ───────────────────────────────
        update_step(db, run_id, "impact", "running")
        await emit({"step": "impact", "status": "running",
                    "message": "Classifying articles by executive impact level..."})

        impact_result = await run_impact_agent(enriched_articles, run_id, websocket_callback)
        classified_articles = impact_result["classified_articles"]
        total_tokens += impact_result["tokens_used"]
        save_articles(db, run_id, classified_articles)

        update_step(db, run_id, "impact", "completed",
                    output={"impact_summary": impact_result["impact_summary"]},
                    tokens=impact_result["tokens_used"])
        await emit({"step": "impact", "status": "completed",
                    "message": (
                        f"Impact classified — "
                        f"{impact_result['impact_summary'].get('critical', 0)} critical, "
                        f"{impact_result['impact_summary'].get('high', 0)} high, "
                        f"{impact_result['impact_summary'].get('medium', 0)} medium, "
                        f"{impact_result['impact_summary'].get('low', 0)} low"
                    ),
                    "data": {"impact_summary": impact_result["impact_summary"]}})
        await emit({"step": "articles_updated", "message": "Articles updated with impact classification"})

        # Inter-agent pause: let token-per-minute window reset before writer
        await emit({"step": "writer", "status": "pending", "message": "Cooling down 45s before writing brief..."})
        await asyncio.sleep(45)

        # ─── STEP 5: WRITER ──────────────────────────────────────────
        update_step(db, run_id, "writer", "running")
        await emit({"step": "writer", "status": "running", "message": "Aggregating last 7 days for country briefs..."})

        # Aggregate last 7 days of classified articles from DB for the PDF brief
        seven_days_ago = datetime.utcnow() - timedelta(days=7)
        seven_day_rows = db.query(NewsArticle).filter(
            NewsArticle.verified == True,
            NewsArticle.created_at >= seven_days_ago,
            NewsArticle.impact_level.isnot(None),
        ).order_by(NewsArticle.created_at.desc()).all()

        seven_day_articles = [
            {
                "title":              a.title or "",
                "url":                a.url or "",
                "source":             a.source or "web",
                "source_name":        a.source_name or "",
                "published_at":       a.published_at or "",
                "raw_content":        a.raw_content or "",
                "impact_summary":     a.summary or "",
                "impact_level":       a.impact_level or "medium",
                "impact_rationale":   a.impact_rationale or "",
                "recommended_action": a.recommended_action or "",
                "executive_headline": a.executive_headline or a.title or "",
                "countries_mentioned": a.countries_mentioned or [],
                "verification_score": a.verification_score or 0.0,
                "follow_up_links":    a.follow_up_links or [],
                "sentiment_signal":   a.sentiment_signal or "",
                "is_official":        a.is_official or False,
                "created_at":         a.created_at.isoformat() if a.created_at else "",
            }
            for a in seven_day_rows
        ]
        await emit({"step": "writer", "status": "running",
                    "message": f"Writing country briefs from {len(seven_day_articles)} articles (last 7 days)..."})

        writer_result = await run_writer(seven_day_articles, extra_instructions, run_id, websocket_callback, country_filter=country_filter)
        report = writer_result["report"]
        total_tokens += writer_result["tokens_used"]

        update_step(db, run_id, "writer", "completed",
                    output={"title": report["title"], "sections": len(report["sections"])},
                    tokens=writer_result["tokens_used"])
        await emit({"step": "writer", "status": "completed",
                    "message": f"Brief written: {len(report['sections'])} country snapshots",
                    "data": {"title": report["title"]}})

        # ─── STEP 5: PDF GENERATOR ───────────────────────────────────
        update_step(db, run_id, "pdf_generator", "running")
        await emit({"step": "pdf_generator", "status": "running", "message": "Generating PDF report..."})

        pdf_path = await generate_pdf(report, run_id)

        run.pdf_path = pdf_path
        db.commit()

        update_step(db, run_id, "pdf_generator", "completed",
                    output={"pdf_path": pdf_path})
        await emit({"step": "pdf_generator", "status": "completed",
                    "message": "PDF generated successfully",
                    "data": {"pdf_path": pdf_path}})

        # ─── STEP 6: EMAIL ───────────────────────────────────────────
        # Only send email on scheduled (Monday) runs, not manual runs
        update_step(db, run_id, "email_sender", "running")
        if EMAIL_ENABLED and trigger == "scheduled":
            await emit({"step": "email_sender", "status": "running", "message": "Sending Monday brief via email..."})
            email_sent = await send_email(pdf_path, report["title"])
            run.email_sent = email_sent
            db.commit()
            update_step(db, run_id, "email_sender",
                        "completed" if email_sent else "failed",
                        output={"sent": email_sent})
            await emit({"step": "email_sender", "status": "completed" if email_sent else "failed",
                        "message": "Email sent" if email_sent else "Email failed"})
        else:
            reason = "manual run — email only sent on scheduled Monday runs" if trigger != "scheduled" else "EMAIL_ENABLED=false"
            update_step(db, run_id, "email_sender", "completed",
                        output={"skipped": True, "reason": reason})
            await emit({"step": "email_sender", "status": "completed",
                        "message": f"Email skipped ({reason})"})

        # Finalize run
        run.status = "completed"
        run.finished_at = datetime.utcnow()
        db.commit()

        await emit({"step": "pipeline", "status": "completed",
                    "message": f"Pipeline complete! Total tokens used: {total_tokens}",
                    "data": {"run_id": run_id, "pdf_path": pdf_path, "total_tokens": total_tokens}})

        return {
            "run_id": run_id,
            "status": "completed",
            "report": report,
            "pdf_path": pdf_path,
            "total_tokens": total_tokens,
            "article_count": len(classified_articles),
        }

    except Exception as e:
        error_msg = str(e)
        run.status = "failed"
        run.error_msg = error_msg
        run.finished_at = datetime.utcnow()
        db.commit()

        await emit({"step": "pipeline", "status": "failed",
                    "message": f"Pipeline failed: {error_msg}"})
        raise

    finally:
        if close_db:
            db.close()
