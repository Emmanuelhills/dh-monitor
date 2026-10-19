"""Daily expiration evaluation: overdue verification and renewal-state upkeep.

A passed date alone never marks a record expired. It requests verification instead.
"""

from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DataSource, Domain, HostingAccount, RenewalStatus, ServiceStatus
from app.services.app_settings import get_app_settings
from app.services.audit import record_audit
from app.services.expiration import local_today
from app.services.records import cancel_obsolete_notifications, supports_auto_check


def evaluate_expirations(db: Session, now: datetime | None = None) -> dict:
    settings = get_app_settings(db)
    now = now or datetime.now(timezone.utc)
    today = local_today(settings.timezone, now)
    start_of_today = datetime.combine(today, time.min, tzinfo=ZoneInfo(settings.timezone))
    summary = {"verification_requested": 0, "renewal_reset": 0, "marked_expired": 0}

    for model in (Domain, HostingAccount):
        records = db.scalars(
            select(model)
            .where(model.deleted_at.is_(None), model.expiration_date.is_not(None), model.expiration_date <= today)
            .with_for_update(skip_locked=True)
        )
        for record in records:
            # The renewed period itself has now lapsed: renewal of the *current* date is unknown.
            if (
                record.renewal_status == RenewalStatus.renewed
                and record.renewal_confirmed_for_date != record.expiration_date
            ):
                record.renewal_status = RenewalStatus.unknown
                record.renewal_confirmed_for_date = None
                summary["renewal_reset"] += 1

            overdue = record.expiration_date < today

            # Non-renewal confirmed by the administrator + date passed = established expiry.
            if (
                overdue
                and record.renewal_status == RenewalStatus.not_renewed
                and record.service_status != ServiceStatus.expired
            ):
                previous = record.service_status
                record.service_status = ServiceStatus.expired
                record.service_status_source = DataSource.manual
                record_audit(
                    db,
                    "status_auto_expired",
                    record_type="domain" if model is Domain else "hosting",
                    record_id=record.id,
                    details={"service_status": {"from": previous.value, "to": "expired"},
                             "reason": "Non-renewal confirmed and expiration date passed."},
                )
                cancel_obsolete_notifications(db, record, settings)
                summary["marked_expired"] += 1
                continue

            # Overdue with unknown outcome: ask the monitor to verify (at most once a day).
            if (
                overdue
                and record.renewal_status == RenewalStatus.unknown
                and record.auto_check_enabled
                and supports_auto_check(record)
                and (record.last_checked_at is None or record.last_checked_at < start_of_today)
                and (record.next_check_at is None or record.next_check_at > now)
            ):
                record.next_check_at = now
                summary["verification_requested"] += 1
    db.flush()
    return summary
