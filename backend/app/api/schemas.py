"""Pydantic request/response models for the JSON API (M8).

Every endpoint declares one of these so the OpenAPI docs and responses are typed.
The `from_*` constructors flatten the ORM join (job + match / application) into the
flat shapes the React UI consumes.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.database.models import (
    Application,
    ApplicationStatus,
    CandidateProfile,
    Job,
    JobMatch,
    Run,
)


class MatchOut(BaseModel):
    """A ranked match for the matches list (card)."""

    job_id: int
    title: str
    company: str
    location: str | None
    url: str | None
    score: int
    pros: list[str]
    cons: list[str]
    reason: str | None
    llm_model: str | None
    run_id: int
    created_at: datetime

    @classmethod
    def from_match(cls, match: JobMatch) -> MatchOut:
        job = match.job
        return cls(
            job_id=match.job_id,
            title=job.title,
            company=job.company,
            location=job.location,
            url=job.url,
            score=match.score,
            pros=list(match.pros_json or []),
            cons=list(match.cons_json or []),
            reason=match.reason,
            llm_model=match.llm_model,
            run_id=match.run_id,
            created_at=match.created_at,
        )


class MatchDetailOut(BaseModel):
    """Full detail for one job (description + the AI's latest opinion)."""

    job_id: int
    title: str
    company: str
    location: str | None
    url: str | None
    description: str | None
    skills: list[str]
    score: int | None
    pros: list[str]
    cons: list[str]
    reason: str | None
    llm_model: str | None
    run_id: int | None
    created_at: datetime | None

    @classmethod
    def from_job(cls, job: Job, match: JobMatch | None) -> MatchDetailOut:
        return cls(
            job_id=job.id,
            title=job.title,
            company=job.company,
            location=job.location,
            url=job.url,
            description=job.description,
            skills=list(job.skills_json or []),
            score=match.score if match else None,
            pros=list(match.pros_json or []) if match else [],
            cons=list(match.cons_json or []) if match else [],
            reason=match.reason if match else None,
            llm_model=match.llm_model if match else None,
            run_id=match.run_id if match else None,
            created_at=match.created_at if match else None,
        )


class JobSummary(BaseModel):
    """The job fields the applications board needs to render a card."""

    title: str
    company: str
    location: str | None
    url: str | None


class ApplicationOut(BaseModel):
    """A tracked application (my action) with its job summary."""

    id: int
    job_id: int
    status: ApplicationStatus
    applied_at: datetime | None
    notes: str | None
    created_at: datetime
    updated_at: datetime
    job: JobSummary | None

    @classmethod
    def from_application(cls, application: Application) -> ApplicationOut:
        job = application.job
        return cls(
            id=application.id,
            job_id=application.job_id,
            status=application.status,
            applied_at=application.applied_at,
            notes=application.notes,
            created_at=application.created_at,
            updated_at=application.updated_at,
            job=(
                JobSummary(title=job.title, company=job.company, location=job.location, url=job.url)
                if job
                else None
            ),
        )


class ApplicationCreate(BaseModel):
    """Body for tracking a match as an application."""

    job_id: int
    status: ApplicationStatus = ApplicationStatus.SAVED
    notes: str | None = None


class ApplicationUpdate(BaseModel):
    """Body for updating an application's status / notes."""

    status: ApplicationStatus | None = None
    notes: str | None = None


class RunOut(BaseModel):
    """A pipeline run for the debug/health view."""

    id: int
    started_at: datetime
    finished_at: datetime | None
    status: str
    source_counts: dict
    error_text: str | None

    @classmethod
    def from_run(cls, run: Run) -> RunOut:
        return cls(
            id=run.id,
            started_at=run.started_at,
            finished_at=run.finished_at,
            status=run.status,
            source_counts=run.source_counts_json or {},
            error_text=run.error_text,
        )


class RunTriggerOut(BaseModel):
    """Response for a manually-triggered run."""

    run_id: int
    status: str


class SettingsOut(BaseModel):
    """Current effective search/account settings (passwords masked as a boolean)."""

    naukri_email: str
    naukri_password_set: bool
    naukri_keywords: str
    naukri_location: str
    naukri_experience: str
    linkedin_email: str
    linkedin_password_set: bool
    linkedin_keywords: str
    linkedin_location: str
    telegram_min_score: int
    telegram_top_n: int


class SettingsUpdate(BaseModel):
    """Settings-page edits. Only provided fields change; blank password = unchanged."""

    naukri_email: str | None = None
    naukri_password: str | None = None
    naukri_keywords: str | None = None
    naukri_location: str | None = None
    naukri_experience: str | None = None
    linkedin_email: str | None = None
    linkedin_password: str | None = None
    linkedin_keywords: str | None = None
    linkedin_location: str | None = None
    telegram_min_score: int | None = None
    telegram_top_n: int | None = None


class ProfileOut(BaseModel):
    """The parsed candidate profile shown on the Profile page."""

    id: int
    name: str | None
    years_experience: float | None
    domain: str | None
    skills: list[str]
    preferred_locations: list[str]
    desired_roles: list[str]
    updated_at: datetime

    @classmethod
    def from_profile(cls, profile: CandidateProfile) -> ProfileOut:
        return cls(
            id=profile.id,
            name=profile.name,
            years_experience=profile.years_experience,
            domain=profile.domain,
            skills=list(profile.skills_json or []),
            preferred_locations=list(profile.preferred_locations_json or []),
            desired_roles=list(profile.desired_roles_json or []),
            updated_at=profile.updated_at,
        )
