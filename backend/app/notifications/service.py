"""Reminder generation (idempotent) and delivery (bounded retries)."""

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import DeliveryStatus, Domain, HostingAccount, NotificationEvent, RecordType
from app.notifications.schedule import current_slot, dedupe_key, ineligibility_reason
from app.notifications.mailer import EmailError, send_email
from app.notifications.template import record_label, render_reminder
from app.services.app_settings import get_app_settings, schedule_config
from app.services.expiration import expiration_info, local_today
from app.services.records import reminder_subject
from app.services.redaction import redact_text

log = logging.getLogger(__name__)

STUCK_SENDING_AFTER = timedelta(minutes=30)


def evaluate_reminders(db: Session, now: datetime | None = None) -> list[uuid.UUID]:
    """Create notification events for reminders due today. Safe to run any number of times
    concurrently: the unique dedupe key makes the insert a no-op for existing reminders."""
    settings = get_app_settings(db)
    recipients = [r.strip().lower() for r in settings.notification_recipients or [] if r.strip()]
    if not settings.notifications_enabled or not recipients:
        return []
    now = now or datetime.now(timezone.utc)
    today = local_today(settings.timezone, now)
    config = schedule_config(settings)
    created: list[uuid.UUID] = []

    for model, record_type in ((Domain, RecordType.domain), (HostingAccount, RecordType.hosting)):
        records = db.scalars(
            select(model).where(
                model.deleted_at.is_(None), model.expiration_date.is_not(None), model.notifications_enabled.is_(True)
            )
        )
        for record in records:
            if ineligibility_reason(reminder_subject(record), config) is not None:
                continue
            slot = current_slot(record.expiration_date, today, config)
            if slot is None:
                continue
            _, name = record_label(record)
            for recipient in recipients:
                stmt = (
                    insert(NotificationEvent)
                    .values(
                        id=uuid.uuid4(),
                        dedupe_key=dedupe_key(record_type, str(record.id), record.expiration_date, slot.key, recipient),
                        is_test=False,
                        record_type=record_type,
                        domain_id=record.id if record_type == RecordType.domain else None,
                        hosting_account_id=record.id if record_type == RecordType.hosting else None,
                        record_name=name[:255],
                        expiration_date_at_send=record.expiration_date,
                        reminder_interval=slot.key,
                        recipient=recipient,
                        delivery_status=DeliveryStatus.queued,
                        attempt_count=0,
                        next_attempt_at=now,
                    )
                    .on_conflict_do_nothing(index_elements=["dedupe_key"])
                    .returning(NotificationEvent.id)
                )
                inserted = db.execute(stmt).scalar_one_or_none()
                if inserted is not None:
                    created.append(inserted)
    db.flush()
    return created


def _subject_record(db: Session, event: NotificationEvent) -> Domain | HostingAccount | None:
    if event.domain_id:
        return db.get(Domain, event.domain_id)
    if event.hosting_account_id:
        return db.get(HostingAccount, event.hosting_account_id)
    return None


def _cancel(event: NotificationEvent, reason: str) -> str:
    event.delivery_status = DeliveryStatus.cancelled
    event.last_error = reason
    event.next_attempt_at = None
    return "cancelled"


def deliver_notification(db: Session, event_id: uuid.UUID, now: datetime | None = None) -> str:
    """Deliver one queued reminder. Commits its own state transitions so that an SES call is
    never repeated for an event already marked as sending."""
    now = now or datetime.now(timezone.utc)
    event = db.get(NotificationEvent, event_id, with_for_update={"skip_locked": True})
    if event is None or event.delivery_status != DeliveryStatus.queued or event.is_test:
        db.rollback()
        return "skipped"
    if event.next_attempt_at and event.next_attempt_at > now + timedelta(seconds=5):
        db.rollback()
        return "not_due"

    settings = get_app_settings(db)
    record = _subject_record(db, event)
    if not settings.notifications_enabled:
        status = _cancel(event, "Cancelled: email notifications are disabled.")
        db.commit()
        return status
    if record is None:
        status = _cancel(event, "Cancelled: record no longer exists.")
        db.commit()
        return status
    reason = ineligibility_reason(reminder_subject(record), schedule_config(settings))
    if reason is not None:
        status = _cancel(event, f"Cancelled: record no longer eligible ({reason}).")
        db.commit()
        return status
    if record.expiration_date != event.expiration_date_at_send:
        status = _cancel(event, "Cancelled: expiration date changed before sending.")
        db.commit()
        return status
    if event.recipient not in [r.strip().lower() for r in settings.notification_recipients or []]:
        status = _cancel(event, "Cancelled: recipient was removed from the notification list.")
        db.commit()
        return status

    info = expiration_info(record.expiration_date, local_today(settings.timezone, now))
    email = render_reminder(record, info, get_settings().app_base_url)
    email.to = event.recipient
    event.subject = email.subject[:512]
    event.delivery_status = DeliveryStatus.sending
    event.attempt_count += 1
    event.last_attempt_at = now
    db.commit()

    max_attempts = get_settings().email_max_attempts
    try:
        message_id = send_email(db, settings, email)
    except EmailError as exc:
        event = db.get(NotificationEvent, event_id)
        event.last_error = redact_text(exc.message, 500)
        if exc.transient and event.attempt_count < max_attempts:
            delay = get_settings().email_backoff_base_seconds * (2 ** (event.attempt_count - 1))
            event.delivery_status = DeliveryStatus.queued
            event.next_attempt_at = now + timedelta(seconds=delay)
            outcome = "retry"
        else:
            event.delivery_status = DeliveryStatus.failed
            event.next_attempt_at = None
            outcome = "failed"
        db.commit()
        log.warning("Reminder delivery %s: %s", outcome, event.last_error, extra={"event": str(event_id)})
        return outcome

    event = db.get(NotificationEvent, event_id)
    event.delivery_status = DeliveryStatus.sent
    event.provider_message_id = message_id[:255] or None
    event.sent_at = datetime.now(timezone.utc)
    event.last_error = None
    event.next_attempt_at = None
    db.commit()
    return "sent"


def due_event_ids(db: Session, now: datetime | None = None, limit: int = 200) -> list[uuid.UUID]:
    now = now or datetime.now(timezone.utc)
    return list(
        db.scalars(
            select(NotificationEvent.id)
            .where(
                NotificationEvent.delivery_status == DeliveryStatus.queued,
                NotificationEvent.is_test.is_(False),
                or_(NotificationEvent.next_attempt_at.is_(None), NotificationEvent.next_attempt_at <= now),
            )
            .order_by(NotificationEvent.created_at)
            .limit(limit)
        )
    )


def fail_stuck_sending(db: Session, now: datetime | None = None) -> int:
    """Events left in 'sending' (worker crashed mid-call) are failed, not resent: SES may already
    have accepted them and resending could duplicate the reminder."""
    now = now or datetime.now(timezone.utc)
    result = db.execute(
        update(NotificationEvent)
        .where(
            NotificationEvent.delivery_status == DeliveryStatus.sending,
            NotificationEvent.last_attempt_at < now - STUCK_SENDING_AFTER,
        )
        .values(
            delivery_status=DeliveryStatus.failed,
            last_error="Delivery outcome unknown (worker interrupted); not retried to avoid a duplicate.",
        )
    )
    return result.rowcount or 0
