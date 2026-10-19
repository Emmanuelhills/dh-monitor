import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.api.common import (
    Clock,
    ExpirationWindow,
    Pagination,
    SortOrder,
    change_history,
    check_history,
    count_of,
    ensure_editable,
    expiration_window_clause,
    get_clock,
    get_pagination,
)
from app.api.deps import AuthContext, require_admin
from app.api.errors import ApiError, not_found
from app.api.registrars import RegistrarKind, validate_registrar
from app.db import get_db
from app.models import (
    DataSource,
    Domain,
    HostingAccount,
    MonitoringCheck,
    Registrar,
    MonitoringStatus,
    ServiceStatus,
    UsageStatus,
)
from app.schemas import (
    AuditEventOut,
    CheckQueuedOut,
    DomainCreate,
    DomainOut,
    DomainUpdate,
    MonitoringCheckOut,
    Page,
)
from app.services.audit import record_audit
from app.services.domain_names import normalize_domain_name
from app.services.queue import enqueue_check
from app.services.records import apply_record_update, cancel_obsolete_notifications, domain_out, refresh_monitoring_mode

router = APIRouter(prefix="/domains", tags=["domains"])

SORT_FIELDS = {"name", "expiration_date", "created_at", "updated_at"}


def _get(db: Session, domain_id: uuid.UUID) -> Domain:
    domain = db.scalar(
        select(Domain).options(joinedload(Domain.hosting_account), joinedload(Domain.registrar))
        .where(Domain.id == domain_id)
        .execution_options(populate_existing=True)
    )
    if domain is None:
        raise not_found("Domain")
    return domain


def _validate_hosting(db: Session, hosting_id: uuid.UUID | None) -> None:
    if hosting_id is None:
        return
    hosting = db.get(HostingAccount, hosting_id)
    if hosting is None:
        raise ApiError(422, "invalid_hosting_account", "The selected hosting account does not exist.")
    if hosting.deleted_at is not None:
        raise ApiError(422, "invalid_hosting_account", "The selected hosting account is archived.")


def _ensure_unique(db: Session, normalized: str, exclude_id: uuid.UUID | None = None) -> None:
    stmt = select(Domain.id).where(Domain.normalized_domain_name == normalized, Domain.deleted_at.is_(None))
    if exclude_id:
        stmt = stmt.where(Domain.id != exclude_id)
    if db.scalar(stmt) is not None:
        raise ApiError(409, "duplicate_domain", f"{normalized} is already in the inventory.")


@router.get("", response_model=Page[DomainOut])
def list_domains(
    search: str | None = Query(None, max_length=255),
    hosting_account_id: str | None = Query(None, description="Hosting account id, or 'unassigned'"),
    registrar_id: str | None = Query(None, description="Registrar id, or 'none'"),
    provider_name: str | None = Query(None, max_length=255),
    usage_status: UsageStatus | None = None,
    service_status: ServiceStatus | None = None,
    monitoring_status: MonitoringStatus | None = None,
    expiration: ExpirationWindow | None = None,
    include_archived: bool = False,
    archived_only: bool = False,
    sort: str = Query("name"),
    order: SortOrder = SortOrder.asc,
    pagination: Pagination = Depends(get_pagination),
    clock: Clock = Depends(get_clock),
    _: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if sort not in SORT_FIELDS:
        raise ApiError(422, "invalid_sort", f"sort must be one of: {', '.join(sorted(SORT_FIELDS))}.")
    stmt = (
        select(Domain)
        .outerjoin(HostingAccount, Domain.hosting_account_id == HostingAccount.id)
        .outerjoin(Registrar, Domain.registrar_id == Registrar.id)
    )
    if archived_only:
        stmt = stmt.where(Domain.deleted_at.is_not(None))
    elif not include_archived:
        stmt = stmt.where(Domain.deleted_at.is_(None))
    if search:
        term = f"%{search.strip().lower()}%"
        stmt = stmt.where(
            or_(
                Domain.normalized_domain_name.like(term),
                func.lower(Domain.domain_name).like(term),
                func.lower(Domain.registrar_name).like(term),
                func.lower(HostingAccount.name).like(term),
                func.lower(Registrar.name).like(term),
            )
        )
    if hosting_account_id:
        if hosting_account_id == "unassigned":
            stmt = stmt.where(Domain.hosting_account_id.is_(None))
        else:
            try:
                stmt = stmt.where(Domain.hosting_account_id == uuid.UUID(hosting_account_id))
            except ValueError:
                raise ApiError(422, "invalid_filter", "hosting_account_id must be a UUID or 'unassigned'.") from None
    if registrar_id:
        if registrar_id == "none":
            stmt = stmt.where(Domain.registrar_id.is_(None))
        else:
            try:
                stmt = stmt.where(Domain.registrar_id == uuid.UUID(registrar_id))
            except ValueError:
                raise ApiError(422, "invalid_filter", "registrar_id must be a UUID or 'none'.") from None
    if provider_name:
        stmt = stmt.where(func.lower(HostingAccount.provider_name) == provider_name.strip().lower())
    if usage_status:
        stmt = stmt.where(Domain.usage_status == usage_status)
    if service_status:
        stmt = stmt.where(Domain.service_status == service_status)
    if monitoring_status:
        stmt = stmt.where(Domain.monitoring_status == monitoring_status)
    if expiration:
        stmt = stmt.where(expiration_window_clause(Domain.expiration_date, expiration, clock.today))

    total = count_of(db, stmt)
    column = {
        "name": Domain.normalized_domain_name,
        "expiration_date": Domain.expiration_date,
        "created_at": Domain.created_at,
        "updated_at": Domain.updated_at,
    }[sort]
    primary = column.asc() if order == SortOrder.asc else column.desc()
    stmt = stmt.order_by(primary.nulls_last(), Domain.normalized_domain_name.asc(), Domain.id.asc())
    rows = db.scalars(
        stmt.options(joinedload(Domain.hosting_account), joinedload(Domain.registrar))
        .offset(pagination.offset).limit(pagination.page_size)
    ).all()
    return {
        "items": [domain_out(d, clock.today, clock.now, clock.settings) for d in rows],
        "total": total,
        "page": pagination.page,
        "page_size": pagination.page_size,
    }


@router.post("", response_model=DomainOut, status_code=201)
def create_domain(
    body: DomainCreate,
    clock: Clock = Depends(get_clock),
    ctx: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
):
    normalized = normalize_domain_name(body.domain_name)
    _ensure_unique(db, normalized)
    _validate_hosting(db, body.hosting_account_id)
    validate_registrar(db, body.registrar_id, RegistrarKind.domain)
    data = body.model_dump(exclude_unset=True, exclude={"domain_name"})
    domain = Domain(
        domain_name=body.domain_name.strip().lower(),
        normalized_domain_name=normalized,
        hosting_account_id=data.pop("hosting_account_id", None),
        registrar_id=data.pop("registrar_id", None),
        registration_date=data.pop("registration_date", None),
        registrar_name=data.pop("registrar_name", None),
        expiration_date=data.pop("expiration_date", None),
        expiration_source=DataSource.manual,
        usage_status=data.pop("usage_status", None) or UsageStatus.active,
        service_status=data.pop("service_status", None) or ServiceStatus.unknown,
        service_status_source=DataSource.manual,
        auto_check_enabled=data.pop("auto_check_enabled", None) is not False,
        notifications_enabled=data.pop("notifications_enabled", None) is not False,
        notes=data.pop("notes", None),
        registry_statuses=[],
        monitoring_status=MonitoringStatus.due,
    )
    if "renewal_status" in data and data["renewal_status"] is not None:
        apply_record_update(domain, {"renewal_status": data["renewal_status"]})
    refresh_monitoring_mode(domain, clock.now)
    db.add(domain)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise ApiError(409, "duplicate_domain", f"{normalized} is already in the inventory.") from None
    record_audit(db, "domain_created", user=ctx.user, record_type="domain", record_id=domain.id,
                 details={"domain_name": normalized}, ip_address=ctx.ip)
    db.commit()
    if domain.auto_check_enabled:
        enqueue_check(db, domain)
    return domain_out(_get(db, domain.id), clock.today, clock.now, clock.settings)


@router.get("/{domain_id}", response_model=DomainOut)
def get_domain(
    domain_id: uuid.UUID, clock: Clock = Depends(get_clock), _: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return domain_out(_get(db, domain_id), clock.today, clock.now, clock.settings)


@router.patch("/{domain_id}", response_model=DomainOut)
def update_domain(
    domain_id: uuid.UUID,
    body: DomainUpdate,
    clock: Clock = Depends(get_clock),
    ctx: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
):
    domain = _get(db, domain_id)
    ensure_editable(domain)
    updates = body.model_dump(exclude_unset=True)
    for required in ("usage_status", "service_status", "renewal_status", "auto_check_enabled", "notifications_enabled"):
        if required in updates and updates[required] is None:
            raise ApiError(422, "validation_error", f"{required} cannot be null.")
    if "domain_name" in updates:
        if updates["domain_name"] is None:
            raise ApiError(422, "validation_error", "domain_name cannot be null.")
        normalized = normalize_domain_name(updates["domain_name"])
        _ensure_unique(db, normalized, exclude_id=domain.id)
        updates["domain_name"] = updates["domain_name"].strip().lower()
        if normalized != domain.normalized_domain_name:
            updates["normalized_domain_name"] = normalized
            # Registration facts belonged to the old name.
            updates.setdefault("registry_statuses", [])
    if "hosting_account_id" in updates:
        _validate_hosting(db, updates["hosting_account_id"])
    if "registrar_id" in updates:
        validate_registrar(db, updates["registrar_id"], RegistrarKind.domain)

    changes = apply_record_update(domain, updates)
    if "normalized_domain_name" in changes and domain.auto_check_enabled:
        domain.next_check_at = clock.now
    if changes:
        cancel_obsolete_notifications(db, domain, clock.settings)
        record_audit(db, "domain_updated", user=ctx.user, record_type="domain", record_id=domain.id,
                     details={"changes": changes}, ip_address=ctx.ip)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ApiError(409, "duplicate_domain", "That domain name is already in the inventory.") from None
    return domain_out(_get(db, domain.id), clock.today, clock.now, clock.settings)


@router.delete("/{domain_id}", status_code=204)
def delete_domain(
    domain_id: uuid.UUID,
    permanent: bool = False,
    clock: Clock = Depends(get_clock),
    ctx: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Archive (default) or permanently delete a domain. Never touches its hosting account."""
    domain = _get(db, domain_id)
    if permanent:
        record_audit(db, "domain_deleted", user=ctx.user, record_type="domain", record_id=domain.id,
                     details={"domain_name": domain.normalized_domain_name}, ip_address=ctx.ip)
        db.delete(domain)
    elif domain.deleted_at is None:
        domain.deleted_at = datetime.now(timezone.utc)
        domain.next_check_at = None
        cancel_obsolete_notifications(db, domain, clock.settings)
        record_audit(db, "domain_archived", user=ctx.user, record_type="domain", record_id=domain.id,
                     ip_address=ctx.ip)
    db.commit()
    return Response(status_code=204)


@router.post("/{domain_id}/restore", response_model=DomainOut)
def restore_domain(
    domain_id: uuid.UUID, clock: Clock = Depends(get_clock), ctx: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
):
    domain = _get(db, domain_id)
    if domain.deleted_at is None:
        return domain_out(domain, clock.today, clock.now, clock.settings)
    _ensure_unique(db, domain.normalized_domain_name, exclude_id=domain.id)
    domain.deleted_at = None
    if domain.hosting_account and domain.hosting_account.deleted_at is not None:
        domain.hosting_account_id = None
    domain.next_check_at = None
    refresh_monitoring_mode(domain, clock.now)
    record_audit(db, "domain_restored", user=ctx.user, record_type="domain", record_id=domain.id, ip_address=ctx.ip)
    db.commit()
    return domain_out(_get(db, domain.id), clock.today, clock.now, clock.settings)


@router.post("/{domain_id}/check", response_model=CheckQueuedOut, status_code=202)
def check_domain(domain_id: uuid.UUID, ctx: AuthContext = Depends(require_admin), db: Session = Depends(get_db)):
    domain = _get(db, domain_id)
    ensure_editable(domain)
    result = enqueue_check(db, domain)
    if result["status"] == "queued":
        record_audit(db, "check_requested", user=ctx.user, record_type="domain", record_id=domain.id, ip_address=ctx.ip)
        db.commit()
    return result


@router.get("/{domain_id}/checks", response_model=Page[MonitoringCheckOut])
def domain_checks(
    domain_id: uuid.UUID, pagination: Pagination = Depends(get_pagination), _: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
):
    _get(db, domain_id)
    return check_history(db, MonitoringCheck.domain_id, domain_id, pagination)


@router.get("/{domain_id}/changes", response_model=Page[AuditEventOut])
def domain_changes(
    domain_id: uuid.UUID, pagination: Pagination = Depends(get_pagination), _: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
):
    _get(db, domain_id)
    return change_history(db, "domain", domain_id, pagination)

