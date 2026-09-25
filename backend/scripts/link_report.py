"""
Link discovery from the command line -- proves the engine works for ANY case,
not just the planted demo ones.

  python scripts/link_report.py CASE0080
        links of an existing case (historical or live), from the identifier index

  python scripts/link_report.py --csv some_case.csv
        dry run: treat a CSV (CDR / UPI / IPDR / historical-format records) as a
        brand-new case and show which historical cases it links to.
        Nothing is saved.

  python scripts/link_report.py --replay CASE0047 --perturb
        take a historical case's own records, strip its case id, reformat every
        identifier (drop '+', add spaces, upper-case UPI IDs...) and run it as a
        new case -- it should still find the same links as the original.

  python scripts/link_report.py --summary
        how many links every historical case has (distribution)
"""
import argparse
import csv
import random
import sys
import uuid
from collections import Counter

import _path  # noqa: F401

from app.db import models
from app.db.postgres_client import SessionLocal, init_db
from app.services import link_engine, normalizer


def print_links(title, results):
    print(f"\n{title}")
    if not results:
        print("  (no links)")
        return
    for r in results:
        d = r if isinstance(r, dict) else r.as_dict()
        tag = "historical" if d["other_is_historical"] else "live"
        print(f"  {d['status']:<10} {d['other_case_id']:<16} {tag:<10} score {d['score']:.2f}")
        for s in d["evidence"][:4]:
            what = s.get("identifier") or s.get("handle") or s.get("fir_id")
            extra = f"({s.get('my_role', '')}/{s.get('other_role', '')}, in {s.get('cases_sharing', '?')} cases)" \
                if s["signal"] == "shared_identifier" else ""
            print(f"      - {s['signal']:<18} {what} {extra}")


def adhoc(db, records, subjects=None):
    """Index a temporary case, discover links, then delete it again."""
    tmp = f"__ADHOC_{uuid.uuid4().hex[:8]}"
    recs, stats = normalizer.normalize_records(records)
    g = normalizer.build_graph_rows(recs, subjects)
    try:
        link_engine.index_identifiers(db, tmp, g.identifiers, is_historical=False)
        results = link_engine.discover_links(db, tmp, include_mo=False)
    finally:
        db.query(models.IdentifierIndex).filter(models.IdentifierIndex.case_id == tmp).delete()
        db.commit()
    return results, stats


def perturb(value: str, rng: random.Random) -> str:
    if not value:
        return value
    if value.startswith("+91") and len(value) == 13:
        v = value[3:]
        return rng.choice([f"0{v}", f"91{v}", f"{v[:5]} {v[5:]}", f"+91-{v}"])
    if value.isdigit() and len(value) == 15:
        return f"{value[:8]}-{value[8:14]}-{value[14]}"
    if "@" in value:
        return value.upper()
    return value


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("case_id", nargs="?")
    ap.add_argument("--csv")
    ap.add_argument("--replay")
    ap.add_argument("--perturb", action="store_true")
    ap.add_argument("--summary", action="store_true")
    args = ap.parse_args()

    init_db()
    db = SessionLocal()
    try:
        if args.summary:
            hist = [c for (c,) in db.query(models.HistoricalCase.case_id)]
            rows = db.query(models.CaseLink.case_id, models.CaseLink.status).filter(
                models.CaseLink.case_id.in_(hist)).all()
            per = Counter(c for c, s in rows if s in ("confirmed", "verified"))
            dist = Counter(per.get(c, 0) for c in hist)
            print(f"{len(hist)} historical cases; confirmed links per case:")
            for k in sorted(dist):
                print(f"  {k} link(s): {dist[k]} case(s)")
            print("probable leads:", sum(1 for _, s in rows if s == "probable"))
            return

        if args.case_id:
            print_links(f"Links for {args.case_id}", link_engine.links_report(db, args.case_id))
            print("network (DSU cluster):", ", ".join(sorted(link_engine.case_cluster(db, args.case_id))))
            return

        if args.csv:
            with open(args.csv, newline="", encoding="utf-8-sig") as f:
                records = list(csv.DictReader(f))
            results, stats = adhoc(db, records)
            print(f"parsed {stats}")
            print_links(f"{args.csv} as a new case would link to:", results)
            return

        if args.replay:
            src = db.query(models.HistoricalRecord).filter(models.HistoricalRecord.case_id == args.replay).all()
            if not src:
                sys.exit(f"No historical records for {args.replay}")
            rng = random.Random(7)
            records = []
            for r in src:
                row = {"record_type": r.record_type, "timestamp": r.timestamp, "source_id": r.source_id,
                       "dest_id": r.dest_id, "device_or_ref": r.device_or_ref, "value": r.value,
                       "location": r.location}
                if args.perturb:
                    for k in ("source_id", "dest_id", "device_or_ref"):
                        row[k] = perturb(row[k], rng)
                records.append(row)
            if args.perturb:
                print("sample perturbed row:", records[0])
            original = {r["other_case_id"]: r["status"] for r in link_engine.links_report(db, args.replay)}
            results, stats = adhoc(db, records)
            results = [r for r in results if r.other_case_id != args.replay]
            print_links(f"{args.replay} replayed as a NEW case{' (perturbed identifiers)' if args.perturb else ''}:",
                        results)
            found = {r.other_case_id for r in results if r.status == "confirmed"}
            want = {c for c, s in original.items() if s in ("confirmed", "verified")}
            print(f"\noriginal confirmed links: {sorted(want)}")
            print(f"re-found:                 {sorted(found & want)}  ({len(found & want)}/{len(want)})")
            return
        ap.print_help()
    finally:
        db.close()


if __name__ == "__main__":
    main()
