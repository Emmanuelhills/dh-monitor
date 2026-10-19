"""Run one monitoring check for a domain or hosting account and persist the outcome."""

import logging
import time
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import (
    CheckResult,
    Domain,
    HostingAccount,
    MonitoringCheck,
    MonitoringStatus,
    RecordType,
)
from app.monitoring import rdap, whois
from app.monitoring.hosting_adapters import AdapterContext, get_adapter
from app.monitoring.reconcile import reconcile
from app.monitoring.types import CheckError, CheckErrorCode, LookupResult
from app.services.app_settings import get_app_settings
from app.services.expiration import local_today
from app.services.records import cancel_obsolete_notifications
from app.services.redaction import redact_data, redact_text
from app.services.secrets import SecretStoreError, get_secret

log = logging.getLogger(__name__)

RDAP_FALLBACK_CODES = {
    CheckErrorCode.UNSUPPORTED,
    CheckErrorCode.INVALID_RESPONSE,
    CheckErrorCode.PROVIDER_ERROR,
    CheckErrorCode.TIMEOUT,
}
# Missing these makes a check "partial" rather than "success".
KEY_FIELDS = {"expiration_date"}


def lookup_domain(normalized: str) -> LookupResult:
    try:
        return rdap.lookup(normalized)
    except CheckError as rdap_error:
        if rdap_error.code not in RDAP_FALLBACK_CODES:
            raise
        try:
            result = whois.lookup(normalized)
        except CheckError as whois_error:
            # Report the more informative error: RDAP unless RDAP is simply unsupported.
            raise (whois_error if rdap_error.code == CheckErrorCode.UNSUPPORTED else rdap_error) from None
        result.observed["rdap_error"] = rdap_error.code
        return result


def lookup_hosting(db: Session, hosting: HostingAccount) -> LookupResult:
    integration = hosting.integration
    if integration is None or not integration.enabled:
        raise CheckError(CheckErrorCode.UNSUPPORTED, "No enabled provider integration is assigned.")
    adapter = get_adapter(integration.adapter)
    try:
        secrets = get_secret(db, integration.secret_name) if integration.secret_name else {}
    except SecretStoreError as exc:
        raise CheckError(CheckErrorCode.CONFIG_ERROR, str(exc)) from None
    result = adapter.check(AdapterContext(config=integration.config or {}, secrets=secrets or {}, external_ref=hosting.external_ref))
    return result


def _retry_delay(failures: int, interval: timedelta) -> timedelta:
    """Exponential backoff for transient errors: 15 min, 30 min, 1 h ... capped at the interval."""
    return min(timedelta(minutes=15) * (2 ** max(failures - 1, 0)), interval)


def run_check(db: Session, record_type: RecordType, record_id: uuid.UUID) -> MonitoringCheck | None:
    model = Domain if record_type == RecordType.domain else HostingAccount
    # Row lock: concurrent workers cannot check the same record at the same time.
    record = db.get(model, record_id, with_for_update={"skip_locked": True})
    if record is None or record.deleted_at is not None:
        return None

    settings = get_app_settings(db)
    now = datetime.now(timezone.utc)
    today = local_today(settings.timezone, now)
    interval_hours = (
        settings.domain_check_interval_hours if record_type == RecordType.domain else settings.hosting_check_interval_hours
    )
    interval = timedelta(hours=interval_hours)
    started = time.monotonic()

    check = MonitoringCheck(
        record_type=record_type,
        domain_id=record.id if record_type == RecordType.domain else None,
        hosting_account_id=record.id if record_type == RecordType.hosting else None,
        checked_at=now,
    )
    try:
        if record_type == RecordType.domain:
            result = lookup_domain(record.normalized_domain_name)
        else:
            result = lookup_hosting(db, record)
        changes, conflicts = reconcile(record, result, today, now)
        missing_key = KEY_FIELDS & set(result.missing)
        check.source = result.source
        check.result = CheckResult.partial if missing_key else CheckResult.success
        check.observed_data = redact_data({**result.observed, "missing_fields": result.missing})
        check.changes = changes
        check.conflicts = conflicts
        record.monitoring_status = MonitoringStatus.partial if missing_key else MonitoringStatus.current
        record.last_successful_check_at = now
        record.consecutive_check_failures = 0
        record.last_check_error = (
            f"Source did not return: {', '.join(sorted(missing_key))}." if missing_key else None
        )
        record.next_check_at = now + interval
        if changes:
            cancel_obsolete_notifications(db, record, settings)
    except CheckError as exc:
        message = redact_text(exc.message, 500)
        check.source = exc.source or ("domain-lookup" if record_type == RecordType.domain else "provider")
        check.result = CheckResult.failure
        check.error_code = exc.code
        check.error_message = message
        record.last_check_error = message
        if exc.code == CheckErrorCode.UNSUPPORTED:
            # Nothing can be verified automatically; the record is maintained manually.
            record.monitoring_status = MonitoringStatus.manual
            record.next_check_at = now + interval
        else:
            record.consecutive_check_failures += 1
            record.monitoring_status = MonitoringStatus.failed
            retries_left = record.consecutive_check_failures <= get_settings().check_max_retries
            record.next_check_at = now + (
                _retry_delay(record.consecutive_check_failures, interval) if exc.transient and retries_left else interval
            )
    except Exception:  # unexpected bug: keep data, record a sanitized failure
        log.exception("Unexpected monitoring error", extra={"record_type": record_type.value, "record_id": str(record_id)})
        check.source = check.source or "internal"
        check.result = CheckResult.failure
        check.error_code = "internal_error"
        check.error_message = "Unexpected internal error during the check."
        record.consecutive_check_failures += 1
        record.monitoring_status = MonitoringStatus.failed
        record.last_check_error = check.error_message
        record.next_check_at = now + interval

    check.duration_ms = int((time.monotonic() - started) * 1000)
    record.last_checked_at = now
    record.check_requested_at = None
    if not record.auto_check_enabled:
        # On-demand check of a record without automatic checks: do not schedule another.
        record.next_check_at = None
    db.add(check)
    db.flush()
    return check
