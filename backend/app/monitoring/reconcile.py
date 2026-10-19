"""Compare a validated lookup result with a saved record and apply only permitted updates.

Rules
-----
* A field the source did not return is never cleared.
* Confirmed manual states (suspended / expired / not renewed) are not overwritten by an
  automatic result; the disagreement is recorded as a conflict instead.
* A source reporting an *earlier* expiration than a manually entered date is a conflict
  (the administrator may have renewed before the registry updated).
* An expiration date pushed forward while the registry shows an auto-renew grace period is
  not treated as a confirmed renewal (registries extend dates before the registrar is paid).
"""

from datetime import date, datetime
from typing import Any

from app.models import DataSource, Domain, HostingAccount, RenewalStatus, ServiceStatus
from app.monitoring.types import LookupResult
from app.services.audit import jsonable

PROTECTED_MANUAL_STATUSES = {ServiceStatus.suspended, ServiceStatus.expired}


def _norm_status(status: str) -> str:
    return status.lower().replace(" ", "").replace("_", "")


def derive_domain_status(
    statuses: list[str] | None, expiration_date: date | None, today: date
) -> tuple[ServiceStatus | None, RenewalStatus | None]:
    normalized = {_norm_status(s) for s in statuses or []}
    if normalized & {"redemptionperiod", "pendingdelete", "pendingrestore"}:
        return ServiceStatus.expired, RenewalStatus.not_renewed
    if normalized & {"clienthold", "serverhold"}:
        return ServiceStatus.suspended, None
    if expiration_date and expiration_date >= today:
        return ServiceStatus.active, None
    return None, None


def in_auto_renew_grace(statuses: list[str] | None) -> bool:
    return "autorenewperiod" in {_norm_status(s) for s in statuses or []}


def source_kind(source: str) -> DataSource:
    if source.startswith("rdap"):
        return DataSource.rdap
    if source.startswith("whois"):
        return DataSource.whois
    return DataSource.provider


def reconcile(
    record: Domain | HostingAccount, result: LookupResult, today: date, now: datetime
) -> tuple[dict[str, Any], dict[str, Any]]:
    changes: dict[str, Any] = {}
    conflicts: dict[str, Any] = {}
    kind = source_kind(result.source)

    def _set(field: str, value: Any, track: bool = True) -> None:
        old = getattr(record, field)
        if old != value:
            if track:
                changes[field] = {"from": jsonable(old), "to": jsonable(value)}
            setattr(record, field, value)

    is_domain = isinstance(record, Domain)
    grace = is_domain and in_auto_renew_grace(result.registry_statuses)

    # --- expiration date
    observed_exp = result.expiration_date
    saved_exp = record.expiration_date
    if observed_exp is not None:
        if grace and saved_exp and observed_exp > saved_exp:
            conflicts["expiration_date"] = {
                "saved": jsonable(saved_exp),
                "observed": jsonable(observed_exp),
                "reason": "Registry shows an auto-renew grace period; renewal is not yet confirmed.",
            }
        elif saved_exp and record.expiration_source == DataSource.manual and observed_exp < saved_exp:
            conflicts["expiration_date"] = {
                "saved": jsonable(saved_exp),
                "observed": jsonable(observed_exp),
                "reason": "Source reports an earlier date than the manually entered one.",
            }
        else:
            _set("expiration_date", observed_exp)
            _set("expiration_source", kind)
            record.expiration_verified_at = now
            if saved_exp and observed_exp > saved_exp:
                _set("renewal_status", RenewalStatus.renewed)
                _set("renewal_confirmed_for_date", saved_exp)

    # --- descriptive registration fields (domains)
    if is_domain:
        if result.registration_date is not None:
            _set("registration_date", result.registration_date)
        if result.registrar_name:
            _set("registrar_name", result.registrar_name)
        if result.registry_statuses is not None:
            _set("registry_statuses", result.registry_statuses)
    elif result.registration_date is not None and record.purchase_date is None:
        _set("purchase_date", result.registration_date)

    # --- service / renewal status
    if is_domain:
        new_service, new_renewal = derive_domain_status(result.registry_statuses, record.expiration_date, today)
    else:
        new_service, new_renewal = result.service_status, result.renewal_status

    if new_service is not None and new_service != ServiceStatus.unknown:
        if new_service != record.service_status:
            if (
                record.service_status_source == DataSource.manual
                and record.service_status in PROTECTED_MANUAL_STATUSES
            ):
                conflicts["service_status"] = {
                    "saved": record.service_status.value,
                    "observed": new_service.value,
                    "reason": "Saved status was confirmed manually and is not overwritten automatically.",
                }
            else:
                _set("service_status", new_service)
                _set("service_status_source", kind)
        else:
            _set("service_status_source", kind)

    if new_renewal == RenewalStatus.not_renewed and record.renewal_status != RenewalStatus.not_renewed:
        if (
            record.renewal_status == RenewalStatus.renewed
            and record.renewal_confirmed_for_date == record.expiration_date
        ):
            conflicts["renewal_status"] = {
                "saved": record.renewal_status.value,
                "observed": new_renewal.value,
                "reason": "Renewal was confirmed manually; source reports it was not renewed.",
            }
        else:
            _set("renewal_status", RenewalStatus.not_renewed)
            _set("renewal_confirmed_for_date", record.expiration_date)

    return changes, conflicts
