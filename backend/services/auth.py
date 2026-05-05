"""
Simple session-based auth helpers.
No external packages needed — uses stdlib hashlib + secrets.
"""
import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Cookie, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.database import get_db, User, UserSession


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260_000)
    return f"{salt}:{key.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, key_hex = stored.split(":", 1)
        key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260_000)
        return secrets.compare_digest(key.hex(), key_hex)
    except Exception:
        return False


def create_session(user_id: int, remember: bool, db: Session) -> str:
    token = secrets.token_urlsafe(32)
    days = 30 if remember else 1
    session = UserSession(
        user_id=user_id,
        token=token,
        expires_at=datetime.utcnow() + timedelta(days=days),
    )
    db.add(session)
    db.commit()
    return token


def get_current_user(
    session_token: Optional[str] = Cookie(None, alias="session"),
    db: Session = Depends(get_db),
) -> User:
    if not session_token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    sess = (
        db.query(UserSession)
        .filter(
            UserSession.token == session_token,
            UserSession.expires_at > datetime.utcnow(),
        )
        .first()
    )
    if not sess:
        raise HTTPException(status_code=401, detail="Session expired or invalid")
    user = db.query(User).filter(User.id == sess.user_id).first()
    if not user or user.status != "active":
        raise HTTPException(status_code=401, detail="Account not active")
    return user


def get_current_user_optional(
    session_token: Optional[str] = Cookie(None, alias="session"),
    db: Session = Depends(get_db),
) -> Optional[User]:
    """Returns None instead of raising when unauthenticated — for soft-gate endpoints."""
    try:
        return get_current_user(session_token, db)
    except HTTPException:
        return None
