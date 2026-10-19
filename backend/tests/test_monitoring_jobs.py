"""Integration tests: monitoring persistence, failure handling, dispatcher, lifecycle job."""

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models import (
    CheckResult,
    DataSource,
    Domain,
    HostingAccount,
    MonitoringCheck,
    MonitoringStatus,
    ProviderIntegration,
    RecordType,
    RenewalStatus,
    ServiceStatus,
)
from app.monitoring import checker
from app.monitoring.types import CheckError, CheckErrorCode, LookupResult
from app.services.lifecycle import evaluate_expirations

API = "/api/v1"


def add_domain(db, name="example.com", **kw) -> Domain:
    domain = Domain(domain_name=name, normalized_domain_name=name, registry_statuses=[], **kw)
    db.add(domain)
    db.commit()
    return domain


@pytest.fixture
def rdap_returns(monkeypatch):
    def _set(result=None, error=None):
        def fake(name):
            if error:
                raise error
            return result

        monkeypatch.setattr(checker.rdap, "lookup", fake)
        monkeypatch.setattr(checker.whois, "lookup", lambda name: (_ for _ in ()).throw(
            CheckError(CheckErrorCode.UNSUPPORTED, "no whois", source="whois")))

    return _set


def test_successful_check_updates_record_and_history(db, rdap_returns):
    domain = add_domain(db, expiration_date=date(2026, 9, 1))
    rdap_returns(LookupResult(source="rdap:rdap.test", expiration_date=date(2027, 9, 1),
                              registrar_name="Reg Inc", registry_statuses=["active"], observed={"ldh_name": "example.com"}))
    check = checker.run_check(db, RecordType.domain, domain.id)
    db.commit()
    db.refresh(domain)
    assert check.result == CheckResult.success
    assert domain.expiration_date == date(2027, 9, 1)
    assert domain.expiration_source == DataSource.rdap
    assert domain.monitoring_status == MonitoringStatus.current
    assert domain.last_successful_check_at is not None
    assert domain.next_check_at > datetime.now(timezone.utc) + timedelta(hours=23)
    assert check.changes["expiration_date"] == {"from": "2026-09-01", "to": "2027-09-01"}
    assert check.observed_data["ldh_name"] == "example.com"


def test_failed_check_preserves_data(db, rdap_returns):
    domain = add_domain(db, expiration_date=date(2026, 9, 1), registrar_name="Keep Me")
    rdap_returns(error=CheckError(CheckErrorCode.TIMEOUT, "timed out", source="rdap"))
    check = checker.run_check(db, RecordType.domain, domain.id)
    db.commit()
    db.refresh(domain)
    assert check.result == CheckResult.failure and check.error_code == "timeout"
    assert domain.expiration_date == date(2026, 9, 1)
    assert domain.registrar_name == "Keep Me"
    assert domain.monitoring_status == MonitoringStatus.failed
    assert domain.consecutive_check_failures == 1
    # Transient: retried with backoff well before the daily interval.
    assert domain.next_check_at < datetime.now(timezone.utc) + timedelta(hours=1)


def test_partial_check(db, rdap_returns):
    domain = add_domain(db, expiration_date=date(2026, 9, 1))
    rdap_returns(LookupResult(source="rdap:x", registrar_name="Reg", missing=["expiration_date"]))
    check = checker.run_check(db, RecordType.domain, domain.id)
    db.commit()
    db.refresh(domain)
    assert check.result == CheckResult.partial
    assert domain.monitoring_status == MonitoringStatus.partial
    assert domain.expiration_date == date(2026, 9, 1)
    assert domain.registrar_name == "Reg"


def test_unsupported_tld_becomes_manual(db, rdap_returns):
    domain = add_domain(db)
    rdap_returns(error=CheckError(CheckErrorCode.UNSUPPORTED, "no rdap", source="rdap"))
    checker.run_check(db, RecordType.domain, domain.id)
    db.commit()
    db.refresh(domain)
    assert domain.monitoring_status == MonitoringStatus.manual


def test_hosting_adapter_check(db, monkeypatch):
    from app.services.secrets import put_secret

    integration = ProviderIntegration(name="WHMCS", adapter="whmcs", config={"api_url": "https://billing.test"},
                                      secret_name="integration:test")
    put_secret(db, "integration:test", {"identifier": "id", "secret": "sec"})
    db.add(integration)
    db.flush()
    hosting = HostingAccount(name="Plan", provider_name="Acme", integration_id=integration.id, external_ref="42")
    db.add(hosting)
    db.commit()

    from app.monitoring.hosting_adapters import whmcs

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"result": "success", "products": {"product": [
                {"id": 42, "status": "Suspended", "nextduedate": "2027-02-01", "regdate": "2024-02-01", "name": "Pro"}]}}

    calls = []
    monkeypatch.setattr(whmcs.http, "request", lambda *a, **k: calls.append((a, k)) or FakeResponse())
    check = checker.run_check(db, RecordType.hosting, hosting.id)
    db.commit()
    db.refresh(hosting)
    assert check.result == CheckResult.success
    assert hosting.expiration_date == date(2027, 2, 1)
    assert hosting.service_status == ServiceStatus.suspended
    assert hosting.service_status_source == DataSource.provider
    assert calls[0][1]["data"]["serviceid"] == "42"
    assert "sec" not in str(check.observed_data)


def test_on_demand_check_is_queued_and_deduplicated(client, db, queued_tasks):
    d = client.post(f"{API}/domains", json={"domain_name": "queue.com", "auto_check_enabled": False}).json()
    first = client.post(f"{API}/domains/{d['id']}/check")
    assert first.status_code == 202 and first.json()["status"] == "queued"
    second = client.post(f"{API}/domains/{d['id']}/check")
    assert second.json()["status"] == "already_queued"
    assert queued_tasks.count(("dhm.check_record", ("domain", d["id"]))) == 1


def test_dispatcher_queues_due_records_once(db, queued_tasks):
    from app.tasks.jobs import dispatch_due_checks

    due = add_domain(db, "due.com", next_check_at=datetime.now(timezone.utc) - timedelta(minutes=1))
    add_domain(db, "later.com", next_check_at=datetime.now(timezone.utc) + timedelta(hours=5))
    add_domain(db, "off.com", auto_check_enabled=False, next_check_at=None)
    dispatch_due_checks.apply()
    dispatch_due_checks.apply()
    checks = [c for c in queued_tasks if c[0] == "dhm.check_record"]
    assert checks == [("dhm.check_record", ("domain", str(due.id)))]


def test_lifecycle_overdue_requests_verification_without_marking_expired(db):
    yesterday = date.today() - timedelta(days=1)
    domain = add_domain(db, "late.com", expiration_date=yesterday - timedelta(days=1),
                        service_status=ServiceStatus.active, last_checked_at=datetime.now(timezone.utc) - timedelta(days=2),
                        next_check_at=datetime.now(timezone.utc) + timedelta(hours=20))
    summary = evaluate_expirations(db)
    db.commit()
    db.refresh(domain)
    assert summary["verification_requested"] == 1
    assert domain.service_status == ServiceStatus.active  # never inferred from the date alone
    assert domain.next_check_at <= datetime.now(timezone.utc)


def test_lifecycle_confirmed_non_renewal_becomes_expired(db):
    past = date.today() - timedelta(days=3)
    domain = add_domain(db, "gone.com", expiration_date=past, renewal_status=RenewalStatus.not_renewed,
                        renewal_confirmed_for_date=past, service_status=ServiceStatus.active)
    evaluate_expirations(db)
    db.commit()
    db.refresh(domain)
    assert domain.service_status == ServiceStatus.expired


def test_lifecycle_resets_renewal_for_lapsed_new_period(db):
    today = date.today()
    domain = add_domain(db, "cycle.com", expiration_date=today, renewal_status=RenewalStatus.renewed,
                        renewal_confirmed_for_date=today - timedelta(days=365))
    evaluate_expirations(db)
    db.commit()
    db.refresh(domain)
    assert domain.renewal_status == RenewalStatus.unknown


def test_check_history_endpoint(client, db, rdap_returns):
    d = client.post(f"{API}/domains", json={"domain_name": "hist.com"}).json()
    rdap_returns(LookupResult(source="rdap:x", expiration_date=date(2027, 1, 1)))
    checker.run_check(db, RecordType.domain, uuid.UUID(d["id"]))
    db.commit()
    history = client.get(f"{API}/domains/{d['id']}/checks").json()
    assert history["total"] == 1 and history["items"][0]["result"] == "success"
    assert db.scalars(select(MonitoringCheck)).one().domain_id == uuid.UUID(d["id"])
