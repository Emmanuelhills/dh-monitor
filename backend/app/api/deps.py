from dataclasses import dataclass

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.api.errors import ApiError
from app.config import get_settings
from app.db import get_db
from app.models import User, UserSession
from app.services.auth import resolve_session

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
CSRF_HEADER = "X-CSRF-Token"


@dataclass
class AuthContext:
    user: User
    session: UserSession
    ip: str | None


def client_ip(request: Request) -> str | None:
    if get_settings().trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()[:64]
        real = request.headers.get("x-real-ip")
        if real:
            return real.strip()[:64]
    return request.client.host if request.client else None


def require_admin(request: Request, db: Session = Depends(get_db)) -> AuthContext:
    """Authenticate the session cookie and enforce CSRF on state-changing requests."""
    token = request.cookies.get(get_settings().session_cookie_name)
    session = resolve_session(db, token)
    if session is None:
        raise ApiError(401, "not_authenticated", "Sign in to continue.")
    if request.method not in SAFE_METHODS:
        sent = request.headers.get(CSRF_HEADER)
        if not sent or sent != session.csrf_token:
            raise ApiError(403, "csrf_failed", "Missing or invalid CSRF token.")
    return AuthContext(user=session.user, session=session, ip=client_ip(request))
