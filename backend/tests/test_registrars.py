"""Registrars: CRUD, domain/hosting kinds, linking from domains and hosting accounts."""

API = "/api/v1"


def make(client, name, **kw):
    r = client.post(f"{API}/registrars", json={"name": name, **kw})
    assert r.status_code == 201, r.text
    return r.json()


def test_create_and_list_by_kind(client):
    make(client, "Namecheap", for_domains=True, for_hosting=True)
    make(client, "GoDaddy", for_domains=True, for_hosting=False)
    make(client, "SiteGround", for_domains=False, for_hosting=True, website="siteground.com")
    names = lambda kind=None: [r["name"] for r in client.get(f"{API}/registrars", params={"kind": kind} if kind else {}).json()]  # noqa: E731
    assert names() == ["GoDaddy", "Namecheap", "SiteGround"]
    assert names("domain") == ["GoDaddy", "Namecheap"]
    assert names("hosting") == ["Namecheap", "SiteGround"]
    site = [r for r in client.get(f"{API}/registrars").json() if r["name"] == "SiteGround"][0]
    assert site["website"] == "https://siteground.com"


def test_validation(client):
    assert client.post(f"{API}/registrars", json={"name": "X", "for_domains": False, "for_hosting": False}).status_code == 422
    make(client, "Namecheap")
    r = client.post(f"{API}/registrars", json={"name": "namecheap"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "duplicate_registrar"


def test_domain_links_only_to_domain_registrar(client):
    domain_reg = make(client, "GoDaddy", for_domains=True)
    hosting_only = make(client, "SiteGround", for_domains=False, for_hosting=True)
    r = client.post(f"{API}/domains", json={"domain_name": "a.com", "registrar_id": hosting_only["id"]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_registrar"
    d = client.post(f"{API}/domains", json={"domain_name": "a.com", "registrar_id": domain_reg["id"]}).json()
    assert d["registrar"] == {"id": domain_reg["id"], "name": "GoDaddy"}
    listed = client.get(f"{API}/domains", params={"registrar_id": domain_reg["id"]}).json()
    assert [x["domain_name"] for x in listed["items"]] == ["a.com"]
    assert client.get(f"{API}/domains", params={"search": "godaddy"}).json()["total"] == 1


def test_hosting_company_from_registrar(client):
    reg = make(client, "SiteGround", for_domains=False, for_hosting=True)
    h = client.post(f"{API}/hosting-accounts", json={"name": "Main", "registrar_id": reg["id"]}).json()
    assert h["provider_name"] == "SiteGround" and h["registrar"]["name"] == "SiteGround"
    # Free-text company still works without a registrar.
    other = client.post(f"{API}/hosting-accounts", json={"name": "Other", "provider_name": "Local Host Ltd"}).json()
    assert other["registrar"] is None and other["provider_name"] == "Local Host Ltd"
    # Neither given: rejected.
    assert client.post(f"{API}/hosting-accounts", json={"name": "Nothing"}).status_code == 422
    # Renaming the registrar renames the company shown on its hosting accounts.
    client.patch(f"{API}/registrars/{reg['id']}", json={"name": "SiteGround Hosting"})
    assert client.get(f"{API}/hosting-accounts/{h['id']}").json()["provider_name"] == "SiteGround Hosting"
    # Switching to "other" keeps the typed name.
    r = client.patch(f"{API}/hosting-accounts/{h['id']}", json={"registrar_id": None, "provider_name": "Typed Co"})
    assert r.json()["registrar"] is None and r.json()["provider_name"] == "Typed Co"


def test_cannot_remove_kind_in_use(client):
    reg = make(client, "Namecheap", for_domains=True, for_hosting=True)
    client.post(f"{API}/domains", json={"domain_name": "a.com", "registrar_id": reg["id"]})
    r = client.patch(f"{API}/registrars/{reg['id']}", json={"for_domains": False})
    assert r.status_code == 409 and r.json()["error"]["code"] == "registrar_in_use"
    assert client.patch(f"{API}/registrars/{reg['id']}", json={"for_hosting": False}).status_code == 200


def test_delete_keeps_records(client):
    reg = make(client, "Namecheap", for_domains=True, for_hosting=True)
    d = client.post(f"{API}/domains", json={"domain_name": "keep.com", "registrar_id": reg["id"]}).json()
    h = client.post(f"{API}/hosting-accounts", json={"name": "Plan", "registrar_id": reg["id"]}).json()
    counts = client.get(f"{API}/registrars").json()[0]
    assert (counts["domain_count"], counts["hosting_count"]) == (1, 1)
    assert client.delete(f"{API}/registrars/{reg['id']}").status_code == 204
    assert client.get(f"{API}/domains/{d['id']}").json()["registrar"] is None
    hosting = client.get(f"{API}/hosting-accounts/{h['id']}").json()
    assert hosting["registrar"] is None and hosting["provider_name"] == "Namecheap"


def test_registrars_require_login(anon_client):
    assert anon_client.get(f"{API}/registrars").status_code == 401
