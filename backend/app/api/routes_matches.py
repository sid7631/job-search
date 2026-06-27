"""Matches API routes (M8)."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException

from app.api.deps import SessionDep
from app.api.schemas import MatchDetailOut, MatchOut
from app.database import repository as repo
from app.database.models import Job

router = APIRouter(prefix="/api", tags=["matches"])


@router.get("/matches", response_model=list[MatchOut])
def list_matches(
    session: SessionDep,
    date: date | None = None,
    min_score: int | None = None,
) -> list[MatchOut]:
    """Ranked matches (jobs + latest job_matches), newest run by default."""
    run_id: int | None = None
    if date is not None:
        run = repo.get_run_for_date(session, date)
        if run is None:
            return []
        run_id = run.id
    matches = repo.get_today_matches(session, run_id=run_id, min_score=min_score)
    return [MatchOut.from_match(m) for m in matches]


@router.get("/matches/{job_id}", response_model=MatchDetailOut)
def match_detail(job_id: int, session: SessionDep) -> MatchDetailOut:
    """Full detail for one job: description, skills, and the AI's latest pros/cons/reason."""
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    match = repo.get_latest_match_for_job(session, job_id)
    return MatchDetailOut.from_job(job, match)
