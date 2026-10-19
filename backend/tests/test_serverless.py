"""Serverless (Vercel) mode: cron endpoint, inline checks, first-admin bootstrap, proxy IPs."""

from datetime import date, datetime, timedelta, timezone

import pytest

from app.config import Settings, get_settings
from app.models import Domain, MonitoringStatus, User
from app.monitoring import checker
from app.monitoring.types import LookupResult

API = "/api/v1"


@pytest.fixture
def settings(monkeypatch):
    s = get_settings()

    def set_(**kw):
        for k, v in kw.items():
            monkeypatch.setattr(s, k, v)

    return set_


@pytest.fixture
def fake_rdap(monkeypatch):
    monkeypatch.setattr(checker.rdap, "lookup", lambda name: LookupResult(
        source="rdap:test", expiration_date=date(2027, 5, 1), registry_statuses=["active"]))


def test_database_url_is_normalized():
    assert Settings(DATABASE_URL="postgres://u:p@h/db").database_url == "postgresql+psycopg://u:p@h/db"
    assert Settings(POSTGRES_URL="postgresql://u:p@h/db?sslmode=require").database_url.startswith("postgresql+psycopg://")


def test_cron_requires_secret(anon_client, settings):
    settings(cron_secret="")
    assert anon_client.get(f"{API}/cron/run").status_code == 503
    settings(cron_secret="s3cret")
    assert anon_client.get(f"{API}/cron/run").status_code == 401
    assert anon_client.get(f"{API}/cron/run", headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_cron_runs_due_checks_inline(anon_client, db, settings, fake_rdap):
    settings(cron_secret="s3cret", lookup_min_interval_seconds=0)
    domain = Domain(domain_name="due.com", normalized_domain_name="due.com", registry_statuses=[],
                    next_check_at=datetime.now(timezone.utc) - timedelta(minutes=1))
    db.add(domain)
    db.commit()
    r = anon_client.get(f"{API}/cron/run", headers={"Authorization": "Bearer s3cret"})
    assert r.status_code == 200, r.text
    summary = r.json()["summary"]
    assert summary["checks"]["checked"] == 1 and summary["checks"]["remaining"] == 0
    db.refresh(domain)
    assert domain.expiration_date == date(2027, 5, 1)
    assert domain.monitoring_status == MonitoringStatus.current


def test_cron_respects_time_budget(anon_client, db, settings, fake_rdap):
    settings(cron_secret="s3cret", cron_time_budget_seconds=1)  # less than one lookup's reserve
    db.add(Domain(domain_name="later.com", normalized_domain_name="later.com", registry_statuses=[],
                  next_check_at=datetime.now(timezone.utc) - timedelta(minutes=1)))
    db.commit()
    summary = anon_client.post(f"{API}/cron/run", headers={"Authorization": "Bearer s3cret"}).json()["summary"]
    assert summary["checks"]["checked"] == 0 and summary["checks"]["remaining"] == 1


def test_inline_on_demand_check(client, settings, fake_rdap, queued_tasks):
    settings(task_mode="inline")
    d = client.post(f"{API}/domains", json={"domain_name": "now.com", "auto_check_enabled": False}).json()
    r = client.post(f"{API}/domains/{d['id']}/check").json()
    assert r["status"] == "completed"
    assert client.get(f"{API}/domains/{d['id']}").json()["expiration_date"] == "2027-05-01"
    assert not [c for c in queued_tasks if c[1] == ("domain", d["id"])][1:]  # no broker use beyond create


def test_bootstrap_admin_only_when_no_users(anon_client, db, settings):
    settings(bootstrap_admin_email="owner@example.com", bootstrap_admin_password="a-long-bootstrap-pass")
    bad = anon_client.post(f"{API}/auth/login", json={"email": "owner@example.com", "password": "wrong-password"})
    assert bad.status_code == 401
    ok = anon_client.post(f"{API}/auth/login", json={"email": "owner@example.com", "password": "a-long-bootstrap-pass"})
    assert ok.status_code == 200
    assert db.query(User).count() == 1
    # Once a user exists, the bootstrap never creates another.
    settings(bootstrap_admin_email="second@example.com")
    r = anon_client.post(f"{API}/auth/login", json={"email": "second@example.com", "password": "a-long-bootstrap-pass"})
    assert r.status_code == 401 and db.query(User).count() == 1


def test_rate_limit_uses_forwarded_ip(anon_client, admin_user, settings):
    settings(trust_proxy_headers=True, login_max_failures=2)
    for _ in range(2):
        anon_client.post(f"{API}/auth/login", json={"email": "x@example.com", "password": "nope"},
                         headers={"X-Forwarded-For": "203.0.113.5, 10.0.0.1"})
    blocked = anon_client.post(f"{API}/auth/login", json={"email": "y@example.com", "password": "nope"},
                               headers={"X-Forwarded-For": "203.0.113.5"})
    assert blocked.status_code == 429
    other = anon_client.post(f"{API}/auth/login", json={"email": "y@example.com", "password": "nope"},
                             headers={"X-Forwarded-For": "198.51.100.7"})
    assert other.status_code == 401


def test_health_in_inline_mode(anon_client, settings):
    settings(task_mode="inline")
    assert anon_client.get(f"{API}/health").json() == {"status": "ok", "database": "ok", "queue": "not used"}
