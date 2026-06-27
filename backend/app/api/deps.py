"""FastAPI dependencies (M8).

`get_session` yields a request-scoped DB session (commit on success, rollback on
error). `get_pipeline_runner` returns the callable `POST /api/run-now` schedules in
the background. Both are overridable in tests via `app.dependency_overrides`.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.database import connection


def get_session() -> Iterator[Session]:
    """Yield a request-scoped session; commit on success, roll back on error."""
    session = connection.get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_pipeline_runner() -> Callable[[int], None]:
    """Return the background runner used by `POST /api/run-now`."""
    from app.scheduler.pipeline import run_pipeline

    def run(run_id: int) -> None:
        run_pipeline(run_id=run_id)

    return run


# Annotated dependency aliases (avoid `Depends()` in argument defaults).
SessionDep = Annotated[Session, Depends(get_session)]
PipelineRunnerDep = Annotated[Callable[[int], None], Depends(get_pipeline_runner)]
