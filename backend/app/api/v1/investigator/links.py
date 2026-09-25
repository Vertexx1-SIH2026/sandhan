from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.graph_store import get_graph_store
from app.db.postgres_client import get_db
from app.services import graph_service, link_engine
from app.services.audit_logger import log_case_event
from app.services.rbac import require_investigator, require_case_access

router = APIRouter(prefix="/api/v1/links", tags=["investigator:links"])


@router.get("/historical")
def historical_links(
    case_id: str = Query(...),
    refresh: bool = Query(default=False),
    db: Session = Depends(get_db),
    claims: dict = Depends(require_investigator),
):
    """
    Ranked list of every case (historical or live) linked to this one, with
    the evidence behind each link. refresh=true re-runs discovery against the
    full identifier index first (automatic after every ingestion).
    """
    require_case_access(case_id, claims)
    summary = graph_service.relink_case(db, case_id) if refresh else None
    cluster = sorted(link_engine.case_cluster(db, case_id))
    log_case_event(db, case_id, claims["user_id"], "query", target="historical_links")
    return {"case_id": case_id, "links": link_engine.links_report(db, case_id),
            "cluster": cluster, "summary": summary}


@router.post("/decide")
def decide(
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    claims: dict = Depends(require_investigator),
):
    """HITL for probable case links: {case_id, other_case_id, decision: verify|dismiss}."""
    case_id, other, decision = payload.get("case_id"), payload.get("other_case_id"), payload.get("decision")
    require_case_access(case_id, claims)
    if decision not in ("verify", "dismiss"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "decision must be 'verify' or 'dismiss'")
    try:
        row = link_engine.decide_link(db, case_id, other, decision, claims["user_id"], get_graph_store())
    except KeyError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such link for this case")
    log_case_event(db, case_id, claims["user_id"], "verify" if decision == "verify" else "reject",
                   target=f"case_link:{other}", detail={"score": row.score})
    return {"case_id": case_id, "other_case_id": other, "status": row.status}
