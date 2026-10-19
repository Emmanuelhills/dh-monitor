"""Unit tests: normalization, expiration countdowns, reminder schedule, eligibility, redaction."""

from datetime import date, datetime, timezone

import pytest

from app.models import RecordType, RenewalStatus, ServiceStatus
from app.notifications.schedule import (
    ReminderSubject,
    ScheduleConfig,
    build_slots,
    current_slot,
    dedupe_key,
    ineligibility_reason,
)
from app.services.domain_names import InvalidDomainName, normalize_domain_name
from app.services.expiration import expiration_info, local_today
from app.services.redaction import redact_data, redact_text

# --------------------------------------------------------------------------- normalization


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Example.COM", "example.com"),
        ("  example.com.  ", "example.com"),
        ("https://www.Example.com/path?q=1", "www.example.com"),
        ("münchen.de", "xn--mnchen-3ya.de"),
        ("sub.domain.co.uk", "sub.domain.co.uk"),
    ],
)
def test_normalize_domain(raw, expected):
    assert normalize_domain_name(raw) == expected


@pytest.mark.parametrize(
    "raw", ["", "localhost", "exa mple.com", "-bad.com", "bad-.com", "a..com", "user@example.com",
            "example.com:8080", "example.123", "a" * 64 + ".com"]
)
def test_invalid_domains_rejected(raw):
    with pytest.raises(InvalidDomainName):
        normalize_domain_name(raw)


# --------------------------------------------------------------------------- expiration


TODAY = date(2026, 6, 15)


@pytest.mark.parametrize(
    "days, urgency, label",
    [
        (45, "ok", "Expires in 45 days"),
        (31, "ok", "Expires in 31 days"),
        (30, "upcoming", "Expires in 30 days"),
        (8, "upcoming", "Expires in 8 days"),
        (7, "urgent", "Expires in 7 days"),
        (1, "urgent", "Expires in 1 day"),
        (0, "today", "Expires today"),
        (-1, "overdue", "Overdue by 1 day"),
        (-12, "overdue", "Overdue by 12 days"),
    ],
)
def test_expiration_labels(days, urgency, label):
    from datetime import timedelta

    info = expiration_info(TODAY + timedelta(days=days), TODAY)
    assert (info.days_remaining, info.urgency, info.label) == (days, urgency, label)


def test_unknown_expiration():
    assert expiration_info(None, TODAY).urgency == "unknown"


def test_local_today_uses_configured_timezone():
    instant = datetime(2026, 6, 15, 23, 30, tzinfo=timezone.utc)
    assert local_today("UTC", instant) == date(2026, 6, 15)
    assert local_today("Asia/Tokyo", instant) == date(2026, 6, 16)
    assert local_today("America/Los_Angeles", instant) == date(2026, 6, 15)


# --------------------------------------------------------------------------- schedule

EXP = date(2026, 7, 31)
DEFAULT = ScheduleConfig()


def test_default_slots_order_and_keys():
    keys = [s.key for s in build_slots(EXP, DEFAULT)]
    assert keys == ["30_days", "14_days", "7_days", "3_days", "1_days", "due_today"] + [
        f"overdue_day_{i}" for i in range(1, 8)
    ]


@pytest.mark.parametrize(
    "today, expected",
    [
        (date(2026, 6, 30), None),  # 31 days before
        (date(2026, 7, 1), "30_days"),
        (date(2026, 7, 10), "30_days"),  # catch-up within window
        (date(2026, 7, 17), "14_days"),
        (date(2026, 7, 24), "7_days"),
        (date(2026, 7, 28), "3_days"),
        (date(2026, 7, 30), "1_days"),
        (date(2026, 7, 31), "due_today"),
        (date(2026, 8, 1), "overdue_day_1"),
        (date(2026, 8, 7), "overdue_day_7"),
        (date(2026, 8, 8), None),  # overdue reminders stop after 7 days
    ],
)
def test_current_slot(today, expected):
    slot = current_slot(EXP, today, DEFAULT)
    assert (slot.key if slot else None) == expected


def test_custom_schedule():
    config = ScheduleConfig(days_before=(60, 10), on_expiration_day=False, overdue_days=0)
    assert [s.key for s in build_slots(EXP, config)] == ["60_days", "10_days"]
    assert current_slot(EXP, EXP, config) is None


def _subject(**kw):
    base = dict(expiration_date=EXP, service_status=ServiceStatus.active, renewal_status=RenewalStatus.unknown,
                renewal_confirmed_for_date=None, notifications_enabled=True, archived=False)
    base.update(kw)
    return ReminderSubject(**base)


def test_eligibility_ignores_usage_and_covers_states():
    assert ineligibility_reason(_subject(), DEFAULT) is None
    assert ineligibility_reason(_subject(service_status=ServiceStatus.unknown), DEFAULT) is None
    assert ineligibility_reason(_subject(service_status=ServiceStatus.suspended), DEFAULT) is None
    assert ineligibility_reason(
        _subject(service_status=ServiceStatus.suspended), ScheduleConfig(remind_suspended=False)
    ) == "suspended_reminders_disabled"
    assert ineligibility_reason(_subject(notifications_enabled=False), DEFAULT) == "notifications_disabled"
    assert ineligibility_reason(_subject(archived=True), DEFAULT) == "archived"
    assert ineligibility_reason(_subject(expiration_date=None), DEFAULT) == "no_expiration_date"
    assert ineligibility_reason(_subject(service_status=ServiceStatus.expired), DEFAULT) == "confirmed_expired"
    assert ineligibility_reason(_subject(renewal_status=RenewalStatus.not_renewed), DEFAULT) == "confirmed_not_renewed"


def test_renewal_confirmed_for_current_date_stops_reminders_only_for_that_date():
    renewed_now = _subject(renewal_status=RenewalStatus.renewed, renewal_confirmed_for_date=EXP)
    assert ineligibility_reason(renewed_now, DEFAULT) == "renewal_confirmed"
    renewed_previous = _subject(renewal_status=RenewalStatus.renewed, renewal_confirmed_for_date=date(2025, 7, 31))
    assert ineligibility_reason(renewed_previous, DEFAULT) is None


def test_dedupe_key_is_stable_and_case_insensitive():
    a = dedupe_key(RecordType.domain, "abc", EXP, "7_days", "Ops@Example.com ")
    b = dedupe_key(RecordType.domain, "abc", EXP, "7_days", "ops@example.com")
    assert a == b == "domain|abc|2026-07-31|7_days|ops@example.com"
    assert a != dedupe_key(RecordType.domain, "abc", date(2027, 7, 31), "7_days", "ops@example.com")


# --------------------------------------------------------------------------- redaction


def test_redaction():
    text = "key AKIAABCDEFGHIJKLMNOP secret=abc123 Authorization: Bearer abcdefghijklmnop https://u:p@host/x"
    out = redact_text(text)
    assert "AKIAABCDEFGHIJKLMNOP" not in out
    assert "abc123" not in out
    assert "abcdefghijklmnop" not in out
    assert "u:p@" not in out
    data = redact_data({"api_key": "x", "nested": {"password": "y", "fine": "ok"}, "list": ["token=zzz"]})
    assert data == {"api_key": "[REDACTED]", "nested": {"password": "[REDACTED]", "fine": "ok"},
                    "list": ["token=[REDACTED]"]}
