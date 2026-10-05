"""Today page routes — the triage queue, triage actions, live run state, schedule."""

from __future__ import annotations

import sys

from fastapi import APIRouter, HTTPException

from app.api.deps import SessionDep
from app.api.schemas import (
    CurrentRunOut,
    MatchOut,
    QueueEntryOut,
    QueueOut,
    RunOut,
    ScheduleIn,
    ScheduleOut,
    TriageIn,
    TriageUndoIn,
)
from app.database import repository as repo
from app.database.models import DISMISS_REASONS
from app.ranking import queue as triage_queue
from app.ranking.prefilter import parse_exclude_terms
from app.runtime_config import effective_settings
from app.scheduler import launchd

router = APIRouter(prefix="/api", tags=["today"])

# "duplicate" is set by the app, never chosen by hand.
_USER_REASONS = {k: v for k, v in DISMISS_REASONS.items() if k != "duplicate"}


@router.get("/queue", response_model=QueueOut)
def get_queue(session: SessionDep) -> QueueOut:
    """Untriaged matches from the latest run, duplicates collapsed, best first."""
    settings = effective_settings(session)
    q = triage_queue.build_queue(
        session, exclude_terms=parse_exclude_terms(settings.exclude_keywords)
    )
    return QueueOut(
        items=[
            QueueEntryOut(
                match=MatchOut.from_match(item.lead),
                similar=[MatchOut.from_match(m) for m in item.similar],
            )
            for item in q.items
        ],
        run_id=q.run_id,
        total_matches=q.total_matches,
        triaged=q.triaged,
        excluded=q.excluded,
        dismiss_reasons=_USER_REASONS,
    )


@router.post("/triage", status_code=204)
def triage(body: TriageIn, session: SessionDep) -> None:
    """Save / apply / dismiss a queue item (and its collapsed duplicates)."""
    try:
        triage_queue.triage(
            session,
            job_id=body.job_id,
            action=body.action,
            reason=body.reason,
            similar_ids=body.similar_ids,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/triage/undo", status_code=204)
def undo_triage(body: TriageUndoIn, session: SessionDep) -> None:
    """Put jobs back in the queue by forgetting their triage decision."""
    triage_queue.undo_triage(session, body.job_ids)


@router.get("/runs/current", response_model=CurrentRunOut)
def current_run(session: SessionDep) -> CurrentRunOut:
    """The running run (with live progress) and the most recent finished one."""
    active = repo.get_active_run(session)
    finished = [r for r in repo.list_runs(session, limit=5) if r.status != "RUNNING"]
    return CurrentRunOut(
        active=RunOut.from_run(active) if active else None,
        last=RunOut.from_run(finished[0]) if finished else None,
    )


def _schedule_out(session) -> ScheduleOut:
    settings = effective_settings(session)
    return ScheduleOut(
        supported=sys.platform == "darwin",
        enabled=launchd.is_loaded(),
        run_hour=settings.run_hour,
        timezone=settings.timezone,
    )


@router.get("/schedule", response_model=ScheduleOut)
def get_schedule(session: SessionDep) -> ScheduleOut:
    """Whether the daily run is installed as a login item (macOS LaunchAgent)."""
    return _schedule_out(session)


@router.put("/schedule", response_model=ScheduleOut)
def set_schedule(body: ScheduleIn, session: SessionDep) -> ScheduleOut:
    """Turn the daily run on or off without touching a terminal."""
    if sys.platform != "darwin":
        raise HTTPException(status_code=400, detail="Scheduling from the UI needs macOS.")
    try:
        launchd.enable() if body.enabled else launchd.disable()
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return _schedule_out(session)
