"""Resend (resend.com) email API client with the same error classification as SES."""

import httpx
from sqlalchemy.orm import Session

from app.models import ApplicationSettings
from app.notifications.ses import OutgoingEmail, SesError, SesNotConfigured
from app.services.redaction import redact_text
from app.services.secrets import RESEND_CREDENTIALS, SecretStoreError, get_secret

API_BASE = "https://api.resend.com"
TIMEOUT = httpx.Timeout(20.0, connect=10.0)


def _api_key(db: Session) -> str:
    try:
        creds = get_secret(db, RESEND_CREDENTIALS)
    except SecretStoreError as exc:
        raise SesNotConfigured(str(exc)) from None
    if not creds or not creds.get("api_key"):
        raise SesNotConfigured("Enter a Resend API key.")
    return creds["api_key"]


def _request(method: str, path: str, api_key: str, **kwargs) -> httpx.Response:
    try:
        return httpx.request(method, f"{API_BASE}{path}", timeout=TIMEOUT,
                             headers={"Authorization": f"Bearer {api_key}", "User-Agent": "domain-hosting-monitor"},
                             **kwargs)
    except httpx.TimeoutException:
        raise SesError("Resend did not respond in time.", transient=True, code="timeout") from None
    except httpx.HTTPError as exc:
        raise SesError(redact_text(f"Could not reach Resend: {type(exc).__name__}", 500), transient=True,
                       code="connection_error") from None


def _error(response: httpx.Response) -> SesError:
    try:
        body = response.json()
    except ValueError:
        body = {}
    name = body.get("name") or f"http_{response.status_code}"
    message = body.get("message") or response.reason_phrase or "Request failed"
    transient = response.status_code == 429 or response.status_code >= 500
    return SesError(redact_text(f"{name}: {message}", 500), transient=transient, code=name)


def send_email(db: Session, settings: ApplicationSettings, email: OutgoingEmail) -> str:
    """Submit an email to Resend. Returns the Resend email id (acceptance, not proof of delivery)."""
    if not settings.resend_sender:
        raise SesNotConfigured("Set a sender address on a domain verified in Resend.")
    api_key = _api_key(db)
    response = _request("POST", "/emails", api_key, json={
        "from": settings.resend_sender,
        "to": [email.to],
        "subject": email.subject,
        "text": email.text,
        "html": email.html,
    })
    if response.status_code >= 300:
        raise _error(response)
    return str(response.json().get("id", ""))


def validate_configuration(db: Session, settings: ApplicationSettings) -> dict:
    """Check the API key and whether the sender's domain is verified in Resend. Never raises."""
    checks: dict = {
        "provider": "resend",
        "sender": settings.resend_sender,
        "credentials": None,
        "sender_verified": None,
        "problems": [],
    }
    try:
        api_key = _api_key(db)
        response = _request("GET", "/domains", api_key)
        if response.status_code in (401, 403):
            err = _error(response)
            if err.code == "restricted_api_key":
                # A "sending access" key works for sending but cannot list domains.
                checks["credentials"] = True
            else:
                checks["credentials"] = False
                checks["problems"].append(err.message)
        elif response.status_code >= 300:
            checks["problems"].append(_error(response).message)
        else:
            checks["credentials"] = True
            if settings.resend_sender:
                domain = settings.resend_sender.rsplit("@", 1)[-1].strip(">").lower()
                domains = response.json().get("data") or []
                checks["sender_verified"] = any(
                    (d.get("name") or "").lower() == domain and d.get("status") == "verified" for d in domains
                )
                if not checks["sender_verified"]:
                    checks["problems"].append(f"The sender's domain ({domain}) is not verified in Resend.")
        if not settings.resend_sender:
            checks["problems"].append("No sender address is configured.")
    except SesError as exc:
        if exc.code == "not_configured":
            checks["credentials"] = False
        checks["problems"].append(exc.message)
    return checks
