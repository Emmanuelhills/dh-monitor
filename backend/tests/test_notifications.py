"""Integration tests: reminder generation, idempotency, cancellation, delivery retries, SES settings."""

from datetime import date, datetime, timedelta, timezone

import pytest
from botocore.exceptions import ClientError
from sqlalchemy import select

from app.models import (
    ApplicationSettings,
    DeliveryStatus,
    Domain,
    HostingAccount,
    NotificationEvent,
    RenewalStatus,
    ServiceStatus,
    UsageStatus,
)
from app.notifications import service, ses
from app.services.app_settings import get_app_settings

API = "/api/v1"
TODAY = date.today()


@pytest.fixture
def notify_settings(db) -> ApplicationSettings:
    s = get_app_settings(db)
    s.notifications_enabled = True
    s.notification_recipients = ["ops@example.com", "boss@example.com"]
    s.ses_region = "us-east-1"
    s.ses_sender = "monitor@example.com"
    db.commit()
    return s


def add_domain(db, name, days, **kw):
    d = Domain(domain_name=name, normalized_domain_name=name, registry_statuses=[],
               expiration_date=TODAY + timedelta(days=days), **kw)
    db.add(d)
    db.commit()
    return d


def events(db):
    return db.scalars(select(NotificationEvent).order_by(NotificationEvent.recipient)).all()


def test_reminders_for_active_and_inactive_records(db, notify_settings):
    add_domain(db, "used.com", 7, usage_status=UsageStatus.active)
    add_domain(db, "idle.com", 7, usage_status=UsageStatus.inactive)
    db.add(HostingAccount(name="Plan", provider_name="Acme", expiration_date=TODAY + timedelta(days=14)))
    db.add(HostingAccount(name="Paused", provider_name="Acme", expiration_date=TODAY,
                          service_status=ServiceStatus.suspended))
    db.commit()
    created = service.evaluate_reminders(db)
    db.commit()
    assert len(created) == 8  # 4 records x 2 recipients
    intervals = {(e.record_name, e.reminder_interval) for e in events(db)}
    assert intervals == {("used.com", "7_days"), ("idle.com", "7_days"), ("Plan", "14_days"), ("Paused", "due_today")}


def test_reminders_are_idempotent(db, notify_settings):
    add_domain(db, "once.com", 3)
    assert len(service.evaluate_reminders(db)) == 2
    db.commit()
    assert service.evaluate_reminders(db) == []
    assert service.evaluate_reminders(db) == []
    db.commit()
    assert len(events(db)) == 2


def test_ineligible_records_are_skipped(db, notify_settings):
    add_domain(db, "off.com", 1, notifications_enabled=False)
    add_domain(db, "expired.com", -2, service_status=ServiceStatus.expired)
    add_domain(db, "renewed.com", 1, renewal_status=RenewalStatus.renewed,
               renewal_confirmed_for_date=TODAY + timedelta(days=1))
    add_domain(db, "far.com", 90)
    assert service.evaluate_reminders(db) == []


def test_disabled_notifications_create_nothing(db, notify_settings):
    notify_settings.notifications_enabled = False
    db.commit()
    add_domain(db, "x.com", 1)
    assert service.evaluate_reminders(db) == []


@pytest.fixture
def fake_ses(monkeypatch):
    sent: list = []
    behaviour = {"error": None}

    def fake_send(db, settings, email):
        if behaviour["error"]:
            raise behaviour["error"]
        sent.append(email)
        return f"msg-{len(sent)}"

    monkeypatch.setattr(service, "send_email", fake_send)
    return sent, behaviour


def test_delivery_success_records_message_id(db, notify_settings, fake_ses):
    sent, _ = fake_ses
    add_domain(db, "deliver.com", 7)
    ids = service.evaluate_reminders(db)
    db.commit()
    assert service.deliver_notification(db, ids[0]) == "sent"
    event = db.get(NotificationEvent, ids[0])
    db.refresh(event)
    assert event.delivery_status == DeliveryStatus.sent
    assert event.provider_message_id == "msg-1"
    assert event.attempt_count == 1
    assert "deliver.com expires in 7 days" in sent[0].subject
    # A second delivery attempt of the same event never resends.
    assert service.deliver_notification(db, ids[0]) == "skipped"
    assert len(sent) == 1


def test_email_never_contains_admin_url(db, notify_settings, fake_ses):
    sent, _ = fake_ses
    h = HostingAccount(name="Plan", provider_name="Acme", admin_url="https://secret-panel.test",
                       expiration_date=TODAY + timedelta(days=1))
    db.add(h)
    db.commit()
    ids = service.evaluate_reminders(db)
    db.commit()
    service.deliver_notification(db, ids[0])
    assert "secret-panel" not in sent[0].html + sent[0].text


def test_transient_failure_retries_with_backoff_then_fails(db, notify_settings, fake_ses, monkeypatch):
    _, behaviour = fake_ses
    behaviour["error"] = ses.SesError("Throttling", transient=True, code="Throttling")
    add_domain(db, "retry.com", 7)
    event_id = service.evaluate_reminders(db)[0]
    db.commit()

    now = datetime.now(timezone.utc)
    assert service.deliver_notification(db, event_id, now=now) == "retry"
    event = db.get(NotificationEvent, event_id)
    db.refresh(event)
    assert event.delivery_status == DeliveryStatus.queued
    assert event.next_attempt_at > now
    # Not due yet: no attempt is made.
    assert service.deliver_notification(db, event_id, now=now) == "not_due"

    from app.config import get_settings

    for _ in range(get_settings().email_max_attempts - 1):
        now = now + timedelta(days=1)
        result = service.deliver_notification(db, event_id, now=now)
    assert result == "failed"
    db.refresh(event)
    assert event.delivery_status == DeliveryStatus.failed
    assert event.attempt_count == get_settings().email_max_attempts


def test_permanent_failure_is_not_retried(db, notify_settings, fake_ses):
    _, behaviour = fake_ses
    behaviour["error"] = ses.SesError("MessageRejected: Email address is not verified.", transient=False)
    add_domain(db, "reject.com", 7)
    event_id = service.evaluate_reminders(db)[0]
    db.commit()
    assert service.deliver_notification(db, event_id) == "failed"


def test_date_change_cancels_queued_reminder_and_schedules_new(client, db, notify_settings, fake_ses):
    sent, _ = fake_ses
    d = client.post(f"{API}/domains", json={"domain_name": "move.com",
                                             "expiration_date": (TODAY + timedelta(days=7)).isoformat()}).json()
    ids = service.evaluate_reminders(db)
    db.commit()
    new_date = (TODAY + timedelta(days=14)).isoformat()
    assert client.patch(f"{API}/domains/{d['id']}", json={"expiration_date": new_date}).status_code == 200
    db.expire_all()
    assert {db.get(NotificationEvent, i).delivery_status for i in ids} == {DeliveryStatus.cancelled}
    # Delivering a cancelled event does nothing.
    assert service.deliver_notification(db, ids[0]) == "skipped"
    assert sent == []
    # The new date gets its own schedule.
    new_ids = service.evaluate_reminders(db)
    db.commit()
    assert {db.get(NotificationEvent, i).reminder_interval for i in new_ids} == {"14_days"}


def test_renewal_confirmation_stops_reminders(client, db, notify_settings, fake_ses):
    d = client.post(f"{API}/domains", json={"domain_name": "paid.com",
                                             "expiration_date": (TODAY + timedelta(days=3)).isoformat()}).json()
    ids = service.evaluate_reminders(db)
    db.commit()
    client.patch(f"{API}/domains/{d['id']}", json={"renewal_status": "renewed"})
    db.expire_all()
    assert {db.get(NotificationEvent, i).delivery_status for i in ids} == {DeliveryStatus.cancelled}
    assert service.evaluate_reminders(db) == []


def test_stale_event_rechecked_at_send_time(db, notify_settings, fake_ses):
    """Even without the API (e.g. a direct DB change), delivery re-validates the date."""
    sent, _ = fake_ses
    domain = add_domain(db, "race.com", 7)
    event_id = service.evaluate_reminders(db)[0]
    db.commit()
    domain.expiration_date = TODAY + timedelta(days=200)
    db.commit()
    assert service.deliver_notification(db, event_id) == "cancelled"
    assert sent == []


def test_stuck_sending_is_failed_not_resent(db, notify_settings):
    add_domain(db, "stuck.com", 7)
    event_id = service.evaluate_reminders(db)[0]
    event = db.get(NotificationEvent, event_id)
    event.delivery_status = DeliveryStatus.sending
    event.last_attempt_at = datetime.now(timezone.utc) - timedelta(hours=2)
    db.commit()
    assert service.fail_stuck_sending(db) == 1
    db.commit()
    db.refresh(event)
    assert event.delivery_status == DeliveryStatus.failed


# --------------------------------------------------------------------------- SES settings API


def test_settings_never_return_secrets(client):
    r = client.patch(f"{API}/notifications/settings", json={
        "ses_region": "eu-west-1", "ses_sender": "monitor@example.com", "ses_auth_method": "access_keys",
        "ses_credentials": {"access_key_id": "AKIAABCDEFGHIJKLMNOP", "secret_access_key": "s" * 40},
        "notification_recipients": ["Ops@Example.com"], "reminder_days_before": [7, 30, 7],
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ses_credentials_set"] is True
    assert body["notification_recipients"] == ["ops@example.com"]
    assert body["reminder_days_before"] == [30, 7]
    assert "AKIA" not in r.text and "s" * 40 not in r.text
    assert "AKIA" not in client.get(f"{API}/notifications/settings").text
    audit = client.get(f"{API}/audit-events").text
    assert "AKIAABCDEFGHIJKLMNOP" not in audit and "s" * 40 not in audit


def test_access_keys_method_requires_credentials(client):
    r = client.patch(f"{API}/notifications/settings", json={"ses_auth_method": "access_keys"})
    assert r.status_code == 422


def test_invalid_settings_rejected(client):
    assert client.patch(f"{API}/notifications/settings", json={"ses_region": "mars"}).status_code == 422
    assert client.patch(f"{API}/notifications/settings", json={"notification_recipients": ["nope"]}).status_code == 422
    assert client.patch(f"{API}/notifications/settings", json={"reminder_days_before": [0]}).status_code == 422


class FakeSesClient:
    def __init__(self, fail_send=False):
        self.fail_send = fail_send
        self.sent = []

    def get_account(self):
        return {"SendingEnabled": True, "ProductionAccessEnabled": False,
                "SendQuota": {"Max24HourSend": 200, "MaxSendRate": 1, "SentLast24Hours": 0}}

    def get_email_identity(self, EmailIdentity):
        if EmailIdentity == "example.com":
            return {"VerifiedForSendingStatus": True}
        raise ClientError({"Error": {"Code": "NotFoundException", "Message": "nope"}}, "GetEmailIdentity")

    def send_email(self, **request):
        if self.fail_send:
            raise ClientError({"Error": {"Code": "MessageRejected", "Message": "Email address is not verified."},
                               "ResponseMetadata": {"HTTPStatusCode": 400}}, "SendEmail")
        self.sent.append(request)
        return {"MessageId": "0100-test"}


def test_test_email_with_mocked_sdk(client, db, monkeypatch, notify_settings):
    fake = FakeSesClient()
    monkeypatch.setattr(ses, "make_client", lambda db, settings: fake)
    r = client.post(f"{API}/notifications/test", json={"recipient": "me@example.com"})
    body = r.json()
    assert body["accepted"] is True and body["provider_message_id"] == "0100-test"
    assert body["checks"]["sender_verified"] is True
    assert any("sandbox" in p for p in body["checks"]["problems"])
    assert fake.sent[0]["Destination"] == {"ToAddresses": ["me@example.com"]}
    history = client.get(f"{API}/notifications").json()["items"]
    assert history[0]["is_test"] is True and history[0]["delivery_status"] == "sent"


def test_test_email_reports_rejection(client, monkeypatch, notify_settings):
    monkeypatch.setattr(ses, "make_client", lambda db, settings: FakeSesClient(fail_send=True))
    body = client.post(f"{API}/notifications/test", json={"recipient": "me@example.com"}).json()
    assert body["accepted"] is False and "MessageRejected" in body["message"]


def test_ses_error_classification():
    throttled = ses._classify(ClientError({"Error": {"Code": "TooManyRequestsException", "Message": "slow"},
                                           "ResponseMetadata": {"HTTPStatusCode": 429}}, "SendEmail"))
    rejected = ses._classify(ClientError({"Error": {"Code": "MessageRejected", "Message": "no"},
                                          "ResponseMetadata": {"HTTPStatusCode": 400}}, "SendEmail"))
    assert throttled.transient and not rejected.transient


def test_retry_failed_notification_endpoint(client, db, notify_settings, queued_tasks):
    add_domain(db, "manual-retry.com", 7)
    event_id = service.evaluate_reminders(db)[0]
    event = db.get(NotificationEvent, event_id)
    event.delivery_status = DeliveryStatus.failed
    db.commit()
    r = client.post(f"{API}/notifications/{event_id}/retry")
    assert r.status_code == 200 and r.json()["delivery_status"] == "queued"
    assert ("dhm.deliver_notification", (str(event_id),)) in queued_tasks
