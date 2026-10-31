"""Forgot-password links: one-time, expire after RESET_TTL, stored only as a SHA-256 hash."""

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import AuditEvent, PasswordResetToken, User, UserSession
from app.notifications.mailer import EmailError, send_email
from app.notifications.template import render_password_reset
from app.services.app_settings import get_app_settings
from app.services.audit import record_audit
from app.services.auth import hash_password

log = logging.getLogger(__name__)

RESET_TTL = timedelta(hours=1)
MAX_REQUESTS_PER_HOUR = 5


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _too_many_requests(db: Session, email: str, ip: str | None) -> bool:
    since = datetime.now(timezone.utc) - timedelta(hours=1)
    conditions = [AuditEvent.actor == email]
    if ip:
        conditions.append(AuditEvent.ip_address == ip)
    count = db.scalar(
        select(func.count()).select_from(AuditEvent)
        .where(AuditEvent.action == "password_reset_requested", AuditEvent.created_at >= since, or_(*conditions))
    )
    return (count or 0) >= MAX_REQUESTS_PER_HOUR


def request_reset(db: Session, email: str, ip: str | None) -> None:
    """Email a reset link if the address belongs to an active admin. Never reveals whether it does."""
    email = email.strip().lower()
    if _too_many_requests(db, email, ip):
        log.warning("Password reset rate limit hit")
        return
    record_audit(db, "password_reset_requested", actor=email, ip_address=ip)
    user = db.scalar(select(User).where(func.lower(User.email) == email))
    if user is None or not user.is_active:
        db.commit()
        return

    now = datetime.now(timezone.utc)
    token = secrets.token_urlsafe(32)
    # Only the newest link works; older unused ones are retired.
    db.execute(update(PasswordResetToken)
               .where(PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None))
               .values(used_at=now))
    db.execute(delete(PasswordResetToken).where(PasswordResetToken.expires_at < now - timedelta(days=7)))
    db.add(PasswordResetToken(token_hash=_hash(token), user_id=user.id, expires_at=now + RESET_TTL, ip_address=ip))
    db.commit()

    link = f"{get_settings().app_base_url.rstrip('/')}/reset-password?token={token}"
    message = render_password_reset(link, int(RESET_TTL.total_seconds() // 60))
    message.to = user.email
    try:
        send_email(db, get_app_settings(db), message)
    except EmailError as exc:
        log.warning("Password reset email failed: %s", exc.message)
        record_audit(db, "password_reset_email_failed", user=user, ip_address=ip, details={"error": exc.message})
        db.commit()
        return
    record_audit(db, "password_reset_email_sent", user=user, ip_address=ip)
    db.commit()


def valid_token(db: Session, token: str) -> PasswordResetToken | None:
    row = db.scalar(select(PasswordResetToken).where(PasswordResetToken.token_hash == _hash(token)))
    if row is None or row.used_at is not None or row.expires_at <= datetime.now(timezone.utc):
        return None
    if not row.user.is_active:
        return None
    return row


def set_password(db: Session, user: User, password: str, *, keep_session_id=None) -> None:
    """Set a new password and sign the user out everywhere (except keep_session_id)."""
    user.password_hash = hash_password(password)
    query = delete(UserSession).where(UserSession.user_id == user.id)
    if keep_session_id is not None:
        query = query.where(UserSession.id != keep_session_id)
    db.execute(query)


def complete_reset(db: Session, token: str, password: str, ip: str | None) -> bool:
    row = valid_token(db, token)
    if row is None:
        return False
    user = row.user
    set_password(db, user, password)
    db.execute(update(PasswordResetToken)
               .where(PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None))
               .values(used_at=datetime.now(timezone.utc)))
    record_audit(db, "password_reset_completed", user=user, ip_address=ip)
    db.commit()
    return True
