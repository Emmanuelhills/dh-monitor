"""Business rules shared by domains and hosting accounts.

Key rules (see Technical Specification §4):
* Usage status is never derived from expiration or service status.
* Moving an expiration date forward is treated as a confirmed renewal of the old period.
* Marking a record "renewed" without a new date stops reminders for the current date.
* Any change of expiration date or renewal state cancels queued reminders that no longer apply.
"""

from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import (
    ApplicationSettings,
    DataSource,
    DeliveryStatus,
    Domain,
    HostingAccount,
    MonitoringStatus,
    NotificationEvent,
    RecordType,
    RenewalStatus,
)
from app.notifications.schedule import ReminderSubject, ineligibility_reason
from app.services.app_settings import schedule_config
from app.services.audit import jsonable
from app.services.domain_names import display_domain_name
from app.services.expiration import expiration_info

MonitoredRecord = Domain | HostingAccount


def record_type_of(record: MonitoredRecord) -> RecordType:
    return RecordType.domain if isinstance(record, Domain) else RecordType.hosting


def supports_auto_check(record: MonitoredRecord) -> bool:
    if isinstance(record, HostingAccount):
        return record.integration_id is not None
    return True


def refresh_monitoring_mode(record: MonitoredRecord, now: datetime) -> None:
    """Keep monitoring_status/next_check_at consistent with auto-check settings."""
    if not record.auto_check_enabled or not supports_auto_check(record):
        record.monitoring_status = MonitoringStatus.manual
        record.next_check_at = None
    elif record.monitoring_status == MonitoringStatus.manual or record.next_check_at is None:
        record.monitoring_status = MonitoringStatus.due
        record.next_check_at = now


def apply_record_update(record: MonitoredRecord, updates: dict[str, Any]) -> dict[str, dict]:
    """Apply a manual (administrator) update. Returns before/after differences."""
    now = datetime.now(timezone.utc)
    changes: dict[str, dict] = {}

    def _set(field: str, value: Any) -> None:
        old = getattr(record, field)
        if old != value:
            changes[field] = {"from": jsonable(old), "to": jsonable(value)}
            setattr(record, field, value)

    old_expiration = record.expiration_date
    date_moved_forward = False
    if "expiration_date" in updates and updates["expiration_date"] != old_expiration:
        new_expiration = updates["expiration_date"]
        _set("expiration_date", new_expiration)
        _set("expiration_source", DataSource.manual)
        _set("expiration_verified_at", None)
        date_moved_forward = bool(old_expiration and new_expiration and new_expiration > old_expiration)
        if date_moved_forward and "renewal_status" not in updates:
            _set("renewal_status", RenewalStatus.renewed)
            _set("renewal_confirmed_for_date", old_expiration)
        elif "renewal_status" not in updates and record.renewal_status != RenewalStatus.unknown:
            # A corrected (not extended) date resets what we know about its renewal.
            _set("renewal_status", RenewalStatus.unknown)
            _set("renewal_confirmed_for_date", None)

    if "renewal_status" in updates:
        status = updates["renewal_status"]
        _set("renewal_status", status)
        if status == RenewalStatus.renewed:
            _set("renewal_confirmed_for_date", old_expiration if date_moved_forward else record.expiration_date)
        elif status == RenewalStatus.not_renewed:
            _set("renewal_confirmed_for_date", record.expiration_date)
        else:
            _set("renewal_confirmed_for_date", None)

    if "service_status" in updates:
        _set("service_status", updates["service_status"])
        if "service_status" in changes:
            _set("service_status_source", DataSource.manual)

    special = {"expiration_date", "renewal_status", "service_status"}
    for field, value in updates.items():
        if field not in special:
            _set(field, value)

    refresh_monitoring_mode(record, now)
    return changes


def reminder_subject(record: MonitoredRecord) -> ReminderSubject:
    return ReminderSubject(
        expiration_date=record.expiration_date,
        service_status=record.service_status,
        renewal_status=record.renewal_status,
        renewal_confirmed_for_date=record.renewal_confirmed_for_date,
        notifications_enabled=record.notifications_enabled,
        archived=record.deleted_at is not None,
    )


def cancel_obsolete_notifications(db: Session, record: MonitoredRecord, settings: ApplicationSettings) -> int:
    """Cancel queued reminders whose expiration date changed or whose record became ineligible."""
    fk = NotificationEvent.domain_id if isinstance(record, Domain) else NotificationEvent.hosting_account_id
    reason = ineligibility_reason(reminder_subject(record), schedule_config(settings))
    stmt = update(NotificationEvent).where(
        fk == record.id, NotificationEvent.delivery_status == DeliveryStatus.queued
    )
    if reason is None:
        stmt = stmt.where(NotificationEvent.expiration_date_at_send != record.expiration_date)
        message = "Cancelled: expiration date changed before sending."
    else:
        message = f"Cancelled: record no longer eligible ({reason})."
    result = db.execute(
        stmt.values(delivery_status=DeliveryStatus.cancelled, last_error=message, next_attempt_at=None)
    )
    return result.rowcount or 0


def is_stale(record: MonitoredRecord, now: datetime, stale_after_hours: int) -> bool:
    if record.monitoring_status == MonitoringStatus.manual or not record.auto_check_enabled:
        return False
    reference = record.last_successful_check_at or record.created_at
    return reference is not None and reference < now - timedelta(hours=stale_after_hours)


def _base_out(record: MonitoredRecord, today: date, now: datetime, settings: ApplicationSettings) -> dict:
    return {
        "id": record.id,
        "expiration_date": record.expiration_date,
        "expiration_source": record.expiration_source,
        "expiration_verified_at": record.expiration_verified_at,
        "expiration": expiration_info(record.expiration_date, today).as_dict(),
        "usage_status": record.usage_status,
        "service_status": record.service_status,
        "service_status_source": record.service_status_source,
        "renewal_status": record.renewal_status,
        "renewal_confirmed_for_date": record.renewal_confirmed_for_date,
        "auto_check_enabled": record.auto_check_enabled,
        "notifications_enabled": record.notifications_enabled,
        "monitoring_status": record.monitoring_status,
        "last_checked_at": record.last_checked_at,
        "last_successful_check_at": record.last_successful_check_at,
        "next_check_at": record.next_check_at,
        "check_requested_at": record.check_requested_at,
        "last_check_error": record.last_check_error,
        "is_stale": is_stale(record, now, settings.stale_after_hours),
        "notes": record.notes,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "archived_at": record.deleted_at,
    }


def domain_out(domain: Domain, today: date, now: datetime, settings: ApplicationSettings) -> dict:
    hosting = domain.hosting_account
    return {
        **_base_out(domain, today, now, settings),
        "domain_name": domain.domain_name,
        "normalized_domain_name": domain.normalized_domain_name,
        "display_name": display_domain_name(domain.normalized_domain_name),
        "hosting_account": (
            {"id": hosting.id, "name": hosting.name, "provider_name": hosting.provider_name}
            if hosting is not None
            else None
        ),
        "registrar": (
            {"id": domain.registrar.id, "name": domain.registrar.name} if domain.registrar is not None else None
        ),
        "registration_date": domain.registration_date,
        "registrar_name": domain.registrar_name,
        "registry_statuses": domain.registry_statuses or [],
    }


def hosting_out(
    hosting: HostingAccount, today: date, now: datetime, settings: ApplicationSettings, domain_count: int
) -> dict:
    integration = hosting.integration
    return {
        **_base_out(hosting, today, now, settings),
        "name": hosting.name,
        "provider_name": hosting.provider_name,
        "registrar": (
            {"id": hosting.registrar.id, "name": hosting.registrar.name} if hosting.registrar is not None else None
        ),
        "purchase_date": hosting.purchase_date,
        "has_admin_url": bool(hosting.admin_url),
        "integration": (
            {"id": integration.id, "name": integration.name, "adapter": integration.adapter}
            if integration is not None
            else None
        ),
        "external_ref": hosting.external_ref,
        "domain_count": domain_count,
    }


def active_domains_for_hosting(db: Session, hosting_id) -> list[Domain]:
    return list(
        db.scalars(
            select(Domain)
            .where(Domain.hosting_account_id == hosting_id, Domain.deleted_at.is_(None))
            .order_by(Domain.normalized_domain_name)
        )
    )
