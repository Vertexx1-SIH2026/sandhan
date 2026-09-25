"""
Deletes all LIVE case data (uploads, records, links, predictions, audit) so
the demo can be recorded from a clean slate. Users, case assignments and the
historical database are kept.

    python scripts/reset_demo.py            # all live cases
    python scripts/reset_demo.py CASE-2026-0001
"""
import os
import shutil
import stat
import sys

import _path  # noqa: F401

from sqlalchemy import delete, or_

from app.core.config import settings
from app.db import models
from app.db.graph_store import get_graph_store
from app.db.postgres_client import SessionLocal, init_db


def _force(func, path, _exc):
    # WORM originals are chmod read-only; Windows refuses to delete those
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except OSError:
        pass


def main():
    init_db()
    db = SessionLocal()
    try:
        hist = {c for (c,) in db.query(models.HistoricalCase.case_id)}
        if len(sys.argv) > 1:
            ids = sys.argv[1:]
        else:
            ids = sorted({c for (c,) in db.query(models.Case.id)} - hist)
        if not ids:
            print("No live cases to reset.")
            return
        for model, col in (
            (models.CaseRecord, models.CaseRecord.case_id),
            (models.CaseFile, models.CaseFile.case_id),
            (models.FIRNarrative, models.FIRNarrative.case_id),
            (models.PredictedLink, models.PredictedLink.case_id),
            (models.VerifiedNode, models.VerifiedNode.case_id),
            (models.Escalation, models.Escalation.case_id),
            (models.CaseAuditLog, models.CaseAuditLog.case_id),
        ):
            db.execute(delete(model).where(col.in_(ids)))
        db.execute(delete(models.IdentifierIndex).where(
            models.IdentifierIndex.case_id.in_(ids), models.IdentifierIndex.is_historical.is_(False)))
        db.execute(delete(models.CaseLink).where(or_(models.CaseLink.case_id.in_(ids),
                                                     models.CaseLink.other_case_id.in_(ids))))
        for cid in ids:
            case = db.get(models.Case, cid)
            if case:
                case.merkle_root = None
        db.commit()
        live_graph_ids = [c for c in ids if c not in hist]
        get_graph_store().delete_cases(live_graph_ids)
        for sub in ("original", "working"):
            for cid in live_graph_ids:
                shutil.rmtree(settings.storage_root / sub / cid, onerror=_force)
        print(f"Reset {len(ids)} live case(s): {', '.join(ids)}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
