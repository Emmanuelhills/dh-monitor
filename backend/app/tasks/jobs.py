"""Celery tasks. Business logic lives in app.monitoring / app.notifications / app.services;
these wrappers add transactions, fan-out and job heartbeats."""

import logging
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert

from app.celery_app import celery
from app.db import SessionLocal, session_scope
from app.models import Domain, HostingAccount, JobRun, MonitoringStatus, RecordType
from app.monitoring.checker import run_check
from app.notifications.service import deliver_notification, due_event_ids, evaluate_reminders, fail_stuck_sending
from app.services.lifecycle import evaluate_expirations
from app.services.redaction import redact_text

log = logging.getLogger(__name__)

DISPATCH_BATCH = 200


@contextmanager
def job_heartbeat(name: str):
    started = datetime.now(timezone.utc)
    summary: dict = {}
    with session_scope() as db:
        db.execute(
            insert(JobRun)
            .values(name=name, last_started_at=started, last_status="running", last_summary={})
            .on_conflict_do_update(index_elements=["name"], set_={"last_started_at": started, "last_status": "running"})
        )
    try:
        yield summary
    except Exception as exc:
        with session_scope() as db:
            row = db.get(JobRun, name)
            row.last_finished_at = datetime.now(timezone.utc)
            row.last_status = "failed"
            row.last_error = redact_text(f"{type(exc).__name__}: {exc}", 1000)
        raise
    with session_scope() as db:
        row = db.get(JobRun, name)
        row.last_finished_at = datetime.now(timezone.utc)
        row.last_status = "ok"
        row.last_error = None
        row.last_summary = summary


@celery.task(name="dhm.check_record", acks_late=True)
def check_record(record_type: str, record_id: str) -> str | None:
    with session_scope() as db:
        check = run_check(db, RecordType(record_type), uuid.UUID(record_id))
        return check.result.value if check else None


@celery.task(name="dhm.dispatch_due_checks")
def dispatch_due_checks() -> dict:
    """Queue checks for records whose next_check_at has passed. next_check_at is pushed forward
    in the same transaction so overlapping dispatchers do not queue a record twice."""
    with job_heartbeat("dispatch_due_checks") as summary:
        now = datetime.now(timezone.utc)
        queued: list[tuple[str, str]] = []
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
                rows = db.scalars(
                    select(model).where(*conditions).order_by(model.next_check_at).limit(DISPATCH_BATCH)
                    .with_for_update(skip_locked=True)
                )
                for record in rows:
                    # Lease: if the queued task is lost, the record becomes due again in an hour.
                    # A completed check replaces this with the real next check time.
                    record.next_check_at = now + timedelta(hours=1)
                    if record.monitoring_status not in (MonitoringStatus.failed, MonitoringStatus.partial):
                        record.monitoring_status = MonitoringStatus.due
                    queued.append((record_type.value, str(record.id)))
        for record_type, record_id in queued:
            check_record.delay(record_type, record_id)
        summary["queued"] = len(queued)
        return summary


@celery.task(name="dhm.evaluate_expirations")
def evaluate_expirations_task() -> dict:
    with job_heartbeat("evaluate_expirations") as summary:
        with session_scope() as db:
            summary.update(evaluate_expirations(db))
        return summary


@celery.task(name="dhm.evaluate_reminders")
def evaluate_reminders_task() -> dict:
    with job_heartbeat("evaluate_reminders") as summary:
        with session_scope() as db:
            created = evaluate_reminders(db)
        for event_id in created:
            deliver_notification_task.delay(str(event_id))
        summary["created"] = len(created)
        return summary


@celery.task(name="dhm.deliver_notification")
def deliver_notification_task(event_id: str) -> str:
    db = SessionLocal()
    try:
        return deliver_notification(db, uuid.UUID(event_id))
    finally:
        db.close()


@celery.task(name="dhm.dispatch_notifications")
def dispatch_notifications() -> dict:
    """Retry sweeper: picks up queued reminders whose retry time has arrived (and any whose
    original task was lost)."""
    with job_heartbeat("dispatch_notifications") as summary:
        with session_scope() as db:
            summary["stuck_failed"] = fail_stuck_sending(db)
            ids = due_event_ids(db)
        for event_id in ids:
            deliver_notification_task.delay(str(event_id))
        summary["dispatched"] = len(ids)
        return summary
