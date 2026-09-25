"""
End-to-end API test: the whole demo flow, in-process.

Uses a REAL Postgres (the database in backend/.env, or SANDHAN_DATABASE_URL)
and the in-memory graph store, so it runs without Neo4j. It DROPS AND
RECREATES every Sandhan table -- point it at a throwaway database:

    createdb sandhan_test
    SANDHAN_DATABASE_URL=postgresql+psycopg2://sandhan:sandhan@localhost/sandhan_test \
    SANDHAN_GRAPH_BACKEND=memory python tests/test_end_to_end.py

(Also runs under pytest.) To test against Neo4j instead, run
scripts/smoke_test.py against a running server.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("SANDHAN_GRAPH_BACKEND", "memory")
os.environ.setdefault("SANDHAN_STORAGE_ROOT", tempfile.mkdtemp(prefix="sandhan_test_"))

from fastapi.testclient import TestClient  # noqa: E402

from app.core.config import settings, PROJECT_DIR  # noqa: E402
from app.db import models  # noqa: E402,F401
from app.db.graph_store import set_graph_store  # noqa: E402
from app.db.memory_graph import MemoryGraphStore  # noqa: E402
from app.db.postgres_client import Base, engine  # noqa: E402

DEMO = PROJECT_DIR / "data" / "demo"
CHECKS: list[str] = []


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)
    CHECKS.append(msg)
    print(f"  PASS  {msg}")


def _files(case_id: str):
    d = DEMO / case_id
    fir = sorted(d.glob("FIR-*.txt"))
    out = [("files", (p.name, p.read_bytes(), "text/csv")) for p in (d / "cdr.csv", d / "upi.csv", d / "ipdr.csv")]
    out += [("files", (p.name, p.read_bytes(), "text/plain")) for p in fir]
    return out


def test_end_to_end():
    assert settings.SANDHAN_GRAPH_BACKEND == "memory", "this test uses the in-memory graph store"
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    set_graph_store(MemoryGraphStore(None))

    # ---- historical DB + seed ------------------------------------------------
    from app.services.historical_loader import load_historical
    sys.path.insert(0, str(BACKEND / "scripts"))
    import seed_db

    summary = load_historical(settings.historical_dir, log=lambda m: None)
    check(summary["cases"] == 220 and summary["records"] == 8756, "historical DB loaded: 220 cases / 8756 records")
    check(summary["rejected_records"] == 0, "no historical record rejected by validation")
    check(summary["confirmed_case_links"] > 0, f"historical cases linked among themselves "
                                               f"({summary['confirmed_case_links']} confirmed links)")
    seed_db.main()

    from app.main import app

    with TestClient(app) as client:
        r = client.get("/api/v1/health").json()
        check(r["postgres"]["ok"] and r["graph"]["ok"], "health endpoint checks both databases")
        check(r["historical_db"]["cases"] == 220, "health reports historical DB size")

        tok = client.post("/api/v1/auth/login", data={"username": "investigator1", "password": "invest123"}).json()
        H = {"Authorization": f"Bearer {tok['access_token']}"}
        admin = client.post("/api/v1/auth/login", data={"username": "admin", "password": "admin123"}).json()
        AH = {"Authorization": f"Bearer {admin['access_token']}"}
        check(len(tok["assigned_case_ids"]) == 3, "investigator login with 3 assigned demo cases")

        # ---- ingest case 1 while listening on the WebSocket -------------------
        with client.websocket_connect("/ws/v1/graphstream?case_id=CASE-2026-0001") as ws:
            res = client.post("/api/v1/upload/ingest", data={"case_id": "CASE-2026-0001"},
                              files=_files("CASE-2026-0001"), headers=H)
            check(res.status_code == 200, "upload accepted")
            job = res.json()["job_id"]
            stages = []
            while True:
                msg = ws.receive_json()
                stages.append(msg["stage"])
                if msg["stage"] in ("ingestion_complete", "ingestion_failed"):
                    break
        check(stages[-1] == "ingestion_complete", f"WebSocket streamed progress to completion ({len(stages)} events)")
        check("links_found" in stages, "WebSocket reported link discovery")
        j = client.get(f"/api/v1/upload/jobs/{job}", headers=H).json()
        check(j["status"] == "complete", "job status endpoint reports complete")

        links1 = client.get("/api/v1/links/historical", params={"case_id": "CASE-2026-0001"}, headers=H).json()
        by = {l["other_case_id"]: l for l in links1["links"]}
        check(by.get("CASE0113", {}).get("status") == "confirmed",
              "CASE-2026-0001 -> historical CASE0113 CONFIRMED (shared UPI rahulk.scam@icb)")

        # ---- ingest cases 2 and 3 --------------------------------------------
        for cid in ("CASE-2026-0002", "CASE-2026-0003"):
            res = client.post("/api/v1/upload/ingest", data={"case_id": cid}, files=_files(cid), headers=H)
            j = client.get(f"/api/v1/upload/jobs/{res.json()['job_id']}", headers=H).json()
            check(j["status"] == "complete", f"{cid} ingested")

        links2 = {l["other_case_id"]: l for l in client.get(
            "/api/v1/links/historical", params={"case_id": "CASE-2026-0002"}, headers=H).json()["links"]}
        check(links2.get("CASE0047", {}).get("status") == "confirmed",
              "CASE-2026-0002 -> historical CASE0047 CONFIRMED (shared IMEI 356938035643809)")
        ev = {s.get("identifier") for s in links2["CASE0047"]["evidence"]}
        check("IMEI:356938035643809" in ev and "UPI:freshmart19@icb" in ev, "CASE0047 link evidence lists IMEI + UPI")
        check(links2.get("CASE-2026-0001", {}).get("status") == "confirmed",
              "CASE-2026-0002 -> live CASE-2026-0001 confirmed (scamdesk01@okhdfc)")

        links3 = {l["other_case_id"]: l for l in client.get(
            "/api/v1/links/historical", params={"case_id": "CASE-2026-0003"}, headers=H).json()["links"]}
        check(links3.get("CASE0082", {}).get("status") == "probable",
              "CASE-2026-0003 -> historical CASE0082 PROBABLE (alias handle vikram.t39 + shared counterparty)")
        check("CASE0028" not in links3 and "CASE0068" not in links3,
              "a lone look-alike UPI handle does NOT create a lead")
        links1 = {l["other_case_id"]: l for l in client.get(
            "/api/v1/links/historical", params={"case_id": "CASE-2026-0001"}, headers=H).json()["links"]}
        check("CASE-2026-0002" in links1 and "CASE-2026-0003" in links1,
              "CASE-2026-0001's link list was refreshed when later cases linked to it")

        # ---- the case network ------------------------------------------------
        snap = client.get("/api/v1/graph/integrated", params={"case_id": "CASE-2026-0001"}, headers=H).json()
        case_ids = {c["case_id"] for c in snap["cases"]}
        check({"CASE0113", "CASE-2026-0002", "CASE-2026-0003", "CASE0047"} <= case_ids,
              f"integrated graph spans live + historical cases ({sorted(case_ids)})")
        check("CASE0082" not in case_ids, "probable (unverified) link is NOT pulled into the graph")
        nodes = {n["entity_id"]: n for n in snap["nodes"]}
        check(nodes["PHONE:+919811100011"]["masked"] and nodes["PHONE:+919811100011"]["display_value"].startswith("+91-XX"),
              "victim phone is DPDP-masked")
        check(not nodes["PHONE:+919812345601"]["masked"], "suspect phone is shown")
        check(nodes["IMEI:356938035643809"]["cases"] == ["CASE-2026-0002", "CASE0047"],
              "shared IMEI node appears in both the live and historical case")

        ana = client.post("/api/v1/analytics/ringleaders", json={"case_id": "CASE-2026-0001"}, headers=H).json()
        check(len(ana["betweenness_centrality"]) > 0 and len(ana["pagerank"]) > 0 and len(ana["eigenvector_centrality"]) > 0,
              "betweenness / pagerank / eigenvector computed over the network")
        check(len(ana["louvain_communities"]) >= 2, f"Louvain found {len(ana['louvain_communities'])} communities")
        top = ana["betweenness_centrality"][0]["entity_id"]
        print(f"        top betweenness node: {top}")

        cyc = client.get("/api/v1/analytics/smurfing-cycles", params={"case_id": "CASE-2026-0001"}, headers=H).json()
        found = [{n["entity_id"] for n in c["cycle"]} for c in cyc["cycles"]]
        check({"UPI:scamdesk01@okhdfc", "UPI:mule.acc02@okicici", "UPI:cashout.hub7@okaxis"} in found,
              "laundering cycle scamdesk01 -> mule.acc02 -> cashout.hub7 -> scamdesk01 detected across 2 cases")
        cyc_hi = client.get("/api/v1/analytics/smurfing-cycles",
                            params={"case_id": "CASE-2026-0001", "threshold": 100000}, headers=H).json()
        check(cyc_hi["cycles"] == [], "threshold filters cycles whose bottleneck is below it")

        pred = client.post("/api/v1/analytics/predict-links", json={"case_id": "CASE-2026-0001"}, headers=H).json()
        pl = pred["predicted_links"]
        check(len(pl) >= 1, f"link prediction returned {len(pl)} unverified leads")
        pairs = [{p["source"], p["target"]} for p in pl]
        check({"PHONE:+919812345601", "PHONE:+919812345604"} in pairs,
              "hidden link +919812345601 <-> +919812345604 predicted (shared handler + IP)")

        r = client.get("/api/v1/report/evidence-pdf", params={"case_id": "CASE-2026-0001"}, headers=H)
        check(r.status_code == 409, "export refused while predictions are pending (server-side gate)")

        for p in pl:
            if {p["source"], p["target"]} == {"PHONE:+919812345601", "PHONE:+919812345604"}:
                v = client.post("/api/v1/evidence/verify-node", json={
                    "case_id": "CASE-2026-0001", "source_id": p["source"], "target_id": p["target"], "score": p["score"]},
                    headers=H)
                check(v.status_code == 200, "verify predicted link")
            else:
                d = client.post("/api/v1/evidence/dismiss-prediction", json={
                    "case_id": "CASE-2026-0001", "source_id": p["source"], "target_id": p["target"]}, headers=H)
                assert d.status_code == 200
        pend = client.get("/api/v1/analytics/predicted-links", params={"case_id": "CASE-2026-0001"}, headers=H).json()
        check(pend["predicted_links"] == [], "no pending predictions after verify/dismiss")
        snap = client.get("/api/v1/graph/integrated", params={"case_id": "CASE-2026-0001"}, headers=H).json()
        check(any(e["relation"] == "PREDICTED_LINK_VERIFIED" for e in snap["edges"]),
              "verified prediction joined the integrated graph")
        pred2 = client.post("/api/v1/analytics/predict-links", json={"case_id": "CASE-2026-0001"}, headers=H).json()
        check(all({p["source"], p["target"]} != {"PHONE:+919812345601", "PHONE:+919812345604"}
                  for p in pred2["predicted_links"]), "decided predictions are not re-suggested")
        for p in pred2["predicted_links"]:
            client.post("/api/v1/evidence/dismiss-prediction", json={
                "case_id": "CASE-2026-0001", "source_id": p["source"], "target_id": p["target"]}, headers=H)

        r = client.get("/api/v1/report/evidence-pdf", params={"case_id": "CASE-2026-0001"}, headers=H)
        check(r.status_code == 200 and r.content[:4] == b"%PDF", f"evidence PDF exported ({len(r.content)} bytes)")
        (Path(settings.SANDHAN_STORAGE_ROOT) / "test_evidence.pdf").write_bytes(r.content)

        # ---- HITL on case links ----------------------------------------------
        d = client.post("/api/v1/links/decide", json={"case_id": "CASE-2026-0003", "other_case_id": "CASE0082",
                                                        "decision": "verify"}, headers=H).json()
        check(d["status"] == "verified", "investigator verifies the probable CASE0082 link")
        snap3 = client.get("/api/v1/graph/integrated", params={"case_id": "CASE-2026-0003"}, headers=H).json()
        check("CASE0082" in {c["case_id"] for c in snap3["cases"]}, "verified case link now pulls CASE0082 into the graph")

        # ---- other endpoints -------------------------------------------------
        base = client.get("/api/v1/baseline/search", params={"q": "rahulk.scam"}, headers=H).json()
        tables = {row["table"] for row in base["rows"]}
        check(tables == {"historical_records", "case_records"}, "Act-1 baseline SQL lookup returns flat rows from both tables")
        s = client.get("/api/v1/graph/search", params={"case_id": "CASE-2026-0001", "prefix": "98123"}, headers=H).json()
        check(any(h["entity_id"] == "PHONE:+919812345601" for h in s), "trie prefix search finds phones")
        sub = client.get("/api/v1/graph/subgraph", params={"case_id": "CASE-2026-0001",
                                                           "center_node": "UPI:rahulk.scam@icb", "hops": 1}, headers=H).json()
        check(0 < len(sub["nodes"]) < len(snap["nodes"]), "subgraph drill-down is a subset of the network")
        e = client.post("/api/v1/graph/escalate", json={"case_id": "CASE-2026-0001",
                                                        "entity_id": "PHONE:+919811100011"}, headers=H)
        snap = client.get("/api/v1/graph/integrated", params={"case_id": "CASE-2026-0001"}, headers=H).json()
        n = {x["entity_id"]: x for x in snap["nodes"]}["PHONE:+919811100011"]
        check(e.status_code == 200 and not n["masked"], "escalation lifts masking (persisted)")

        r = client.get("/api/v1/graph/integrated", params={"case_id": "CASE-2026-0001"}, headers=AH)
        check(r.status_code == 403, "admin cannot read case content")
        users = client.get("/api/v1/admin/users", headers=AH).json()
        inv = [u for u in users if u["username"] == "investigator1"][0]
        client.post(f"/api/v1/admin/users/{inv['id']}/assign-case", json={"case_id": "CASE0080"}, headers=AH)
        r = client.get("/api/v1/links/historical", params={"case_id": "CASE0080"}, headers=H)
        check(r.status_code == 200, "newly assigned (historical) case usable without re-login")
        check(any(l["status"] == "confirmed" for l in r.json()["links"]),
              "any historical case can be investigated and shows its own links")
        me = client.get("/api/v1/auth/me", headers=H).json()
        check("CASE0080" in me["assigned_case_ids"], "/auth/me returns live assignments")
        audit = client.get("/api/v1/investigator/audit-log", params={"case_id": "CASE-2026-0001"}, headers=H).json()
        check({"upload", "verify", "reject", "export", "escalate"} <= {a["action"] for a in audit},
              "case audit log records upload/verify/reject/export/escalate")

    print(f"\nALL {len(CHECKS)} CHECKS PASSED")


if __name__ == "__main__":
    test_end_to_end()
