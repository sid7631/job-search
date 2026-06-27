"""Shared pytest fixtures."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from app.database.models import Base
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture
def db_engine() -> Iterator[Engine]:
    """A single in-memory SQLite engine (StaticPool keeps the DB across sessions)."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def session(db_engine: Engine) -> Iterator[Session]:
    """A session on the shared in-memory engine."""
    factory = sessionmaker(bind=db_engine, expire_on_commit=False)
    with factory() as s:
        yield s


@pytest.fixture
def scope(db_engine: Engine):
    """A `session_scope`-style context manager (commits on exit) for collectors."""
    factory = sessionmaker(bind=db_engine, expire_on_commit=False)

    @contextmanager
    def _scope() -> Iterator[Session]:
        s = factory()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    return _scope
