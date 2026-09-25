from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import models
from app.db.postgres_client import get_db
from app.services.rbac import require_investigator, require_case_access

router = APIRouter(prefix="/api/v1/investigator", tags=["investigator:audit"])


@router.get("/audit-log")
def case_audit_log(
    case_id: str = Query(...),
    db: Session = Depends(get_db),
    claims: dict = Depends(require_investigator),
):
    """Case-level audit log -- self-view only. An investigator can only see
    the log for a case in their own assigned_case_ids claim."""
    require_case_access(case_id, claims)
    rows = (
        db.query(models.CaseAuditLog)
        .filter(models.CaseAuditLog.case_id == case_id)
        .order_by(models.CaseAuditLog.timestamp.desc())
        .limit(200)
        .all()
    )
    return [
        {
            "id": r.id, "case_id": r.case_id, "investigator_id": r.investigator_id,
            "action": r.action, "target": r.target, "detail": r.detail,
            "timestamp": str(r.timestamp),
        }
        for r in rows
    ]
