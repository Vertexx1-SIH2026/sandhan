"""
Act 1 of the demo: the 'siloed' baseline -- a plain SQL keyword lookup over
the historical records table and the investigator's own case records. It
returns flat, disconnected rows with no linkage, which is exactly the point.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.db import models
from app.db.postgres_client import get_db
from app.services.rbac import assigned_case_ids, require_investigator

router = APIRouter(prefix="/api/v1/baseline", tags=["investigator:baseline"])


def _like(col, q):
    return col.ilike(f"%{q}%")


@router.get("/search")
def baseline_search(
    q: str = Query(..., min_length=3),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    claims: dict = Depends(require_investigator),
):
    q = q.strip()
    if q.startswith("+91"):
        q_alt = q[3:]
    else:
        q_alt = q
    hist = (
        db.query(models.HistoricalRecord)
        .filter(or_(*[_like(c, q_alt) for c in (models.HistoricalRecord.source_id,
                                                  models.HistoricalRecord.dest_id,
                                                  models.HistoricalRecord.device_or_ref)]))
        .limit(limit)
        .all()
    )
    mine = assigned_case_ids(claims["user_id"])
    live = (
        db.query(models.CaseRecord)
        .filter(models.CaseRecord.case_id.in_(mine))
        .filter(or_(*[_like(c, q_alt) for c in (models.CaseRecord.source_id,
                                                  models.CaseRecord.dest_id,
                                                  models.CaseRecord.device_or_ref)]))
        .limit(limit)
        .all()
    ) if mine else []

    def row(r, table):
        return {"table": table, "case_id": r.case_id, "record_type": r.record_type, "timestamp": r.timestamp,
                "source_id": r.source_id, "dest_id": r.dest_id, "device_or_ref": r.device_or_ref,
                "value": r.value, "location": r.location}

    rows = [row(r, "case_records") for r in live] + [row(r, "historical_records") for r in hist]
    return {"query": q, "count": len(rows), "rows": rows[:limit]}
