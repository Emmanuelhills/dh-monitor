"""Unit tests for lookup parsing and reconciliation (no network, no database)."""

from datetime import date, datetime, timezone

import pytest

from app.models import DataSource, Domain, HostingAccount, RenewalStatus, ServiceStatus
from app.monitoring.rdap import parse_rdap_domain
from app.monitoring.reconcile import derive_domain_status, reconcile
from app.monitoring.types import CheckError, LookupResult
from app.monitoring.whois import parse_whois

NOW = datetime(2026, 6, 15, 12, tzinfo=timezone.utc)
TODAY = NOW.date()


def rdap_payload(name="example.com", expiration="2027-08-13T04:00:00Z", status=("client transfer prohibited",)):
    events = [{"eventAction": "registration", "eventDate": "1995-08-14T04:00:00Z"}]
    if expiration:
        events.append({"eventAction": "expiration", "eventDate": expiration})
    return {
        "objectClassName": "domain",
        "ldhName": name.upper(),
        "status": list(status),
        "events": events,
        "entities": [
            {"roles": ["registrar"], "vcardArray": ["vcard", [["version", {}, "text", "4.0"], ["fn", {}, "text", "Example Registrar, Inc."]]]},
            {"roles": ["registrant"], "vcardArray": ["vcard", [["fn", {}, "text", "Private Person"]]]},
        ],
        "nameservers": [{"ldhName": "A.IANA-SERVERS.NET"}],
    }


def test_rdap_parse_extracts_fields_and_drops_personal_data():
    result = parse_rdap_domain(rdap_payload(), "example.com")
    assert result.expiration_date == date(2027, 8, 13)
    assert result.registration_date == date(1995, 8, 14)
    assert result.registrar_name == "Example Registrar, Inc."
    assert result.missing == []
    assert "Private Person" not in str(result.observed)


def test_rdap_parse_rejects_other_domain():
    with pytest.raises(CheckError) as exc:
        parse_rdap_domain(rdap_payload(name="other.com"), "example.com")
    assert exc.value.code == "invalid_response"


def test_rdap_missing_expiration_reported_not_blank():
    result = parse_rdap_domain(rdap_payload(expiration=None), "example.com")
    assert result.expiration_date is None
    assert "expiration_date" in result.missing


WHOIS_TEXT = """Domain Name: EXAMPLE.ORG
Registry Domain ID: 123
Registrar: Example Registrar LLC
Creation Date: 2001-02-03T04:05:06Z
Registry Expiry Date: 2027-02-03T04:05:06Z
Domain Status: clientTransferProhibited https://icann.org/epp#clientTransferProhibited
"""


def test_whois_parse():
    result = parse_whois(WHOIS_TEXT, "example.org")
    assert result.expiration_date == date(2027, 2, 3)
    assert result.registration_date == date(2001, 2, 3)
    assert result.registrar_name == "Example Registrar LLC"
    assert result.registry_statuses == ["clienttransferprohibited"]


def test_whois_not_found_and_mismatch():
    with pytest.raises(CheckError) as exc:
        parse_whois("No match for domain \"NOPE.ORG\".", "nope.org")
    assert exc.value.code == "not_found"
    with pytest.raises(CheckError):
        parse_whois(WHOIS_TEXT, "different.org")


def make_domain(**kw) -> Domain:
    base = dict(
        domain_name="example.com", normalized_domain_name="example.com", expiration_date=date(2026, 8, 13),
        expiration_source=DataSource.manual, service_status=ServiceStatus.unknown,
        service_status_source=DataSource.manual, renewal_status=RenewalStatus.unknown,
        renewal_confirmed_for_date=None, registrar_name="Saved Registrar", registration_date=None,
        registry_statuses=[],
    )
    base.update(kw)
    return Domain(**base)


def test_reconcile_applies_forward_date_as_confirmed_renewal():
    domain = make_domain()
    result = LookupResult(source="rdap:x", expiration_date=date(2027, 8, 13), registry_statuses=["active"])
    changes, conflicts = reconcile(domain, result, TODAY, NOW)
    assert domain.expiration_date == date(2027, 8, 13)
    assert domain.expiration_source == DataSource.rdap
    assert domain.renewal_status == RenewalStatus.renewed
    assert domain.renewal_confirmed_for_date == date(2026, 8, 13)
    assert domain.service_status == ServiceStatus.active
    assert "expiration_date" in changes and not conflicts


def test_reconcile_never_clears_missing_fields():
    domain = make_domain()
    result = LookupResult(source="rdap:x", missing=["expiration_date", "registrar_name"])
    reconcile(domain, result, TODAY, NOW)
    assert domain.expiration_date == date(2026, 8, 13)
    assert domain.registrar_name == "Saved Registrar"


def test_reconcile_earlier_than_manual_date_is_conflict():
    domain = make_domain(expiration_date=date(2027, 8, 13))
    result = LookupResult(source="rdap:x", expiration_date=date(2026, 8, 13))
    changes, conflicts = reconcile(domain, result, TODAY, NOW)
    assert domain.expiration_date == date(2027, 8, 13)
    assert "expiration_date" in conflicts and "expiration_date" not in changes


def test_reconcile_auto_renew_grace_is_not_a_confirmed_renewal():
    domain = make_domain()
    result = LookupResult(source="rdap:x", expiration_date=date(2027, 8, 13), registry_statuses=["auto renew period"])
    _, conflicts = reconcile(domain, result, TODAY, NOW)
    assert domain.expiration_date == date(2026, 8, 13)
    assert domain.renewal_status == RenewalStatus.unknown
    assert "expiration_date" in conflicts


def test_reconcile_does_not_overwrite_manual_suspension():
    domain = make_domain(service_status=ServiceStatus.suspended, service_status_source=DataSource.manual)
    result = LookupResult(source="rdap:x", expiration_date=date(2026, 8, 13), registry_statuses=["active"])
    _, conflicts = reconcile(domain, result, TODAY, NOW)
    assert domain.service_status == ServiceStatus.suspended
    assert conflicts["service_status"]["observed"] == "active"


def test_reconcile_redemption_period_marks_expired():
    domain = make_domain(expiration_date=date(2026, 5, 1))
    result = LookupResult(source="rdap:x", expiration_date=date(2026, 5, 1), registry_statuses=["redemption period"])
    reconcile(domain, result, TODAY, NOW)
    assert domain.service_status == ServiceStatus.expired
    assert domain.renewal_status == RenewalStatus.not_renewed


def test_derive_status():
    assert derive_domain_status(["client hold"], date(2027, 1, 1), TODAY) == (ServiceStatus.suspended, None)
    assert derive_domain_status(["clientHold"], date(2027, 1, 1), TODAY) == (ServiceStatus.suspended, None)
    assert derive_domain_status([], date(2027, 1, 1), TODAY) == (ServiceStatus.active, None)
    # Past date without registry evidence: no inference.
    assert derive_domain_status([], date(2026, 1, 1), TODAY) == (None, None)


def test_reconcile_hosting_provider_status():
    hosting = HostingAccount(
        name="Main", provider_name="Acme", expiration_date=None, expiration_source=DataSource.manual,
        service_status=ServiceStatus.unknown, service_status_source=DataSource.manual,
        renewal_status=RenewalStatus.unknown, purchase_date=None,
    )
    result = LookupResult(source="provider:whmcs", expiration_date=date(2027, 1, 1),
                          service_status=ServiceStatus.active, registration_date=date(2024, 1, 1))
    reconcile(hosting, result, TODAY, NOW)
    assert hosting.expiration_date == date(2027, 1, 1)
    assert hosting.expiration_source == DataSource.provider
    assert hosting.service_status == ServiceStatus.active
    assert hosting.purchase_date == date(2024, 1, 1)
    # First date learned is not a "renewal".
    assert hosting.renewal_status == RenewalStatus.unknown
