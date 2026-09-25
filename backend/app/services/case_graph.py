"""
case_graph.py -- builds "the network for this case":

    the case itself
  + every case linked to it by a confirmed / verified LINKED_VIA
    (historical or live), out to SANDHAN_CASE_HOPS hops
  + every entity appearing in those cases and the typed edges between them

One function (`load_case_graph`) is used by the canvas, the analytics, the
subgraph drill-down and the evidence export, so they always agree.
"""
from __future__ import annotations

from collections import defaultdict

import networkx as nx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db import models
from app.db.graph_store import get_graph_store
from app.services import privacy_guard

# Identifiers that represent actors/infrastructure -- what the graph
# algorithms rank. FIR / Person / Location nodes are context only.
ACTOR_TYPES = {"Phone", "Device", "UPIAccount", "BankAccount", "IPAddress"}


def load_case_graph(case_id: str, hops: int | None = None) -> dict:
    store = get_graph_store()
    hops = settings.SANDHAN_CASE_HOPS if hops is None else hops
    cases = store.case_set(case_id, hops)
    if not cases:
        return {"root": case_id, "cases": [], "entities": [], "edges": []}
    case_ids = [c["case_id"] for c in cases]
    entities = store.entities_for_cases(case_ids)
    ids = [e["entity_id"] for e in entities]
    edges = store.edges_among(ids, case_ids)
    return {"root": case_id, "cases": cases, "entities": entities, "edges": edges}


def _visible_ids(db: Session | None, case_id: str) -> set[str]:
    if db is None:
        return set()
    visible = privacy_guard.escalated_ids(db, case_id)
    for s, t in db.query(models.PredictedLink.source_id, models.PredictedLink.target_id).filter(
        models.PredictedLink.case_id == case_id, models.PredictedLink.status == "verified"
    ):
        visible.update((s, t))
    return visible


def serialize(raw: dict, db: Session | None = None) -> dict:
    """API/PDF shape with DPDP masking applied."""
    root = raw["root"]
    case_meta = {c["case_id"]: c for c in raw["cases"]}
    visible = _visible_ids(db, root)

    nodes = []
    for e in raw["entities"]:
        props = e.get("props") or {}
        etype = e["entity_type"]
        appearances = e.get("appearances") or []
        case_ids = sorted({a["case_id"] for a in appearances})
        is_subject = any(a.get("role") == "subject" for a in appearances)
        value = props.get("value") or e["entity_id"].split(":", 1)[-1]
        shown = is_subject or e["entity_id"] in visible or etype not in privacy_guard.MASKED_TYPES
        nodes.append({
            "entity_id": e["entity_id"],
            "entity_type": etype,
            "display_value": value if shown else privacy_guard.mask_value(etype, value),
            "masked": not shown,
            "is_subject": is_subject,
            "cases": case_ids,
            "in_root_case": root in case_ids,
            "historical_only": all(case_meta.get(c, {}).get("historical") for c in case_ids),
            "luhn_valid": props.get("luhn_valid"),
        })

    agg: dict[tuple, dict] = {}
    for ed in raw["edges"]:
        p = ed.get("props") or {}
        key = (ed["a"], ed["b"], ed["rel"])
        cur = agg.get(key)
        if cur is None:
            cur = agg[key] = {
                "source": ed["a"], "target": ed["b"], "relation": ed["rel"],
                "count": 0, "total_amount": 0.0, "max_amount": 0.0, "total_duration": 0,
                "first_ts": None, "last_ts": None, "case_ids": [], "verified": False,
            }
        cur["count"] += int(p.get("count") or 0)
        cur["total_amount"] += float(p.get("total_amount") or 0)
        cur["max_amount"] = max(cur["max_amount"], float(p.get("max_amount") or 0))
        cur["total_duration"] += int(p.get("total_duration") or 0)
        for k, better in (("first_ts", min), ("last_ts", max)):
            if p.get(k):
                cur[k] = p[k] if cur[k] is None else better(cur[k], p[k])
        if p.get("case_id") and p["case_id"] not in cur["case_ids"]:
            cur["case_ids"].append(p["case_id"])
        if ed["rel"] == "PREDICTED_LINK_VERIFIED":
            cur["verified"] = True
            cur["verified_by"] = p.get("verified_by")
            cur["score"] = p.get("score")

    return {
        "root": root,
        "cases": raw["cases"],
        "nodes": nodes,
        "edges": list(agg.values()),
        "stats": {
            "cases": len(raw["cases"]),
            "historical_cases": sum(1 for c in raw["cases"] if c.get("historical")),
            "nodes": len(nodes),
            "edges": len(agg),
        },
    }


def to_networkx(raw: dict, directed: bool = False, rel_types: set[str] | None = None,
                actor_only: bool = True) -> tuple[nx.Graph, dict]:
    """Collapses per-case parallel edges into one weighted edge per pair."""
    g = nx.DiGraph() if directed else nx.Graph()
    meta: dict[str, dict] = {}
    for e in raw["entities"]:
        if actor_only and e["entity_type"] not in ACTOR_TYPES:
            continue
        roles = {a.get("role") for a in e.get("appearances") or []}
        meta[e["entity_id"]] = {
            "entity_type": e["entity_type"],
            "is_subject": "subject" in roles,
            "cases": sorted({a["case_id"] for a in e.get("appearances") or []}),
        }
        g.add_node(e["entity_id"], **meta[e["entity_id"]])
    weights: dict[tuple, dict] = defaultdict(lambda: {"count": 0, "amount": 0.0})
    for ed in raw["edges"]:
        if rel_types and ed["rel"] not in rel_types:
            continue
        a, b = ed["a"], ed["b"]
        if a not in meta or b not in meta or a == b:
            continue
        key = (a, b) if directed else tuple(sorted((a, b)))
        p = ed.get("props") or {}
        weights[key]["count"] += int(p.get("count") or 1)
        weights[key]["amount"] += float(p.get("total_amount") or 0)
    for (a, b), w in weights.items():
        g.add_edge(a, b, count=w["count"], amount=w["amount"])
    return g, meta
