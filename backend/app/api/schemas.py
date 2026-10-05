"""Pydantic request/response models for the JSON API (M8).

Every endpoint declares one of these so the OpenAPI docs and responses are typed.
The `from_*` constructors flatten the ORM join (job + match / application) into the
flat shapes the React UI consumes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, field_validator

from app.database.models import (
    Application,
    ApplicationStatus,
    CandidateProfile,
    Job,
    JobMatch,
    Run,
)
from app.llm_client import PROVIDER_KEYS


class MatchOut(BaseModel):
    """A ranked match for the matches list (card)."""

    job_id: int
    title: str
    company: str
    location: str | None
    url: str | None
    #: Which job board this came from ("naukri", "linkedin"), shown as a tag.
    source: str
    score: int
    pros: list[str]
    cons: list[str]
    reason: str | None
    llm_model: str | None
    run_id: int
    created_at: datetime
    #: First seen in this run — lets the UI badge today's genuinely new roles.
    is_new: bool

    @classmethod
    def from_match(cls, match: JobMatch) -> MatchOut:
        job = match.job
        return cls(
            job_id=match.job_id,
            title=job.title,
            company=job.company,
            location=job.location,
            url=job.url,
            source=job.source,
            score=match.score,
            pros=list(match.pros_json or []),
            cons=list(match.cons_json or []),
            reason=match.reason,
            llm_model=match.llm_model,
            run_id=match.run_id,
            created_at=match.created_at,
            is_new=job.first_seen_run_id == match.run_id,
        )


class MatchDetailOut(BaseModel):
    """Full detail for one job (description + the AI's latest opinion)."""

    job_id: int
    title: str
    company: str
    location: str | None
    url: str | None
    source: str
    description: str | None
    #: True when `description` is the real posting rather than the card summary.
    description_enriched: bool
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
            source=job.source,
            description=job.effective_description,
            description_enriched=bool(job.detail_text),
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
    dismiss_reason: str | None = None
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
            dismiss_reason=application.dismiss_reason,
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
    dismiss_reason: str | None = None


class RunOut(BaseModel):
    """A pipeline run for the debug/health view."""

    id: int
    started_at: datetime
    finished_at: datetime | None
    status: str
    source_counts: dict
    #: Fatal error. Present only on a FAILED run.
    error_text: str | None
    #: {source: message} for sources that were skipped. The run can still be a
    #: SUCCESS — the UI shows these as warnings, not failures.
    source_errors: dict[str, str]
    #: Live {stage, detail, attention, updated_at} while RUNNING.
    progress: dict = {}

    @classmethod
    def from_run(cls, run: Run) -> RunOut:
        return cls(
            id=run.id,
            started_at=run.started_at,
            finished_at=run.finished_at,
            status=run.status,
            source_counts=run.source_counts_json or {},
            error_text=run.error_text,
            source_errors=run.source_errors_json or {},
            progress=run.progress_json or {},
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
    llm_provider: str
    llm_base_url: str
    llm_model: str
    llm_api_key_set: bool
    # The base URL / model actually used when the fields above are blank.
    llm_effective_base_url: str
    llm_effective_model: str
    llm_requires_key: bool
    exclude_keywords: str = ""
    #: Search terms the parsed résumé implies, keyed by setting name. The UI shows
    #: these as placeholders so it is obvious which fields are auto-filled.
    derived_from_resume: dict[str, str]
    #: Fields currently coming from the résumé rather than an explicit value.
    auto_fields: list[str]


class LLMProviderOut(BaseModel):
    """One selectable provider, with the defaults the UI shows as placeholders."""

    key: str
    label: str
    default_base_url: str
    default_model: str
    requires_key: bool
    docs_url: str


class LLMTestIn(BaseModel):
    """Unsaved provider values to test.

    Anything omitted or blank falls back to the saved setting, so the UI can test
    exactly what is on screen — including a key typed but not yet saved — without
    the test writing anything to the database.
    """

    llm_provider: str | None = None
    llm_base_url: str | None = None
    llm_model: str | None = None
    llm_api_key: str | None = None


class LLMTestOut(BaseModel):
    """Result of a live round-trip against the configured provider."""

    ok: bool
    provider: str
    model: str
    detail: str | None = None


class SettingsUpdate(BaseModel):
    """Settings-page edits. Only provided fields change; blank password/api_key = unchanged."""

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
    llm_provider: str | None = None
    llm_base_url: str | None = None
    llm_model: str | None = None
    llm_api_key: str | None = None
    exclude_keywords: str | None = None

    @field_validator("llm_provider")
    @classmethod
    def _known_provider(cls, value: str | None) -> str | None:
        """Reject unknown providers here rather than at the next pipeline run."""
        if value is None or not value.strip():
            return value
        key = value.strip().lower()
        if key not in PROVIDER_KEYS:
            raise ValueError(
                f"unknown provider '{value}'; choose one of: {', '.join(PROVIDER_KEYS)}"
            )
        return key


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


class QueueEntryOut(BaseModel):
    """One role in the triage queue, with near-identical postings collapsed in."""

    match: MatchOut
    similar: list[MatchOut]


class QueueOut(BaseModel):
    items: list[QueueEntryOut]
    run_id: int | None
    total_matches: int
    triaged: int
    excluded: int
    #: {reason key: label} for the dismiss buttons.
    dismiss_reasons: dict[str, str]


class TriageIn(BaseModel):
    job_id: int
    action: Literal["save", "apply", "dismiss"]
    reason: str | None = None
    #: Collapsed duplicates that should follow this decision.
    similar_ids: list[int] = []


class TriageUndoIn(BaseModel):
    job_ids: list[int]


class CurrentRunOut(BaseModel):
    """What the Today page needs about runs: the active one, else the last one."""

    active: RunOut | None
    last: RunOut | None


class ScheduleOut(BaseModel):
    supported: bool
    enabled: bool
    run_hour: int
    timezone: str


class ScheduleIn(BaseModel):
    enabled: bool
