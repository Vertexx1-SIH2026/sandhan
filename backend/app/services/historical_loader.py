"""
historical_loader.py -- loads the historical reference database.

Input files (any number of cases -- nothing here is specific to the planted
demo cases):
  case index   case_id, suspect_number, suspect_imei, suspect_upi, n_records, planted_overlap
  records      record_id, case_id, record_type, timestamp, source_id, dest_id,
               device_or_ref, value, location
  FIRs (opt.)  case_id, fir_id, mo_category, narrative

Pipeline:
  1. Postgres: historical_sources (file hashes), historical_cases,
     historical_records, historical_firs
  2. Normalise every record through app/services/normalizer.py (the same code
     live uploads use, so IDs match exactly)
  3. Postgres identifier_index (inverted index used by the link engine)
  4. Graph store: one (:Case {historical:true}) per case, entities,
     APPEARS_IN, typed edges -- batched UNWIND writes
  5. Link discovery for every historical case -> case_links + LINKED_VIA
  6. Re-run link discovery for every live case already in the system, so
     existing investigations pick up a reloaded / enlarged history
"""
from __future__ import annotations

import csv
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Callable

from sqlalchemy import delete, or_

from app.core.security import sha256_file
from app.db import models
from app.db.graph_store import get_graph_store
from app.db.postgres_client import SessionLocal, init_db
from app.services import link_engine, normalizer

INDEX_FILE = "sandhan_historical_case_index.csv"
RECORDS_FILE = "sandhan_historical_dummy_data.csv"
FIRS_FILE = "sandhan_historical_fir_narratives.csv"


def _read_csv(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        return [{(k or "").strip().lower(): (v or "").strip() for k, v in row.items()} for row in csv.DictReader(f)]


def _float_or_none(v):
    try:
        return float(v) if v not in (None, "") else None
    except ValueError:
        return None


def load_historical(
    historical_dir: Path,
    index_file: str = INDEX_FILE,
    records_file: str = RECORDS_FILE,
    firs_file: str | None = FIRS_FILE,
    reset: bool = True,
    with_mo: bool = False,
    log: Callable[[str], None] = print,
) -> dict:
    t0 = time.time()
    historical_dir = Path(historical_dir)
    index_path = historical_dir / index_file
    records_path = historical_dir / records_file
    firs_path = historical_dir / firs_file if firs_file else None
    for p in (index_path, records_path):
        if not p.exists():
            raise FileNotFoundError(f"Historical file not found: {p}")

    init_db()
    store = get_graph_store()
    store.ensure_schema()

    index_rows = _read_csv(index_path)
    record_rows = _read_csv(records_path)
    fir_rows = _read_csv(firs_path) if firs_path and firs_path.exists() else []
    log(f"read {len(index_rows)} cases, {len(record_rows)} records, {len(fir_rows)} FIR narratives")

    by_case: dict[str, list[dict]] = defaultdict(list)
    for r in record_rows:
        by_case[r["case_id"]].append(r)
    case_ids = sorted({r["case_id"] for r in index_rows} | set(by_case))
    index_by_case = {r["case_id"]: r for r in index_rows}

    db = SessionLocal()
    try:
        # ---------------------------------------------------------- reset
        if reset:
            old_ids = [c for (c,) in db.query(models.HistoricalCase.case_id)]
            wipe = sorted(set(old_ids) | set(case_ids))
            db.execute(delete(models.HistoricalRecord))
            db.execute(delete(models.HistoricalFIR))
            db.execute(delete(models.HistoricalCase))
            db.execute(delete(models.HistoricalSource))
            db.execute(delete(models.IdentifierIndex).where(models.IdentifierIndex.is_historical.is_(True)))
            db.execute(delete(models.CaseLink).where(or_(
                models.CaseLink.case_id.in_(wipe),
                models.CaseLink.other_case_id.in_(wipe),
            )))
            db.commit()
            store.delete_cases(wipe)
            log(f"reset: cleared {len(wipe)} historical cases from Postgres + graph")

        # ---------------------------------------------------------- sources
        for kind, path, n in (("case_index", index_path, len(index_rows)),
                              ("records", records_path, len(record_rows)),
                              ("firs", firs_path, len(fir_rows))):
            if path and path.exists():
                db.add(models.HistoricalSource(kind=kind, filename=path.name,
                                               sha256_hash=sha256_file(str(path)), row_count=n))
        db.commit()

        # ---------------------------------------------------------- records
        table = models.HistoricalRecord.__table__
        payload = [
            {
                "record_id": r.get("record_id") or f"{r['case_id']}-{i}",
                "case_id": r["case_id"],
                "record_type": (r.get("record_type") or "").upper(),
                "timestamp": r.get("timestamp") or None,
                "source_id": r.get("source_id") or None,
                "dest_id": r.get("dest_id") or None,
                "device_or_ref": r.get("device_or_ref") or None,
                "value": _float_or_none(r.get("value")),
                "location": (r.get("location") or None) if (r.get("location") or "").upper() != "N/A" else None,
            }
            for i, r in enumerate(record_rows)
        ]
        for start in range(0, len(payload), 2000):
            db.execute(table.insert(), payload[start : start + 2000])
        db.commit()

        for f in fir_rows:
            db.add(models.HistoricalFIR(
                fir_id=f.get("fir_id") or f"HFIR-{f['case_id']}",
                case_id=f["case_id"], mo_category=f.get("mo_category"),
                narrative=f.get("narrative") or "",
            ))
        db.commit()

        # ---------------------------------------------------------- per case
        totals = Counter()
        for n, cid in enumerate(case_ids, 1):
            rows = by_case.get(cid, [])
            recs, stats = normalizer.normalize_records(rows, "records")
            totals["records"] += stats["accepted"]
            totals["rejected"] += stats["rejected"]
            idx = index_by_case.get(cid, {})
            explicit = {
                x for x in (
                    normalizer.phone_eid(idx.get("suspect_number")),
                    normalizer.imei_eid(idx.get("suspect_imei")),
                    normalizer.upi_eid(idx.get("suspect_upi")),
                ) if x
            }
            g = normalizer.build_graph_rows(recs, explicit_subjects=explicit or None)

            stamps = sorted(r.timestamp for r in recs if r.timestamp)
            locs = Counter(r.location for r in recs if r.location and r.location.upper() != "N/A")
            db.add(models.HistoricalCase(
                case_id=cid,
                suspect_number=idx.get("suspect_number") or None,
                suspect_imei=idx.get("suspect_imei") or None,
                suspect_upi=idx.get("suspect_upi") or None,
                n_records=int(idx["n_records"]) if (idx.get("n_records") or "").isdigit() else len(rows),
                note=idx.get("planted_overlap") or None,
                first_ts=stamps[0] if stamps else None,
                last_ts=stamps[-1] if stamps else None,
                primary_location=locs.most_common(1)[0][0] if locs else None,
            ))

            store.upsert_case(cid, {
                "historical": True,
                "title": f"Historical case {cid}",
                "first_ts": stamps[0] if stamps else None,
                "last_ts": stamps[-1] if stamps else None,
                "primary_location": locs.most_common(1)[0][0] if locs else None,
            })
            store.upsert_entities(cid, g.entity_rows())
            for rel in g.edges:
                store.upsert_edges(cid, rel, g.edge_rows(rel))
            link_engine.index_identifiers(db, cid, g.identifiers, is_historical=True)
            totals["entities"] += len(g.entities)
            if n % 50 == 0:
                log(f"  loaded {n}/{len(case_ids)} cases")
        db.commit()
        log(f"graph + identifier index built for {len(case_ids)} cases "
            f"({totals['records']} records, {totals['rejected']} rejected)")

        # ---------------------------------------------------------- links
        link_totals = Counter()
        for cid in case_ids:
            results = link_engine.discover_links(db, cid, include_mo=with_mo)
            # at load time only link historical cases among themselves; live
            # cases are re-linked (from their own side) just below
            results = [r for r in results if r.other_is_historical]
            s = link_engine.persist_links(db, cid, results, store, case_is_historical=True)
            link_totals.update(s)

        live_ids = [c for (c,) in db.query(models.IdentifierIndex.case_id)
                    .filter(models.IdentifierIndex.is_historical.is_(False)).distinct()]
        for cid in live_ids:
            results = link_engine.discover_links(db, cid, include_mo=with_mo)
            link_engine.persist_links(db, cid, results, store)
        clusters = _cluster_sizes(db)

        summary = {
            "cases": len(case_ids),
            "records": totals["records"],
            "rejected_records": totals["rejected"],
            "entities_written": totals["entities"],
            # each pair is stored from both sides -> halve
            "confirmed_case_links": link_totals["confirmed"] // 2,
            "probable_case_links": link_totals["probable"] // 2,
            "linked_clusters": clusters,
            "live_cases_relinked": len(live_ids),
            "graph": store.stats(),
            "seconds": round(time.time() - t0, 1),
        }
        log(f"done: {summary}")
        return summary
    finally:
        db.close()


def _cluster_sizes(db) -> dict:
    from app.data_structures.union_find import UnionFind

    uf = UnionFind()
    for a, b in db.query(models.CaseLink.case_id, models.CaseLink.other_case_id).filter(
        models.CaseLink.status.in_(("confirmed", "verified"))
    ):
        uf.union(a, b)
    sizes = sorted((len(g) for g in uf.groups()), reverse=True)
    return {"clusters": len(sizes), "largest": sizes[0] if sizes else 0,
            "cases_in_clusters": sum(sizes)}
