import hmac
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, client_ip, require_admin
from app.api.errors import ApiError
from app.config import get_settings
from app.db import get_db
from app.models import User, UserSession
from app.schemas import ChangePasswordIn, LoginIn, MeOut
from app.services.audit import record_audit
from app.services.auth import (
    create_session,
    destroy_session,
    hash_password,
    too_many_failures,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])

# Verifying against a dummy hash keeps response timing similar for unknown emails.
_DUMMY_HASH = hash_password("timing-equalizer-password")


def _set_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        settings.session_cookie_name,
        token,
        max_age=settings.session_ttl_hours * 3600,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


def _bootstrap_admin(db: Session, email: str, password: str) -> User | None:
    """Create the first administrator from DHM_BOOTSTRAP_ADMIN_EMAIL / _PASSWORD, but only while
    no users exist at all. Remove the password variable after the first sign-in."""
    settings = get_settings()
    if not settings.bootstrap_admin_email or len(settings.bootstrap_admin_password) < 12:
        return None
    if email != settings.bootstrap_admin_email.strip().lower() or db.scalar(select(func.count()).select_from(User)):
        return None
    if not hmac.compare_digest(password.encode(), settings.bootstrap_admin_password.encode()):
        return None
    user = User(email=email, password_hash=hash_password(password))
    db.add(user)
    db.flush()
    record_audit(db, "admin_bootstrapped", user=user)
    return user


@router.post("/login", response_model=MeOut)
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    email = body.email.lower()
    ip = client_ip(request)
    if too_many_failures(db, email, ip):
        raise ApiError(429, "too_many_attempts", "Too many failed sign-in attempts. Try again later.")
    user = db.scalar(select(User).where(func.lower(User.email) == email)) or _bootstrap_admin(db, email, body.password)
    valid = verify_password(user.password_hash if user else _DUMMY_HASH, body.password)
    if not user or not valid or not user.is_active:
        record_audit(db, "login_failed", actor=email, ip_address=ip)
        db.commit()
        raise ApiError(401, "invalid_credentials", "Incorrect email or password.")

    token, session = create_session(db, user, ip, request.headers.get("user-agent"))
    user.last_login_at = datetime.now(timezone.utc)
    record_audit(db, "login", user=user, ip_address=ip)
    db.commit()
    _set_cookie(response, token)
    return MeOut(id=user.id, email=user.email, csrf_token=session.csrf_token)


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, ctx: AuthContext = Depends(require_admin), db: Session = Depends(get_db)):
    destroy_session(db, request.cookies.get(get_settings().session_cookie_name))
    record_audit(db, "logout", user=ctx.user, ip_address=ctx.ip)
    db.commit()
    response.delete_cookie(get_settings().session_cookie_name, path="/")
    response.status_code = 204
    return response


@router.get("/me", response_model=MeOut)
def me(ctx: AuthContext = Depends(require_admin)):
    return MeOut(id=ctx.user.id, email=ctx.user.email, csrf_token=ctx.session.csrf_token)


@router.post("/change-password", status_code=204)
def change_password(
    body: ChangePasswordIn,
    response: Response,
    ctx: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = db.get(User, ctx.user.id)
    if not verify_password(user.password_hash, body.current_password):
        raise ApiError(400, "invalid_password", "Current password is incorrect.")
    user.password_hash = hash_password(body.new_password)
    # Sign out every other session.
    for session in db.scalars(select(UserSession).where(UserSession.user_id == user.id)):
        if session.id != ctx.session.id:
            db.delete(session)
    record_audit(db, "password_changed", user=user, ip_address=ctx.ip)
    db.commit()
    response.status_code = 204
    return response
