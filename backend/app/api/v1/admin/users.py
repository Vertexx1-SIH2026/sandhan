from fastapi import APIRouter, Depends, Body, HTTPException, status
from sqlalchemy.orm import Session

from app.db import models
from app.db.postgres_client import get_db
from app.core.security import hash_password
from app.services.rbac import require_admin
from app.services.audit_logger import log_system_event

router = APIRouter(prefix="/api/v1/admin", tags=["admin:users"])


@router.get("/users")
def list_users(db: Session = Depends(get_db), claims: dict = Depends(require_admin)):
    users = db.query(models.User).all()
    return [
        {
            "id": u.id, "username": u.username, "role": u.role, "full_name": u.full_name,
            "is_active": u.is_active,
            "assigned_case_ids": [a.case_id for a in u.assigned_cases] if u.role == "investigator" else [],
        }
        for u in users
    ]


@router.post("/users")
def create_user(
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    claims: dict = Depends(require_admin),
):
    """Admin provisions accounts and roles only -- no case content ever
    passes through this router (Section 4: 'Admin: account/access
    management only, not oversight of investigative work')."""
    username = payload.get("username")
    password = payload.get("password")
    role = payload.get("role")
    full_name = payload.get("full_name", "")

    if role not in ("investigator", "admin"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "role must be 'investigator' or 'admin'")
    if db.query(models.User).filter(models.User.username == username).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "username already exists")

    user = models.User(username=username, password_hash=hash_password(password), role=role, full_name=full_name)
    db.add(user)
    db.commit()
    db.refresh(user)

    log_system_event(db, claims["user_id"], "account_created", {"username": username, "role": role})
    return {"id": user.id, "username": user.username, "role": user.role}


@router.post("/users/{user_id}/assign-case")
def assign_case(
    user_id: str,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    claims: dict = Depends(require_admin),
):
    case_id = payload.get("case_id")
    user = db.get(models.User, user_id)
    if user is None or user.role != "investigator":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Investigator not found")

    case = db.get(models.Case, case_id)
    if case is None:
        case = models.Case(id=case_id, title=payload.get("title", case_id))
        db.add(case)
        db.commit()

    exists = (
        db.query(models.CaseAssignment)
        .filter(models.CaseAssignment.user_id == user_id, models.CaseAssignment.case_id == case_id)
        .first()
    )
    if not exists:
        db.add(models.CaseAssignment(user_id=user_id, case_id=case_id))
        db.commit()

    log_system_event(db, claims["user_id"], "case_assigned", {"user_id": user_id, "case_id": case_id})
    return {"status": "assigned", "user_id": user_id, "case_id": case_id}


@router.post("/users/{user_id}/role")
def change_role(
    user_id: str,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    claims: dict = Depends(require_admin),
):
    new_role = payload.get("role")
    if new_role not in ("investigator", "admin"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "role must be 'investigator' or 'admin'")

    user = db.get(models.User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")

    old_role = user.role
    user.role = new_role
    db.commit()

    log_system_event(db, claims["user_id"], "role_changed", {"user_id": user_id, "from": old_role, "to": new_role})
    return {"status": "updated", "user_id": user_id, "role": new_role}
