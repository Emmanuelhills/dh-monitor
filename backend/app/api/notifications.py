import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.common import Pagination, count_of, get_pagination
from app.api.deps import AuthContext, require_admin
from app.api.errors import ApiError, not_found
from app.config import get_settings
from app.db import get_db
from app.models import DeliveryStatus, NotificationEvent, RecordType, SesAuthMethod
from app.notifications.mailer import EmailError, provider_label, send_email, sender_of, validate_configuration
from app.notifications.template import render_test_email
from app.schemas import (
    NotificationOut,
    NotificationSettingsIn,
    NotificationSettingsOut,
    Page,
    TestEmailIn,
    TestEmailOut,
)
from app.services.app_settings import get_app_settings
from app.services.audit import diff_fields, record_audit
from app.services.secrets import (
    RESEND_CREDENTIALS,
    SES_CREDENTIALS,
    SecretStoreError,
    delete_secret,
    has_secret,
    put_secret,
)

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _settings_out(db: Session) -> dict:
    s = get_app_settings(db)
    return {
        "notifications_enabled": s.notifications_enabled,
        "notification_recipients": s.notification_recipients or [],
        "reminder_days_before": s.reminder_days_before or [],
        "remind_on_expiration_day": s.remind_on_expiration_day,
        "overdue_reminder_days": s.overdue_reminder_days,
        "remind_suspended": s.remind_suspended,
        "email_provider": s.email_provider or "ses",
        "resend_sender": s.resend_sender,
        "resend_api_key_set": has_secret(db, RESEND_CREDENTIALS),
        "ses_region": s.ses_region,
        "ses_sender": s.ses_sender,
        "ses_configuration_set": s.ses_configuration_set,
        "ses_auth_method": s.ses_auth_method,
        "ses_credentials_set": has_secret(db, SES_CREDENTIALS),
        "ses_last_validated_at": s.ses_last_validated_at,
        "ses_last_validation": s.ses_last_validation or {},
    }


@router.get("", response_model=Page[NotificationOut])
def list_notifications(
    delivery_status: DeliveryStatus | None = None,
    record_type: RecordType | None = None,
    record_id: uuid.UUID | None = None,
    include_tests: bool = True,
    pagination: Pagination = Depends(get_pagination),
    _: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
):
    stmt = select(NotificationEvent)
    if delivery_status:
        stmt = stmt.where(NotificationEvent.delivery_status == delivery_status)
    if record_type:
        stmt = stmt.where(NotificationEvent.record_type == record_type)
    if record_id:
        stmt = stmt.where((NotificationEvent.domain_id == record_id) | (NotificationEvent.hosting_account_id == record_id))
    if not include_tests:
        stmt = stmt.where(NotificationEvent.is_test.is_(False))
    total = count_of(db, stmt)
    items = db.scalars(
        stmt.order_by(NotificationEvent.created_at.desc(), NotificationEvent.id)
        .offset(pagination.offset).limit(pagination.page_size)
    ).all()
    return {"items": items, "total": total, "page": pagination.page, "page_size": pagination.page_size}


@router.get("/settings", response_model=NotificationSettingsOut)
def get_notification_settings(_: AuthContext = Depends(require_admin), db: Session = Depends(get_db)):
    return _settings_out(db)


@router.patch("/settings", response_model=NotificationSettingsOut)
def update_notification_settings(
    body: NotificationSettingsIn, ctx: AuthContext = Depends(require_admin), db: Session = Depends(get_db)
):
    settings = get_app_settings(db)
    data = body.model_dump(exclude_unset=True, exclude={"ses_credentials", "clear_ses_credentials",
                                                              "resend_api_key", "clear_resend_api_key"})
    for field in ("notifications_enabled", "reminder_days_before", "remind_on_expiration_day",
                  "overdue_reminder_days", "remind_suspended", "ses_auth_method", "notification_recipients",
                  "email_provider"):
        if field in data and data[field] is None:
            raise ApiError(422, "validation_error", f"{field} cannot be null.")
    if "notification_recipients" in data:
        data["notification_recipients"] = sorted({str(r).strip().lower() for r in data["notification_recipients"]})
    if "ses_sender" in data and data["ses_sender"]:
        data["ses_sender"] = str(data["ses_sender"]).strip()
    if "resend_sender" in data and data["resend_sender"]:
        data["resend_sender"] = str(data["resend_sender"]).strip()
    if "ses_configuration_set" in data:
        data["ses_configuration_set"] = (data["ses_configuration_set"] or "").strip() or None

    changes = diff_fields(settings, data)
    for field, value in data.items():
        setattr(settings, field, value)

    try:
        if body.clear_ses_credentials:
            delete_secret(db, SES_CREDENTIALS)
            changes["ses_credentials"] = {"from": "[set]", "to": "[cleared]"}
        elif body.ses_credentials is not None:
            put_secret(db, SES_CREDENTIALS, body.ses_credentials.model_dump())
            changes["ses_credentials"] = {"from": "[hidden]", "to": "[updated]"}
        if body.clear_resend_api_key:
            delete_secret(db, RESEND_CREDENTIALS)
            changes["resend_api_key"] = {"from": "[set]", "to": "[cleared]"}
        elif body.resend_api_key is not None:
            put_secret(db, RESEND_CREDENTIALS, {"api_key": body.resend_api_key.strip()})
            changes["resend_api_key"] = {"from": "[hidden]", "to": "[updated]"}
    except SecretStoreError as exc:
        raise ApiError(500, "secret_store_unavailable", str(exc)) from None

    if settings.ses_auth_method == SesAuthMethod.access_keys and not has_secret(db, SES_CREDENTIALS) \
            and body.ses_credentials is None:
        db.rollback()
        raise ApiError(422, "credentials_required", "Enter AWS access keys or choose the IAM role / default credential chain.")
    if settings.email_provider == "resend" and not has_secret(db, RESEND_CREDENTIALS) and body.resend_api_key is None:
        db.rollback()
        raise ApiError(422, "credentials_required", "Enter a Resend API key to send with Resend.",
                       [{"field": "resend_api_key", "message": "Enter a Resend API key."}])
    if changes:
        record_audit(db, "notification_settings_updated", user=ctx.user, details={"changes": changes}, ip_address=ctx.ip)
    db.commit()
    return _settings_out(db)


@router.post("/validate", response_model=TestEmailOut)
def validate_ses(ctx: AuthContext = Depends(require_admin), db: Session = Depends(get_db)):
    """Check the selected provider's credentials and sender verification without sending."""
    settings = get_app_settings(db)
    checks = validate_configuration(db, settings)
    settings.ses_last_validated_at = datetime.now(timezone.utc)
    settings.ses_last_validation = checks
    record_audit(db, "ses_validated", user=ctx.user, details={"problems": checks["problems"]}, ip_address=ctx.ip)
    db.commit()
    ok = checks["credentials"] is True and not [p for p in checks["problems"] if "sandbox" not in p]
    return {
        "ok": ok,
        "accepted": False,
        "message": "Configuration looks good." if ok else "Configuration has problems.",
        "checks": checks,
    }


@router.post("/test", response_model=TestEmailOut)
def send_test_email(body: TestEmailIn, ctx: AuthContext = Depends(require_admin), db: Session = Depends(get_db)):
    """Validate the configuration and ask the selected provider to accept a test message. Acceptance is
    reported; inbox delivery cannot be confirmed by this call."""
    settings = get_app_settings(db)
    recipient = (str(body.recipient) if body.recipient else None) or next(iter(settings.notification_recipients or []), None)
    if not recipient:
        raise ApiError(422, "no_recipient", "Enter a test recipient or add a notification recipient first.")
    checks = validate_configuration(db, settings)
    settings.ses_last_validated_at = datetime.now(timezone.utc)
    settings.ses_last_validation = checks

    now = datetime.now(timezone.utc)
    event = NotificationEvent(
        id=uuid.uuid4(), dedupe_key=f"test|{uuid.uuid4()}", is_test=True, reminder_interval="test",
        recipient=recipient.lower(), delivery_status=DeliveryStatus.sending, attempt_count=1, last_attempt_at=now,
    )
    email = render_test_email(sender_of(settings) or "", provider_label(settings))
    email.to = recipient
    event.subject = email.subject
    db.add(event)
    db.flush()
    try:
        message_id = send_email(db, settings, email)
    except EmailError as exc:
        event.delivery_status = DeliveryStatus.failed
        event.last_error = exc.message
        record_audit(db, "ses_test_failed", user=ctx.user, details={"recipient": recipient, "error": exc.message},
                     ip_address=ctx.ip)
        db.commit()
        return {"ok": False, "accepted": False, "message": exc.message, "checks": checks}
    event.delivery_status = DeliveryStatus.sent
    event.provider_message_id = message_id or None
    event.sent_at = datetime.now(timezone.utc)
    record_audit(db, "ses_test_sent", user=ctx.user, details={"recipient": recipient}, ip_address=ctx.ip)
    db.commit()
    return {
        "ok": True,
        "accepted": True,
        "message": f"{provider_label(settings)} accepted the test message for {recipient}. Check the inbox to confirm delivery.",
        "checks": checks,
        "provider_message_id": message_id or None,
    }


@router.get("/{event_id}", response_model=NotificationOut)
def get_notification(event_id: uuid.UUID, _: AuthContext = Depends(require_admin), db: Session = Depends(get_db)):
    event = db.get(NotificationEvent, event_id)
    if event is None:
        raise not_found("Notification")
    return event


@router.post("/{event_id}/retry", response_model=NotificationOut)
def retry_notification(event_id: uuid.UUID, ctx: AuthContext = Depends(require_admin), db: Session = Depends(get_db)):
    """Re-queue a failed reminder after the administrator fixed the cause."""
    event = db.get(NotificationEvent, event_id)
    if event is None:
        raise not_found("Notification")
    if event.is_test or event.delivery_status != DeliveryStatus.failed:
        raise ApiError(409, "not_retryable", "Only failed reminders can be retried.")
    event.delivery_status = DeliveryStatus.queued
    event.next_attempt_at = datetime.now(timezone.utc)
    record_audit(db, "notification_retry", user=ctx.user, details={"notification_id": str(event.id)}, ip_address=ctx.ip)
    db.commit()
    if get_settings().task_mode == "inline":
        from app.notifications.service import deliver_notification

        deliver_notification(db, event.id)
    else:
        from app.tasks.jobs import deliver_notification_task

        try:
            deliver_notification_task.delay(str(event.id))
        except Exception:  # broker down: the retry sweeper picks it up
            pass
    db.refresh(event)
    return event

