from datetime import datetime

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.v1.investigator.graph import build_integrated
from app.db import models
from app.db.graph_store import get_graph_store
from app.db.postgres_client import get_db
from app.services import evidence_engine, hitl_gate, link_engine, storage_client
from app.services.audit_logger import log_case_event, log_system_event
from app.services.rbac import require_investigator, require_case_access

router = APIRouter(prefix="/api/v1", tags=["investigator:evidence"])


def _link_args(payload: dict):
    case_id = payload.get("case_id")
    source_id, target_id = payload.get("source_id"), payload.get("target_id")
    if not (case_id and source_id and target_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "case_id, source_id and target_id are required")
    return case_id, source_id, target_id


@router.post("/evidence/verify-node")
def verify_node(payload: dict = Body(...), db: Session = Depends(get_db),
                claims: dict = Depends(require_investigator)):
    """HITL gate -- investigator confirms a predicted link; only now does it
    join the graph and become eligible for export."""
    case_id, source_id, target_id = _link_args(payload)
    require_case_access(case_id, claims)
    return hitl_gate.verify_predicted_link(db, get_graph_store(), case_id, source_id, target_id,
                                           float(payload.get("score") or 0.0), claims["user_id"])


@router.post("/evidence/dismiss-prediction")
def dismiss_prediction(payload: dict = Body(...), db: Session = Depends(get_db),
                       claims: dict = Depends(require_investigator)):
    case_id, source_id, target_id = _link_args(payload)
    require_case_access(case_id, claims)
    return hitl_gate.dismiss_prediction(db, case_id, source_id, target_id, claims["user_id"],
                                        payload.get("reason"))


@router.get("/report/evidence-pdf")
def evidence_pdf(
    case_id: str = Query(...),
    pending_node_ids: str = Query(default=""),  # accepted for backwards compatibility; server state is authoritative
    db: Session = Depends(get_db),
    claims: dict = Depends(require_investigator),
):
    require_case_access(case_id, claims)
    if hitl_gate.has_pending_unverified_predictions(db, case_id):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Resolve pending verifications before exporting (verify or dismiss each predicted link).")

    case = db.get(models.Case, case_id)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found")

    files = db.query(models.CaseFile).filter(models.CaseFile.case_id == case_id).all()
    dates = [f.ingested_at for f in files] or [case.created_at]
    date_range = f"{min(dates).date()} to {max(dates).date()}"
    snapshot = build_integrated(case_id, db)
    linked = link_engine.links_report(db, case_id)
    sources = [{"kind": s.kind, "filename": s.filename, "row_count": s.row_count, "sha256": s.sha256_hash}
               for s in db.query(models.HistoricalSource).all()]
    audit_rows = (
        db.query(models.CaseAuditLog).filter(models.CaseAuditLog.case_id == case_id)
        .order_by(models.CaseAuditLog.timestamp.desc()).limit(40).all()
    )
    pdf_bytes = evidence_engine.build_evidence_pdf(
        case_id=case_id,
        investigator_id=claims["user_id"],
        date_range=date_range,
        source_files=[f.source_filename for f in files],
        merkle_root=case.merkle_root or "N/A - no files ingested yet",
        graph_snapshot=snapshot,
        audit_excerpt=[{"timestamp": str(a.timestamp), "investigator_id": a.investigator_id,
                        "action": a.action, "target": a.target} for a in audit_rows],
        linked_cases=linked,
        historical_sources=sources,
        verified_predictions=hitl_gate.verified_links(db, case_id),
    )
    filename = f"evidence_{case_id}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.pdf"
    storage_client.save_evidence_pdf(case_id, filename, pdf_bytes)
    log_case_event(db, case_id, claims["user_id"], "export", target=filename)
    log_system_event(db, claims["user_id"], "export_event", {"export": "evidence_pdf"})  # no case content
    return Response(content=pdf_bytes, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})
