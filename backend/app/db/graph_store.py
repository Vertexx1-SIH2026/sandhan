"""
graph_store.py -- the ONE place the rest of the backend talks to the graph.

Graph model (identical in both backends):

  (:Case   {case_id, historical, title, ...})
  (:Entity {entity_id, entity_type, ...props})      entity_id e.g. "PHONE:+919812345601"

  (Entity)-[:APPEARS_IN {role, count}]->(Case)       role: subject | counterparty
  (Case)-[:LINKED_VIA {score, status, via, ...}]->(Case)
        only confirmed / investigator-verified case links are written here

  Entity->Entity relationships, each tagged with the case it came from
  (property case_id) so a case can be re-loaded or deleted cleanly:
      CALLED            Phone -> Phone      {count, total_duration, first_ts, last_ts, locations}
      USED_DEVICE       Phone -> Device     {count, ...}
      USED_IP           Phone -> IPAddress
      TRANSFERRED       UPI   -> UPI        {count, total_amount, max_amount, first_ts, last_ts}
      REGISTERED_MOBILE UPI   -> Phone
      LINKED_BANK       UPI   -> BankAccount
      MENTIONS          FIR   -> Phone / UPI / Person / Location
      ALIAS_OF          Person -> Person    (fuzzy name match, DSU)
      PREDICTED_LINK_VERIFIED              (only after HITL verification)

Backends:
  Neo4jGraphStore   -- default, app/db/neo4j_client.py
  MemoryGraphStore  -- app/db/memory_graph.py (tests / emergency fallback)
"""
from __future__ import annotations

from typing import Protocol

from app.core.config import settings

# Whitelist -- relationship types are interpolated into Cypher, so they must
# never come from user input.
ENTITY_REL_TYPES = {
    "CALLED", "USED_DEVICE", "USED_IP", "TRANSFERRED", "REGISTERED_MOBILE",
    "LINKED_BANK", "MENTIONS", "ALIAS_OF", "PREDICTED_LINK_VERIFIED", "CO_OCCURS_WITH",
}


class GraphStore(Protocol):
    def ping(self) -> tuple[bool, str]: ...
    def ensure_schema(self) -> None: ...
    def upsert_case(self, case_id: str, props: dict) -> None: ...
    def upsert_entities(self, case_id: str, rows: list[dict]) -> None: ...
    def upsert_edges(self, case_id: str, rel_type: str, rows: list[dict]) -> None: ...
    def link_cases(self, rows: list[dict]) -> None: ...
    def unlink_cases(self, case_a: str, case_b: str) -> None: ...
    def delete_cases(self, case_ids: list[str]) -> None: ...
    def case_set(self, case_id: str, hops: int) -> list[dict]: ...
    def entities_for_cases(self, case_ids: list[str]) -> list[dict]: ...
    def edges_among(self, entity_ids: list[str], case_ids: list[str]) -> list[dict]: ...
    def all_appearances(self) -> list[tuple[str, str]]: ...
    def appearance_count(self) -> int: ...
    def stats(self) -> dict: ...
    def close(self) -> None: ...


_store: GraphStore | None = None


def get_graph_store() -> GraphStore:
    global _store
    if _store is None:
        backend = settings.SANDHAN_GRAPH_BACKEND.lower().strip()
        if backend == "memory":
            from app.db.memory_graph import MemoryGraphStore

            _store = MemoryGraphStore(settings.storage_root / "graph_memory.pkl")
        else:
            from app.db.neo4j_client import Neo4jGraphStore

            _store = Neo4jGraphStore()
    return _store


def set_graph_store(store: GraphStore | None) -> None:
    """Test hook."""
    global _store
    _store = store


def close_graph_store() -> None:
    global _store
    if _store is not None:
        _store.close()
    _store = None


def batched(rows: list, size: int = 1000):
    for i in range(0, len(rows), size):
        yield rows[i : i + size]
