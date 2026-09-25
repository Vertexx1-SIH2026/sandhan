"""
Central configuration. Every value is read from the environment (or
backend/.env) so the same code runs unchanged whether Postgres/Neo4j are on
localhost, in docker-compose, or on a hosted instance.
"""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]      # .../sandhan/backend
PROJECT_DIR = BACKEND_DIR.parent                        # .../sandhan


class Settings(BaseSettings):
    # Always read backend/.env, no matter which directory uvicorn/scripts are
    # started from (a relative ".env" silently broke this before).
    model_config = SettingsConfigDict(env_file=str(BACKEND_DIR / ".env"), extra="ignore")

    # --- App / auth ---
    SANDHAN_SECRET_KEY: str = "dev-only-secret-change-me"
    SANDHAN_ACCESS_TOKEN_EXPIRE_MINUTES: int = 480
    SANDHAN_CORS_ORIGINS: str = "http://localhost:3000"

    # --- Postgres ---
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "sandhan"
    POSTGRES_USER: str = "sandhan"
    POSTGRES_PASSWORD: str = "sandhan"
    # Optional full SQLAlchemy URL; overrides the POSTGRES_* values above.
    SANDHAN_DATABASE_URL: str = ""

    # --- Graph store ---
    # "neo4j" (default, what the blueprint specifies) or "memory" (an in-process
    # NetworkX-backed store persisted to storage/graph_memory.pkl -- used by the
    # automated tests, and as an emergency fallback if Neo4j can't be installed).
    SANDHAN_GRAPH_BACKEND: str = "neo4j"
    NEO4J_URI: str = "bolt://localhost:7687"
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str = "sandhan123"

    # --- Storage (local filesystem stand-in for MinIO) ---
    SANDHAN_STORAGE_ROOT: str = str(BACKEND_DIR / "storage")

    # --- Historical database source files ---
    SANDHAN_HISTORICAL_DIR: str = str(PROJECT_DIR / "data" / "historical")

    # --- Linking / NLP tuning ---
    # How many LINKED_VIA hops out from the case under investigation the
    # integrated graph pulls in (1 = directly linked cases only).
    SANDHAN_CASE_HOPS: int = 2
    # An identifier shared by more than this many cases is treated as a hub
    # (common merchant, shared NAT IP ...) and can never auto-confirm a link.
    SANDHAN_HUB_CASE_LIMIT: int = 5
    SANDHAN_PROBABLE_LINK_MIN_SCORE: float = 0.30
    # SBERT cosine threshold for M.O. matches. NOT empirically calibrated yet
    # (blueprint Sec. 9) -- tune against your own labelled FIR pairs.
    SANDHAN_MO_THRESHOLD: float = 0.60
    SANDHAN_SBERT_MODEL: str = "all-MiniLM-L6-v2"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.SANDHAN_CORS_ORIGINS.split(",") if o.strip()]

    @property
    def database_url(self) -> str:
        if self.SANDHAN_DATABASE_URL:
            return self.SANDHAN_DATABASE_URL
        return (
            f"postgresql+psycopg2://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    # kept for backwards compatibility with older imports
    @property
    def postgres_url(self) -> str:
        return self.database_url

    @property
    def storage_root(self) -> Path:
        p = Path(self.SANDHAN_STORAGE_ROOT).resolve()
        for sub in ("original", "working", "evidence"):
            (p / sub).mkdir(parents=True, exist_ok=True)
        return p

    @property
    def historical_dir(self) -> Path:
        return Path(self.SANDHAN_HISTORICAL_DIR).resolve()


settings = Settings()
