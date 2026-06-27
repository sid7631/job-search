"""Applications API routes (M8)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.api.deps import SessionDep
from app.api.schemas import ApplicationCreate, ApplicationOut, ApplicationUpdate
from app.database import repository as repo
from app.database.models import ApplicationStatus, Job

router = APIRouter(prefix="/api", tags=["applications"])


@router.post("/applications", response_model=ApplicationOut, status_code=201)
def create_application(body: ApplicationCreate, session: SessionDep) -> ApplicationOut:
    """Create/track an application from a match."""
    if session.get(Job, body.job_id) is None:
        raise HTTPException(status_code=404, detail="job not found")
    application = repo.create_application(
        session, job_id=body.job_id, status=body.status, notes=body.notes
    )
    return ApplicationOut.from_application(application)


@router.get("/applications", response_model=list[ApplicationOut])
def list_applications(
    session: SessionDep, status: ApplicationStatus | None = None
) -> list[ApplicationOut]:
    """List tracked applications, optionally filtered by status."""
    applications = repo.list_applications(session, status=status)
    return [ApplicationOut.from_application(a) for a in applications]


@router.patch("/applications/{application_id}", response_model=ApplicationOut)
def update_application(
    application_id: int, body: ApplicationUpdate, session: SessionDep
) -> ApplicationOut:
    """Update an application's status and/or notes."""
    try:
        application = repo.update_application_status(
            session, application_id, status=body.status, notes=body.notes
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="application not found") from exc
    return ApplicationOut.from_application(application)
