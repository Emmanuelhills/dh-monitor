"""Queue on-demand checks without waiting for the provider."""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import HostingAccount
from app.services.records import MonitoredRecord, record_type_of

log = logging.getLogger(__name__)

DUPLICATE_WINDOW = timedelta(minutes=5)


def enqueue_check(db: Session, record: MonitoredRecord) -> dict:
    now = datetime.now(timezone.utc)
    if isinstance(record, HostingAccount) and (record.integration is None or not record.integration.enabled):
        return {
            "status": "not_supported",
            "requested_at": None,
            "message": "No enabled provider integration is assigned; this account is maintained manually.",
        }
    pending = record.check_requested_at and record.check_requested_at > now - DUPLICATE_WINDOW
    if pending and (record.last_checked_at is None or record.last_checked_at < record.check_requested_at):
        return {
            "status": "already_queued",
            "requested_at": record.check_requested_at,
            "message": "A check was already requested and has not finished yet.",
        }
    record.check_requested_at = now
    # Fallback: the periodic dispatcher picks this up if the broker is unreachable right now.
    record.next_check_at = now
    db.commit()

    if get_settings().task_mode == "inline":
        # No worker (serverless): run the check now. It is bounded by the lookup timeouts.
        from app.monitoring.checker import run_check

        check = run_check(db, record_type_of(record), record.id)
        db.commit()
        result = check.result.value if check else "skipped"
        return {"status": "completed", "requested_at": now, "message": f"Check finished ({result})."}

    from app.tasks.jobs import check_record

    try:
        check_record.delay(record_type_of(record).value, str(record.id))
    except Exception:  # broker down: dispatcher will retry from next_check_at
        log.warning("Could not enqueue check; it will run on the next dispatcher cycle.")
        return {
            "status": "queued",
            "requested_at": now,
            "message": "Queue is temporarily unavailable; the check will run on the next scheduled cycle.",
        }
    return {"status": "queued", "requested_at": now, "message": "Check queued."}
