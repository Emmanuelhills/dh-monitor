"""Pure reminder-schedule logic (no I/O), so it can be unit tested exhaustively.

A schedule is a list of *slots*. Each slot has a stable key (``30_days``, ``due_today``,
``overdue_day_3``) and a window ``[start, end)`` of local calendar dates during which it is
the current reminder. Only the slot whose window contains today may be sent, which gives
catch-up behaviour (a record added 10 days before expiry still gets its "14 days" warning)
without ever back-filling several stale reminders at once.
"""

from dataclasses import dataclass
from datetime import date, timedelta

from app.models import RecordType, RenewalStatus, ServiceStatus


@dataclass(frozen=True)
class ReminderSlot:
    key: str
    start: date
    end: date  # exclusive


@dataclass(frozen=True)
class ScheduleConfig:
    days_before: tuple[int, ...] = (30, 14, 7, 3, 1)
    on_expiration_day: bool = True
    overdue_days: int = 7
    remind_suspended: bool = True


def build_slots(expiration_date: date, config: ScheduleConfig) -> list[ReminderSlot]:
    slots: list[ReminderSlot] = []
    before = sorted({d for d in config.days_before if d > 0}, reverse=True)
    for i, days in enumerate(before):
        start = expiration_date - timedelta(days=days)
        end = (
            expiration_date - timedelta(days=before[i + 1]) if i + 1 < len(before) else expiration_date
        )
        slots.append(ReminderSlot(f"{days}_days", start, end))
    if config.on_expiration_day:
        slots.append(ReminderSlot("due_today", expiration_date, expiration_date + timedelta(days=1)))
    for k in range(1, max(config.overdue_days, 0) + 1):
        day = expiration_date + timedelta(days=k)
        slots.append(ReminderSlot(f"overdue_day_{k}", day, day + timedelta(days=1)))
    return slots


def current_slot(expiration_date: date, today: date, config: ScheduleConfig) -> ReminderSlot | None:
    for slot in build_slots(expiration_date, config):
        if slot.start <= today < slot.end:
            return slot
    return None


@dataclass(frozen=True)
class ReminderSubject:
    """The fields of a domain or hosting account that decide reminder eligibility."""

    expiration_date: date | None
    service_status: ServiceStatus
    renewal_status: RenewalStatus
    renewal_confirmed_for_date: date | None
    notifications_enabled: bool
    archived: bool


def ineligibility_reason(subject: ReminderSubject, config: ScheduleConfig) -> str | None:
    """Return why no reminder should be sent, or None if the record is eligible.

    Usage status (active/inactive) is deliberately not an input.
    """
    if subject.archived:
        return "archived"
    if not subject.notifications_enabled:
        return "notifications_disabled"
    if subject.expiration_date is None:
        return "no_expiration_date"
    if subject.service_status == ServiceStatus.expired:
        return "confirmed_expired"
    if subject.renewal_status == RenewalStatus.not_renewed:
        return "confirmed_not_renewed"
    if (
        subject.renewal_status == RenewalStatus.renewed
        and subject.renewal_confirmed_for_date == subject.expiration_date
    ):
        return "renewal_confirmed"
    if subject.service_status == ServiceStatus.suspended and not config.remind_suspended:
        return "suspended_reminders_disabled"
    return None


def dedupe_key(
    record_type: RecordType, record_id: str, expiration_date: date, interval: str, recipient: str
) -> str:
    return "|".join(
        [record_type.value, str(record_id), expiration_date.isoformat(), interval, recipient.strip().lower()]
    )
