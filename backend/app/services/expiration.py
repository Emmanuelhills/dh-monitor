"""Expiration countdowns, computed from date-only values in the application timezone."""

from dataclasses import dataclass
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo


def local_today(tz_name: str, now: datetime | None = None) -> date:
    now = now or datetime.now(timezone.utc)
    return now.astimezone(ZoneInfo(tz_name)).date()


@dataclass(frozen=True)
class ExpirationInfo:
    days_remaining: int | None
    urgency: str  # none | ok | upcoming | urgent | today | overdue | unknown
    label: str

    def as_dict(self) -> dict:
        return {"days_remaining": self.days_remaining, "urgency": self.urgency, "label": self.label}


def _plural(n: int) -> str:
    return "day" if n == 1 else "days"


def expiration_info(expiration_date: date | None, today: date) -> ExpirationInfo:
    if expiration_date is None:
        return ExpirationInfo(None, "unknown", "Expiration unknown")
    days = (expiration_date - today).days
    if days > 30:
        return ExpirationInfo(days, "ok", f"Expires in {days} days")
    if days >= 8:
        return ExpirationInfo(days, "upcoming", f"Expires in {days} days")
    if days >= 1:
        return ExpirationInfo(days, "urgent", f"Expires in {days} {_plural(days)}")
    if days == 0:
        return ExpirationInfo(0, "today", "Expires today")
    overdue = -days
    return ExpirationInfo(days, "overdue", f"Overdue by {overdue} {_plural(overdue)}")
