from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.postgres_client import get_db
from app.services import nlp_processor
from app.services.audit_logger import log_case_event
from app.services.rbac import require_investigator, require_case_access

router = APIRouter(prefix="/api/v1/nlp", tags=["investigator:nlp"])


@router.post("/mo-match")
def mo_match(
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    claims: dict = Depends(require_investigator),
):
    """SBERT cosine match of a narrative against every historical + live FIR.
    Advisory only -- never touches the graph."""
    case_id = payload.get("case_id")
    fir_text = (payload.get("fir_text") or "").strip()
    require_case_access(case_id, claims)
    if not fir_text:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "fir_text is required")
    if not nlp_processor.sbert_available():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "SBERT model not available -- pip install sentence-transformers")
    matches = nlp_processor.find_similar_narratives(db, fir_text, exclude_case=case_id,
                                                    top_k=int(payload.get("top_k", 5)))
    log_case_event(db, case_id, claims["user_id"], "query", target="mo_match")
    return {"matches": matches}
