"""Scheduled-job trigger for serverless hosting (Vercel Cron / GitHub Actions schedule)."""

import hmac

from fastapi import APIRouter, Request

from app.api.errors import ApiError
from app.config import get_settings
from app.services.cron import run_scheduled_jobs

router = APIRouter(prefix="/cron", tags=["cron"])


def _authorize(request: Request) -> None:
    secret = get_settings().cron_secret
    if not secret:
        raise ApiError(503, "cron_not_configured", "Set CRON_SECRET to enable scheduled jobs.")
    sent = request.headers.get("authorization", "")
    if not hmac.compare_digest(sent.encode(), f"Bearer {secret}".encode()):
        raise ApiError(401, "not_authenticated", "Invalid cron secret.")


@router.get("/run")
@router.post("/run")
def run(request: Request):
    """Run due checks, expiration evaluation, reminders and deliveries once."""
    _authorize(request)
    return {"ok": True, "summary": run_scheduled_jobs(get_settings().cron_time_budget_seconds)}
