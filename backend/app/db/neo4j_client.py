"""
Neo4j backend for the graph store. All Cypher lives in this file.
Only plain Cypher (no APOC / GDS plugins needed), Neo4j 5.x.
"""
from __future__ import annotations

from neo4j import GraphDatabase

from app.core.config import settings
from app.db.graph_store import ENTITY_REL_TYPES, batched

_driver = None


def get_driver():
    global _driver
    if _driver is None:
        _driver = GraphDatabase.driver(
            settings.NEO4J_URI, auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD)
        )
    return _driver


def close_driver():
    global _driver
    if _driver is not None:
        _driver.close()
        _driver = None


def run_query(query: str, params: dict | None = None) -> list[dict]:
    driver = get_driver()
    with driver.session() as session:
        result = session.run(query, params or {})
        return [record.data() for record in result]


def ensure_constraints() -> None:
    """Backwards-compatible name used by older scripts."""
    Neo4jGraphStore().ensure_schema()


class Neo4jGraphStore:
    # ------------------------------------------------------------------
    def ping(self) -> tuple[bool, str]:
        try:
            run_query("RETURN 1 AS ok")
            return True, "ok"
        except Exception as exc:  # pragma: no cover
            return False, str(exc).splitlines()[0]

    def ensure_schema(self) -> None:
        stmts = [
            "CREATE CONSTRAINT entity_id IF NOT EXISTS FOR (e:Entity) REQUIRE e.entity_id IS UNIQUE",
            "CREATE CONSTRAINT case_id IF NOT EXISTS FOR (c:Case) REQUIRE c.case_id IS UNIQUE",
        ]
        for stmt in stmts:
            run_query(stmt)

    def close(self) -> None:
        close_driver()

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------
    def upsert_case(self, case_id: str, props: dict) -> None:
        run_query(
            "MERGE (c:Case {case_id: $case_id}) SET c += $props",
            {"case_id": case_id, "props": props or {}},
        )

    def upsert_entities(self, case_id: str, rows: list[dict]) -> None:
        """rows: [{entity_id, entity_type, props: {...primitives}, role, count}]"""
        q = """
        UNWIND $rows AS row
        MERGE (e:Entity {entity_id: row.entity_id})
        SET e.entity_type = row.entity_type, e += row.props
        WITH e, row
        MATCH (c:Case {case_id: $case_id})
        MERGE (e)-[r:APPEARS_IN]->(c)
        SET r.role = CASE WHEN r.role = 'subject' THEN 'subject' ELSE row.role END,
            r.count = coalesce(r.count, 0) + row.count
        """
        for chunk in batched(rows):
            run_query(q, {"rows": chunk, "case_id": case_id})

    def upsert_edges(self, case_id: str, rel_type: str, rows: list[dict]) -> None:
        """rows: [{a, b, count, total_amount, max_amount, total_duration,
                   first_ts, last_ts, locations, extra: {...}}]"""
        if rel_type not in ENTITY_REL_TYPES:
            raise ValueError(f"Unknown relationship type {rel_type}")
        q = f"""
        UNWIND $rows AS row
        MATCH (a:Entity {{entity_id: row.a}})
        MATCH (b:Entity {{entity_id: row.b}})
        MERGE (a)-[r:{rel_type} {{case_id: $case_id}}]->(b)
        SET r.count = coalesce(r.count, 0) + row.count,
            r.total_amount = coalesce(r.total_amount, 0.0) + row.total_amount,
            r.max_amount = CASE WHEN coalesce(r.max_amount, 0.0) > row.max_amount
                                THEN r.max_amount ELSE row.max_amount END,
            r.total_duration = coalesce(r.total_duration, 0) + row.total_duration,
            r.first_ts = CASE WHEN r.first_ts IS NULL OR row.first_ts < r.first_ts
                              THEN row.first_ts ELSE r.first_ts END,
            r.last_ts = CASE WHEN r.last_ts IS NULL OR row.last_ts > r.last_ts
                             THEN row.last_ts ELSE r.last_ts END,
            r.locations = coalesce(r.locations, []) +
                          [l IN row.locations WHERE NOT l IN coalesce(r.locations, [])]
        SET r += row.extra
        """
        for chunk in batched(rows):
            run_query(q, {"rows": chunk, "case_id": case_id})

    def link_cases(self, rows: list[dict]) -> None:
        """rows: [{a, b, score, status, via: [entity ids], kind}] -- a < b."""
        q = """
        UNWIND $rows AS row
        MATCH (a:Case {case_id: row.a})
        MATCH (b:Case {case_id: row.b})
        MERGE (a)-[r:LINKED_VIA]->(b)
        SET r.score = row.score, r.status = row.status, r.via = row.via,
            r.kind = row.kind, r.updated_at = timestamp()
        """
        for chunk in batched(rows):
            run_query(q, {"rows": chunk})

    def unlink_cases(self, case_a: str, case_b: str) -> None:
        run_query(
            "MATCH (:Case {case_id: $a})-[r:LINKED_VIA]-(:Case {case_id: $b}) DELETE r",
            {"a": case_a, "b": case_b},
        )

    def delete_cases(self, case_ids: list[str]) -> None:
        if not case_ids:
            return
        run_query("MATCH ()-[r]->() WHERE r.case_id IN $ids DELETE r", {"ids": case_ids})
        run_query("MATCH (c:Case) WHERE c.case_id IN $ids DETACH DELETE c", {"ids": case_ids})
        run_query("MATCH (e:Entity) WHERE NOT EXISTS { (e)-[:APPEARS_IN]->(:Case) } DETACH DELETE e")

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------
    def case_set(self, case_id: str, hops: int) -> list[dict]:
        hops = max(0, min(int(hops), 4))
        if hops == 0:
            rows = run_query(
                "MATCH (c:Case {case_id: $case_id}) "
                "RETURN c.case_id AS case_id, coalesce(c.historical, false) AS historical",
                {"case_id": case_id},
            )
            return [{"case_id": r["case_id"], "historical": r["historical"], "depth": 0} for r in rows]

        rows = run_query(
            f"""
            MATCH (c:Case {{case_id: $case_id}})
            OPTIONAL MATCH p = (c)-[:LINKED_VIA*1..{hops}]-(o:Case)
            WITH c, o, min(length(p)) AS depth
            RETURN c.case_id AS root, coalesce(c.historical, false) AS root_historical,
                   o.case_id AS case_id, coalesce(o.historical, false) AS historical, depth
            """,
            {"case_id": case_id},
        )
        if not rows:
            return []
        out = [{"case_id": rows[0]["root"], "historical": rows[0]["root_historical"], "depth": 0}]
        seen = {rows[0]["root"]}
        for r in sorted(rows, key=lambda x: (x["depth"] is None, x["depth"] or 0)):
            cid = r["case_id"]
            if cid and cid not in seen:
                seen.add(cid)
                out.append({"case_id": cid, "historical": r["historical"], "depth": r["depth"]})
        return out

    def entities_for_cases(self, case_ids: list[str]) -> list[dict]:
        if not case_ids:
            return []
        return run_query(
            """
            UNWIND $case_ids AS cid
            MATCH (e:Entity)-[r:APPEARS_IN]->(:Case {case_id: cid})
            WITH e, collect({case_id: cid, role: r.role}) AS appearances
            RETURN e.entity_id AS entity_id, e.entity_type AS entity_type,
                   properties(e) AS props, appearances
            """,
            {"case_ids": case_ids},
        )

    def edges_among(self, entity_ids: list[str], case_ids: list[str]) -> list[dict]:
        if not entity_ids or not case_ids:
            return []
        return run_query(
            """
            MATCH (a:Entity)-[r]->(b:Entity)
            WHERE a.entity_id IN $ids AND b.entity_id IN $ids AND r.case_id IN $case_ids
            RETURN a.entity_id AS a, b.entity_id AS b, type(r) AS rel, properties(r) AS props
            """,
            {"ids": entity_ids, "case_ids": case_ids},
        )

    def all_appearances(self) -> list[tuple[str, str]]:
        rows = run_query(
            "MATCH (e:Entity)-[:APPEARS_IN]->(c:Case) RETURN e.entity_id AS eid, c.case_id AS cid"
        )
        return [(r["eid"], r["cid"]) for r in rows]

    def appearance_count(self) -> int:
        rows = run_query("MATCH (:Entity)-[r:APPEARS_IN]->(:Case) RETURN count(r) AS n")
        return int(rows[0]["n"]) if rows else 0

    def stats(self) -> dict:
        def one(q: str) -> int:
            rows = run_query(q)
            return int(rows[0]["n"]) if rows else 0

        return {
            "cases": one("MATCH (c:Case) RETURN count(c) AS n"),
            "historical_cases": one("MATCH (c:Case) WHERE c.historical = true RETURN count(c) AS n"),
            "entities": one("MATCH (e:Entity) RETURN count(e) AS n"),
            "case_links": one("MATCH ()-[r:LINKED_VIA]->() RETURN count(r) AS n"),
        }
