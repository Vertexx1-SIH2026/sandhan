"""
Smoke test against a RUNNING backend (real Postgres + real Neo4j). Walks the
whole demo flow through the HTTP API and prints PASS/FAIL per step.

    # terminal 1
    uvicorn app.main:app --port 8000
    # terminal 2
    python scripts/smoke_test.py                 # ingests the 3 demo cases
    python scripts/smoke_test.py --skip-ingest   # re-check without re-uploading

Afterwards run `python scripts/reset_demo.py` to get a clean slate for recording.
"""
import argparse
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
DEMO = ROOT / "data" / "demo"
results = []


def step(ok, msg, detail=""):
    results.append(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {msg}" + (f"  -- {detail}" if detail and not ok else ""))
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--skip-ingest", action="store_true")
    ap.add_argument("--fir", choices=("pdf", "txt"), default="pdf", help="FIR file format to upload")
    args = ap.parse_args()
    api = args.api.rstrip("/")
    s = requests.Session()

    try:
        h = s.get(f"{api}/api/v1/health", timeout=10).json()
    except Exception as exc:
        sys.exit(f"Backend not reachable at {api}: {exc}")
    step(h["postgres"]["ok"], "Postgres reachable", h["postgres"]["detail"])
    step(h["graph"]["ok"], f"Graph store reachable ({h['graph']['backend']})", h["graph"]["detail"])
    hist = h.get("historical_db") or {}
    if not step(hist.get("cases", 0) > 0, f"historical DB loaded ({hist.get('cases', 0)} cases)",
                "run python scripts/bootstrap.py"):
        sys.exit(1)

    r = s.post(f"{api}/api/v1/auth/login", data={"username": "investigator1", "password": "invest123"})
    if not step(r.status_code == 200, "login investigator1", r.text):
        sys.exit(1)
    s.headers["Authorization"] = f"Bearer {r.json()['access_token']}"

    cases = ["CASE-2026-0001", "CASE-2026-0002", "CASE-2026-0003"]
    if not args.skip_ingest:
        for cid in cases:
            d = DEMO / cid
            fir = sorted(d.glob(f"FIR-*.{args.fir}")) or sorted(d.glob("FIR-*.txt"))
            paths = [d / "cdr.csv", d / "upi.csv", d / "ipdr.csv"] + fir[:1]
            files = [("files", (p.name, p.read_bytes())) for p in paths]
            r = s.post(f"{api}/api/v1/upload/ingest", data={"case_id": cid}, files=files)
            if not step(r.status_code == 200, f"upload {cid} ({len(paths)} files)", r.text):
                continue
            job_id = r.json()["job_id"]
            for _ in range(180):
                job = s.get(f"{api}/api/v1/upload/jobs/{job_id}").json()
                if job.get("status") in ("complete", "failed"):
                    break
                time.sleep(1)
            step(job.get("status") == "complete", f"ingest {cid}", job.get("error", job.get("status")))

    def links(cid):
        return {l["other_case_id"]: l["status"] for l in
                s.get(f"{api}/api/v1/links/historical", params={"case_id": cid}).json()["links"]}

    l1, l2, l3 = links(cases[0]), links(cases[1]), links(cases[2])
    step(l1.get("CASE0113") == "confirmed", "CASE-2026-0001 linked to historical CASE0113", str(l1))
    step(l2.get("CASE0047") == "confirmed", "CASE-2026-0002 linked to historical CASE0047", str(l2))
    step(l3.get("CASE0082") in ("probable", "verified"), "CASE-2026-0003 has probable lead CASE0082", str(l3))

    snap = s.get(f"{api}/api/v1/graph/integrated", params={"case_id": cases[0]}).json()
    ids = {c["case_id"] for c in snap["cases"]}
    step({"CASE0113", "CASE-2026-0003"} <= ids, f"integrated network spans {len(ids)} cases", str(sorted(ids)))

    ana = s.post(f"{api}/api/v1/analytics/ringleaders", json={"case_id": cases[0]})
    step(ana.status_code == 200 and ana.json()["pagerank"], "centrality + Louvain", ana.text[:200])
    cyc = s.get(f"{api}/api/v1/analytics/smurfing-cycles", params={"case_id": cases[0]}).json()
    step(len(cyc.get("cycles", [])) >= 1, f"laundering cycle detected ({len(cyc.get('cycles', []))})")

    pred = s.post(f"{api}/api/v1/analytics/predict-links", json={"case_id": cases[0]}).json()["predicted_links"]
    step(len(pred) >= 1, f"link prediction ({len(pred)} leads)")
    blocked = s.get(f"{api}/api/v1/report/evidence-pdf", params={"case_id": cases[0]})
    step(blocked.status_code == 409 or not pred, "export blocked while predictions pending")
    for i, p in enumerate(pred):
        body = {"case_id": cases[0], "source_id": p["source"], "target_id": p["target"], "score": p["score"]}
        url = "/api/v1/evidence/verify-node" if i == 0 else "/api/v1/evidence/dismiss-prediction"
        s.post(f"{api}{url}", json=body)
    r = s.get(f"{api}/api/v1/report/evidence-pdf", params={"case_id": cases[0]})
    ok = step(r.status_code == 200 and r.content[:4] == b"%PDF", "evidence PDF exported", r.text[:200])
    if ok:
        out = ROOT / "backend" / "storage" / "smoke_test_evidence.pdf"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(r.content)
        print(f"       saved {out}")

    mo = s.post(f"{api}/api/v1/nlp/mo-match", json={
        "case_id": cases[0],
        "fir_text": "Caller claiming to be from the bank said my KYC expired and asked me to install a "
                    "screen sharing app, then money was sent to a UPI ID."})
    if mo.status_code == 503:
        print("[SKIP] M.O. matching (sentence-transformers not installed)")
    else:
        step(mo.status_code == 200 and len(mo.json()["matches"]) > 0, "SBERT M.O. match against historical FIRs",
             mo.text[:200])

    base = s.get(f"{api}/api/v1/baseline/search", params={"q": "rahulk.scam"}).json()
    step(base["count"] > 0, f"baseline SQL lookup ({base['count']} flat rows)")

    failed = results.count(False)
    print(f"\n{len(results) - failed}/{len(results)} checks passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
