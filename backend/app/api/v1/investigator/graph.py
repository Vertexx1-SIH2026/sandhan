import networkx as nx
from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.data_structures.trie_search import Trie
from app.db.postgres_client import get_db
from app.services import case_graph, privacy_guard
from app.services.audit_logger import log_case_event
from app.services.rbac import require_investigator, require_case_access

router = APIRouter(prefix="/api/v1/graph", tags=["investigator:graph"])


def build_integrated(case_id: str, db: Session, hops: int | None = None) -> dict:
    return case_graph.serialize(case_graph.load_case_graph(case_id, hops), db)


@router.get("/integrated")
def integrated(
    case_id: str = Query(...),
    hops: int | None = Query(default=None, ge=0, le=4),
    db: Session = Depends(get_db),
    claims: dict = Depends(require_investigator),
):
    """The case network: this case + every confirmed/verified linked case
    (historical and live) out to `hops` LINKED_VIA hops, with DPDP masking."""
    require_case_access(case_id, claims)
    snap = build_integrated(case_id, db, hops)
    log_case_event(db, case_id, claims["user_id"], "view", target="integrated_graph",
                   detail={"cases": snap["stats"]["cases"]})
    return snap


@router.get("/subgraph")
def subgraph(
    case_id: str = Query(...),
    center_node: str = Query(...),
    hops: int = Query(default=2, ge=1, le=6),
    db: Session = Depends(get_db),
    claims: dict = Depends(require_investigator),
):
    """N-hop neighbourhood of one entity -- restricted to the case network."""
    require_case_access(case_id, claims)
    raw = case_graph.load_case_graph(case_id)
    g, _ = case_graph.to_networkx(raw, actor_only=False)
    if center_node not in g:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Entity is not part of this case network")
    keep = set(nx.ego_graph(g, center_node, radius=hops).nodes)
    raw_sub = {
        **raw,
        "entities": [e for e in raw["entities"] if e["entity_id"] in keep],
        "edges": [e for e in raw["edges"] if e["a"] in keep and e["b"] in keep],
    }
    log_case_event(db, case_id, claims["user_id"], "query", target=center_node, detail={"hops": hops})
    return case_graph.serialize(raw_sub, db)


@router.get("/search")
def search(
    case_id: str = Query(...),
    prefix: str = Query(..., min_length=3),
    db: Session = Depends(get_db),
    claims: dict = Depends(require_investigator),
):
    """Trie prefix search over identifiers in this case network
    (phones, IMEIs, UPI IDs...). Returns masked display values."""
    require_case_access(case_id, claims)
    snap = build_integrated(case_id, db)
    trie = Trie()
    by_id = {}
    for n in snap["nodes"]:
        by_id[n["entity_id"]] = n
        value = n["entity_id"].split(":", 1)[-1].lower()
        trie.insert(value, n["entity_id"])
        if value.startswith("+91"):
            trie.insert(value[3:], n["entity_id"])
    hits = trie.search_prefix(prefix.strip().lower(), limit=15)
    return [{k: by_id[h][k] for k in ("entity_id", "entity_type", "display_value", "cases")} for h in hits]


@router.post("/escalate")
def escalate(
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    claims: dict = Depends(require_investigator),
):
    """Lift DPDP masking for one entity in one case -- logged and persisted."""
    case_id, entity_id = payload.get("case_id"), payload.get("entity_id")
    require_case_access(case_id, claims)
    if not entity_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "entity_id is required")
    return privacy_guard.escalate_entity(db, case_id, entity_id, claims["user_id"], payload.get("reason"))
