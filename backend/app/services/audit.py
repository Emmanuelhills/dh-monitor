import uuid
from datetime import date, datetime
from enum import Enum
from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditEvent, User
from app.services.redaction import redact_data


def jsonable(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


def diff_fields(obj: Any, updates: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Before/after for fields whose value actually changes."""
    changes = {}
    for field, new in updates.items():
        old = getattr(obj, field)
        if old != new:
            changes[field] = {"from": jsonable(old), "to": jsonable(new)}
    return changes


def record_audit(
    db: Session,
    action: str,
    *,
    user: User | None = None,
    actor: str | None = None,
    record_type: str | None = None,
    record_id: uuid.UUID | None = None,
    details: dict | None = None,
    ip_address: str | None = None,
) -> None:
    db.add(
        AuditEvent(
            user_id=user.id if user else None,
            actor=actor or (user.email if user else "system"),
            action=action,
            record_type=record_type,
            record_id=record_id,
            details=redact_data(details or {}),
            ip_address=ip_address,
        )
    )
