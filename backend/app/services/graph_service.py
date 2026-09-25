"""
graph_service.py -- the ingestion pipeline for a LIVE case:

  WORM storage -> parse -> normalise -> Postgres (case_records, identifier_index)
  -> graph (entities, typed edges) -> LINK DISCOVERY against every historical
  and live case -> case_links + LINKED_VIA -> Merkle root -> alerts

Runs synchronously inside a FastAPI background task (threadpool). Progress is
pushed with ws_manager.notify (thread-safe) and mirrored into an in-memory job
table readable at GET /api/v1/upload/jobs/{job_id}, so the UI and the smoke
test can poll if a WebSocket frame is missed.
"""
from __future__ import annotations

import re
import threading
import traceback
from datetime import datetime
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.core.security import merkle_root
from app.db import models
from app.db.graph_store import get_graph_store
from app.services import (
    etl_parser, link_engine, nlp_processor, normalizer, storage_client, validators,
)
from app.services.audit_logger import log_case_event
from app.ws.manager import ws_manager

JOBS: dict[str, dict] = {}
_jobs_lock = threading.Lock()


def _job_update(job_id: str, **kw) -> None:
    with _jobs_lock:
        JOBS.setdefault(job_id, {}).update(kw, updated_at=datetime.utcnow().isoformat())


def get_job(job_id: str) -> dict | None:
    with _jobs_lock:
        j = JOBS.get(job_id)
        return dict(j) if j else None


def ensure_live_case(db: Session, case_id: str, title: str | None = None) -> models.Case:
    case = db.get(models.Case, case_id)
    if case is None:
        case = models.Case(id=case_id, title=title or f"Case {case_id}")
        db.add(case)
        db.commit()
    is_hist = db.get(models.HistoricalCase, case_id) is not None
    get_graph_store().upsert_case(case_id, {"historical": is_hist, "title": case.title})
    return case


# ----------------------------------------------------------------------
# FIR
# ----------------------------------------------------------------------
def _fir_id_for(filename: str, fallback: str) -> str:
    m = re.search(r"FIR[-_ ]?\d{4}[-_ ]?\d+", filename, re.IGNORECASE)
    return m.group(0).upper().replace("_", "-").replace(" ", "-") if m else f"FIR-{fallback[:8]}"


def _process_fir(db: Session, store, case_id: str, fir_id: str, text: str) -> dict:
    """
    - identifiers named in the complaint (phone / UPI / IMEI) -> subject side
    - spaCy PERSON / GPE / LOC -> Person / Location nodes (if spaCy installed)
    - fuzzy person-name aliasing against every other case (RapidFuzz + DSU)
    - SBERT M.O. matches -> advisory alerts (if SBERT installed)
    """
    existing = db.get(models.FIRNarrative, fir_id)
    if existing:
        existing.narrative, existing.case_id = text, case_id
    else:
        db.add(models.FIRNarrative(fir_id=fir_id, case_id=case_id, narrative=text))
    db.commit()

    fir_eid = f"FIR:{fir_id}"
    named = nlp_processor.extract_identifiers(text)
    ents = nlp_processor.extract_entities(text)
    persons = [f"PERSON:{p.strip().lower()}" for p in ents.get("PERSON", [])]
    places = [f"LOCATION:{p.strip().lower()}" for p in ents.get("GPE", []) + ents.get("LOC", [])]

    # fuzzy alias: same person spelled differently in another case
    other_people = [
        i for (i,) in db.query(models.IdentifierIndex.identifier).filter(
            models.IdentifierIndex.id_type == "Person", models.IdentifierIndex.case_id != case_id
        ).distinct()
    ]
    alias_edges, alias_index = [], []
    for p in persons:
        if p in other_people:
            continue
        match, score = validators.fuzzy_best_match(p.split(":", 1)[1], [o.split(":", 1)[1] for o in other_people])
        if match:
            canonical = f"PERSON:{match}"
            alias_edges.append({"a": p, "b": canonical, "score": score})
            alias_index.append({"identifier": canonical, "id_type": "Person", "role": "counterparty",
                                "handle": None, "occurrences": 1})

    rows = [{"entity_id": fir_eid, "entity_type": "FIR", "props": {"value": fir_id}, "role": "subject", "count": 1}]
    for eid in named:
        rows.append({"entity_id": eid, "entity_type": normalizer.entity_type_of(eid),
                     "props": {"value": normalizer.bare_value(eid)}, "role": "subject", "count": 1})
    for eid in persons + places:
        rows.append({"entity_id": eid, "entity_type": normalizer.entity_type_of(eid),
                     "props": {"value": eid.split(":", 1)[1].title()}, "role": "counterparty", "count": 1})
    for al in alias_edges:
        rows.append({"entity_id": al["b"], "entity_type": "Person",
                     "props": {"value": al["b"].split(":", 1)[1].title()}, "role": "counterparty", "count": 1})
    store.upsert_entities(case_id, rows)

    blank = {"count": 1, "total_amount": 0.0, "max_amount": 0.0, "total_duration": 0,
             "first_ts": None, "last_ts": None, "locations": [], "extra": {}}
    store.upsert_edges(case_id, "MENTIONS", [{"a": fir_eid, "b": eid, **blank} for eid in named + persons + places])
    if alias_edges:
        store.upsert_edges(case_id, "ALIAS_OF", [
            {"a": al["a"], "b": al["b"], **blank, "extra": {"fuzzy_score": al["score"]}} for al in alias_edges
        ])

    index_rows = [
        {"identifier": eid, "id_type": normalizer.entity_type_of(eid), "role": "subject",
         "handle": validators.upi_handle(normalizer.bare_value(eid)) if eid.startswith("UPI:") else None,
         "occurrences": 1}
        for eid in named
    ] + [
        {"identifier": eid, "id_type": "Person", "role": "counterparty", "handle": None, "occurrences": 1}
        for eid in persons
    ] + alias_index
    link_engine.index_identifiers(db, case_id, index_rows, is_historical=False)

    mo_matches = []
    try:
        mo_matches = nlp_processor.find_similar_narratives(db, text, exclude_case=case_id)
    except Exception as exc:
        print(f"[graph_service] SBERT M.O. match skipped: {exc}")

    return {"named_identifiers": named, "persons": persons, "locations": places,
            "aliases": alias_edges, "mo_matches": mo_matches, "fir_id": fir_id}


# ----------------------------------------------------------------------
# Structured (CDR / UPI / IPDR / records)
# ----------------------------------------------------------------------
def _process_structured(db: Session, store, case_id: str, file_id: str, parsed: dict) -> dict:
    recs, stats = normalizer.normalize_records(parsed["records"], parsed["content_type"])
    g = normalizer.build_graph_rows(recs)

    store.upsert_entities(case_id, g.entity_rows())
    for rel in g.edges:
        store.upsert_edges(case_id, rel, g.edge_rows(rel))

    rows = normalizer.record_rows(recs)
    for r in rows:
        r.update(case_id=case_id, file_id=file_id)
    if rows:
        db.execute(models.CaseRecord.__table__.insert(), rows)
        db.commit()
    link_engine.index_identifiers(db, case_id, g.identifiers, is_historical=False)
    return {**stats, "entities": len(g.entities),
            "subjects": sorted(g.subjects)[:20],
            "edges": {rel: len(e) for rel, e in g.edges.items()}}


# ----------------------------------------------------------------------
# Link discovery (also callable on demand from the API)
# ----------------------------------------------------------------------
def relink_case(db: Session, case_id: str, cascade: bool = True) -> dict:
    results = link_engine.discover_links(db, case_id)
    summary = link_engine.persist_links(db, case_id, results, get_graph_store())
    if cascade:
        # other LIVE cases this one now touches get their own link list refreshed,
        # so the link shows up from both sides (historical cases were linked at load)
        for r in results:
            if not r.other_is_historical:
                relink_case(db, r.other_case_id, cascade=False)
    cluster = link_engine.case_cluster(db, case_id)
    summary["cluster_size"] = len(cluster)
    summary["top"] = [
        {"other_case_id": r.other_case_id, "status": r.status, "score": round(r.score, 3),
         "historical": r.other_is_historical}
        for r in results[:5]
    ]
    return summary


# ----------------------------------------------------------------------
# Main entrypoint
# ----------------------------------------------------------------------
def run_ingestion(
    db: Session,
    case_id: str,
    investigator_id: str,
    files: list[dict],          # [{filename, raw_bytes, declared_type}]
    job_id: str,
    notify: Callable[[str, dict], None] | None = None,
) -> dict:
    notify = notify or ws_manager.notify

    def push(stage: str, **extra: Any) -> None:
        _job_update(job_id, stage=stage, **{k: v for k, v in extra.items() if k in ("file", "error")})
        notify(case_id, {"case_id": case_id, "job_id": job_id, "stage": stage, **extra})

    _job_update(job_id, case_id=case_id, status="running", files=[f["filename"] for f in files])
    try:
        store = get_graph_store()
        case = ensure_live_case(db, case_id)
        push("ingestion_started")

        # FIRs first, so identifiers named in the complaint are already marked
        # as suspect-side when the CSVs are indexed.
        ordered = sorted(files, key=lambda f: 0 if f["filename"].lower().endswith((".pdf", ".txt")) else 1)
        alerts: list[dict] = []
        file_stats: list[dict] = []

        for f in ordered:
            filename, raw = f["filename"], f["raw_bytes"]
            push("storing", file=filename)
            stored = storage_client.save_original_and_copy(case_id, filename, raw)
            case_file = models.CaseFile(
                case_id=case_id, investigator_id=investigator_id, source_filename=filename,
                file_type=f.get("declared_type") or "unknown", sha256_hash=stored["sha256"],
                original_path=stored["original_path"], working_path=stored["working_path"], job_id=job_id,
            )
            db.add(case_file)
            db.commit()

            push("parsing", file=filename)
            parsed = etl_parser.parse_file(filename, storage_client.open_working_copy(stored["working_path"]),
                                           f.get("declared_type"))
            case_file.file_type = parsed["file_type"]
            db.commit()

            push("validating_and_merging", file=filename)
            if parsed["content_type"] == "fir":
                res = _process_fir(db, store, case_id, _fir_id_for(filename, case_file.id), parsed["full_text"])
                file_stats.append({"file": filename, "type": "fir",
                                   "named_identifiers": res["named_identifiers"],
                                   "persons": res["persons"], "aliases": res["aliases"]})
                for m in res["mo_matches"]:
                    alerts.append({"type": "sbert_mo_match", "case_id": case_id, **m})
            else:
                res = _process_structured(db, store, case_id, case_file.id, parsed)
                file_stats.append({"file": filename, "type": parsed["content_type"], **res})
            push("neo4j_inserted", file=filename)

        # ------------------------------------------------ link discovery
        push("linking")
        links = relink_case(db, case_id)
        alerts.append({"type": "historical_links", "case_id": case_id, **links})
        push("links_found", confirmed=links["confirmed"], probable=links["probable"],
             cluster_size=links["cluster_size"])

        case.merkle_root = merkle_root([cf.sha256_hash for cf in
                                        db.query(models.CaseFile).filter(models.CaseFile.case_id == case_id)])
        db.commit()
        log_case_event(db, case_id, investigator_id, "upload", target=job_id,
                       detail={"files": [f["filename"] for f in files], "links": links})

        result = {"merkle_root": case.merkle_root, "alerts": alerts, "stats": {"files": file_stats},
                  "links": links}
        _job_update(job_id, status="complete", result=result)
        notify(case_id, {"case_id": case_id, "job_id": job_id, "stage": "ingestion_complete", **result})
        return result
    except Exception as exc:
        db.rollback()
        traceback.print_exc()
        _job_update(job_id, status="failed", error=str(exc))
        notify(case_id, {"case_id": case_id, "job_id": job_id, "stage": "ingestion_failed", "error": str(exc)})
        return {"error": str(exc)}
