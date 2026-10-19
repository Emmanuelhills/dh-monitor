"""Password hashing and server-side sessions."""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import AuditEvent, User, UserSession

_hasher = PasswordHasher()

MIN_PASSWORD_LENGTH = 12


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(db: Session, user: User, ip: str | None, user_agent: str | None) -> tuple[str, UserSession]:
    """Create a session and return (raw token for the cookie, session row)."""
    token = secrets.token_urlsafe(32)
    session = UserSession(
        token_hash=_hash_token(token),
        csrf_token=secrets.token_urlsafe(32),
        user_id=user.id,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=get_settings().session_ttl_hours),
        ip_address=ip,
        user_agent=(user_agent or "")[:512],
    )
    db.add(session)
    # Opportunistic cleanup of expired sessions.
    db.execute(delete(UserSession).where(UserSession.expires_at < datetime.now(timezone.utc)))
    return token, session


def resolve_session(db: Session, token: str | None) -> UserSession | None:
    if not token:
        return None
    session = db.scalar(select(UserSession).where(UserSession.token_hash == _hash_token(token)))
    if session is None or session.expires_at <= datetime.now(timezone.utc):
        return None
    if not session.user.is_active:
        return None
    return session


def destroy_session(db: Session, token: str | None) -> None:
    if token:
        db.execute(delete(UserSession).where(UserSession.token_hash == _hash_token(token)))


def too_many_failures(db: Session, email: str, ip: str | None) -> bool:
    settings = get_settings()
    since = datetime.now(timezone.utc) - timedelta(minutes=settings.login_failure_window_minutes)
    conditions = [AuditEvent.actor == email.lower()]
    if ip:
        conditions.append(AuditEvent.ip_address == ip)
    count = db.scalar(
        select(func.count())
        .select_from(AuditEvent)
        .where(AuditEvent.action == "login_failed", AuditEvent.created_at >= since, or_(*conditions))
    )
    return (count or 0) >= settings.login_max_failures
