from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from enum import Enum

from fastapi import Depends, Query
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.api.errors import ApiError
from app.db import get_db
from app.models import ApplicationSettings, AuditEvent, MonitoringCheck
from app.services.app_settings import get_app_settings
from app.services.expiration import local_today

MAX_PAGE_SIZE = 100


class SortOrder(str, Enum):
    asc = "asc"
    desc = "desc"


class ExpirationWindow(str, Enum):
    overdue = "overdue"
    today = "today"
    within_7 = "within_7"
    within_30 = "within_30"
    beyond_30 = "beyond_30"
    unknown = "unknown"


@dataclass
class Clock:
    now: datetime
    today: date
    settings: ApplicationSettings


def get_clock(db: Session = Depends(get_db)) -> Clock:
    settings = get_app_settings(db)
    now = datetime.now(timezone.utc)
    return Clock(now=now, today=local_today(settings.timezone, now), settings=settings)


@dataclass
class Pagination:
    page: int
    page_size: int

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


def get_pagination(
    page: int = Query(1, ge=1, le=100000), page_size: int = Query(25, ge=1, le=MAX_PAGE_SIZE)
) -> Pagination:
    return Pagination(page=page, page_size=page_size)


def expiration_window_clause(column, window: ExpirationWindow, today: date):
    match window:
        case ExpirationWindow.overdue:
            return column < today
        case ExpirationWindow.today:
            return column == today
        case ExpirationWindow.within_7:
            return column.between(today, today + timedelta(days=7))
        case ExpirationWindow.within_30:
            return column.between(today, today + timedelta(days=30))
        case ExpirationWindow.beyond_30:
            return column > today + timedelta(days=30)
        case ExpirationWindow.unknown:
            return column.is_(None)


def count_of(db: Session, stmt: Select) -> int:
    return db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0


def check_history(db: Session, fk_column, record_id, pagination: Pagination) -> dict:
    stmt = select(MonitoringCheck).where(fk_column == record_id)
    total = count_of(db, stmt)
    items = db.scalars(
        stmt.order_by(MonitoringCheck.checked_at.desc()).offset(pagination.offset).limit(pagination.page_size)
    ).all()
    return {"items": items, "total": total, "page": pagination.page, "page_size": pagination.page_size}


def change_history(db: Session, record_type: str, record_id, pagination: Pagination) -> dict:
    stmt = select(AuditEvent).where(AuditEvent.record_type == record_type, AuditEvent.record_id == record_id)
    total = count_of(db, stmt)
    items = db.scalars(
        stmt.order_by(AuditEvent.created_at.desc()).offset(pagination.offset).limit(pagination.page_size)
    ).all()
    return {"items": items, "total": total, "page": pagination.page, "page_size": pagination.page_size}


def ensure_editable(record) -> None:
    if record.deleted_at is not None:
        raise ApiError(409, "archived", "This record is archived. Restore it before editing.")
