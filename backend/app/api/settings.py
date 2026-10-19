from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, require_admin
from app.api.errors import ApiError
from app.db import get_db
from app.schemas import GeneralSettingsIn, GeneralSettingsOut
from app.services.app_settings import get_app_settings
from app.services.audit import diff_fields, record_audit

router = APIRouter(prefix="/settings", tags=["settings"])


def _out(db: Session) -> dict:
    s = get_app_settings(db)
    return {
        "timezone": s.timezone,
        "domain_check_interval_hours": s.domain_check_interval_hours,
        "hosting_check_interval_hours": s.hosting_check_interval_hours,
        "stale_after_hours": s.stale_after_hours,
        "public_page_enabled": s.public_page_enabled,
    }


@router.get("", response_model=GeneralSettingsOut)
def get_general_settings(_: AuthContext = Depends(require_admin), db: Session = Depends(get_db)):
    return _out(db)


@router.patch("", response_model=GeneralSettingsOut)
def update_general_settings(body: GeneralSettingsIn, ctx: AuthContext = Depends(require_admin),
                            db: Session = Depends(get_db)):
    settings = get_app_settings(db)
    data = body.model_dump(exclude_unset=True)
    for field, value in data.items():
        if value is None:
            raise ApiError(422, "validation_error", f"{field} cannot be null.")
    changes = diff_fields(settings, data)
    for field, value in data.items():
        setattr(settings, field, value)
    if changes:
        record_audit(db, "settings_updated", user=ctx.user, details={"changes": changes}, ip_address=ctx.ip)
    db.commit()
    return _out(db)
