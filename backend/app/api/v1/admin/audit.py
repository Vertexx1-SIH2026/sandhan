from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import models
from app.db.postgres_client import get_db
from app.services.rbac import require_admin

router = APIRouter(prefix="/api/v1/admin", tags=["admin:audit"])


@router.get("/audit-log")
def system_audit_log(db: Session = Depends(get_db), claims: dict = Depends(require_admin)):
    """System-level audit log -- admin only, NEVER contains case content
    (logins, account creation, role changes, export events)."""
    rows = (
        db.query(models.SystemAuditLog)
        .order_by(models.SystemAuditLog.timestamp.desc())
        .limit(200)
        .all()
    )
    return [
        {
            "id": r.id, "actor_id": r.actor_id, "event_type": r.event_type,
            "detail": r.detail, "timestamp": str(r.timestamp),
        }
        for r in rows
    ]
