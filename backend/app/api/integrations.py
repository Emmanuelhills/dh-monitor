import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, require_admin
from app.api.errors import ApiError, not_found
from app.db import get_db
from app.models import HostingAccount, MonitoringStatus, ProviderIntegration
from app.monitoring.hosting_adapters import AdapterContext, HostingAdapter, all_adapters, get_adapter
from app.monitoring.types import CheckError
from app.schemas import (
    AdapterInfoOut,
    IntegrationCreate,
    IntegrationOut,
    IntegrationTestOut,
    IntegrationUpdate,
)
from app.services.audit import record_audit
from app.services.redaction import redact_text
from app.services.secrets import SecretStoreError, delete_secret, get_secret, has_secret, put_secret

router = APIRouter(prefix="/integrations", tags=["integrations"])


def _secret_name(integration_id: uuid.UUID) -> str:
    return f"integration:{integration_id}"


def _clean_config(adapter: HostingAdapter, config: dict) -> dict:
    allowed = {f.key for f in adapter.config_fields}
    unknown = set(config) - allowed
    if unknown:
        raise ApiError(422, "invalid_config", f"Unknown settings for {adapter.label}: {', '.join(sorted(unknown))}.")
    cleaned = {}
    for key, value in config.items():
        if key == "status_map" and isinstance(value, str):
            if not value.strip():
                continue
            try:
                value = json.loads(value)
            except ValueError:
                raise ApiError(422, "invalid_config", "Status mapping must be a JSON object.") from None
        if key == "status_map":
            if not isinstance(value, dict):
                raise ApiError(422, "invalid_config", "Status mapping must be a JSON object.")
            value = {str(k).lower(): str(v).lower() for k, v in value.items()}
        elif isinstance(value, str):
            value = value.strip()
        cleaned[key] = value
    return cleaned


def _clean_secrets(adapter: HostingAdapter, secrets: dict[str, str]) -> dict[str, str]:
    allowed = {f.key for f in adapter.secret_fields}
    unknown = set(secrets) - allowed
    if unknown:
        raise ApiError(422, "invalid_secret", f"Unknown secrets for {adapter.label}: {', '.join(sorted(unknown))}.")
    return {k: v.strip() for k, v in secrets.items()}


def _out(db: Session, integration: ProviderIntegration) -> dict:
    count = db.scalar(
        select(func.count()).select_from(HostingAccount)
        .where(HostingAccount.integration_id == integration.id, HostingAccount.deleted_at.is_(None))
    )
    return {
        "id": integration.id,
        "name": integration.name,
        "adapter": integration.adapter,
        "enabled": integration.enabled,
        "config": integration.config or {},
        "secret_set": bool(integration.secret_name and has_secret(db, integration.secret_name)),
        "last_tested_at": integration.last_tested_at,
        "last_test_ok": integration.last_test_ok,
        "last_test_message": integration.last_test_message,
        "hosting_account_count": count or 0,
        "created_at": integration.created_at,
    }


def _adapter_or_422(key: str) -> HostingAdapter:
    try:
        return get_adapter(key)
    except CheckError as exc:
        raise ApiError(422, "unknown_adapter", exc.message) from None


@router.get("/adapters", response_model=list[AdapterInfoOut])
def list_adapters(_: AuthContext = Depends(require_admin)):
    return [a.info() for a in all_adapters()]


@router.get("", response_model=list[IntegrationOut])
def list_integrations(_: AuthContext = Depends(require_admin), db: Session = Depends(get_db)):
    rows = db.scalars(select(ProviderIntegration).order_by(func.lower(ProviderIntegration.name))).all()
    return [_out(db, r) for r in rows]


@router.post("", response_model=IntegrationOut, status_code=201)
def create_integration(body: IntegrationCreate, ctx: AuthContext = Depends(require_admin), db: Session = Depends(get_db)):
    adapter = _adapter_or_422(body.adapter)
    integration = ProviderIntegration(
        id=uuid.uuid4(), name=body.name.strip(), adapter=adapter.key, enabled=body.enabled,
        config=_clean_config(adapter, body.config),
    )
    if body.secrets:
        integration.secret_name = _secret_name(integration.id)
        try:
            put_secret(db, integration.secret_name, {k: v for k, v in _clean_secrets(adapter, body.secrets).items() if v})
        except SecretStoreError as exc:
            raise ApiError(500, "secret_store_unavailable", str(exc)) from None
    db.add(integration)
    record_audit(db, "integration_created", user=ctx.user, details={"name": integration.name, "adapter": adapter.key},
                 ip_address=ctx.ip)
    db.commit()
    return _out(db, integration)


@router.patch("/{integration_id}", response_model=IntegrationOut)
def update_integration(
    integration_id: uuid.UUID, body: IntegrationUpdate, ctx: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
):
    integration = db.get(ProviderIntegration, integration_id)
    if integration is None:
        raise not_found("Integration")
    adapter = _adapter_or_422(integration.adapter)
    changed = []
    if body.name is not None:
        integration.name = body.name.strip()
        changed.append("name")
    if body.enabled is not None and body.enabled != integration.enabled:
        integration.enabled = body.enabled
        changed.append("enabled")
        accounts = db.scalars(select(HostingAccount).where(HostingAccount.integration_id == integration.id))
        for account in accounts:
            if not body.enabled:
                account.monitoring_status = MonitoringStatus.manual
                account.next_check_at = None
            elif account.auto_check_enabled:
                account.monitoring_status = MonitoringStatus.due
                account.next_check_at = datetime.now(timezone.utc)
    if body.config is not None:
        integration.config = _clean_config(adapter, body.config)
        changed.append("config")
    if body.secrets is not None:
        try:
            current = (get_secret(db, integration.secret_name) if integration.secret_name else None) or {}
            for key, value in _clean_secrets(adapter, body.secrets).items():
                if value:
                    current[key] = value
                else:
                    current.pop(key, None)  # empty string clears a secret
            integration.secret_name = integration.secret_name or _secret_name(integration.id)
            put_secret(db, integration.secret_name, current)
        except SecretStoreError as exc:
            raise ApiError(500, "secret_store_unavailable", str(exc)) from None
        changed.append("secrets")
    record_audit(db, "integration_updated", user=ctx.user, details={"id": str(integration.id), "fields": changed},
                 ip_address=ctx.ip)
    db.commit()
    return _out(db, integration)


@router.delete("/{integration_id}", status_code=204)
def delete_integration(integration_id: uuid.UUID, ctx: AuthContext = Depends(require_admin), db: Session = Depends(get_db)):
    integration = db.get(ProviderIntegration, integration_id)
    if integration is None:
        raise not_found("Integration")
    for account in db.scalars(select(HostingAccount).where(HostingAccount.integration_id == integration.id)):
        account.integration_id = None
        account.monitoring_status = MonitoringStatus.manual
        account.next_check_at = None
    if integration.secret_name:
        delete_secret(db, integration.secret_name)
    record_audit(db, "integration_deleted", user=ctx.user, details={"name": integration.name}, ip_address=ctx.ip)
    db.delete(integration)
    db.commit()
    return Response(status_code=204)


@router.post("/{integration_id}/test", response_model=IntegrationTestOut)
def test_integration(integration_id: uuid.UUID, ctx: AuthContext = Depends(require_admin), db: Session = Depends(get_db)):
    integration = db.get(ProviderIntegration, integration_id)
    if integration is None:
        raise not_found("Integration")
    adapter = _adapter_or_422(integration.adapter)
    sample_ref = db.scalar(
        select(HostingAccount.external_ref)
        .where(HostingAccount.integration_id == integration.id, HostingAccount.external_ref.is_not(None)).limit(1)
    )
    try:
        secrets = (get_secret(db, integration.secret_name) if integration.secret_name else None) or {}
        message = adapter.test_connection(AdapterContext(config=integration.config or {}, secrets=secrets,
                                                         external_ref=sample_ref))
        ok = True
    except CheckError as exc:
        ok, message = False, exc.message
    except SecretStoreError as exc:
        ok, message = False, str(exc)
    message = redact_text(message, 500)
    integration.last_tested_at = datetime.now(timezone.utc)
    integration.last_test_ok = ok
    integration.last_test_message = message
    record_audit(db, "integration_tested", user=ctx.user, details={"id": str(integration.id), "ok": ok}, ip_address=ctx.ip)
    db.commit()
    return {"ok": ok, "message": message}
