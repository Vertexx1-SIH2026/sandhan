import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.db import postgres_client
from app.db.graph_store import get_graph_store, close_graph_store
from app.api.v1.router import api_router
from app.ws.graphstream import router as ws_router
from app.ws.manager import ws_manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    ws_manager.set_loop(asyncio.get_running_loop())
    try:
        postgres_client.init_db()
    except Exception as exc:
        print(f"[startup] Postgres not reachable ({str(exc).splitlines()[0]}). "
              f"Check POSTGRES_* in backend/.env -- see README section 1.")
    try:
        get_graph_store().ensure_schema()
    except Exception as exc:
        print(f"[startup] Graph store not reachable ({str(exc).splitlines()[0]}). "
              f"Start Neo4j (or docker compose up -d) and restart the backend.")
    yield
    close_graph_store()


app = FastAPI(
    title="Sandhan API",
    description="AI-powered criminal network analysis system -- local prototype",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)
app.include_router(ws_router)


@app.get("/api/v1/health")
def health():
    """Actually checks both databases (the old endpoint always said ok)."""
    from app.db import models
    from app.services import nlp_processor

    pg_ok, pg_msg = postgres_client.ping()
    try:
        graph_ok, graph_msg = get_graph_store().ping()
    except Exception as exc:
        graph_ok, graph_msg = False, str(exc).splitlines()[0]

    historical = None
    if pg_ok:
        db = postgres_client.SessionLocal()
        try:
            historical = {
                "cases": db.query(models.HistoricalCase).count(),
                "records": db.query(models.HistoricalRecord).count(),
                "fir_narratives": db.query(models.HistoricalFIR).count(),
            }
        except Exception:
            historical = None
        finally:
            db.close()

    return {
        "status": "ok" if (pg_ok and graph_ok) else "degraded",
        "service": "sandhan-backend",
        "postgres": {"ok": pg_ok, "detail": pg_msg},
        "graph": {"ok": graph_ok, "backend": settings.SANDHAN_GRAPH_BACKEND, "detail": graph_msg},
        "historical_db": historical,
        "nlp": {"spacy_ner": nlp_processor._spacy_nlp is not None,
                "sbert": nlp_processor._sbert_model is not None,
                "note": "models load lazily on first FIR ingest"},
    }
