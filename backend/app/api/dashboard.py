from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import and_, case, func, select
from sqlalchemy.orm import Session, joinedload

from app.api.common import Clock, get_clock
from app.api.deps import AuthContext, require_admin
from app.db import get_db
from app.models import (
    DeliveryStatus,
    Domain,
    HostingAccount,
    JobRun,
    MonitoringStatus,
    NotificationEvent,
    ServiceStatus,
    UsageStatus,
)
from app.services.expiration import expiration_info

router = APIRouter(tags=["dashboard"])

UPCOMING_DAYS = 30
UPCOMING_LIMIT = 15


def _summary(db: Session, model, clock: Clock) -> dict:
    stale_before = clock.now - timedelta(hours=clock.settings.stale_after_hours)
    stale_condition = and_(
        model.auto_check_enabled.is_(True),
        model.monitoring_status != MonitoringStatus.manual,
        func.coalesce(model.last_successful_check_at, model.created_at) < stale_before,
    )

    def _count(condition):
        return func.count(case((condition, 1)))

    row = db.execute(
        select(
            func.count(),
            _count(model.usage_status == UsageStatus.active),
            _count(model.usage_status == UsageStatus.inactive),
            _count(model.service_status == ServiceStatus.expired),
            _count(model.service_status == ServiceStatus.suspended),
            _count(model.expiration_date.is_(None)),
            _count(and_(model.expiration_date < clock.today, model.service_status != ServiceStatus.expired)),
            _count(model.expiration_date.between(clock.today, clock.today + timedelta(days=UPCOMING_DAYS))),
            _count(model.monitoring_status == MonitoringStatus.failed),
            _count(model.monitoring_status == MonitoringStatus.partial),
            _count(stale_condition),
        ).where(model.deleted_at.is_(None))
    ).one()
    keys = ["total", "active", "inactive", "expired", "suspended", "unknown_expiration", "overdue",
            "expiring_30_days", "monitoring_failed", "monitoring_partial", "stale"]
    return dict(zip(keys, row))


@router.get("/dashboard")
def dashboard(clock: Clock = Depends(get_clock), _: AuthContext = Depends(require_admin), db: Session = Depends(get_db)):
    horizon = clock.today + timedelta(days=UPCOMING_DAYS)
    upcoming = []
    domains = db.scalars(
        select(Domain).options(joinedload(Domain.hosting_account))
        .where(Domain.deleted_at.is_(None), Domain.expiration_date <= horizon,
               Domain.service_status != ServiceStatus.expired)
        .order_by(Domain.expiration_date, Domain.normalized_domain_name).limit(UPCOMING_LIMIT)
    ).all()
    for d in domains:
        upcoming.append({
            "record_type": "domain", "id": d.id, "name": d.domain_name, "expiration_date": d.expiration_date,
            "expiration": expiration_info(d.expiration_date, clock.today).as_dict(),
            "usage_status": d.usage_status, "service_status": d.service_status,
            "context": d.hosting_account.name if d.hosting_account else "Unassigned",
        })
    hostings = db.scalars(
        select(HostingAccount)
        .where(HostingAccount.deleted_at.is_(None), HostingAccount.expiration_date <= horizon,
               HostingAccount.service_status != ServiceStatus.expired)
        .order_by(HostingAccount.expiration_date, func.lower(HostingAccount.name)).limit(UPCOMING_LIMIT)
    ).all()
    for h in hostings:
        upcoming.append({
            "record_type": "hosting", "id": h.id, "name": h.name, "expiration_date": h.expiration_date,
            "expiration": expiration_info(h.expiration_date, clock.today).as_dict(),
            "usage_status": h.usage_status, "service_status": h.service_status, "context": h.provider_name,
        })
    upcoming.sort(key=lambda r: (r["expiration_date"], r["name"].lower()))

    week_ago = clock.now - timedelta(days=7)
    notifications = db.execute(
        select(
            func.count(case((NotificationEvent.delivery_status == DeliveryStatus.sent, 1))),
            func.count(case((NotificationEvent.delivery_status == DeliveryStatus.failed, 1))),
            func.count(case((NotificationEvent.delivery_status == DeliveryStatus.queued, 1))),
        ).where(NotificationEvent.created_at >= week_ago, NotificationEvent.is_test.is_(False))
    ).one()

    jobs = [
        {"name": j.name, "last_started_at": j.last_started_at, "last_finished_at": j.last_finished_at,
         "last_status": j.last_status, "last_error": j.last_error}
        for j in db.scalars(select(JobRun).order_by(JobRun.name))
    ]
    scheduler_stale = not jobs or any(
        j["last_finished_at"] is None or j["last_finished_at"] < clock.now - timedelta(hours=2)
        for j in jobs if j["name"] in ("evaluate_reminders", "dispatch_due_checks")
    )

    return {
        "today": clock.today,
        "timezone": clock.settings.timezone,
        "domains": _summary(db, Domain, clock),
        "hosting": _summary(db, HostingAccount, clock),
        "upcoming": upcoming[:UPCOMING_LIMIT],
        "notifications_last_7_days": dict(zip(["sent", "failed", "queued"], notifications)),
        "notifications_enabled": clock.settings.notifications_enabled,
        "jobs": jobs,
        "scheduler_stale": scheduler_stale,
        "warnings": _warnings(clock, scheduler_stale),
    }


def _warnings(clock: Clock, scheduler_stale: bool) -> list[str]:
    warnings = []
    s = clock.settings
    if not s.notifications_enabled:
        warnings.append("Email reminders are turned off.")
    elif not s.notification_recipients:
        warnings.append("No reminder recipients are configured.")
    elif not s.ses_sender or not s.ses_region:
        warnings.append("Amazon SES is not fully configured.")
    if scheduler_stale:
        warnings.append("Background jobs have not run recently. Check that the worker and scheduler are running.")
    return warnings

