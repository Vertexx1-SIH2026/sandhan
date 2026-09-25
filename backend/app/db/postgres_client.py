from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base

from app.core.config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all tables that don't exist yet. Safe to call on every startup.
    (create_all never ALTERs an existing table -- the tables added in this
    version are all new tables, so existing databases upgrade cleanly.)"""
    from app.db import models  # noqa: F401  (ensures models are registered)

    Base.metadata.create_all(bind=engine)


def ping() -> tuple[bool, str]:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True, "ok"
    except Exception as exc:  # pragma: no cover - depends on local setup
        return False, str(exc).splitlines()[0]
