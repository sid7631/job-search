"""Runs API routes (M8)."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks

from app.api.deps import PipelineRunnerDep, SessionDep
from app.api.schemas import RunOut, RunTriggerOut
from app.database import repository as repo

router = APIRouter(prefix="/api", tags=["runs"])


@router.get("/runs", response_model=list[RunOut])
def list_runs(session: SessionDep, limit: int = 50) -> list[RunOut]:
    """Recent runs for the debug/health view, newest first."""
    return [RunOut.from_run(r) for r in repo.list_runs(session, limit=limit)]


@router.post("/run-now", response_model=RunTriggerOut, status_code=202)
def run_now(
    background: BackgroundTasks,
    session: SessionDep,
    runner: PipelineRunnerDep,
) -> RunTriggerOut:
    """Manually trigger a pipeline run; returns the run_id immediately."""
    run_id = repo.start_run(session).id
    session.commit()  # persist the run before the background task picks it up
    background.add_task(runner, run_id)
    return RunTriggerOut(run_id=run_id, status="started")
