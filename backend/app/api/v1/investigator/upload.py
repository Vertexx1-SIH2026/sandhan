import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile, status

from app.db.postgres_client import SessionLocal
from app.services import graph_service
from app.services.rbac import require_investigator, require_case_access

router = APIRouter(prefix="/api/v1/upload", tags=["investigator:upload"])

MAX_FILE_BYTES = 50 * 1024 * 1024


@router.post("/ingest")
async def ingest(
    background_tasks: BackgroundTasks,
    case_id: str = Form(...),
    declared_type: str | None = Form(default=None),  # cdr | upi | ipdr | records | fir; omit to auto-detect
    files: list[UploadFile] = File(...),
    claims: dict = Depends(require_investigator),
):
    require_case_access(case_id, claims)
    job_id = uuid.uuid4().hex[:10]
    payloads = []
    for f in files:
        raw = await f.read()
        if len(raw) > MAX_FILE_BYTES:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, f"{f.filename} is larger than 50 MB")
        payloads.append({"filename": f.filename, "raw_bytes": raw, "declared_type": declared_type or None})

    graph_service._job_update(job_id, case_id=case_id, status="queued", files=[p["filename"] for p in payloads])
    # Sync function -> Starlette runs it in the threadpool after the response;
    # progress goes over /ws/v1/graphstream and GET /jobs/{job_id}.
    background_tasks.add_task(_run_ingest, case_id, claims["user_id"], payloads, job_id)
    return {"job_id": job_id, "case_id": case_id, "files_queued": [p["filename"] for p in payloads]}


def _run_ingest(case_id: str, investigator_id: str, payloads: list[dict], job_id: str) -> None:
    db = SessionLocal()
    try:
        graph_service.run_ingestion(db, case_id, investigator_id, payloads, job_id)
    finally:
        db.close()


@router.get("/jobs/{job_id}")
def job_status(job_id: str, claims: dict = Depends(require_investigator)):
    job = graph_service.get_job(job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown job")
    require_case_access(job.get("case_id"), claims)
    return job
