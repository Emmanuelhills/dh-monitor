"""Unauthenticated, read-only overview for team members.

Exposes only non-sensitive fields: names, hosting assignment, expiration and statuses.
Never notes, admin URLs, registrar data, monitoring errors, history or settings.
Administrators can turn it off in General settings.
"""

from fastapi import APIRouter, Depends, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.api.common import Clock, get_clock
from app.api.errors import ApiError
from app.db import get_db
from app.models import DataSource, Domain, HostingAccount
from app.services.domain_names import display_domain_name
from app.services.expiration import expiration_info

router = APIRouter(prefix="/public", tags=["public"])

MAX_ROWS = 2000


def _verified(record) -> bool:
    return record.expiration_source != DataSource.manual and record.expiration_verified_at is not None


@router.get("/overview")
def public_overview(response: Response, clock: Clock = Depends(get_clock), db: Session = Depends(get_db)):
    if not clock.settings.public_page_enabled:
        raise ApiError(404, "public_page_disabled", "The public overview is turned off.")
    response.headers["Cache-Control"] = "public, max-age=60"

    domains = db.scalars(
        select(Domain).options(joinedload(Domain.hosting_account))
        .where(Domain.deleted_at.is_(None))
        .order_by(Domain.normalized_domain_name).limit(MAX_ROWS)
    ).all()

    domain_count = (
        select(func.count(Domain.id))
        .where(Domain.hosting_account_id == HostingAccount.id, Domain.deleted_at.is_(None))
        .correlate(HostingAccount).scalar_subquery()
    )
    hosting_rows = db.execute(
        select(HostingAccount, domain_count)
        .where(HostingAccount.deleted_at.is_(None))
        .order_by(func.lower(HostingAccount.name)).limit(MAX_ROWS)
    ).all()

    def hosting_name(d: Domain) -> str | None:
        h = d.hosting_account
        return h.name if h is not None and h.deleted_at is None else None

    return {
        "today": clock.today,
        "timezone": clock.settings.timezone,
        "domains": [
            {
                "id": d.id,
                "domain_name": display_domain_name(d.normalized_domain_name),
                "hosting_account": hosting_name(d),
                "hosting_provider": d.hosting_account.provider_name if hosting_name(d) else None,
                "expiration_date": d.expiration_date,
                "expiration": expiration_info(d.expiration_date, clock.today).as_dict(),
                "expiration_verified": _verified(d),
                "usage_status": d.usage_status,
                "service_status": d.service_status,
            }
            for d in domains
        ],
        "hosting": [
            {
                "id": h.id,
                "name": h.name,
                "provider_name": h.provider_name,
                "domain_count": count,
                "expiration_date": h.expiration_date,
                "expiration": expiration_info(h.expiration_date, clock.today).as_dict(),
                "expiration_verified": _verified(h),
                "usage_status": h.usage_status,
                "service_status": h.service_status,
            }
            for h, count in hosting_rows
        ],
    }
