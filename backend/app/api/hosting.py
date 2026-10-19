import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, or_, select
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
    MonitoringStatus,
    ProviderIntegration,
    ServiceStatus,
    UsageStatus,
)
from app.schemas import (
    AdminUrlOut,
    AuditEventOut,
    CheckQueuedOut,
    HostingCreate,
    HostingDetailOut,
    HostingOut,
    HostingUpdate,
    MonitoringCheckOut,
    Page,
)
from app.services.audit import record_audit
from app.services.expiration import expiration_info
from app.services.queue import enqueue_check
from app.services.records import (
    active_domains_for_hosting,
    apply_record_update,
    cancel_obsolete_notifications,
    hosting_out,
    refresh_monitoring_mode,
)

router = APIRouter(prefix="/hosting-accounts", tags=["hosting"])

SORT_FIELDS = {"name", "expiration_date", "provider_name", "created_at", "updated_at", "domain_count"}


def _domain_count_subquery():
    return (
        select(func.count(Domain.id))
        .where(Domain.hosting_account_id == HostingAccount.id, Domain.deleted_at.is_(None))
        .correlate(HostingAccount)
        .scalar_subquery()
    )


def _get(db: Session, hosting_id: uuid.UUID) -> HostingAccount:
    hosting = db.scalar(
        select(HostingAccount)
        .options(joinedload(HostingAccount.integration), joinedload(HostingAccount.registrar))
        .where(HostingAccount.id == hosting_id)
        .execution_options(populate_existing=True)
    )
    if hosting is None:
        raise not_found("Hosting account")
    return hosting


def _validate_integration(db: Session, integration_id: uuid.UUID | None) -> None:
    if integration_id is not None and db.get(ProviderIntegration, integration_id) is None:
        raise ApiError(422, "invalid_integration", "The selected provider integration does not exist.")


def _detail(db: Session, hosting: HostingAccount, clock: Clock) -> dict:
    domains = active_domains_for_hosting(db, hosting.id)
    out = hosting_out(hosting, clock.today, clock.now, clock.settings, len(domains))
    out["domains"] = [
        {
            "id": d.id,
            "domain_name": d.domain_name,
            "expiration_date": d.expiration_date,
            "expiration": expiration_info(d.expiration_date, clock.today).as_dict(),
            "usage_status": d.usage_status,
            "service_status": d.service_status,
            "monitoring_status": d.monitoring_status,
        }
        for d in domains
    ]
    return out


@router.get("", response_model=Page[HostingOut])
def list_hosting(
    search: str | None = Query(None, max_length=255),
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
    domain_count = _domain_count_subquery().label("domain_count")
    stmt = select(HostingAccount, domain_count)
    if archived_only:
        stmt = stmt.where(HostingAccount.deleted_at.is_not(None))
    elif not include_archived:
        stmt = stmt.where(HostingAccount.deleted_at.is_(None))
    if search:
        term = f"%{search.strip().lower()}%"
        stmt = stmt.where(
            or_(func.lower(HostingAccount.name).like(term), func.lower(HostingAccount.provider_name).like(term))
        )
    if provider_name:
        stmt = stmt.where(func.lower(HostingAccount.provider_name) == provider_name.strip().lower())
    if usage_status:
        stmt = stmt.where(HostingAccount.usage_status == usage_status)
    if service_status:
        stmt = stmt.where(HostingAccount.service_status == service_status)
    if monitoring_status:
        stmt = stmt.where(HostingAccount.monitoring_status == monitoring_status)
    if expiration:
        stmt = stmt.where(expiration_window_clause(HostingAccount.expiration_date, expiration, clock.today))

    total = count_of(db, stmt)
    column = {
        "name": func.lower(HostingAccount.name),
        "expiration_date": HostingAccount.expiration_date,
        "provider_name": func.lower(HostingAccount.provider_name),
        "created_at": HostingAccount.created_at,
        "updated_at": HostingAccount.updated_at,
        "domain_count": domain_count,
    }[sort]
    primary = column.asc() if order == SortOrder.asc else column.desc()
    stmt = stmt.order_by(primary.nulls_last(), func.lower(HostingAccount.name).asc(), HostingAccount.id.asc())
    rows = db.execute(
        stmt.options(joinedload(HostingAccount.integration), joinedload(HostingAccount.registrar))
        .offset(pagination.offset).limit(pagination.page_size)
    ).all()
    return {
        "items": [hosting_out(h, clock.today, clock.now, clock.settings, count) for h, count in rows],
        "total": total,
        "page": pagination.page,
        "page_size": pagination.page_size,
    }


@router.get("/providers", response_model=list[str])
def list_providers(_: AuthContext = Depends(require_admin), db: Session = Depends(get_db)):
    """Distinct hosting company names, for filter dropdowns."""
    names = db.scalars(
        select(HostingAccount.provider_name).where(HostingAccount.deleted_at.is_(None))
        .distinct().order_by(HostingAccount.provider_name)
    ).all()
    unique: dict[str, str] = {}
    for name in names:
        unique.setdefault(name.strip().lower(), name.strip())
    return sorted(unique.values(), key=str.lower)


@router.post("", response_model=HostingDetailOut, status_code=201)
def create_hosting(
    body: HostingCreate,
    clock: Clock = Depends(get_clock),
    ctx: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
):
    _validate_integration(db, body.integration_id)
    registrar = validate_registrar(db, body.registrar_id, RegistrarKind.hosting)
    if registrar is None and not body.provider_name:
        raise ApiError(422, "validation_error", "Choose a hosting company or enter its name.",
                       [{"field": "provider_name", "message": "Choose a hosting company or enter its name."}])
    data = body.model_dump(exclude_unset=True)
    data.pop("provider_name", None)
    hosting = HostingAccount(
        name=data.pop("name"),
        provider_name=registrar.name if registrar else body.provider_name,
        registrar_id=data.pop("registrar_id", None),
        purchase_date=data.pop("purchase_date", None),
        admin_url=data.pop("admin_url", None),
        integration_id=data.pop("integration_id", None),
        external_ref=(data.pop("external_ref", None) or None),
        expiration_date=data.pop("expiration_date", None),
        expiration_source=DataSource.manual,
        usage_status=data.pop("usage_status", None) or UsageStatus.active,
        service_status=data.pop("service_status", None) or ServiceStatus.unknown,
        service_status_source=DataSource.manual,
        auto_check_enabled=data.pop("auto_check_enabled", None) is not False,
        notifications_enabled=data.pop("notifications_enabled", None) is not False,
        notes=data.pop("notes", None),
        monitoring_status=MonitoringStatus.due,
    )
    if data.get("renewal_status") is not None:
        apply_record_update(hosting, {"renewal_status": data["renewal_status"]})
    refresh_monitoring_mode(hosting, clock.now)
    db.add(hosting)
    db.flush()
    record_audit(db, "hosting_created", user=ctx.user, record_type="hosting", record_id=hosting.id,
                 details={"name": hosting.name, "provider_name": hosting.provider_name}, ip_address=ctx.ip)
    db.commit()
    hosting = _get(db, hosting.id)
    if hosting.integration_id and hosting.auto_check_enabled:
        enqueue_check(db, hosting)
    return _detail(db, hosting, clock)


@router.get("/{hosting_id}", response_model=HostingDetailOut)
def get_hosting(
    hosting_id: uuid.UUID, clock: Clock = Depends(get_clock), _: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return _detail(db, _get(db, hosting_id), clock)


@router.get("/{hosting_id}/admin-url", response_model=AdminUrlOut)
def get_admin_url(hosting_id: uuid.UUID, ctx: AuthContext = Depends(require_admin), db: Session = Depends(get_db)):
    """Protected edit workflow only: the admin URL is never part of list/detail responses."""
    hosting = _get(db, hosting_id)
    record_audit(db, "admin_url_viewed", user=ctx.user, record_type="hosting", record_id=hosting.id, ip_address=ctx.ip)
    db.commit()
    return {"admin_url": hosting.admin_url}


@router.patch("/{hosting_id}", response_model=HostingDetailOut)
def update_hosting(
    hosting_id: uuid.UUID,
    body: HostingUpdate,
    clock: Clock = Depends(get_clock),
    ctx: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
):
    hosting = _get(db, hosting_id)
    ensure_editable(hosting)
    updates = body.model_dump(exclude_unset=True)
    if "provider_name" in updates and updates["provider_name"] is None:
        updates.pop("provider_name")  # a null company name means "use the selected registrar"
    for required in ("name", "provider_name", "usage_status", "service_status", "renewal_status",
                     "auto_check_enabled", "notifications_enabled"):
        if required in updates and updates[required] is None:
            raise ApiError(422, "validation_error", f"{required} cannot be null.")
    if "integration_id" in updates:
        _validate_integration(db, updates["integration_id"])
    if "external_ref" in updates:
        updates["external_ref"] = updates["external_ref"] or None
    if "registrar_id" in updates:
        registrar = validate_registrar(db, updates["registrar_id"], RegistrarKind.hosting)
        if registrar is not None:
            updates["provider_name"] = registrar.name
        elif not updates.get("provider_name"):
            updates.pop("provider_name", None)  # keep the existing company name as text
    elif hosting.registrar_id and updates.get("provider_name"):
        # The name of a linked company is managed on the Registrars page.
        updates.pop("provider_name")

    changes = apply_record_update(hosting, updates)
    if "admin_url" in changes:
        changes["admin_url"] = {"from": "[private]", "to": "[private]"}
    if {"integration_id", "external_ref"} & changes.keys() and hosting.auto_check_enabled and hosting.integration_id:
        hosting.next_check_at = clock.now
        hosting.monitoring_status = MonitoringStatus.due
    if changes:
        cancel_obsolete_notifications(db, hosting, clock.settings)
        record_audit(db, "hosting_updated", user=ctx.user, record_type="hosting", record_id=hosting.id,
                     details={"changes": changes}, ip_address=ctx.ip)
    db.commit()
    return _detail(db, _get(db, hosting.id), clock)


@router.delete("/{hosting_id}", status_code=204)
def delete_hosting(
    hosting_id: uuid.UUID,
    permanent: bool = False,
    clock: Clock = Depends(get_clock),
    ctx: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Archive (default) or permanently delete. Domains are never deleted: on permanent delete
    their hosting reference is cleared by the ON DELETE SET NULL foreign key."""
    hosting = _get(db, hosting_id)
    affected = [str(d.id) for d in active_domains_for_hosting(db, hosting.id)]
    if permanent:
        record_audit(db, "hosting_deleted", user=ctx.user, record_type="hosting", record_id=hosting.id,
                     details={"name": hosting.name, "unassigned_domains": affected}, ip_address=ctx.ip)
        db.delete(hosting)
    elif hosting.deleted_at is None:
        hosting.deleted_at = datetime.now(timezone.utc)
        hosting.next_check_at = None
        cancel_obsolete_notifications(db, hosting, clock.settings)
        record_audit(db, "hosting_archived", user=ctx.user, record_type="hosting", record_id=hosting.id,
                     details={"associated_domains": affected}, ip_address=ctx.ip)
    db.commit()
    return Response(status_code=204)


@router.post("/{hosting_id}/restore", response_model=HostingDetailOut)
def restore_hosting(
    hosting_id: uuid.UUID, clock: Clock = Depends(get_clock), ctx: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
):
    hosting = _get(db, hosting_id)
    if hosting.deleted_at is not None:
        hosting.deleted_at = None
        hosting.next_check_at = None
        refresh_monitoring_mode(hosting, clock.now)
        record_audit(db, "hosting_restored", user=ctx.user, record_type="hosting", record_id=hosting.id,
                     ip_address=ctx.ip)
        db.commit()
    return _detail(db, _get(db, hosting.id), clock)


@router.post("/{hosting_id}/check", response_model=CheckQueuedOut, status_code=202)
def check_hosting(hosting_id: uuid.UUID, ctx: AuthContext = Depends(require_admin), db: Session = Depends(get_db)):
    hosting = _get(db, hosting_id)
    ensure_editable(hosting)
    result = enqueue_check(db, hosting)
    if result["status"] == "queued":
        record_audit(db, "check_requested", user=ctx.user, record_type="hosting", record_id=hosting.id,
                     ip_address=ctx.ip)
        db.commit()
    return result


@router.get("/{hosting_id}/checks", response_model=Page[MonitoringCheckOut])
def hosting_checks(
    hosting_id: uuid.UUID, pagination: Pagination = Depends(get_pagination), _: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
):
    _get(db, hosting_id)
    return check_history(db, MonitoringCheck.hosting_account_id, hosting_id, pagination)


@router.get("/{hosting_id}/changes", response_model=Page[AuditEventOut])
def hosting_changes(
    hosting_id: uuid.UUID, pagination: Pagination = Depends(get_pagination), _: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
):
    _get(db, hosting_id)
    return change_history(db, "hosting", hosting_id, pagination)
