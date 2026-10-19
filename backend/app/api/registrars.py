"""Registrars: companies that sell domain names, hosting plans, or both."""

import uuid
from enum import Enum

from fastapi import APIRouter, Depends, Response
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, require_admin
from app.api.errors import ApiError, not_found
from app.db import get_db
from app.models import Domain, HostingAccount, Registrar
from app.schemas import RegistrarIn, RegistrarOut
from app.services.audit import diff_fields, record_audit

router = APIRouter(prefix="/registrars", tags=["registrars"])


class RegistrarKind(str, Enum):
    domain = "domain"
    hosting = "hosting"


def _counts(db: Session, registrar_id: uuid.UUID) -> tuple[int, int]:
    domains = db.scalar(
        select(func.count()).select_from(Domain)
        .where(Domain.registrar_id == registrar_id, Domain.deleted_at.is_(None))
    )
    hosting = db.scalar(
        select(func.count()).select_from(HostingAccount)
        .where(HostingAccount.registrar_id == registrar_id, HostingAccount.deleted_at.is_(None))
    )
    return domains or 0, hosting or 0


def _out(db: Session, r: Registrar) -> dict:
    domains, hosting = _counts(db, r.id)
    return {
        "id": r.id, "name": r.name, "website": r.website, "notes": r.notes,
        "for_domains": r.for_domains, "for_hosting": r.for_hosting,
        "domain_count": domains, "hosting_count": hosting,
        "created_at": r.created_at, "updated_at": r.updated_at,
    }


def _ensure_unique(db: Session, name: str, exclude: uuid.UUID | None = None) -> None:
    stmt = select(Registrar.id).where(func.lower(Registrar.name) == name.lower())
    if exclude:
        stmt = stmt.where(Registrar.id != exclude)
    if db.scalar(stmt):
        raise ApiError(409, "duplicate_registrar", f"A registrar named '{name}' already exists.")


def _get(db: Session, registrar_id: uuid.UUID) -> Registrar:
    registrar = db.get(Registrar, registrar_id)
    if registrar is None:
        raise not_found("Registrar")
    return registrar


@router.get("", response_model=list[RegistrarOut])
def list_registrars(
    kind: RegistrarKind | None = None, _: AuthContext = Depends(require_admin), db: Session = Depends(get_db)
):
    stmt = select(Registrar).order_by(func.lower(Registrar.name))
    if kind == RegistrarKind.domain:
        stmt = stmt.where(Registrar.for_domains.is_(True))
    elif kind == RegistrarKind.hosting:
        stmt = stmt.where(Registrar.for_hosting.is_(True))
    return [_out(db, r) for r in db.scalars(stmt)]


@router.post("", response_model=RegistrarOut, status_code=201)
def create_registrar(body: RegistrarIn, ctx: AuthContext = Depends(require_admin), db: Session = Depends(get_db)):
    if not body.name:
        raise ApiError(422, "validation_error", "Name is required.", [{"field": "name", "message": "Enter a name."}])
    for_domains = body.for_domains if body.for_domains is not None else True
    for_hosting = bool(body.for_hosting)
    if not (for_domains or for_hosting):
        raise ApiError(422, "invalid_kind", "Tick domain names, hosting, or both.")
    _ensure_unique(db, body.name)
    registrar = Registrar(name=body.name, website=body.website, notes=body.notes,
                          for_domains=for_domains, for_hosting=for_hosting)
    db.add(registrar)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise ApiError(409, "duplicate_registrar", f"A registrar named '{body.name}' already exists.") from None
    record_audit(db, "registrar_created", user=ctx.user, record_type="registrar", record_id=registrar.id,
                 details={"name": registrar.name}, ip_address=ctx.ip)
    db.commit()
    return _out(db, registrar)


@router.patch("/{registrar_id}", response_model=RegistrarOut)
def update_registrar(
    registrar_id: uuid.UUID, body: RegistrarIn, ctx: AuthContext = Depends(require_admin), db: Session = Depends(get_db)
):
    registrar = _get(db, registrar_id)
    data = body.model_dump(exclude_unset=True)
    for field in ("name", "for_domains", "for_hosting"):
        if field in data and data[field] is None:
            raise ApiError(422, "validation_error", f"{field} cannot be null.")
    for_domains = data.get("for_domains", registrar.for_domains)
    for_hosting = data.get("for_hosting", registrar.for_hosting)
    if not (for_domains or for_hosting):
        raise ApiError(422, "invalid_kind", "Tick domain names, hosting, or both.")
    domains, hosting = _counts(db, registrar.id)
    if not for_domains and domains:
        raise ApiError(409, "registrar_in_use", f"{domains} domain(s) use this registrar. Reassign them first.")
    if not for_hosting and hosting:
        raise ApiError(409, "registrar_in_use", f"{hosting} hosting account(s) use this registrar. Reassign them first.")
    if "name" in data:
        _ensure_unique(db, data["name"], exclude=registrar.id)

    changes = diff_fields(registrar, data)
    for field, value in data.items():
        setattr(registrar, field, value)
    if "name" in changes:
        # Hosting accounts display their company name; keep it in sync.
        db.execute(update(HostingAccount).where(HostingAccount.registrar_id == registrar.id)
                   .values(provider_name=registrar.name))
    if changes:
        record_audit(db, "registrar_updated", user=ctx.user, record_type="registrar", record_id=registrar.id,
                     details={"changes": changes}, ip_address=ctx.ip)
    db.commit()
    return _out(db, registrar)


@router.delete("/{registrar_id}", status_code=204)
def delete_registrar(registrar_id: uuid.UUID, ctx: AuthContext = Depends(require_admin), db: Session = Depends(get_db)):
    """Linked domains and hosting accounts are kept; their registrar link is cleared
    (hosting accounts keep the company name as text)."""
    registrar = _get(db, registrar_id)
    domains, hosting = _counts(db, registrar.id)
    record_audit(db, "registrar_deleted", user=ctx.user, record_type="registrar", record_id=registrar.id,
                 details={"name": registrar.name, "unlinked_domains": domains, "unlinked_hosting": hosting},
                 ip_address=ctx.ip)
    db.delete(registrar)
    db.commit()
    return Response(status_code=204)


def validate_registrar(db: Session, registrar_id: uuid.UUID | None, kind: RegistrarKind) -> Registrar | None:
    """Used by the domain and hosting endpoints."""
    if registrar_id is None:
        return None
    registrar = db.get(Registrar, registrar_id)
    if registrar is None:
        raise ApiError(422, "invalid_registrar", "The selected registrar does not exist.")
    if kind == RegistrarKind.domain and not registrar.for_domains:
        raise ApiError(422, "invalid_registrar", f"{registrar.name} is not set up as a domain registrar.")
    if kind == RegistrarKind.hosting and not registrar.for_hosting:
        raise ApiError(422, "invalid_registrar", f"{registrar.name} is not set up as a hosting provider.")
    return registrar
