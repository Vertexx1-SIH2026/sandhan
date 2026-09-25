"""
rbac.py -- role/case-claim enforcement, investigator/admin namespace split.

Admin tokens carry no case claim, and require_investigator runs first on every
case endpoint, so an admin can never read case content.

Change vs. the first prototype: case assignments used to be read ONLY from the
login token, so a case assigned after login was 403 until re-login. Now the
token is checked first and, if the case is missing, the assignment table is
checked live.
"""
from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from app.core.security import decode_access_token
from app.db import models
from app.db.postgres_client import SessionLocal

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


def get_current_claims(token: str = Depends(oauth2_scheme)) -> dict:
    claims = decode_access_token(token)
    if claims is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")
    return claims


def require_investigator(claims: dict = Depends(get_current_claims)) -> dict:
    if claims.get("role") != "investigator":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Investigator role required")
    return claims


def require_admin(claims: dict = Depends(get_current_claims)) -> dict:
    if claims.get("role") != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin role required")
    return claims


def assigned_case_ids(user_id: str) -> list[str]:
    db = SessionLocal()
    try:
        return [
            c for (c,) in db.query(models.CaseAssignment.case_id).filter(models.CaseAssignment.user_id == user_id)
        ]
    finally:
        db.close()


def require_case_access(case_id: str | None, claims: dict) -> None:
    if not case_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "case_id is required")
    if claims.get("role") != "investigator":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Investigator role required")
    if case_id in claims.get("assigned_case_ids", []):
        return
    if case_id in assigned_case_ids(claims.get("user_id")):
        return
    raise HTTPException(status.HTTP_403_FORBIDDEN, f"Not assigned to case {case_id}")
