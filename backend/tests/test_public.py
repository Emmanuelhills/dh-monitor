"""The public overview is readable without signing in and exposes only safe fields."""

API = "/api/v1"


def _seed(client):
    h = client.post(f"{API}/hosting-accounts", json={
        "name": "Main hosting", "provider_name": "Acme", "admin_url": "https://secret-panel.test",
        "notes": "hosting-private-note", "expiration_date": "2027-01-01",
    }).json()
    client.post(f"{API}/domains", json={
        "domain_name": "shown.com", "hosting_account_id": h["id"], "expiration_date": "2026-12-01",
        "notes": "domain-private-note", "registrar_name": "Private Registrar", "usage_status": "inactive",
    })
    archived = client.post(f"{API}/domains", json={"domain_name": "archived.com"}).json()
    client.delete(f"{API}/domains/{archived['id']}")
    return h


def test_public_overview_without_login(client, anon_client):
    _seed(client)
    r = anon_client.get(f"{API}/public/overview")
    assert r.status_code == 200
    body = r.json()
    assert [d["domain_name"] for d in body["domains"]] == ["shown.com"]
    domain = body["domains"][0]
    assert domain["hosting_account"] == "Main hosting"
    assert domain["usage_status"] == "inactive"
    assert domain["expiration_date"] == "2026-12-01"
    assert body["hosting"][0]["domain_count"] == 1


def test_public_overview_hides_private_fields(client, anon_client):
    _seed(client)
    text = anon_client.get(f"{API}/public/overview").text
    for secret in ("secret-panel", "private-note", "Private Registrar", "admin_url", "notes", "last_check_error"):
        assert secret not in text


def test_public_overview_can_be_disabled(client, anon_client):
    assert client.patch(f"{API}/settings", json={"public_page_enabled": False}).json()["public_page_enabled"] is False
    r = anon_client.get(f"{API}/public/overview")
    assert r.status_code == 404 and r.json()["error"]["code"] == "public_page_disabled"


def test_management_endpoints_still_require_login(anon_client):
    assert anon_client.get(f"{API}/domains").status_code == 401
    assert anon_client.get(f"{API}/settings").status_code == 401
