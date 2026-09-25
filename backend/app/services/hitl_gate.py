"""
hitl_gate.py -- Human-in-the-Loop gate for link predictions.

Every prediction is stored server-side (predicted_links, status=pending).
An investigator must Verify (edge joins the graph, eligible for export) or
Dismiss (logged as 'reject', never re-suggested) each one. The evidence
export refuses while any prediction for the case is still pending -- enforced
here on the server, not just by a disabled button.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.db import models
from app.services.audit_logger import log_case_event


def decided_pairs(db: Session, case_id: str) -> set[tuple[str, str]]:
    return {
        tuple(sorted((s, t)))
        for s, t in db.query(models.PredictedLink.source_id, models.PredictedLink.target_id).filter(
            models.PredictedLink.case_id == case_id,
            models.PredictedLink.status.in_(("verified", "dismissed")),
        )
    }


def record_predictions(db: Session, case_id: str, predictions: list[dict]) -> None:
    """Replaces the case's pending predictions with the latest run."""
    db.query(models.PredictedLink).filter(
        models.PredictedLink.case_id == case_id, models.PredictedLink.status == "pending"
    ).delete(synchronize_session=False)
    for p in predictions:
        db.add(models.PredictedLink(
            case_id=case_id, node_id=p["node_id"], source_id=p["source"], target_id=p["target"],
            score=p["score"], detail=p, status="pending",
        ))
    db.commit()


def pending_predictions(db: Session, case_id: str) -> list[dict]:
    rows = (
        db.query(models.PredictedLink)
        .filter(models.PredictedLink.case_id == case_id, models.PredictedLink.status == "pending")
        .order_by(models.PredictedLink.score.desc())
        .all()
    )
    return [r.detail or {"source": r.source_id, "target": r.target_id, "score": r.score,
                         "node_id": r.node_id} for r in rows]


def _get_or_create(db: Session, case_id: str, source_id: str, target_id: str, score: float):
    a, b = sorted((source_id, target_id))
    node_id = f"{a}__{b}"
    row = (
        db.query(models.PredictedLink)
        .filter(models.PredictedLink.case_id == case_id, models.PredictedLink.node_id == node_id)
        .first()
    )
    if row is None:
        row = models.PredictedLink(case_id=case_id, node_id=node_id, source_id=a, target_id=b,
                                   score=score or 0.0, status="pending")
        db.add(row)
    return row


def verify_predicted_link(db: Session, store, case_id: str, source_id: str, target_id: str,
                          score: float, investigator_id: str) -> dict:
    row = _get_or_create(db, case_id, source_id, target_id, score)
    row.status = "verified"
    row.decided_by = investigator_id
    row.decided_at = datetime.utcnow()
    db.add(models.VerifiedNode(case_id=case_id, node_id=row.node_id, source_id=row.source_id,
                               target_id=row.target_id, predicted_score=str(score),
                               verified_by=investigator_id))
    db.commit()

    store.upsert_edges(case_id, "PREDICTED_LINK_VERIFIED", [{
        "a": row.source_id, "b": row.target_id, "count": 1, "total_amount": 0.0, "max_amount": 0.0,
        "total_duration": 0, "first_ts": None, "last_ts": None, "locations": [],
        "extra": {"score": float(score or 0.0), "verified_by": investigator_id},
    }])
    log_case_event(db, case_id, investigator_id, "verify", target=row.node_id,
                   detail={"source_id": row.source_id, "target_id": row.target_id, "score": score})
    return {"node_id": row.node_id, "status": "verified", "joined_integrated_graph": True}


def dismiss_prediction(db: Session, case_id: str, source_id: str, target_id: str,
                       investigator_id: str, reason: str | None = None) -> dict:
    row = _get_or_create(db, case_id, source_id, target_id, 0.0)
    row.status = "dismissed"
    row.decided_by = investigator_id
    row.decided_at = datetime.utcnow()
    db.commit()
    log_case_event(db, case_id, investigator_id, "reject", target=row.node_id, detail={"reason": reason})
    return {"node_id": row.node_id, "status": "dismissed"}


def has_pending_unverified_predictions(db: Session, case_id: str, pending_node_ids: list[str] | None = None) -> bool:
    return (
        db.query(models.PredictedLink)
        .filter(models.PredictedLink.case_id == case_id, models.PredictedLink.status == "pending")
        .count()
        > 0
    )


def verified_links(db: Session, case_id: str) -> list[dict]:
    rows = db.query(models.PredictedLink).filter(
        models.PredictedLink.case_id == case_id, models.PredictedLink.status == "verified"
    ).all()
    return [{"source": r.source_id, "target": r.target_id, "score": r.score,
             "verified_by": r.decided_by, "verified_at": str(r.decided_at)} for r in rows]
