"""
In-process graph store with exactly the same semantics as Neo4jGraphStore.

Used by the automated tests (tests/test_end_to_end.py) and available as an
emergency fallback (SANDHAN_GRAPH_BACKEND=memory) if Neo4j can't be installed
on a demo machine. State is pickled to storage/graph_memory.pkl after every
write so the loader script and the API server (two processes) see the same
data. Not meant for production use -- Neo4j is the real backend.
"""
from __future__ import annotations

import os
import pickle
import threading
from pathlib import Path

from app.db.graph_store import ENTITY_REL_TYPES


class MemoryGraphStore:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else None
        self._lock = threading.RLock()
        self._mtime = None
        self._reset()
        self._load()

    # -- persistence ----------------------------------------------------
    def _reset(self):
        self.cases: dict[str, dict] = {}
        self.entities: dict[str, dict] = {}              # id -> {entity_type, props}
        self.appears: dict[tuple[str, str], dict] = {}   # (eid, cid) -> {role, count}
        self.edges: dict[tuple[str, str, str, str], dict] = {}  # (a, b, rel, case_id) -> props
        self.case_links: dict[tuple[str, str], dict] = {}

    def _load(self):
        if self.path and self.path.exists():
            mtime = self.path.stat().st_mtime
            if mtime != self._mtime:
                with open(self.path, "rb") as f:
                    state = pickle.load(f)
                (self.cases, self.entities, self.appears, self.edges, self.case_links) = state
                self._mtime = mtime

    def _save(self):
        if not self.path:
            return
        tmp = self.path.with_suffix(".tmp")
        with open(tmp, "wb") as f:
            pickle.dump((self.cases, self.entities, self.appears, self.edges, self.case_links), f)
        os.replace(tmp, self.path)
        self._mtime = self.path.stat().st_mtime

    def _refresh(self):
        self._load()

    # -- interface --------------------------------------------------------
    def ping(self):
        return True, "ok (in-memory graph store)"

    def ensure_schema(self):
        pass

    def close(self):
        pass

    def upsert_case(self, case_id, props):
        with self._lock:
            self._refresh()
            self.cases.setdefault(case_id, {"case_id": case_id}).update(props or {})
            self._save()

    def upsert_entities(self, case_id, rows):
        with self._lock:
            self._refresh()
            if case_id not in self.cases:
                return
            for row in rows:
                ent = self.entities.setdefault(row["entity_id"], {"entity_type": row["entity_type"], "props": {}})
                ent["entity_type"] = row["entity_type"]
                ent["props"].update(row.get("props") or {})
                ap = self.appears.setdefault((row["entity_id"], case_id), {"role": None, "count": 0})
                ap["role"] = "subject" if ap["role"] == "subject" else row["role"]
                ap["count"] += row.get("count", 1)
            self._save()

    def upsert_edges(self, case_id, rel_type, rows):
        if rel_type not in ENTITY_REL_TYPES:
            raise ValueError(rel_type)
        with self._lock:
            self._refresh()
            for row in rows:
                if row["a"] not in self.entities or row["b"] not in self.entities:
                    continue
                key = (row["a"], row["b"], rel_type, case_id)
                r = self.edges.setdefault(key, {"case_id": case_id})
                r["count"] = r.get("count", 0) + row["count"]
                r["total_amount"] = r.get("total_amount", 0.0) + row["total_amount"]
                r["max_amount"] = max(r.get("max_amount", 0.0), row["max_amount"])
                r["total_duration"] = r.get("total_duration", 0) + row["total_duration"]
                if row.get("first_ts") and (r.get("first_ts") is None or row["first_ts"] < r["first_ts"]):
                    r["first_ts"] = row["first_ts"]
                else:
                    r.setdefault("first_ts", None)
                if row.get("last_ts") and (r.get("last_ts") is None or row["last_ts"] > r["last_ts"]):
                    r["last_ts"] = row["last_ts"]
                else:
                    r.setdefault("last_ts", None)
                locs = r.get("locations") or []
                r["locations"] = locs + [l for l in row.get("locations", []) if l not in locs]
                r.update(row.get("extra") or {})
            self._save()

    def link_cases(self, rows):
        with self._lock:
            self._refresh()
            for row in rows:
                if row["a"] in self.cases and row["b"] in self.cases:
                    self.case_links[(row["a"], row["b"])] = {
                        k: row.get(k) for k in ("score", "status", "via", "kind")
                    }
            self._save()

    def unlink_cases(self, case_a, case_b):
        with self._lock:
            self._refresh()
            self.case_links.pop((case_a, case_b), None)
            self.case_links.pop((case_b, case_a), None)
            self._save()

    def delete_cases(self, case_ids):
        ids = set(case_ids)
        with self._lock:
            self._refresh()
            self.edges = {k: v for k, v in self.edges.items() if k[3] not in ids}
            for cid in ids:
                self.cases.pop(cid, None)
            self.appears = {k: v for k, v in self.appears.items() if k[1] not in ids}
            self.case_links = {k: v for k, v in self.case_links.items() if k[0] not in ids and k[1] not in ids}
            alive = {eid for (eid, _cid) in self.appears}
            dead = set(self.entities) - alive
            for eid in dead:
                self.entities.pop(eid)
            self.edges = {k: v for k, v in self.edges.items() if k[0] in alive and k[1] in alive}
            self._save()

    def case_set(self, case_id, hops):
        with self._lock:
            self._refresh()
            if case_id not in self.cases:
                return []
            adj: dict[str, set[str]] = {}
            for (a, b) in self.case_links:
                adj.setdefault(a, set()).add(b)
                adj.setdefault(b, set()).add(a)
            depth = {case_id: 0}
            frontier = [case_id]
            for d in range(1, max(0, int(hops)) + 1):
                nxt = []
                for c in frontier:
                    for o in adj.get(c, ()):
                        if o not in depth:
                            depth[o] = d
                            nxt.append(o)
                frontier = nxt
            return [
                {"case_id": c, "historical": bool(self.cases[c].get("historical", False)), "depth": d}
                for c, d in sorted(depth.items(), key=lambda kv: kv[1])
            ]

    def entities_for_cases(self, case_ids):
        ids = set(case_ids)
        with self._lock:
            self._refresh()
            out: dict[str, dict] = {}
            for (eid, cid), ap in self.appears.items():
                if cid in ids:
                    ent = self.entities[eid]
                    row = out.setdefault(eid, {
                        "entity_id": eid,
                        "entity_type": ent["entity_type"],
                        "props": {"entity_id": eid, "entity_type": ent["entity_type"], **ent["props"]},
                        "appearances": [],
                    })
                    row["appearances"].append({"case_id": cid, "role": ap["role"]})
            return list(out.values())

    def edges_among(self, entity_ids, case_ids):
        eids, cids = set(entity_ids), set(case_ids)
        with self._lock:
            self._refresh()
            return [
                {"a": a, "b": b, "rel": rel, "props": dict(props)}
                for (a, b, rel, cid), props in self.edges.items()
                if cid in cids and a in eids and b in eids
            ]

    def all_appearances(self):
        with self._lock:
            self._refresh()
            return list(self.appears.keys())

    def appearance_count(self):
        with self._lock:
            self._refresh()
            return len(self.appears)

    def stats(self):
        with self._lock:
            self._refresh()
            return {
                "cases": len(self.cases),
                "historical_cases": sum(1 for c in self.cases.values() if c.get("historical")),
                "entities": len(self.entities),
                "case_links": len(self.case_links),
            }
