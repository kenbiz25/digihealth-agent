import hashlib, secrets
from sqlalchemy import create_engine, Column, Integer, String, Text, Float, DateTime, Boolean, JSON, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
from backend.config import DATABASE_URL

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class AgentRun(Base):
    """Tracks each agent pipeline execution."""
    __tablename__ = "agent_runs"

    id          = Column(Integer, primary_key=True, index=True)
    run_id      = Column(String, unique=True, index=True)
    status      = Column(String, default="pending")   # pending|running|completed|failed
    trigger     = Column(String, default="scheduled") # scheduled|manual
    started_at  = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)
    error_msg   = Column(Text, nullable=True)
    pdf_path    = Column(String, nullable=True)
    email_sent  = Column(Boolean, default=False)
    ai_provider = Column(String, default="claude")
    model_tier  = Column(String, default="balanced")


class AgentStep(Base):
    """Tracks individual steps within a run."""
    __tablename__ = "agent_steps"

    id          = Column(Integer, primary_key=True, index=True)
    run_id      = Column(String, index=True)
    step_name   = Column(String)                      # scraper|verifier|enricher|writer|pdf|email
    status      = Column(String, default="pending")   # pending|running|completed|failed
    started_at  = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    output      = Column(JSON, nullable=True)
    error_msg   = Column(Text, nullable=True)
    tokens_used = Column(Integer, default=0)


class NewsArticle(Base):
    """Stores scraped and verified news articles."""
    __tablename__ = "news_articles"

    id                 = Column(Integer, primary_key=True, index=True)
    run_id             = Column(String, index=True)
    title              = Column(String)
    url                = Column(String)
    source             = Column(String)          # twitter|linkedin|web
    source_name        = Column(String)
    published_at       = Column(String, nullable=True)
    raw_content        = Column(Text, nullable=True)
    summary            = Column(Text, nullable=True)
    verification_score = Column(Float, default=0.0)
    verified           = Column(Boolean, default=False)
    verification_notes = Column(Text, nullable=True)
    follow_up_links    = Column(JSON, nullable=True)
    countries_mentioned = Column(JSON, nullable=True)    # ["Kenya", "Rwanda", ...]
    impact_level       = Column(String, nullable=True)   # critical | high | medium | low
    impact_rationale   = Column(Text, nullable=True)     # strategic significance
    recommended_action = Column(Text, nullable=True)     # imperative action for exec
    executive_headline = Column(Text, nullable=True)     # punchy Monday morning framing
    sentiment_signal         = Column(String, nullable=True)   # positive | negative | neutral | mixed
    is_official              = Column(Boolean, default=False)  # from ministry/official source
    source_diversity_score   = Column(Float, nullable=True)    # 0-1: how many independent source types
    is_continuation_story    = Column(Boolean, default=False)  # story seen in a previous run
    continuation_of          = Column(Text, nullable=True)     # matched past article title
    urgency_tier             = Column(String, nullable=True)   # URGENT | STANDARD | BACKGROUND (AI-classified)
    created_at               = Column(DateTime, default=datetime.utcnow)


class ReportRequest(Base):
    """User requests to modify/re-query content."""
    __tablename__ = "report_requests"

    id          = Column(Integer, primary_key=True, index=True)
    run_id      = Column(String, index=True)
    request     = Column(Text)
    response    = Column(Text, nullable=True)
    status      = Column(String, default="pending")
    created_at  = Column(DateTime, default=datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)


class ArticleFeedback(Base):
    """User ratings on individual articles."""
    __tablename__ = "article_feedback"
    id          = Column(Integer, primary_key=True, index=True)
    article_url = Column(String, index=True)
    article_title = Column(String)
    rating      = Column(String)   # "relevant" | "noise" | "critical_miss"
    country     = Column(String, nullable=True)
    category    = Column(String, nullable=True)
    run_id      = Column(String, nullable=True)
    created_at  = Column(DateTime, default=datetime.utcnow)

class SourceExclusion(Base):
    """Sources the user has excluded from the pipeline."""
    __tablename__ = "source_exclusions"
    id          = Column(Integer, primary_key=True, index=True)
    source_name = Column(String, unique=True, index=True)
    created_at  = Column(DateTime, default=datetime.utcnow)


class CuratedSource(Base):
    """User-curated sources that the scraper always searches."""
    __tablename__ = "curated_sources"
    id          = Column(Integer, primary_key=True, index=True)
    name        = Column(String)                        # friendly label
    url         = Column(String, unique=True, index=True)  # domain or full URL
    source_type = Column(String, default="site")       # site | rss | keyword
    active      = Column(Boolean, default=True)
    notes       = Column(String, nullable=True)
    created_at  = Column(DateTime, default=datetime.utcnow)


class User(Base):
    """Portal user accounts."""
    __tablename__ = "users"
    id            = Column(Integer, primary_key=True, index=True)
    full_name     = Column(String, nullable=False)
    email         = Column(String, unique=True, index=True, nullable=False)
    phone         = Column(String, nullable=True)
    title         = Column(String, nullable=True)
    country       = Column(String, nullable=True)
    password_hash = Column(String, nullable=False)
    status        = Column(String, default="pending")   # pending | active | suspended
    role          = Column(String, default="user")      # user | admin
    created_at    = Column(DateTime, default=datetime.utcnow)
    last_login    = Column(DateTime, nullable=True)


class UserSession(Base):
    """Browser sessions for authenticated users."""
    __tablename__ = "user_sessions"
    id         = Column(Integer, primary_key=True, index=True)
    user_id    = Column(Integer, index=True, nullable=False)
    token      = Column(String, unique=True, index=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)


class EmailPreference(Base):
    """Per-user email digest preferences."""
    __tablename__ = "email_preferences"
    id          = Column(Integer, primary_key=True, index=True)
    user_id     = Column(Integer, unique=True, index=True, nullable=False)
    enabled     = Column(Boolean, default=False)  # OFF until user explicitly opts in
    # "after_run" = send immediately when pipeline finishes
    # "scheduled" = send at a fixed time
    frequency   = Column(String, default="after_run")
    send_hour   = Column(Integer, default=7)    # 24h, used when frequency="scheduled"
    send_minute = Column(Integer, default=0)
    day_of_week = Column(String, default="mon") # mon|tue|...|sun|daily
    timezone    = Column(String, default="Africa/Nairobi")
    updated_at  = Column(DateTime, default=datetime.utcnow)


class PasswordResetToken(Base):
    """Single-use tokens for password reset emails."""
    __tablename__ = "password_reset_tokens"
    id         = Column(Integer, primary_key=True, index=True)
    user_id    = Column(Integer, index=True, nullable=False)
    token      = Column(String, unique=True, index=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    used       = Column(Boolean, default=False)


def init_db():
    Base.metadata.create_all(bind=engine)
    # Safe migration: add new columns to existing databases without dropping data
    _new_cols = [
        ("impact_level",            "TEXT"),
        ("impact_rationale",        "TEXT"),
        ("recommended_action",      "TEXT"),
        ("executive_headline",      "TEXT"),
        ("countries_mentioned",     "TEXT"),
        ("sentiment_signal",        "TEXT"),
        ("is_official",             "INTEGER DEFAULT 0"),
        ("source_diversity_score",  "REAL"),
        ("is_continuation_story",   "INTEGER DEFAULT 0"),
        ("continuation_of",         "TEXT"),
        ("urgency_tier",            "TEXT DEFAULT 'STANDARD'"),
    ]
    with engine.connect() as conn:
        for col_name, col_type in _new_cols:
            try:
                conn.execute(text(f"ALTER TABLE news_articles ADD COLUMN {col_name} {col_type}"))
                conn.commit()
            except Exception:
                pass  # Column already exists — safe to ignore

    # Safe migration: new tables (users, user_sessions, email_preferences)
    # create_all above already handles brand-new databases; the blocks below
    # add any columns that may be missing in older deployments.
    _user_cols = [
        ("phone",      "TEXT"),
        ("title",      "TEXT"),
        ("country",    "TEXT"),
        ("last_login", "TEXT"),
    ]
    _session_cols: list = []          # all columns present at creation; nothing to backfill
    _pref_cols = [
        ("send_minute", "INTEGER DEFAULT 0"),
        ("day_of_week", "TEXT DEFAULT 'mon'"),
        ("timezone",    "TEXT DEFAULT 'Africa/Nairobi'"),
        ("updated_at",  "TEXT"),
    ]
    _table_extra = [
        ("users",            _user_cols),
        ("user_sessions",    _session_cols),
        ("email_preferences", _pref_cols),
    ]
    with engine.connect() as conn:
        for table, cols in _table_extra:
            for col_name, col_type in cols:
                try:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type}"))
                    conn.commit()
                except Exception:
                    pass  # Column already exists — safe to ignore


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
