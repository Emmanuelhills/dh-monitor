from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.api.common import Pagination, count_of, get_pagination
from app.api.deps import AuthContext, require_admin
from app.config import get_settings
from app.db import get_db
from app.models import AuditEvent
from app.schemas import AuditEventOut, Page

router = APIRouter(tags=["system"])


@router.get("/health")
def health(db: Session = Depends(get_db)):
    """Unauthenticated liveness/readiness probe. Reports component health only."""
    result = {"status": "ok", "database": "ok", "queue": "ok"}
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        result["database"] = "unavailable"
    if get_settings().task_mode == "inline":
        result["queue"] = "not used"
    else:
        try:
            from kombu import Connection

            with Connection(get_settings().broker_url, connect_timeout=2) as conn:
                conn.ensure_connection(max_retries=1)
        except Exception:
            result["queue"] = "unavailable"
    if "unavailable" in result.values():
        result["status"] = "degraded"
        return JSONResponse(status_code=503, content=result)
    return result


@router.get("/audit-events", response_model=Page[AuditEventOut])
def audit_events(
    action: str | None = Query(None, max_length=64),
    pagination: Pagination = Depends(get_pagination),
    _: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
):
    stmt = select(AuditEvent)
    if action:
        stmt = stmt.where(AuditEvent.action == action)
    total = count_of(db, stmt)
    items = db.scalars(
        stmt.order_by(AuditEvent.created_at.desc()).offset(pagination.offset).limit(pagination.page_size)
    ).all()
    return {"items": items, "total": total, "page": pagination.page, "page_size": pagination.page_size}
