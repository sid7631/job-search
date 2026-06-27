"""Engine / session factory built from `DB_URL` (SQLite by default).

The SQLite→Postgres swap is just a `DB_URL` change plus re-running migrations —
see `MIGRATIONS.md`. Nothing here is SQLite-specific except the connect-args shim.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.database.models import Base

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def create_db_engine(db_url: str | None = None, **kwargs) -> Engine:
    """Build an engine from `db_url` (defaults to the configured `DB_URL`)."""
    url = db_url or get_settings().db_url
    connect_args: dict = {}
    if url.startswith("sqlite"):
        # The API and scheduler share one process / multiple threads.
        connect_args["check_same_thread"] = False
    return create_engine(url, connect_args=connect_args, future=True, **kwargs)


def get_engine() -> Engine:
    """Return the lazily-created process-wide engine."""
    global _engine
    if _engine is None:
        _engine = create_db_engine()
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    """Return the lazily-created session factory bound to the process engine."""
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)
    return _session_factory


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional session scope: commits on success, rolls back on error."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def create_all(engine: Engine | None = None) -> None:
    """Create every table from the models (used by tests / quick local bootstrap;
    production schema is owned by Alembic)."""
    Base.metadata.create_all(engine or get_engine())
