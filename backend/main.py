"""
FastAPI Backend - REST API + WebSocket for the Digital Health Africa AI Agent.
Run with: uvicorn backend.main:app --reload --port 8000
"""
import asyncio
import sys
import json
import os

# Windows: ProactorEventLoop breaks concurrent DNS resolution — switch to Selector
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
from contextlib import asynccontextmanager
from datetime import datetime, date
from typing import Any, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException, BackgroundTasks, Response, Cookie
from sqlalchemy import case, func, String
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.config import (
    AI_PROVIDER, CLAUDE_MODELS, OPENAI_MODELS,
    SCHEDULE_HOUR, SCHEDULE_MINUTE, TIMEZONE, EMAIL_ENABLED,
    ANTHROPIC_API_KEY, OPENAI_API_KEY, TAVILY_API_KEY, TAVILY_API_KEYS_LIST,
    TWITTER_BEARER_TOKEN, SMTP_PASSWORD, BASE_URL,
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
            "tavily": bool(TAVILY_API_KEYS_LIST),
            "twitter": bool(TWITTER_BEARER_TOKEN),
            "smtp": bool(SMTP_PASSWORD),
        },
    }
from backend.database import init_db, get_db, SessionLocal, AgentRun, AgentStep, NewsArticle, ReportRequest, ArticleFeedback, SourceExclusion, CuratedSource, User, UserSession, EmailPreference, PasswordResetToken
from backend.services.auth import hash_password, verify_password, create_session, get_current_user, get_current_user_optional
from urllib.parse import urlparse
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
    country_filter: str = ""          # single country (legacy)
    country_filters: list[str] = []   # multi-country selection
    pipeline_mode: str = "full"       # "quick" = scrape+verify only; "full" = all steps + PDF
    lookback_days: int = 7            # how many days back to search


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


class FeedbackRequest(BaseModel):
    url: str
    title: str
    rating: str   # "relevant" | "noise" | "critical_miss"
    country: str = ""
    category: str = ""
    run_id: str = ""


class LoginRequest(BaseModel):
    email: str
    password: str
    remember: bool = False


class RegisterRequest(BaseModel):
    full_name: str
    email: str
    password: str
    phone: str = ""
    title: str = ""
    country: str = ""


class EmailPrefRequest(BaseModel):
    enabled: bool = True
    frequency: str = "after_run"   # "after_run" | "scheduled"
    send_hour: int = 7
    send_minute: int = 0
    day_of_week: str = "daily"     # "daily" | "mon" | "tue" | ... | "sun"
    timezone: str = "Africa/Nairobi"


class ProfileUpdateRequest(BaseModel):
    phone: str = ""
    title: str = ""
    country: str = ""


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    password: str


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


@app.get("/login")
async def serve_login():
    return FileResponse(os.path.join(FRONTEND_DIR, "login.html"))


@app.get("/register")
async def serve_register():
    return FileResponse(os.path.join(FRONTEND_DIR, "register.html"))


@app.get("/forgot-password")
async def serve_forgot():
    return FileResponse(os.path.join(FRONTEND_DIR, "forgot-password.html"))


@app.get("/reset-password")
async def serve_reset():
    return FileResponse(os.path.join(FRONTEND_DIR, "reset-password.html"))


# ── Auth ─────────────────────────────────────────────────────────────────────

@app.post("/auth/register")
async def auth_register(req: RegisterRequest, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == req.email.lower()).first():
        raise HTTPException(status_code=400, detail="An account with this email already exists.")
    if len(req.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")
    user = User(
        full_name=req.full_name.strip(),
        email=req.email.lower().strip(),
        phone=req.phone.strip(),
        title=req.title.strip(),
        country=req.country.strip(),
        password_hash=hash_password(req.password),
        status="active",
        role="user",
    )
    db.add(user)
    db.commit()
    return {"message": "Account created successfully."}


@app.post("/auth/login")
async def auth_login(req: LoginRequest, response: Response, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == req.email.lower().strip()).first()
    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    if user.status == "pending":
        raise HTTPException(status_code=403, detail="Your account is pending admin approval.")
    if user.status == "suspended":
        raise HTTPException(status_code=403, detail="Your account has been suspended. Contact your administrator.")
    token = create_session(user.id, req.remember, db)
    user.last_login = datetime.utcnow()
    db.commit()
    max_age = 60 * 60 * 24 * (30 if req.remember else 1)
    response.set_cookie("session", token, max_age=max_age, httponly=True, samesite="lax", path="/")
    return {"message": "Logged in", "user": {"name": user.full_name, "email": user.email, "role": user.role}}


@app.post("/auth/logout")
async def auth_logout(response: Response, session: Optional[str] = Cookie(None), db: Session = Depends(get_db)):
    if session:
        db.query(UserSession).filter(UserSession.token == session).delete()
        db.commit()
    response.delete_cookie("session", path="/")
    return {"message": "Logged out"}


@app.post("/auth/forgot-password")
async def auth_forgot_password(req: ForgotPasswordRequest, db: Session = Depends(get_db)):
    from backend.services.email_service import send_password_reset_email
    import secrets
    from datetime import timedelta
    user = db.query(User).filter(User.email == req.email.lower().strip()).first()
    if not user:
        # Don't reveal whether the email exists
        return {"message": "If that email is registered you will receive a reset link shortly."}
    # Invalidate any previous unused tokens for this user
    db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user.id,
        PasswordResetToken.used == False,
    ).delete()
    db.commit()
    token = secrets.token_urlsafe(32)
    reset_token = PasswordResetToken(
        user_id=user.id,
        token=token,
        expires_at=datetime.utcnow() + timedelta(hours=1),
    )
    db.add(reset_token)
    db.commit()
    reset_url = f"{BASE_URL}/reset-password?token={token}"
    await send_password_reset_email(user.email, reset_url)
    return {"message": "If that email is registered you will receive a reset link shortly."}


@app.post("/auth/reset-password")
async def auth_reset_password(req: ResetPasswordRequest, db: Session = Depends(get_db)):
    reset_token = db.query(PasswordResetToken).filter(
        PasswordResetToken.token == req.token,
        PasswordResetToken.used == False,
        PasswordResetToken.expires_at > datetime.utcnow(),
    ).first()
    if not reset_token:
        raise HTTPException(status_code=400, detail="Reset link is invalid or has expired.")
    if len(req.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")
    user = db.query(User).filter(User.id == reset_token.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    from backend.services.auth import hash_password
    user.password_hash = hash_password(req.password)
    reset_token.used = True
    # Invalidate all active sessions so old sessions can't be reused
    db.query(UserSession).filter(UserSession.user_id == user.id).delete()
    db.commit()
    return {"message": "Password updated successfully. You can now sign in."}


@app.get("/auth/me")
async def auth_me(current_user: User = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "name": current_user.full_name,
        "email": current_user.email,
        "phone": current_user.phone or "",
        "role": current_user.role,
        "country": current_user.country,
        "title": current_user.title or "",
    }


@app.put("/api/profile")
async def update_profile(req: ProfileUpdateRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == current_user.id).first()
    user.phone = req.phone.strip()
    user.title = req.title.strip()
    if req.country.strip():
        user.country = req.country.strip()
    db.commit()
    return {"message": "Profile updated", "phone": user.phone, "title": user.title, "country": user.country}


# ── Admin: user management ────────────────────────────────────────────────────

@app.get("/api/admin/users")
async def list_users(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    users = db.query(User).order_by(User.created_at.desc()).all()
    return [{"id": u.id, "name": u.full_name, "email": u.email, "title": u.title,
             "country": u.country, "status": u.status, "role": u.role,
             "created_at": u.created_at.isoformat()} for u in users]


@app.patch("/api/admin/users/{user_id}/status")
async def update_user_status(user_id: int, body: dict, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    new_status = body.get("status")
    if new_status not in ("active", "pending", "suspended"):
        raise HTTPException(status_code=400, detail="Invalid status")
    user.status = new_status
    db.commit()
    return {"message": f"User {user.email} status set to {new_status}"}


# ── Email preferences ─────────────────────────────────────────────────────────

_COUNTRY_TZ: dict[str, str] = {
    "Kenya": "Africa/Nairobi", "Tanzania": "Africa/Nairobi", "Uganda": "Africa/Nairobi",
    "Rwanda": "Africa/Nairobi", "Ethiopia": "Africa/Nairobi",
    "Nigeria": "Africa/Lagos", "Senegal": "Africa/Lagos",
    "Ghana": "Africa/Accra", "Sierra Leone": "Africa/Accra",
    "South Africa": "Africa/Johannesburg", "Zambia": "Africa/Johannesburg",
    "Malawi": "Africa/Johannesburg", "Zimbabwe": "Africa/Johannesburg",
    "India": "Asia/Kolkata", "Nepal": "Asia/Kolkata",
    "Bangladesh": "Asia/Dhaka", "Bhutan": "Asia/Dhaka",
    "Pakistan": "Asia/Karachi",
    "Saudi Arabia": "Asia/Riyadh",
    "United States": "America/New_York",
    "United Kingdom": "Europe/London",
    "Netherlands": "Europe/Amsterdam", "Switzerland": "Europe/Amsterdam",
}

def _country_to_tz(country: str) -> str:
    return _COUNTRY_TZ.get(country, "Africa/Nairobi")


@app.get("/api/email-preferences")
async def get_email_prefs(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    prefs = db.query(EmailPreference).filter(EmailPreference.user_id == current_user.id).first()
    if not prefs:
        # Return disabled defaults — user must explicitly opt in
        tz = current_user.country and _country_to_tz(current_user.country) or "Africa/Nairobi"
        return {"enabled": False, "frequency": "after_run", "send_hour": 7,
                "send_minute": 0, "day_of_week": "daily", "timezone": tz}
    return {"enabled": prefs.enabled, "frequency": prefs.frequency,
            "send_hour": prefs.send_hour, "send_minute": prefs.send_minute,
            "day_of_week": prefs.day_of_week, "timezone": prefs.timezone}


@app.put("/api/email-preferences")
async def save_email_prefs(req: EmailPrefRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    prefs = db.query(EmailPreference).filter(EmailPreference.user_id == current_user.id).first()
    if prefs:
        prefs.enabled = req.enabled; prefs.frequency = req.frequency
        prefs.send_hour = req.send_hour; prefs.send_minute = req.send_minute
        prefs.day_of_week = req.day_of_week; prefs.timezone = req.timezone
        prefs.updated_at = datetime.utcnow()
    else:
        prefs = EmailPreference(user_id=current_user.id, enabled=req.enabled,
                                frequency=req.frequency, send_hour=req.send_hour,
                                send_minute=req.send_minute, day_of_week=req.day_of_week,
                                timezone=req.timezone)
        db.add(prefs)
    db.commit()
    return {"message": "Email preferences saved"}


@app.get("/api/config")
async def get_safe_config():
    """Public config — safe for the frontend. NO secrets returned."""
    return _safe_config()


@app.get("/api/status")
async def get_status(db: Session = Depends(get_db)):
    """System status overview — no secrets exposed."""
    recent_runs = db.query(AgentRun).order_by(AgentRun.started_at.desc()).limit(5).all()
    last_run = recent_runs[0] if recent_runs else None
    total_articles = db.query(func.count(NewsArticle.id)).scalar() or 0
    verified_articles = db.query(func.count(NewsArticle.id)).filter(NewsArticle.verified == True).scalar() or 0
    total_runs = db.query(func.count(AgentRun.id)).scalar() or 0
    return {
        "status": "running",
        "ai_provider": AI_PROVIDER,
        "schedule": f"{SCHEDULE_HOUR:02d}:{SCHEDULE_MINUTE:02d} {TIMEZONE}",
        "next_run": get_next_run_time(),
        "email_enabled": EMAIL_ENABLED,
        "active_connections": len(manager.active),
        "keys_configured": _safe_config()["keys_configured"],
        "total_articles": total_articles,
        "verified_articles": verified_articles,
        "total_runs": total_runs,
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
                country_filters=request.country_filters or None,
                pipeline_mode=request.pipeline_mode,
                lookback_days=request.lookback_days,
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
    User-triggered search with Tavily (primary) + free-source fallbacks + Claude extraction.
    Always returns a valid JSON array — never raises an exception to the frontend.
    """
    try:
        raw: list[dict] = []

        # Primary: Tavily — two topic angles in parallel
        if TAVILY_API_KEY:
            t1, t2 = await asyncio.gather(
                search_tavily(body.query, "general", days=body.days),
                search_tavily(body.query, "news",    days=body.days),
                return_exceptions=True,
            )
            if isinstance(t1, list): raw.extend(t1)
            if isinstance(t2, list): raw.extend(t2)

        # Fallback / supplement: free sources (always run; PubMed adds academic evidence)
        from backend.agents.scraper_agent import (
            search_google_news_rss, search_pubmed, search_world_bank,
        )
        free_results = await asyncio.gather(
            search_google_news_rss(body.query, days=body.days),
            search_pubmed(body.query),
            search_world_bank(body.query),
            return_exceptions=True,
        )
        for r in free_results:
            if isinstance(r, list):
                raw.extend(r)

        if not raw:
            return []

        # Deduplicate by URL and preserve source field
        seen: set[str] = set()
        unique: list[dict] = []
        for r in raw:
            url = r.get("url", "")
            if url and url not in seen:
                seen.add(url)
                # Normalise to common schema
                unique.append({
                    "title":        r.get("title", ""),
                    "url":          url,
                    "source":       r.get("source", "web"),
                    "source_name":  r.get("source_name", ""),
                    "published_at": r.get("published_date") or r.get("published_at", ""),
                    "content":      (r.get("content") or r.get("raw_content") or "")[:300],
                })
        raw = unique[:40]

        system = (
            "You are a research assistant. Extract relevant news/articles from raw search results. "
            "Return a JSON array. Each item: "
            "{title, url, source, source_name, published_at, summary, relevance_score}. "
            "Only include items clearly relevant to the user's query. relevance_score 0.0-1.0. "
            "If none qualify, return []."
        )
        user_prompt = (
            f"Query: {body.query}\n\n"
            f"Raw results:\n{json.dumps(raw, indent=2)}\n\n"
            "Return a JSON array of the most relevant articles."
        )
        client = get_ai_client(AI_PROVIDER)
        response_text, _ = call_ai(
            client, system, user_prompt,
            model_tier=SCRAPER_MODEL, max_tokens=4000, provider=AI_PROVIDER,
        )
        try:
            articles = parse_json_response(response_text)
            return [a for a in articles if isinstance(a, dict) and a.get("relevance_score", 0) >= 0.4]
        except Exception:
            return []

    except Exception as e:
        print(f"[CustomSearch] Unhandled error: {e}")
        return []  # Always valid JSON — frontend never sees "Search failed"


@app.post("/api/feedback")
async def submit_feedback(body: FeedbackRequest, db: Session = Depends(get_db)):
    existing = db.query(ArticleFeedback).filter(ArticleFeedback.article_url == body.url).first()
    if existing:
        existing.rating   = body.rating
        existing.country  = body.country
        existing.category = body.category
    else:
        db.add(ArticleFeedback(
            article_url=body.url, article_title=body.title,
            rating=body.rating, country=body.country,
            category=body.category, run_id=body.run_id,
        ))
    db.commit()
    return {"success": True}


@app.get("/api/tuning/feedback")
async def get_tuning_feedback(db: Session = Depends(get_db)):
    items = db.query(ArticleFeedback).order_by(ArticleFeedback.created_at.desc()).limit(500).all()
    counts = {"relevant": 0, "noise": 0, "critical_miss": 0}
    for i in items:
        if i.rating in counts:
            counts[i.rating] += 1
    return {
        "stats": {**counts, "total": len(items)},
        "items": [{"url": i.article_url, "title": i.article_title,
                   "rating": i.rating, "country": i.country,
                   "category": i.category, "created_at": i.created_at.isoformat() if i.created_at else ""
                  } for i in items],
    }


@app.get("/api/tuning/queries")
async def get_query_performance(db: Session = Depends(get_db)):
    """Compute query-source performance from the articles table."""
    from sqlalchemy import func as sa_func, case as sa_case
    impact_score = sa_case(
        (NewsArticle.impact_level == "critical", 1.0),
        (NewsArticle.impact_level == "high",     0.75),
        (NewsArticle.impact_level == "medium",   0.5),
        else_=0.25,
    )
    rows = (
        db.query(
            NewsArticle.source.label("source_type"),
            sa_func.count().label("total"),
            sa_func.sum(sa_case((NewsArticle.verified == True, 1), else_=0)).label("verified_count"),
            sa_func.avg(impact_score).label("avg_impact"),
        )
        .filter(NewsArticle.source.isnot(None))
        .group_by(NewsArticle.source)
        .order_by(sa_func.avg(impact_score).desc())
        .all()
    )
    SOURCE_LABELS = {
        "tavily_t1": "Tier 1 (Sierra Leone / Bangladesh)",
        "tavily_t2": "Tier 2 (Kenya / Rwanda / Ghana / India)",
        "tavily_t3": "Tier 3 (Saudi / Tanzania / Bhutan / US)",
        "linkedin_tavily": "LinkedIn Discussions",
        "moh_site": "Ministry of Health Sites",
        "official": "Official Pronouncements",
        "donor": "Donor & Global Orgs",
        "sentiment": "Social Sentiment",
        "regulatory": "Regulatory / Market Access",
        "budget": "Budget & Fiscal Cycle",
        "reimbursement": "NCD Reimbursement / Pricing",
        "clinical": "Clinical Domains (Medtronic LABS)",
        "conference": "Conference Outcomes",
        "officials": "Named Officials Monitoring",
        "funding": "Funding & Grant Opportunities",
        "pubmed": "PubMed Academic Evidence",
        "world_bank": "World Bank Documents",
        "who_iris": "WHO IRIS Repository",
        "usaid_rss": "USAID Content",
        "gates_rss": "Gates Foundation Content",
        "news": "Google News RSS",
        "web": "Web (DuckDuckGo / General)",
        "twitter_api": "Twitter / X API",
    }
    result = []
    for r in rows:
        total = r.total or 0
        ver   = int(r.verified_count or 0)
        avg   = round(float(r.avg_impact or 0.25), 3)
        grade = "good" if avg >= 0.65 else ("ok" if avg >= 0.45 else "poor")
        result.append({
            "source_type":  r.source_type,
            "label":        SOURCE_LABELS.get(r.source_type, r.source_type),
            "total":        total,
            "verified":     ver,
            "verify_pct":   round(ver / total * 100) if total else 0,
            "avg_impact":   avg,
            "grade":        grade,
        })
    return result


@app.get("/api/tuning/sources")
async def get_source_quality(db: Session = Depends(get_db)):
    """Compute per-source-name quality metrics from the articles table."""
    from sqlalchemy import func as sa_func, case as sa_case
    impact_score = sa_case(
        (NewsArticle.impact_level == "critical", 1.0),
        (NewsArticle.impact_level == "high",     0.75),
        (NewsArticle.impact_level == "medium",   0.5),
        else_=0.25,
    )
    rows = (
        db.query(
            NewsArticle.source_name.label("source_name"),
            sa_func.count().label("total"),
            sa_func.avg(NewsArticle.verification_score).label("avg_ver"),
            sa_func.avg(impact_score).label("avg_impact"),
        )
        .filter(NewsArticle.verified == True)
        .filter(NewsArticle.source_name.isnot(None))
        .filter(NewsArticle.source_name != "")
        .group_by(NewsArticle.source_name)
        .order_by(sa_func.avg(NewsArticle.verification_score).desc())
        .all()
    )
    excluded = {e.source_name for e in db.query(SourceExclusion).all()}
    # Feedback noise counts per source
    fb_rows = db.query(ArticleFeedback.article_url, ArticleFeedback.rating).all()
    # Map URL → rating
    fb_map = {r.article_url: r.rating for r in fb_rows}
    # Map source_name → noise count (via article lookup)
    art_rows = db.query(NewsArticle.source_name, NewsArticle.url).filter(NewsArticle.verified == True).all()
    noise_by_src: dict[str, int] = {}
    for ar in art_rows:
        if fb_map.get(ar.url) == "noise":
            noise_by_src[ar.source_name] = noise_by_src.get(ar.source_name, 0) + 1
    result = []
    for r in rows:
        sn = r.source_name
        total = r.total or 0
        avg_ver = round(float(r.avg_ver or 0), 3)
        avg_imp = round(float(r.avg_impact or 0.25), 3)
        noise_c = noise_by_src.get(sn, 0)
        noise_rt = round(noise_c / total, 2) if total else 0
        grade = "good" if avg_ver >= 0.7 else ("ok" if avg_ver >= 0.5 else "poor")
        result.append({
            "source_name": sn,
            "total":       total,
            "avg_ver":     avg_ver,
            "avg_impact":  avg_imp,
            "noise_count": noise_c,
            "noise_rate":  noise_rt,
            "excluded":    sn in excluded,
            "grade":       grade,
        })
    return result


@app.post("/api/tuning/sources/toggle")
async def toggle_source_exclude(body: dict, db: Session = Depends(get_db)):
    sn      = body.get("source_name", "")
    exclude = body.get("exclude", True)
    if not sn:
        raise HTTPException(400, "source_name required")
    existing = db.query(SourceExclusion).filter(SourceExclusion.source_name == sn).first()
    if exclude and not existing:
        db.add(SourceExclusion(source_name=sn))
        db.commit()
    elif not exclude and existing:
        db.delete(existing)
        db.commit()
    return {"success": True, "source_name": sn, "excluded": exclude}


# ── Curated Sources ─────────────────────────────────────────────────────────

@app.get("/api/curated-sources")
async def list_curated_sources(db: Session = Depends(get_db)):
    rows = db.query(CuratedSource).order_by(CuratedSource.created_at.desc()).all()
    return [
        {"id": r.id, "name": r.name, "url": r.url, "source_type": r.source_type,
         "active": r.active, "notes": r.notes,
         "created_at": r.created_at.isoformat() if r.created_at else None}
        for r in rows
    ]


@app.post("/api/curated-sources")
async def add_curated_source(body: dict, db: Session = Depends(get_db)):
    url = (body.get("url") or "").strip()
    name = (body.get("name") or url).strip()
    if not url:
        raise HTTPException(400, "url required")
    if db.query(CuratedSource).filter(CuratedSource.url == url).first():
        raise HTTPException(409, "Source already exists")
    src = CuratedSource(
        name=name, url=url,
        source_type=body.get("source_type", "site"),
        notes=body.get("notes", ""),
    )
    db.add(src); db.commit(); db.refresh(src)
    return {"id": src.id, "name": src.name, "url": src.url, "active": src.active}


@app.delete("/api/curated-sources/{source_id}")
async def delete_curated_source(source_id: int, db: Session = Depends(get_db)):
    src = db.query(CuratedSource).filter(CuratedSource.id == source_id).first()
    if not src:
        raise HTTPException(404, "Not found")
    db.delete(src); db.commit()
    return {"deleted": source_id}


@app.patch("/api/curated-sources/{source_id}/toggle")
async def toggle_curated_source(source_id: int, db: Session = Depends(get_db)):
    src = db.query(CuratedSource).filter(CuratedSource.id == source_id).first()
    if not src:
        raise HTTPException(404, "Not found")
    src.active = not src.active; db.commit()
    return {"id": src.id, "active": src.active}


@app.get("/api/tuning/articles")
async def get_articles_for_feedback(
    limit: int = 30,
    offset: int = 0,
    country: Optional[str] = None,
    impact_level: Optional[str] = None,
    search: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Articles for the feedback tab — includes their current rating if rated."""
    q = db.query(NewsArticle).filter(NewsArticle.verified == True)
    if country:
        q = q.filter(NewsArticle.countries_mentioned.cast(String).ilike(f"%{country}%"))
    if impact_level:
        q = q.filter(NewsArticle.impact_level == impact_level)
    if search:
        term = f"%{search}%"
        q = q.filter(NewsArticle.title.ilike(term) | NewsArticle.source_name.ilike(term))
    severity = case(
        (NewsArticle.impact_level == "critical", 0),
        (NewsArticle.impact_level == "high", 1),
        (NewsArticle.impact_level == "medium", 2),
        (NewsArticle.impact_level == "low", 3),
        else_=4,
    )
    articles = q.order_by(severity, NewsArticle.created_at.desc()).offset(offset).limit(limit).all()
    # Fetch ratings for these URLs
    urls = [a.url for a in articles if a.url]
    ratings_map = {}
    if urls:
        fbs = db.query(ArticleFeedback).filter(ArticleFeedback.article_url.in_(urls)).all()
        ratings_map = {f.article_url: f.rating for f in fbs}
    return [
        {
            "title":        a.title,
            "url":          a.url,
            "source_name":  a.source_name,
            "impact_level": a.impact_level,
            "countries_mentioned": a.countries_mentioned or [],
            "category":     None,
            "run_id":       a.run_id,
            "created_at":   a.created_at.isoformat() if a.created_at else "",
            "rating":       ratings_map.get(a.url),
        }
        for a in articles
    ]


@app.get("/api/executive-summary")
async def get_executive_summary(
    country: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """
    Returns executive-ready impact summary for the most recent completed run.
    Powers the Executive Pulse section on the dashboard.
    Optional ?country= filters all stats and alerts to that country only.
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

    q = (
        db.query(NewsArticle)
        .filter(NewsArticle.run_id == last_run.run_id, NewsArticle.verified == True)
    )
    if country:
        q = q.filter(NewsArticle.countries_mentioned.cast(String).ilike(f"%{country}%"))
    articles = q.all()

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


@app.get("/api/articles/country-counts")
async def get_article_country_counts(db: Session = Depends(get_db)):
    """Returns total verified article count per target country (no cap)."""
    from backend.config import TARGET_COUNTRIES
    result = {}
    for country in TARGET_COUNTRIES:
        result[country] = (
            db.query(func.count(NewsArticle.id))
            .filter(
                NewsArticle.verified == True,
                NewsArticle.countries_mentioned.cast(String).ilike(f"%{country}%"),
            )
            .scalar() or 0
        )
    return result


@app.get("/api/articles")
async def get_articles(
    limit: int = 50,
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

    # Default sort: most recently published first; fall back to scrape date when no publish date
    from sqlalchemy import nullslast
    articles = query.order_by(
        nullslast(NewsArticle.published_at.desc()),
        NewsArticle.created_at.desc(),
    ).limit(limit).all()

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
            "source_diversity_score": a.source_diversity_score,
            "is_continuation_story": a.is_continuation_story or False,
            "continuation_of": a.continuation_of,
            "category": None,
        }
        for a in articles
    ]
