"""
Loads the historical reference database (Postgres + graph + identifier index)
and links every historical case to the others. Safe to re-run (it resets the
historical portion first; live cases are kept and re-linked).

    python scripts/load_historical.py                      # uses data/historical/
    python scripts/load_historical.py --dir path/to/folder --records my_records.csv --index my_index.csv
    python scripts/load_historical.py --with-mo            # also use SBERT M.O. similarity between historical cases

Works for any number of cases in the same CSV format (see
app/services/historical_loader.py for the schema).
"""
import argparse

import _path  # noqa: F401

from app.core.config import settings
from app.services.historical_loader import load_historical, INDEX_FILE, RECORDS_FILE, FIRS_FILE


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=str(settings.historical_dir))
    ap.add_argument("--index", default=INDEX_FILE)
    ap.add_argument("--records", default=RECORDS_FILE)
    ap.add_argument("--firs", default=FIRS_FILE)
    ap.add_argument("--no-reset", action="store_true", help="append instead of replacing the historical data")
    ap.add_argument("--with-mo", action="store_true", help="include SBERT M.O. similarity (needs sentence-transformers)")
    args = ap.parse_args()
    load_historical(args.dir, args.index, args.records, args.firs, reset=not args.no_reset, with_mo=args.with_mo)


if __name__ == "__main__":
    main()
