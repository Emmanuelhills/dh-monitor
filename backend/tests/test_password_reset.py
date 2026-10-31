"""Forgot-password links and admin-set passwords. Email sending is faked."""

import re
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models import PasswordResetToken
from app.notifications.ses import SesError
from app.services import password_reset
from tests.conftest import ADMIN_EMAIL, ADMIN_PASSWORD

API = "/api/v1"
NEW_PASSWORD = "a brand new long password"


@pytest.fixture
def outbox(monkeypatch):
    sent = []
    monkeypatch.setattr(password_reset, "send_email", lambda db, settings, email: sent.append(email) or "msg-1")
    return sent


def _token(email) -> str:
    return re.search(r"token=([\w-]+)", email.text).group(1)


def test_forgot_password_emails_a_working_one_time_link(admin_user, anon_client, outbox):
    r = anon_client.post(f"{API}/auth/forgot-password", json={"email": ADMIN_EMAIL.upper()})
    assert r.status_code == 202
    assert len(outbox) == 1 and outbox[0].to == ADMIN_EMAIL
    assert "/reset-password?token=" in outbox[0].text
    token = _token(outbox[0])

    assert anon_client.post(f"{API}/auth/reset-password/check", json={"token": token}).json() == {"valid": True}
    assert anon_client.post(f"{API}/auth/reset-password", json={"token": token, "new_password": NEW_PASSWORD}).status_code == 204

    assert anon_client.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}).status_code == 401
    assert anon_client.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": NEW_PASSWORD}).status_code == 200
    # Used once; it can't be used again.
    again = anon_client.post(f"{API}/auth/reset-password", json={"token": token, "new_password": "yet another password"})
    assert again.status_code == 400


def test_unknown_email_gets_the_same_answer_and_no_email(admin_user, anon_client, outbox):
    known = anon_client.post(f"{API}/auth/forgot-password", json={"email": ADMIN_EMAIL})
    unknown = anon_client.post(f"{API}/auth/forgot-password", json={"email": "nobody@example.com"})
    assert unknown.status_code == known.status_code == 202
    assert unknown.json() == known.json()
    assert [e.to for e in outbox] == [ADMIN_EMAIL]


def test_reset_signs_out_existing_sessions(client, anon_client, outbox):
    anon_client.post(f"{API}/auth/forgot-password", json={"email": ADMIN_EMAIL})
    anon_client.post(f"{API}/auth/reset-password", json={"token": _token(outbox[0]), "new_password": NEW_PASSWORD})
    assert client.get(f"{API}/auth/me").status_code == 401


def test_only_newest_link_works_and_expired_links_fail(admin_user, anon_client, outbox, db):
    anon_client.post(f"{API}/auth/forgot-password", json={"email": ADMIN_EMAIL})
    anon_client.post(f"{API}/auth/forgot-password", json={"email": ADMIN_EMAIL})
    old, new = _token(outbox[0]), _token(outbox[1])
    assert anon_client.post(f"{API}/auth/reset-password/check", json={"token": old}).json()["valid"] is False

    row = db.scalar(select(PasswordResetToken).where(PasswordResetToken.used_at.is_(None)))
    row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()
    assert anon_client.post(f"{API}/auth/reset-password", json={"token": new, "new_password": NEW_PASSWORD}).status_code == 400


def test_requests_are_rate_limited(admin_user, anon_client, outbox):
    for _ in range(8):
        assert anon_client.post(f"{API}/auth/forgot-password", json={"email": ADMIN_EMAIL}).status_code == 202
    assert len(outbox) == password_reset.MAX_REQUESTS_PER_HOUR


def test_email_failure_is_not_revealed(admin_user, anon_client, monkeypatch):
    def fail(db, settings, email):
        raise SesError("not configured", transient=False)
    monkeypatch.setattr(password_reset, "send_email", fail)
    assert anon_client.post(f"{API}/auth/forgot-password", json={"email": ADMIN_EMAIL}).status_code == 202


def test_short_password_rejected(admin_user, anon_client, outbox):
    anon_client.post(f"{API}/auth/forgot-password", json={"email": ADMIN_EMAIL})
    r = anon_client.post(f"{API}/auth/reset-password", json={"token": _token(outbox[0]), "new_password": "short"})
    assert r.status_code == 422


def test_admin_can_set_another_admins_password(client, anon_client):
    other = client.post(f"{API}/users", json={"email": "two@example.com", "password": "first long password"}).json()
    assert client.post(f"{API}/users/{other['id']}/password", json={"password": NEW_PASSWORD}).status_code == 204
    assert anon_client.post(f"{API}/auth/login", json={"email": "two@example.com", "password": NEW_PASSWORD}).status_code == 200

    me = client.get(f"{API}/auth/me").json()
    assert client.post(f"{API}/users/{me['id']}/password", json={"password": NEW_PASSWORD}).status_code == 400
