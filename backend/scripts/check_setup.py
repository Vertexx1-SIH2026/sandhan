"""
Checks everything the demo needs and prints the exact fix for anything missing.

    python scripts/check_setup.py
"""
import importlib
import sys

import _path  # noqa: F401

OK, WARN, FAIL = "\033[32mOK  \033[0m", "\033[33mWARN\033[0m", "\033[31mFAIL\033[0m"
problems = 0


def line(status, what, fix=""):
    global problems
    if status == FAIL:
        problems += 1
    print(f"[{status}] {what}" + (f"\n        -> {fix}" if fix else ""))


def main():
    v = sys.version_info
    if (3, 10) <= (v.major, v.minor) <= (3, 12):
        line(OK, f"Python {v.major}.{v.minor}")
    else:
        line(FAIL, f"Python {v.major}.{v.minor}", "use Python 3.11 (spaCy 3.7 / pinned wheels support 3.10-3.12)")

    from app.core.config import settings as _s

    driver = ("psycopg", "psycopg[binary]") if "+psycopg:" in _s.database_url else ("psycopg2", "psycopg2-binary")
    required = {
        "fastapi": "fastapi", "uvicorn": "uvicorn[standard]", "multipart": "python-multipart",
        "sqlalchemy": "sqlalchemy", driver[0]: driver[1], "neo4j": "neo4j", "jwt": "PyJWT",
        "phonenumbers": "phonenumbers", "rapidfuzz": "rapidfuzz", "networkx": "networkx",
        "scipy": "scipy", "numpy": "numpy", "community": "python-louvain", "reportlab": "reportlab",
        "qrcode": "qrcode[pil]", "PIL": "pillow", "pydantic_settings": "pydantic-settings",
    }
    for mod, pkg in required.items():
        try:
            importlib.import_module(mod)
            line(OK, f"import {mod}")
        except Exception as exc:
            line(FAIL, f"import {mod} ({exc.__class__.__name__})", f"pip install -r requirements.txt   (package: {pkg})")

    optional = {
        "fitz": ("pymupdf", "PDF FIR upload (TXT FIRs still work)"),
        "spacy": ("spacy", "person / place NER on FIRs"),
        "sentence_transformers": ("sentence-transformers", "SBERT M.O. matching"),
    }
    for mod, (pkg, feat) in optional.items():
        try:
            importlib.import_module(mod)
            line(OK, f"import {mod}")
        except Exception:
            line(WARN, f"{mod} missing -- {feat} disabled", f"pip install {pkg}")
    try:
        import spacy

        spacy.load("en_core_web_sm")
        line(OK, "spaCy model en_core_web_sm")
    except Exception:
        line(WARN, "spaCy model en_core_web_sm not installed", "python -m spacy download en_core_web_sm")

    from app.core.config import settings, BACKEND_DIR

    if (BACKEND_DIR / ".env").exists():
        line(OK, "backend/.env present")
    else:
        line(WARN, "backend/.env missing -- using defaults", "cp .env.example .env")

    from app.db import postgres_client

    ok, msg = postgres_client.ping()
    line(OK if ok else FAIL, f"Postgres {settings.database_url.split('@')[-1]} ({msg})",
         "" if ok else "start Postgres (or `docker compose up -d`) and check POSTGRES_* in backend/.env")

    from app.db.graph_store import get_graph_store

    try:
        gok, gmsg = get_graph_store().ping()
    except Exception as exc:
        gok, gmsg = False, str(exc).splitlines()[0]
    line(OK if gok else FAIL, f"Graph store [{settings.SANDHAN_GRAPH_BACKEND}] {settings.NEO4J_URI} ({gmsg})",
         "" if gok else "start Neo4j 5 (or `docker compose up -d`); password must match NEO4J_PASSWORD")

    if ok:
        from app.db import models

        postgres_client.init_db()
        db = postgres_client.SessionLocal()
        try:
            n = db.query(models.HistoricalCase).count()
            line(OK if n else WARN, f"historical DB: {n} cases loaded",
                 "" if n else "python scripts/load_historical.py   (or python scripts/bootstrap.py)")
            u = db.query(models.User).count()
            line(OK if u else WARN, f"{u} user account(s)", "" if u else "python scripts/seed_db.py")
        finally:
            db.close()

    print()
    if problems:
        print(f"{problems} blocking problem(s) -- fix the FAIL lines above.")
        sys.exit(1)
    print("Setup looks good. Start the API with: uvicorn app.main:app --reload --port 8000")


if __name__ == "__main__":
    main()
