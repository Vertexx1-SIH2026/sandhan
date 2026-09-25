from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.db import models
from app.db.postgres_client import get_db
from app.core.security import verify_password, create_access_token
from app.services.audit_logger import log_system_event
from app.services.rbac import get_current_claims, assigned_case_ids

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/login")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.username == form_data.username).first()
    if not user or not user.is_active or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect username or password")

    claims = {"sub": str(user.id), "role": user.role, "user_id": str(user.id), "full_name": user.full_name}
    if user.role == "investigator":
        claims["assigned_case_ids"] = sorted(a.case_id for a in user.assigned_cases)

    token = create_access_token(claims)
    log_system_event(db, user.id, "login", {"username": user.username, "role": user.role})
    return {
        "access_token": token,
        "token_type": "bearer",
        "role": user.role,
        "user_id": str(user.id),
        "full_name": user.full_name,
        "assigned_case_ids": claims.get("assigned_case_ids", []),
    }


@router.get("/me")
def me(claims: dict = Depends(get_current_claims)):
    """Fresh view of the caller -- assigned cases are read live from Postgres,
    so a case assigned after login shows up without signing out."""
    out = {"user_id": claims.get("user_id"), "role": claims.get("role"), "full_name": claims.get("full_name")}
    if claims.get("role") == "investigator":
        out["assigned_case_ids"] = sorted(assigned_case_ids(claims.get("user_id")))
    return out
