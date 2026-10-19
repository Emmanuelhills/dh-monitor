"""Integration tests: authentication, domain/hosting CRUD, relationships, filters, privacy."""

from datetime import date, timedelta

from app.models import Domain, HostingAccount
from tests.conftest import ADMIN_EMAIL

API = "/api/v1"


def create_hosting(client, **kw):
    body = {"name": "Main hosting", "provider_name": "Acme Hosting", "admin_url": "https://panel.acme.test/secret"}
    body.update(kw)
    r = client.post(f"{API}/hosting-accounts", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def create_domain(client, name="example.com", **kw):
    r = client.post(f"{API}/domains", json={"domain_name": name, **kw})
    assert r.status_code == 201, r.text
    return r.json()


# --------------------------------------------------------------------------- auth & security


def test_requires_authentication(anon_client):
    assert anon_client.get(f"{API}/domains").status_code == 401
    assert anon_client.get(f"{API}/dashboard").status_code == 401
    assert anon_client.get(f"{API}/notifications/settings").status_code == 401


def test_state_changes_require_csrf_token(client):
    token = client.headers.pop("X-CSRF-Token")
    r = client.post(f"{API}/domains", json={"domain_name": "example.com"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "csrf_failed"
    client.headers["X-CSRF-Token"] = token
    assert client.post(f"{API}/domains", json={"domain_name": "example.com"}).status_code == 201


def test_login_rate_limit(anon_client, admin_user):
    for _ in range(5):
        assert anon_client.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": "wrong"}).status_code == 401
    r = anon_client.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": "wrong"})
    assert r.status_code == 429


def test_session_cookie_is_httponly(anon_client, admin_user):
    from tests.conftest import ADMIN_PASSWORD

    r = anon_client.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie


def test_logout_invalidates_session(client):
    assert client.post(f"{API}/auth/logout").status_code == 204
    assert client.get(f"{API}/auth/me").status_code == 401


# --------------------------------------------------------------------------- domains


def test_domain_create_normalizes_and_rejects_duplicates(client, queued_tasks):
    d = create_domain(client, "  HTTPS://Example.COM/ ")
    assert d["normalized_domain_name"] == "example.com"
    assert d["hosting_account"] is None
    assert d["monitoring_status"] == "due"
    assert ("dhm.check_record", ("domain", d["id"])) in queued_tasks  # check queued, not run inline
    r = client.post(f"{API}/domains", json={"domain_name": "example.com."})
    assert r.status_code == 409 and r.json()["error"]["code"] == "duplicate_domain"


def test_domain_validation_errors_are_structured(client):
    r = client.post(f"{API}/domains", json={"domain_name": "not a domain"})
    assert r.status_code == 422
    body = r.json()["error"]
    assert body["code"] == "validation_error"
    assert body["details"][0]["field"] == "domain_name"
    r = client.post(f"{API}/domains", json={"domain_name": "ok.com", "expiration_date": "31/12/2026"})
    assert r.status_code == 422
    r = client.post(f"{API}/domains", json={"domain_name": "ok.com", "usage_status": "maybe"})
    assert r.status_code == 422


def test_archived_name_can_be_reused(client):
    d = create_domain(client, "reuse.com")
    assert client.delete(f"{API}/domains/{d['id']}").status_code == 204
    create_domain(client, "reuse.com")
    # Restoring the archived one would now be a duplicate.
    assert client.post(f"{API}/domains/{d['id']}/restore").status_code == 409


def test_many_domains_per_hosting_and_unassigned(client):
    h = create_hosting(client)
    a = create_domain(client, "alpha.com", hosting_account_id=h["id"])
    create_domain(client, "beta.com", hosting_account_id=h["id"])
    create_domain(client, "gamma.com")
    assert a["hosting_account"]["name"] == "Main hosting"

    detail = client.get(f"{API}/hosting-accounts/{h['id']}").json()
    assert detail["domain_count"] == 2
    assert [d["domain_name"] for d in detail["domains"]] == ["alpha.com", "beta.com"]

    unassigned = client.get(f"{API}/domains", params={"hosting_account_id": "unassigned"}).json()
    assert [d["domain_name"] for d in unassigned["items"]] == ["gamma.com"]


def test_invalid_hosting_reference_rejected(client):
    r = client.post(f"{API}/domains", json={"domain_name": "x.com", "hosting_account_id": "00000000-0000-0000-0000-000000000000"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_hosting_account"


def test_changing_hosting_does_not_change_expiration(client):
    h1, h2 = create_hosting(client, name="One"), create_hosting(client, name="Two")
    d = create_domain(client, "stable.com", hosting_account_id=h1["id"], expiration_date="2027-03-01")
    r = client.patch(f"{API}/domains/{d['id']}", json={"hosting_account_id": h2["id"]})
    assert r.json()["expiration_date"] == "2027-03-01"
    assert r.json()["hosting_account"]["name"] == "Two"
    r = client.patch(f"{API}/domains/{d['id']}", json={"hosting_account_id": None})
    assert r.json()["hosting_account"] is None


def test_deleting_hosting_never_deletes_domains(client, db):
    h = create_hosting(client)
    d = create_domain(client, "survivor.com", hosting_account_id=h["id"])
    assert client.delete(f"{API}/hosting-accounts/{h['id']}", params={"permanent": "true"}).status_code == 204
    domain = client.get(f"{API}/domains/{d['id']}").json()
    assert domain["hosting_account"] is None
    assert domain["archived_at"] is None
    assert db.get(HostingAccount, h["id"]) is None


def test_usage_status_independent_of_expiration_and_service(client):
    d = create_domain(client, "idle.com", expiration_date=(date.today() - timedelta(days=3)).isoformat(),
                      service_status="active")
    r = client.patch(f"{API}/domains/{d['id']}", json={"usage_status": "inactive"})
    body = r.json()
    assert body["usage_status"] == "inactive"
    assert body["service_status"] == "active"
    assert body["expiration"]["urgency"] == "overdue"
    r = client.patch(f"{API}/domains/{d['id']}", json={"usage_status": "active"})
    assert r.json()["service_status"] == "active"


def test_expiration_date_moved_forward_marks_renewed_and_is_audited(client):
    d = create_domain(client, "renew.com", expiration_date="2026-11-01")
    r = client.patch(f"{API}/domains/{d['id']}", json={"expiration_date": "2027-11-01"})
    assert r.json()["renewal_status"] == "renewed"
    assert r.json()["renewal_confirmed_for_date"] == "2026-11-01"
    changes = client.get(f"{API}/domains/{d['id']}/changes").json()["items"]
    assert changes[0]["action"] == "domain_updated"
    assert changes[0]["details"]["changes"]["expiration_date"] == {"from": "2026-11-01", "to": "2027-11-01"}


def test_disabling_auto_check_sets_manual(client):
    d = create_domain(client, "manual.com", auto_check_enabled=False)
    assert d["monitoring_status"] == "manual"
    r = client.patch(f"{API}/domains/{d['id']}", json={"auto_check_enabled": True})
    assert r.json()["monitoring_status"] == "due"


def test_domain_sorting_and_filters(client, db):
    h = create_hosting(client, provider_name="Zeta Host")
    create_domain(client, "charlie.com", expiration_date="2027-01-01", usage_status="inactive")
    create_domain(client, "alpha.com", expiration_date="2028-01-01", hosting_account_id=h["id"])
    create_domain(client, "bravo.com")  # unknown expiration sorts last
    names = lambda r: [d["domain_name"] for d in r.json()["items"]]  # noqa: E731

    assert names(client.get(f"{API}/domains")) == ["alpha.com", "bravo.com", "charlie.com"]
    assert names(client.get(f"{API}/domains", params={"order": "desc"})) == ["charlie.com", "bravo.com", "alpha.com"]
    assert names(client.get(f"{API}/domains", params={"sort": "expiration_date"})) == ["charlie.com", "alpha.com", "bravo.com"]
    assert names(client.get(f"{API}/domains", params={"sort": "expiration_date", "order": "desc"})) == [
        "alpha.com", "charlie.com", "bravo.com"]
    assert names(client.get(f"{API}/domains", params={"usage_status": "inactive"})) == ["charlie.com"]
    assert names(client.get(f"{API}/domains", params={"provider_name": "zeta host"})) == ["alpha.com"]
    assert names(client.get(f"{API}/domains", params={"hosting_account_id": h["id"]})) == ["alpha.com"]
    assert names(client.get(f"{API}/domains", params={"monitoring_status": "due"})) == ["alpha.com", "bravo.com", "charlie.com"]
    assert names(client.get(f"{API}/domains", params={"search": "rav"})) == ["bravo.com"]
    assert names(client.get(f"{API}/domains", params={"expiration": "unknown"})) == ["bravo.com"]
    assert client.get(f"{API}/domains", params={"sort": "bogus"}).status_code == 422
    assert client.get(f"{API}/domains", params={"page_size": 500}).status_code == 422

    page = client.get(f"{API}/domains", params={"page_size": 2, "page": 2}).json()
    assert page["total"] == 3 and [d["domain_name"] for d in page["items"]] == ["charlie.com"]


# --------------------------------------------------------------------------- hosting


def test_hosting_admin_url_is_private(client):
    h = create_hosting(client)
    assert "admin_url" not in h and h["has_admin_url"] is True
    listing = client.get(f"{API}/hosting-accounts").json()
    assert "panel.acme.test" not in str(listing)
    detail = client.get(f"{API}/hosting-accounts/{h['id']}").json()
    assert "panel.acme.test" not in str(detail)
    # Changes log must not leak it either.
    client.patch(f"{API}/hosting-accounts/{h['id']}", json={"admin_url": "https://panel.acme.test/new"})
    assert "panel.acme.test" not in str(client.get(f"{API}/hosting-accounts/{h['id']}/changes").json())
    # Only the protected endpoint returns it.
    assert client.get(f"{API}/hosting-accounts/{h['id']}/admin-url").json() == {"admin_url": "https://panel.acme.test/new"}


def test_hosting_without_integration_is_manual(client):
    h = create_hosting(client)
    assert h["monitoring_status"] == "manual"
    r = client.post(f"{API}/hosting-accounts/{h['id']}/check")
    assert r.status_code == 202 and r.json()["status"] == "not_supported"


def test_hosting_sorting_filters(client):
    create_hosting(client, name="beta", provider_name="Acme", expiration_date="2027-05-01")
    create_hosting(client, name="Alpha", provider_name="Zeta", expiration_date="2026-12-01", service_status="suspended")
    create_hosting(client, name="gamma", provider_name="acme", usage_status="inactive")
    names = lambda r: [h["name"] for h in r.json()["items"]]  # noqa: E731
    assert names(client.get(f"{API}/hosting-accounts")) == ["Alpha", "beta", "gamma"]
    assert names(client.get(f"{API}/hosting-accounts", params={"order": "desc"})) == ["gamma", "beta", "Alpha"]
    assert names(client.get(f"{API}/hosting-accounts", params={"sort": "expiration_date"})) == ["Alpha", "beta", "gamma"]
    assert names(client.get(f"{API}/hosting-accounts", params={"provider_name": "ACME"})) == ["beta", "gamma"]
    assert names(client.get(f"{API}/hosting-accounts", params={"service_status": "suspended"})) == ["Alpha"]
    assert names(client.get(f"{API}/hosting-accounts", params={"usage_status": "inactive"})) == ["gamma"]
    assert [p.lower() for p in client.get(f"{API}/hosting-accounts/providers").json()] == ["acme", "zeta"]


def test_dashboard_counts(client):
    h = create_hosting(client, expiration_date=(date.today() + timedelta(days=5)).isoformat())
    create_domain(client, "a.com", hosting_account_id=h["id"], expiration_date=(date.today() + timedelta(days=10)).isoformat())
    create_domain(client, "b.com", usage_status="inactive")
    body = client.get(f"{API}/dashboard").json()
    assert body["domains"]["total"] == 2
    assert body["domains"]["inactive"] == 1
    assert body["domains"]["unknown_expiration"] == 1
    assert body["hosting"]["total"] == 1
    assert [u["name"] for u in body["upcoming"]] == ["Main hosting", "a.com"]


def test_archive_keeps_record_out_of_lists(client, db):
    d = create_domain(client, "old.com")
    client.delete(f"{API}/domains/{d['id']}")
    assert client.get(f"{API}/domains").json()["total"] == 0
    assert client.get(f"{API}/domains", params={"archived_only": True}).json()["total"] == 1
    assert db.get(Domain, d["id"]) is not None
    assert client.patch(f"{API}/domains/{d['id']}", json={"notes": "x"}).status_code == 409
