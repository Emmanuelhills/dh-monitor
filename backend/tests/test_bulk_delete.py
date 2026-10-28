"""Bulk delete for domains, hosting accounts and registrars."""

import uuid

from sqlalchemy import func, select

from app.models import AuditEvent, Domain, HostingAccount, Registrar
from tests.test_api_records import create_domain, create_hosting

API = "/api/v1"


def _audits(db, action: str) -> int:
    return db.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.action == action))


def test_bulk_archive_domains(client, db):
    a, b, keep = (create_domain(client, n) for n in ("a.com", "b.com", "keep.com"))
    r = client.post(f"{API}/domains/bulk-delete", json={"ids": [a["id"], b["id"], a["id"]]})
    assert r.status_code == 200, r.text
    assert r.json() == {"deleted": 2}
    names = [d["domain_name"] for d in client.get(f"{API}/domains").json()["items"]]
    assert names == ["keep.com"]
    assert db.get(Domain, uuid.UUID(a["id"])).deleted_at is not None  # archived, not removed
    assert _audits(db, "domain_archived") == 2


def test_bulk_permanent_delete_domains(client, db):
    a, b = create_domain(client, "a.com"), create_domain(client, "b.com")
    r = client.post(f"{API}/domains/bulk-delete", json={"ids": [a["id"], b["id"]], "permanent": True})
    assert r.json() == {"deleted": 2}
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(Domain)) == 0
    assert _audits(db, "domain_deleted") == 2


def test_bulk_delete_hosting_keeps_domains(client, db):
    h1, h2 = create_hosting(client, name="One"), create_hosting(client, name="Two")
    d = create_domain(client, "survivor.com", hosting_account_id=h1["id"])
    r = client.post(f"{API}/hosting-accounts/bulk-delete", json={"ids": [h1["id"], h2["id"]], "permanent": True})
    assert r.json() == {"deleted": 2}
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(HostingAccount)) == 0
    domain = client.get(f"{API}/domains/{d['id']}").json()
    assert domain["hosting_account"] is None and domain["archived_at"] is None


def test_bulk_archive_hosting(client, db):
    h = create_hosting(client)
    assert client.post(f"{API}/hosting-accounts/bulk-delete", json={"ids": [h["id"]]}).json() == {"deleted": 1}
    assert db.get(HostingAccount, uuid.UUID(h["id"])).deleted_at is not None
    assert _audits(db, "hosting_archived") == 1


def test_bulk_delete_registrars_unlinks_records(client, db):
    regs = [client.post(f"{API}/registrars", json={"name": n, "for_domains": True, "for_hosting": True}).json()
            for n in ("Namecheap", "GoDaddy", "Keep")]
    d = create_domain(client, "linked.com", registrar_id=regs[0]["id"])
    h = create_hosting(client, registrar_id=regs[1]["id"], provider_name=None)
    r = client.post(f"{API}/registrars/bulk-delete", json={"ids": [regs[0]["id"], regs[1]["id"]]})
    assert r.json() == {"deleted": 2}
    db.expire_all()
    assert [x.name for x in db.scalars(select(Registrar))] == ["Keep"]
    assert db.get(Domain, uuid.UUID(d["id"])) is not None
    assert db.get(Domain, uuid.UUID(d["id"])).registrar_id is None
    hosting = db.get(HostingAccount, uuid.UUID(h["id"]))
    assert hosting.registrar_id is None and hosting.provider_name == "GoDaddy"
    assert _audits(db, "registrar_deleted") == 2


def test_unknown_id_changes_nothing(client, db):
    a = create_domain(client, "a.com")
    r = client.post(f"{API}/domains/bulk-delete", json={"ids": [a["id"], str(uuid.uuid4())], "permanent": True})
    assert r.status_code == 404
    db.expire_all()
    assert db.get(Domain, uuid.UUID(a["id"])) is not None


def test_validation_limits(client):
    assert client.post(f"{API}/domains/bulk-delete", json={"ids": []}).status_code == 422
    too_many = [str(uuid.uuid4()) for _ in range(501)]
    assert client.post(f"{API}/registrars/bulk-delete", json={"ids": too_many}).status_code == 422


def test_requires_sign_in_and_csrf(client, anon_client):
    body = {"ids": [str(uuid.uuid4())]}
    for path in ("domains", "hosting-accounts", "registrars"):
        assert anon_client.post(f"{API}/{path}/bulk-delete", json=body).status_code == 401
    del client.headers["X-CSRF-Token"]
    for path in ("domains", "hosting-accounts", "registrars"):
        assert client.post(f"{API}/{path}/bulk-delete", json=body).status_code == 403
