"""
FastAPI Backend - REST API + WebSocket for the Digital Health Africa AI Agent.
Run with: uvicorn backend.main:app --reload --port 8000
"""
import asyncio
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime, date
from typing import Any, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException, BackgroundTasks
from sqlalchemy import case, String
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.config import (
    AI_PROVIDER, CLAUDE_MODELS, OPENAI_MODELS,
    SCHEDULE_HOUR, SCHEDULE_MINUTE, TIMEZONE, EMAIL_ENABLED,
    ANTHROPIC_API_KEY, OPENAI_API_KEY, TAVILY_API_KEY,
    TWITTER_BEARER_TOKEN, SMTP_PASSWORD,
)

# Keys that must NEVER appear in any API response
_NEVER_EXPOSE = {
    "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "TAVILY_API_KEY",
    "TWITTER_BEARER_TOKEN", "SMTP_PASSWORD", "SERPER_API_KEY",
}

def _safe_config() -> dict:
    """Return only non-secret config safe for the frontend."""
    return {
        "ai_provider": AI_PROVIDER,
        "schedule": f"{SCHEDULE_HOUR:02d}:{SCHEDULE_MINUTE:02d}",
        "timezone": TIMEZONE,
        "email_enabled": EMAIL_ENABLED,
        "keys_configured": {
            "anthropic": bool(ANTHROPIC_API_KEY),
            "openai": bool(OPENAI_API_KEY),
            "tavily": bool(TAVILY_API_KEY),
            "twitter": bool(TWITTER_BEARER_TOKEN),
            "smtp": bool(SMTP_PASSWORD),
        },
    }
from backend.database import init_db, get_db, SessionLocal, AgentRun, AgentStep, NewsArticle, ReportRequest
from backend.agents.orchestrator import run_pipeline
from backend.agents.writer_agent import apply_user_request
from backend.agents.scraper_agent import search_tavily, search_serper
from backend.agents.base_agent import get_ai_client, call_ai, parse_json_response
from backend.config import SCRAPER_MODEL, SERPER_API_KEY
from backend.services.scheduler import start_scheduler, stop_scheduler, get_next_run_time, set_broadcast_callback


# ── WebSocket Connection Manager ────────────────────────────────────────────
class ConnectionManager:
    def __init__(self):
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket):
        if ws in self.active:
            self.active.remove(ws)

    async def broadcast(self, data: dict):
        dead = []
        for ws in self.active:
            try:
                await ws.send_text(json.dumps(data))
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


manager = ConnectionManager()


async def broadcast_to_all(data: dict):
    await manager.broadcast(data)


# ── App Lifecycle ────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    set_broadcast_callback(broadcast_to_all)
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(
    title="Digital Health Africa AI Agent",
    description="AI-powered daily intelligence brief on digital health in Africa",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve frontend
FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.exists(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

# Serve public assets (logo, images)
PUBLIC_DIR = os.path.join(os.path.dirname(__file__), "..", "public")
os.makedirs(PUBLIC_DIR, exist_ok=True)
app.mount("/public", StaticFiles(directory=PUBLIC_DIR), name="public")


# ── Pydantic Models ──────────────────────────────────────────────────────────
class RunRequest(BaseModel):
    extra_instructions: str = ""
    ai_provider: str = AI_PROVIDER
    model_tier: str = "balanced"
    country_filter: str = ""   # empty = all countries; set to run a single-country scan


class UserRequest(BaseModel):
    run_id: str
    request: str


class ConfigUpdate(BaseModel):
    ai_provider: str | None = None
    model_tier: str | None = None
    schedule_hour: int | None = None
    schedule_minute: int | None = None


class CustomSearchRequest(BaseModel):
    query: str
    days: int = 7


# ── WebSocket ────────────────────────────────────────────────────────────────
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    await ws.send_text(json.dumps({
        "step": "system",
        "message": "Connected to Digital Health Africa AI Agent",
        "timestamp": datetime.utcnow().isoformat(),
    }))
    try:
        while True:
            data = await ws.receive_text()
            msg = json.loads(data)
            if msg.get("type") == "ping":
                await ws.send_text(json.dumps({"type": "pong"}))
    except WebSocketDisconnect:
        manager.disconnect(ws)


# ── REST Endpoints ────────────────────────────────────────────────────────────

@app.get("/")
async def serve_frontend():
    """Serve the dashboard UI."""
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return JSONResponse({"message": "Digital Health Africa AI Agent API", "docs": "/docs"})


@app.get("/api/config")
async def get_safe_config():
    """Public config — safe for the frontend. NO secrets returned."""
    return _safe_config()


@app.get("/api/status")
async def get_status(db: Session = Depends(get_db)):
    """System status overview — no secrets exposed."""
    recent_runs = db.query(AgentRun).order_by(AgentRun.started_at.desc()).limit(5).all()
    last_run = recent_runs[0] if recent_runs else None
    return {
        "status": "running",
        "ai_provider": AI_PROVIDER,           # provider name only, never the key
        "schedule": f"{SCHEDULE_HOUR:02d}:{SCHEDULE_MINUTE:02d} {TIMEZONE}",
        "next_run": get_next_run_time(),
        "email_enabled": EMAIL_ENABLED,
        "active_connections": len(manager.active),
        "keys_configured": _safe_config()["keys_configured"],
        "last_run": {
            "run_id": last_run.run_id if last_run else None,
            "status": last_run.status if last_run else None,
            "started_at": last_run.started_at.isoformat() if last_run else None,
            "pdf_path": last_run.pdf_path if last_run else None,
        } if last_run else None,
    }


@app.post("/api/run")
async def trigger_run(
    request: RunRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Manually trigger an agent pipeline run."""
    run_id = None

    async def run_in_bg():
        try:
            await run_pipeline(
                trigger="manual",
                extra_instructions=request.extra_instructions,
                country_filter=request.country_filter or None,
                websocket_callback=broadcast_to_all,
            )
        except Exception as e:
            await broadcast_to_all({
                "step": "pipeline",
                "status": "failed",
                "message": f"Run failed: {str(e)}",
            })

    background_tasks.add_task(run_in_bg)
    return {"message": "Pipeline started", "status": "running"}


@app.get("/api/runs")
async def list_runs(limit: int = 20, db: Session = Depends(get_db)):
    """List recent pipeline runs."""
    runs = db.query(AgentRun).order_by(AgentRun.started_at.desc()).limit(limit).all()
    return [
        {
            "run_id": r.run_id,
            "status": r.status,
            "trigger": r.trigger,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            "pdf_path": r.pdf_path,
            "email_sent": r.email_sent,
            "ai_provider": r.ai_provider,
            "error_msg": r.error_msg,
        }
        for r in runs
    ]


@app.get("/api/runs/{run_id}")
async def get_run_detail(run_id: str, db: Session = Depends(get_db)):
    """Get full detail of a specific run including steps and articles."""
    run = db.query(AgentRun).filter(AgentRun.run_id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    steps = db.query(AgentStep).filter(AgentStep.run_id == run_id).all()
    articles = db.query(NewsArticle).filter(NewsArticle.run_id == run_id).limit(50).all()

    return {
        "run": {
            "run_id": run.run_id,
            "status": run.status,
            "trigger": run.trigger,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
            "pdf_path": run.pdf_path,
            "email_sent": run.email_sent,
            "ai_provider": run.ai_provider,
            "error_msg": run.error_msg,
        },
        "steps": [
            {
                "step_name": s.step_name,
                "status": s.status,
                "started_at": s.started_at.isoformat() if s.started_at else None,
                "finished_at": s.finished_at.isoformat() if s.finished_at else None,
                "output": s.output,
                "tokens_used": s.tokens_used,
                "error_msg": s.error_msg,
            }
            for s in steps
        ],
        "articles": [
            {
                "title": a.title,
                "url": a.url,
                "source": a.source,
                "source_name": a.source_name,
                "verification_score": a.verification_score,
                "verified": a.verified,
                "verification_notes": a.verification_notes,
                "summary": a.summary,
                "follow_up_links": a.follow_up_links,
            }
            for a in articles
        ],
    }


@app.get("/api/runs/{run_id}/pdf")
async def download_pdf(run_id: str, inline: bool = False, db: Session = Depends(get_db)):
    """
    Serve the PDF report for a run.
    ?inline=true  → opens in browser (for in-platform viewer)
    ?inline=false → triggers download (default)
    """
    run = db.query(AgentRun).filter(AgentRun.run_id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if not run.pdf_path or not os.path.exists(run.pdf_path):
        raise HTTPException(status_code=404, detail="PDF not yet generated")
    disposition = "inline" if inline else "attachment"
    filename    = os.path.basename(run.pdf_path)
    return FileResponse(
        run.pdf_path,
        media_type="application/pdf",
        filename=filename,
        headers={"Content-Disposition": f"{disposition}; filename=\"{filename}\""},
    )


@app.get("/api/reports/latest/pdf")
async def latest_pdf(inline: bool = True, db: Session = Depends(get_db)):
    """Serve the most recent completed run's PDF (inline by default for in-platform view)."""
    run = (
        db.query(AgentRun)
        .filter(AgentRun.status == "completed", AgentRun.pdf_path.isnot(None))
        .order_by(AgentRun.finished_at.desc())
        .first()
    )
    if not run or not run.pdf_path or not os.path.exists(run.pdf_path):
        raise HTTPException(status_code=404, detail="No completed PDF available yet")
    disposition = "inline" if inline else "attachment"
    filename    = os.path.basename(run.pdf_path)
    return FileResponse(
        run.pdf_path,
        media_type="application/pdf",
        filename=filename,
        headers={"Content-Disposition": f"{disposition}; filename=\"{filename}\""},
    )


@app.post("/api/request")
async def submit_request(
    body: UserRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Submit a request to modify or query the report content.
    e.g. 'Add more focus on Sierra Leone', 'Expand the Bangladesh telemedicine section'
    """
    # Save request to DB
    req = ReportRequest(run_id=body.run_id, request=body.request, status="pending")
    db.add(req)
    db.commit()
    db.refresh(req)
    req_id = req.id

    async def process_request():
        _db = SessionLocal()
        try:
            # Get articles for the run
            articles = _db.query(NewsArticle).filter(
                NewsArticle.run_id == body.run_id
            ).all()
            articles_data = [
                {
                    "title":              a.title or "",
                    "url":                a.url or "",
                    "summary":            a.summary or "",
                    "impact_level":       a.impact_level or "medium",
                    "executive_headline": a.executive_headline or a.title or "",
                    "impact_summary":     a.summary or "",
                    "countries_mentioned": a.countries_mentioned or [],
                    "recommended_action": a.recommended_action or "",
                }
                for a in articles
            ]
            report = {
                "title": "Digi-Health Brief",
                "articles": articles_data,
                "sections": [],
            }
            result = await apply_user_request(report, body.request, broadcast_to_all)

            req_obj = _db.query(ReportRequest).filter(ReportRequest.id == req_id).first()
            if req_obj:
                req_obj.response = json.dumps(result.get("result", {}))
                req_obj.status = "completed"
                req_obj.resolved_at = datetime.utcnow()
                _db.commit()

            await broadcast_to_all({
                "step": "request",
                "status": "completed",
                "message": f"Request processed: {result.get('result', {}).get('explanation', 'Done')}",
                "data": result.get("result", {}),
            })
        except Exception as e:
            await broadcast_to_all({
                "step": "request",
                "status": "failed",
                "message": f"Request failed: {str(e)}",
            })
        finally:
            _db.close()

    background_tasks.add_task(process_request)
    return {"message": "Request submitted", "request_id": req_id}


@app.get("/api/requests/{run_id}")
async def get_requests(run_id: str, db: Session = Depends(get_db)):
    """Get all user requests for a run."""
    requests = db.query(ReportRequest).filter(
        ReportRequest.run_id == run_id
    ).order_by(ReportRequest.created_at.desc()).all()
    return [
        {
            "id": r.id,
            "request": r.request,
            "response": json.loads(r.response) if r.response else None,
            "status": r.status,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in requests
    ]


@app.get("/api/models")
async def get_models():
    """Return available AI models and current selection."""
    return {
        "current_provider": AI_PROVIDER,
        "claude_models": CLAUDE_MODELS,
        "openai_models": OPENAI_MODELS,
        "recommendation": {
            "provider": "claude",
            "tier": "balanced",
            "model": CLAUDE_MODELS["balanced"],
            "reason": "Claude Sonnet 4.6 offers the best balance of speed, quality, and cost for news analysis.",
        },
        "agent_roles": {
            "scraper": "Collects news — use 'fast' (cheaper) or 'balanced'",
            "verifier": "Fact-checks — use 'powerful' for best accuracy",
            "enricher": "Adds context — use 'balanced'",
            "writer": "Writes report — use 'balanced' or 'powerful'",
        }
    }


@app.post("/api/custom-search")
async def custom_search(body: CustomSearchRequest):
    """
    User-triggered search on any topic/description using Tavily + Claude extraction.
    Returns a list of relevant articles without saving to the database.
    """
    from backend.config import TAVILY_API_KEY as _TAV
    if not _TAV:
        raise HTTPException(status_code=400, detail="TAVILY_API_KEY not configured")

    # Search via Tavily
    raw = await search_tavily(body.query, "general")
    raw += await search_tavily(body.query, "news")

    if not raw:
        return []

    import json as _json
    system = (
        "You are a research assistant. Extract relevant news/articles from raw search results. "
        "Return a JSON array. Each item: {title, url, source_name, published_at, summary, relevance_score}. "
        "Only include items clearly relevant to the user's query. If none, return []."
    )
    user_prompt = (
        f"Query: {body.query}\n\nRaw results:\n{_json.dumps(raw[:40], indent=2)}\n\n"
        "Return a JSON array of relevant articles."
    )
    client = get_ai_client(AI_PROVIDER)
    response_text, _ = call_ai(client, system, user_prompt,
                               model_tier=SCRAPER_MODEL, max_tokens=4000, provider=AI_PROVIDER)
    try:
        articles = parse_json_response(response_text)
        return [a for a in articles if isinstance(a, dict) and a.get("relevance_score", 0) >= 0.4]
    except Exception:
        return []


@app.get("/api/executive-summary")
async def get_executive_summary(db: Session = Depends(get_db)):
    """
    Returns executive-ready impact summary for the most recent completed run.
    Powers the Executive Pulse section on the dashboard.
    """
    last_run = (
        db.query(AgentRun)
        .filter(AgentRun.status == "completed")
        .order_by(AgentRun.started_at.desc())
        .first()
    )
    if not last_run:
        return {
            "run_id": None, "run_date": None,
            "impact_distribution": {"critical": 0, "high": 0, "medium": 0, "low": 0},
            "critical_alerts": [], "high_priority": [],
            "recommended_actions": [], "total_articles": 0,
        }

    articles = (
        db.query(NewsArticle)
        .filter(NewsArticle.run_id == last_run.run_id, NewsArticle.verified == True)
        .all()
    )

    distribution = {"critical": 0, "high": 0, "medium": 0, "low": 0, "unclassified": 0}
    for a in articles:
        lvl = a.impact_level if a.impact_level in distribution else "unclassified"
        distribution[lvl] += 1

    level_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    sorted_articles = sorted(articles, key=lambda a: level_order.get(a.impact_level, 4))

    def article_card(a):
        return {
            "title": a.title, "url": a.url, "source_name": a.source_name,
            "impact_level": a.impact_level,
            "executive_headline": a.executive_headline or a.title,
            "impact_rationale": a.impact_rationale,
            "recommended_action": a.recommended_action,
            "verification_score": a.verification_score,
            "published_at": a.published_at,
        }

    critical_alerts = [article_card(a) for a in sorted_articles if a.impact_level == "critical"]
    high_priority   = [article_card(a) for a in sorted_articles if a.impact_level == "high"][:5]

    recommended_actions, seen = [], set()
    for a in sorted_articles:
        if a.impact_level in ("critical", "high") and a.recommended_action:
            action = a.recommended_action.strip()
            if action and action not in seen:
                seen.add(action)
                recommended_actions.append({
                    "action": action,
                    "article_title": a.title,
                    "impact_level": a.impact_level,
                    "url": a.url,
                })

    return {
        "run_id": last_run.run_id,
        "run_date": last_run.started_at.isoformat() if last_run.started_at else None,
        "impact_distribution": distribution,
        "critical_alerts": critical_alerts,
        "high_priority": high_priority,
        "recommended_actions": recommended_actions[:8],
        "total_articles": len(articles),
    }


@app.get("/api/articles")
async def get_articles(
    limit: int = 20,
    source: Optional[str] = None,
    search: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    impact_level: Optional[str] = None,
    country: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Get recent articles with optional search, date, source, impact-level and country filtering."""
    query = db.query(NewsArticle).filter(NewsArticle.verified == True)
    if source:
        query = query.filter(NewsArticle.source == source)
    if impact_level:
        query = query.filter(NewsArticle.impact_level == impact_level)
    if country:
        # countries_mentioned stored as JSON array — match via text search on serialised column
        query = query.filter(NewsArticle.countries_mentioned.cast(String).ilike(f"%{country}%"))
    if search:
        term = f"%{search}%"
        query = query.filter(
            NewsArticle.title.ilike(term) |
            NewsArticle.source_name.ilike(term) |
            NewsArticle.summary.ilike(term)
        )
    if date_from:
        query = query.filter(NewsArticle.created_at >= datetime.combine(date_from, datetime.min.time()))
    if date_to:
        query = query.filter(NewsArticle.created_at <= datetime.combine(date_to, datetime.max.time()))

    # Default sort: impact severity first, then newest
    severity = case(
        (NewsArticle.impact_level == "critical", 0),
        (NewsArticle.impact_level == "high", 1),
        (NewsArticle.impact_level == "medium", 2),
        (NewsArticle.impact_level == "low", 3),
        else_=4,
    )
    articles = query.order_by(severity, NewsArticle.created_at.desc()).limit(limit).all()

    return [
        {
            "title": a.title,
            "url": a.url,
            "source": a.source,
            "source_name": a.source_name,
            "published_at": a.published_at,
            "verification_score": a.verification_score,
            "summary": a.summary,
            "run_id": a.run_id,
            "created_at": a.created_at.isoformat() if a.created_at else None,
            "impact_level": a.impact_level,
            "executive_headline": a.executive_headline,
            "impact_rationale": a.impact_rationale,
            "recommended_action": a.recommended_action,
            "countries_mentioned": a.countries_mentioned or [],
            "category": None,  # enriched in enricher; not persisted separately yet
        }
        for a in articles
    ]
