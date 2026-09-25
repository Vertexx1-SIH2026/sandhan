from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy.orm import Session

from app.db.postgres_client import get_db
from app.services import graph_analytics, hitl_gate
from app.services.audit_logger import log_case_event
from app.services.rbac import require_investigator, require_case_access
from app.ws.manager import ws_manager

router = APIRouter(prefix="/api/v1/analytics", tags=["investigator:analytics"])


@router.post("/ringleaders")
def ringleaders(
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    claims: dict = Depends(require_investigator),
):
    """Algorithms 1-5 over the whole case network (case + linked cases),
    from ONE graph load. Fires one 'analytics_complete' WS event."""
    case_id = payload.get("case_id")
    require_case_access(case_id, claims)
    result = graph_analytics.run_all(case_id)
    log_case_event(db, case_id, claims["user_id"], "query", target="ringleaders")
    ws_manager.notify(case_id, {"case_id": case_id, "stage": "analytics_complete"})
    return result


@router.get("/smurfing-cycles")
def smurfing_cycles(
    case_id: str = Query(...),
    max_depth: int = Query(default=5, ge=2, le=8),
    threshold: float = Query(default=50000, ge=0),
    db: Session = Depends(get_db),
    claims: dict = Depends(require_investigator),
):
    require_case_access(case_id, claims)
    result = graph_analytics.smurfing_cycles(case_id, max_depth=max_depth, threshold=threshold)
    log_case_event(db, case_id, claims["user_id"], "query", target="smurfing_cycles",
                   detail={"max_depth": max_depth, "threshold": threshold})
    return result


@router.post("/predict-links")
def predict_links(
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    claims: dict = Depends(require_investigator),
):
    """Algorithm 6 -- returns 'predicted (unverified)' links only; each one
    is stored as pending and must be verified or dismissed (HITL)."""
    case_id = payload.get("case_id")
    require_case_access(case_id, claims)
    predictions = graph_analytics.predict_links(case_id, exclude=hitl_gate.decided_pairs(db, case_id),
                                                top_k=int(payload.get("top_k", 5)))
    hitl_gate.record_predictions(db, case_id, predictions)
    log_case_event(db, case_id, claims["user_id"], "query", target="predict_links",
                   detail={"count": len(predictions)})
    ws_manager.notify(case_id, {"case_id": case_id, "stage": "alert",
                                "alert_type": "predicted_link", "count": len(predictions)})
    return {"predicted_links": predictions}


@router.get("/predicted-links")
def pending_predicted_links(
    case_id: str = Query(...),
    claims: dict = Depends(require_investigator),
    db: Session = Depends(get_db),
):
    require_case_access(case_id, claims)
    return {"predicted_links": hitl_gate.pending_predictions(db, case_id)}
