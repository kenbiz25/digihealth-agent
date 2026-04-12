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
    sentiment_signal   = Column(String, nullable=True)   # positive | negative | neutral | mixed
    is_official        = Column(Boolean, default=False)  # from ministry/official source
    created_at         = Column(DateTime, default=datetime.utcnow)


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


def init_db():
    Base.metadata.create_all(bind=engine)
    # Safe migration: add new columns to existing databases without dropping data
    _new_cols = [
        ("impact_level",        "TEXT"),
        ("impact_rationale",    "TEXT"),
        ("recommended_action",  "TEXT"),
        ("executive_headline",  "TEXT"),
        ("countries_mentioned", "TEXT"),
        ("sentiment_signal",    "TEXT"),
        ("is_official",         "INTEGER DEFAULT 0"),
    ]
    with engine.connect() as conn:
        for col_name, col_type in _new_cols:
            try:
                conn.execute(text(f"ALTER TABLE news_articles ADD COLUMN {col_name} {col_type}"))
                conn.commit()
            except Exception:
                pass  # Column already exists — safe to ignore


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
