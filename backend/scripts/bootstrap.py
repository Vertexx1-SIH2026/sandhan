"""
One-shot setup after the databases are running:

  1. create tables              4. load the historical DB into Postgres + graph
  2. seed users + demo cases       and link the historical cases
  3. generate historical FIR    5. render demo FIR PDFs/TXTs
     narratives (if missing)

    python scripts/bootstrap.py
    python scripts/bootstrap.py --reset-live   # also wipe live demo cases (clean slate before recording)
"""
import argparse
import subprocess
import sys

import _path  # noqa: F401
from _path import BACKEND_DIR

from app.core.config import settings
from app.db import postgres_client


def run(script: str):
    print(f"\n=== {script} ===")
    subprocess.run([sys.executable, str(BACKEND_DIR / "scripts" / script)], check=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset-live", action="store_true")
    args = ap.parse_args()

    ok, msg = postgres_client.ping()
    if not ok:
        sys.exit(f"Postgres is not reachable: {msg}\nStart it (docker compose up -d) and check backend/.env")
    postgres_client.init_db()

    if args.reset_live:
        run("reset_demo.py")
    run("seed_db.py")
    if not (settings.historical_dir / "sandhan_historical_fir_narratives.csv").exists():
        run("make_historical_firs.py")
    if not (BACKEND_DIR.parent / "data" / "demo" / "CASE-2026-0001" / "cdr.csv").exists():
        run("make_demo_data.py")
    run("load_historical.py")
    run("generate_sample_firs.py")
    print("\nBootstrap complete. Next: uvicorn app.main:app --reload --port 8000")


if __name__ == "__main__":
    main()
