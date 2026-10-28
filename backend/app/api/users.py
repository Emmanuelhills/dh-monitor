"""Administrator accounts: list, add and remove. Every signed-in user is an administrator."""

import uuid

from fastapi import APIRouter, Depends, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, require_admin
from app.api.errors import ApiError, not_found
from app.db import get_db
from app.models import User
from app.schemas import AdminCreateIn, AdminOut
from app.services.audit import record_audit
from app.services.auth import hash_password

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=list[AdminOut])
def list_admins(ctx: AuthContext = Depends(require_admin), db: Session = Depends(get_db)):
    return db.scalars(select(User).order_by(User.created_at)).all()


@router.post("", response_model=AdminOut, status_code=201)
def create_admin(body: AdminCreateIn, ctx: AuthContext = Depends(require_admin), db: Session = Depends(get_db)):
    email = str(body.email).strip().lower()
    if db.scalar(select(User).where(func.lower(User.email) == email)):
        message = "An administrator with this email already exists."
        raise ApiError(409, "email_taken", message, details=[{"field": "email", "message": message}])
    user = User(email=email, password_hash=hash_password(body.password))
    db.add(user)
    db.flush()
    record_audit(db, "admin_created", user=ctx.user, ip_address=ctx.ip, details={"email": email})
    db.commit()
    db.refresh(user)
    return user


@router.delete("/{user_id}", status_code=204)
def delete_admin(user_id: uuid.UUID, response: Response, ctx: AuthContext = Depends(require_admin),
                 db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if user is None:
        raise not_found("Administrator")
    if user.id == ctx.user.id:
        raise ApiError(400, "cannot_remove_self", "You can't remove your own account.")
    record_audit(db, "admin_removed", user=ctx.user, ip_address=ctx.ip, details={"email": user.email})
    db.delete(user)  # sessions are removed by ON DELETE CASCADE
    db.commit()
    response.status_code = 204
    return response
