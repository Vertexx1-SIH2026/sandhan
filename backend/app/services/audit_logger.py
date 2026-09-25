"""
audit_logger.py -- writes case-level vs system-level log entries (Postgres),
mirroring the RBAC silo: case-level log entries are visible only to the
investigator who owns the case; system-level entries are admin-only and
never contain case content.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.db import models


def log_case_event(db: Session, case_id: str, investigator_id: str, action: str,
                    target: str | None = None, detail: dict | None = None) -> None:
    entry = models.CaseAuditLog(
        case_id=case_id,
        investigator_id=investigator_id,
        action=action,
        target=target,
        detail=detail or {},
    )
    db.add(entry)
    db.commit()


def log_system_event(db: Session, actor_id: str | None, event_type: str, detail: dict | None = None) -> None:
    entry = models.SystemAuditLog(
        actor_id=actor_id,
        event_type=event_type,
        detail=detail or {},
    )
    db.add(entry)
    db.commit()
