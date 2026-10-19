"""Run every scheduled job inline, within a time budget (serverless hosting, no Celery worker).

Called by /api/v1/cron/run from Vercel Cron and/or the GitHub Actions schedule. Every job is
idempotent, so overlapping or repeated calls are harmless; work left over when the budget runs
out is picked up by the next call.
"""

import time
import uuid
from datetime import datetime, timezone

from sqlalchemy import or_, select

from app.db import SessionLocal, session_scope
from app.models import Domain, HostingAccount, RecordType
from app.monitoring.checker import run_check
from app.notifications.service import deliver_notification, due_event_ids, evaluate_reminders, fail_stuck_sending
from app.services.lifecycle import evaluate_expirations
from app.tasks.jobs import job_heartbeat

# Stop starting new lookups when less than this is left (one lookup can take ~15 s).
LOOKUP_RESERVE_SECONDS = 16
MAX_CHECKS_PER_RUN = 200


def _due_records(now: datetime) -> list[tuple[RecordType, uuid.UUID]]:
    refs: list[tuple[RecordType, uuid.UUID]] = []
    with session_scope() as db:
        for model, record_type in ((Domain, RecordType.domain), (HostingAccount, RecordType.hosting)):
            conditions = [
                model.deleted_at.is_(None),
                model.next_check_at.is_not(None),
                model.next_check_at <= now,
                or_(model.auto_check_enabled.is_(True), model.check_requested_at.is_not(None)),
            ]
            if model is HostingAccount:
                conditions.append(HostingAccount.integration_id.is_not(None))
            ids = db.scalars(select(model.id).where(*conditions).order_by(model.next_check_at).limit(MAX_CHECKS_PER_RUN))
            refs.extend((record_type, i) for i in ids)
    return refs


def run_scheduled_jobs(budget_seconds: int) -> dict:
    deadline = time.monotonic() + budget_seconds

    def left() -> float:
        return deadline - time.monotonic()

    summary: dict = {}

    with job_heartbeat("evaluate_expirations") as s:
        with session_scope() as db:
            s.update(evaluate_expirations(db))
        summary["expirations"] = s

    with job_heartbeat("evaluate_reminders") as s:
        with session_scope() as db:
            created = evaluate_reminders(db)
        s["created"] = len(created)
        summary["reminders"] = s

    with job_heartbeat("dispatch_notifications") as s:
        with session_scope() as db:
            s["stuck_failed"] = fail_stuck_sending(db)
            pending = due_event_ids(db)
        outcomes: dict[str, int] = {}
        for event_id in pending:
            if left() < 5:
                break
            db = SessionLocal()
            try:
                outcome = deliver_notification(db, event_id)
            finally:
                db.close()
            outcomes[outcome] = outcomes.get(outcome, 0) + 1
        s["deliveries"] = outcomes
        summary["notifications"] = s

    with job_heartbeat("dispatch_due_checks") as s:
        due = _due_records(datetime.now(timezone.utc))
        done = 0
        for record_type, record_id in due:
            if left() < LOOKUP_RESERVE_SECONDS:
                break
            with session_scope() as db:
                run_check(db, record_type, record_id)
            done += 1
        s.update({"due": len(due), "checked": done, "remaining": len(due) - done})
        summary["checks"] = s

    summary["seconds_used"] = round(budget_seconds - left(), 1)
    return summary

