"""Resend as an alternative email provider. HTTP calls to Resend are always faked."""

import httpx
import pytest

from app.notifications import resend
from app.services.app_settings import get_app_settings

API = "/api/v1"
KEY = "re_test_0123456789abcdef"


class FakeResend:
    def __init__(self, send_status=200, send_body=None, domains_status=200, domains=None):
        self.send_status = send_status
        self.send_body = send_body if send_body is not None else {"id": "resend-msg-1"}
        self.domains_status = domains_status
        self.domains = domains if domains is not None else [{"name": "example.com", "status": "verified"}]
        self.calls = []

    def __call__(self, method, path, api_key, **kwargs):
        self.calls.append((method, path, api_key, kwargs))
        request = httpx.Request(method, f"https://api.resend.com{path}")
        if path == "/emails":
            return httpx.Response(self.send_status, json=self.send_body, request=request)
        if self.domains_status != 200:
            return httpx.Response(self.domains_status, json={"name": "restricted_api_key", "message": "restricted"},
                                  request=request)
        return httpx.Response(200, json={"data": self.domains}, request=request)


@pytest.fixture
def resend_settings(client, db):
    r = client.patch(f"{API}/notifications/settings", json={
        "email_provider": "resend", "resend_sender": "monitor@example.com", "resend_api_key": KEY,
        "notifications_enabled": True, "notification_recipients": ["ops@example.com"],
    })
    assert r.status_code == 200, r.text
    return r.json()


def test_switching_to_resend_stores_key_but_never_returns_it(client, resend_settings):
    assert resend_settings["email_provider"] == "resend"
    assert resend_settings["resend_sender"] == "monitor@example.com"
    assert resend_settings["resend_api_key_set"] is True
    assert KEY not in client.get(f"{API}/notifications/settings").text
    assert KEY not in client.get(f"{API}/audit-events").text


def test_resend_requires_api_key(client):
    r = client.patch(f"{API}/notifications/settings", json={"email_provider": "resend"})
    assert r.status_code == 422
    assert client.patch(f"{API}/notifications/settings", json={"email_provider": "mailgun"}).status_code == 422


def test_test_email_goes_through_resend(client, resend_settings, monkeypatch):
    fake = FakeResend()
    monkeypatch.setattr(resend, "_request", fake)
    body = client.post(f"{API}/notifications/test", json={"recipient": "me@example.com"}).json()
    assert body["accepted"] is True and body["provider_message_id"] == "resend-msg-1"
    assert "Resend accepted" in body["message"]
    assert body["checks"]["provider"] == "resend" and body["checks"]["sender_verified"] is True
    method, path, api_key, kwargs = fake.calls[-1]
    assert (method, path, api_key) == ("POST", "/emails", KEY)
    assert kwargs["json"]["from"] == "monitor@example.com" and kwargs["json"]["to"] == ["me@example.com"]


def test_validate_flags_unverified_domain_and_accepts_send_only_keys(client, resend_settings, monkeypatch):
    monkeypatch.setattr(resend, "_request", FakeResend(domains=[{"name": "other.com", "status": "verified"}]))
    checks = client.post(f"{API}/notifications/validate").json()["checks"]
    assert checks["credentials"] is True and checks["sender_verified"] is False
    assert any("not verified" in p for p in checks["problems"])

    monkeypatch.setattr(resend, "_request", FakeResend(domains_status=401))
    result = client.post(f"{API}/notifications/validate").json()
    assert result["ok"] is True and result["checks"]["sender_verified"] is None


def test_resend_error_classification(db, resend_settings, monkeypatch):
    settings = get_app_settings(db)
    db.refresh(settings)
    email = resend.OutgoingEmail(to="a@example.com", subject="s", text="t", html="h")

    monkeypatch.setattr(resend, "_request", FakeResend(send_status=429, send_body={"name": "rate_limit_exceeded", "message": "slow"}))
    with pytest.raises(resend.SesError) as transient:
        resend.send_email(db, settings, email)
    assert transient.value.transient is True

    monkeypatch.setattr(resend, "_request", FakeResend(send_status=403, send_body={"name": "validation_error", "message": "domain not verified"}))
    with pytest.raises(resend.SesError) as permanent:
        resend.send_email(db, settings, email)
    assert permanent.value.transient is False and "domain not verified" in permanent.value.message


def test_switching_back_to_ses(client, resend_settings):
    r = client.patch(f"{API}/notifications/settings", json={"email_provider": "ses", "clear_resend_api_key": True})
    assert r.status_code == 200
    assert r.json()["email_provider"] == "ses" and r.json()["resend_api_key_set"] is False
