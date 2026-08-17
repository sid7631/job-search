"""SQLAlchemy 2.x models — the shared schema contract for every module.

Tables (per the M1 spec):
    candidate_profile, raw_jobs, jobs, job_matches, applications, ranking_cache, runs.

Design notes:
- `job_matches` is the AI's opinion, regenerated per run; `applications` is my
  hand-edited action — they are never conflated.
- `ranking_cache` is keyed by `content_hash` so an unchanged job is never re-ranked.
- JSON columns hold native Python lists/dicts (SQLite stores them as TEXT; Postgres
  as JSON). The application status enum is stored as a portable VARCHAR + CHECK
  (`native_enum=False`) so the SQLite→Postgres swap needs no enum-type juggling.
"""

from __future__ import annotations

import enum
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    """Timezone-aware UTC now — used for Python-side column defaults."""
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Declarative base for all models."""


class ApplicationStatus(enum.StrEnum):
    """Lifecycle of a tracked application (my action)."""

    SAVED = "SAVED"
    APPLIED = "APPLIED"
    INTERVIEWING = "INTERVIEWING"
    REJECTED = "REJECTED"
    OFFER = "OFFER"
    DROPPED = "DROPPED"


class RunStatus(enum.StrEnum):
    """Lifecycle of a pipeline run. Stored as a plain string on `runs.status`."""

    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class CandidateProfile(Base):
    """The single candidate profile parsed from my resume (see M2)."""

    __tablename__ = "candidate_profile"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str | None] = mapped_column(String(300))
    years_experience: Mapped[float | None] = mapped_column(Float)
    skills_json: Mapped[list] = mapped_column(JSON, default=list)
    domain: Mapped[str | None] = mapped_column(String(200))
    preferred_locations_json: Mapped[list] = mapped_column(JSON, default=list)
    desired_roles_json: Mapped[list] = mapped_column(JSON, default=list)
    resume_text: Mapped[str | None] = mapped_column(Text)
    raw_parsed_json: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class Run(Base):
    """One pipeline run — wraps collect→normalize→dedup→rank→notify (see M6)."""

    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default=RunStatus.RUNNING.value)
    source_counts_json: Mapped[dict] = mapped_column(JSON, default=dict)
    #: Fatal error that ended the run. Only ever set when status is FAILED.
    error_text: Mapped[str | None] = mapped_column(Text)
    #: Per-source problems ({source: message}) that were isolated and skipped. A run
    #: with these is still a SUCCESS — the other sources produced matches — so they
    #: are kept apart from `error_text` rather than making a good run look broken.
    source_errors_json: Mapped[dict] = mapped_column(JSON, default=dict)

    raw_jobs: Mapped[list[RawJob]] = relationship(back_populates="run")
    matches: Mapped[list[JobMatch]] = relationship(back_populates="run")


class RawJob(Base):
    """Untouched payload as scraped by a collector, tagged with its run."""

    __tablename__ = "raw_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(50), index=True)
    source_job_id: Mapped[str | None] = mapped_column(String(200), index=True)
    url: Mapped[str | None] = mapped_column(Text, index=True)
    raw_payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
    scraped_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("runs.id"), index=True)

    run: Mapped[Run | None] = relationship(back_populates="raw_jobs")


class Job(Base):
    """A normalized, deduplicated job. `content_hash` is the dedup key."""

    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(500))
    company: Mapped[str] = mapped_column(String(300))
    location: Mapped[str | None] = mapped_column(String(300))
    #: The thin summary synthesized from the search-result card. Rewritten every run.
    description: Mapped[str | None] = mapped_column(Text)
    #: The real posting text, fetched from the job's detail page by the enrich stage.
    #: Kept separate from `description` because `upsert_job` overwrites the latter on
    #: every run — enrichment is expensive and must survive re-scraping.
    detail_text: Mapped[str | None] = mapped_column(Text)
    #: When the detail fetch last ran (success or give-up), so it is not retried daily.
    detail_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    skills_json: Mapped[list] = mapped_column(JSON, default=list)
    source: Mapped[str] = mapped_column(String(50), index=True)
    url: Mapped[str | None] = mapped_column(Text, index=True)
    content_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    #: The run that first saw this job — drives "new since last run" in the digest.
    first_seen_run_id: Mapped[int | None] = mapped_column(Integer, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    @property
    def effective_description(self) -> str | None:
        """The best text available for ranking: the real posting, else the card."""
        return self.detail_text or self.description

    matches: Mapped[list[JobMatch]] = relationship(back_populates="job")
    application: Mapped[Application | None] = relationship(back_populates="job")


class JobMatch(Base):
    """The AI's opinion of a job for a given run. Regenerated every run."""

    __tablename__ = "job_matches"
    __table_args__ = (UniqueConstraint("job_id", "run_id", name="uq_job_match_job_run"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), index=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), index=True)
    score: Mapped[int] = mapped_column(Integer)
    pros_json: Mapped[list] = mapped_column(JSON, default=list)
    cons_json: Mapped[list] = mapped_column(JSON, default=list)
    reason: Mapped[str | None] = mapped_column(Text)
    llm_model: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    job: Mapped[Job] = relationship(back_populates="matches")
    run: Mapped[Run] = relationship(back_populates="matches")


class Application(Base):
    """My tracked action on a job. Permanent and hand-edited in the UI."""

    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), unique=True, index=True)
    status: Mapped[ApplicationStatus] = mapped_column(
        Enum(ApplicationStatus, native_enum=False, length=20),
        default=ApplicationStatus.SAVED,
        index=True,
    )
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    job: Mapped[Job] = relationship(back_populates="application")


class RankingCache(Base):
    """Ranking result keyed by `content_hash` so unchanged jobs are never re-ranked."""

    __tablename__ = "ranking_cache"

    content_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    score: Mapped[int] = mapped_column(Integer)
    pros_json: Mapped[list] = mapped_column(JSON, default=list)
    cons_json: Mapped[list] = mapped_column(JSON, default=list)
    reason: Mapped[str | None] = mapped_column(Text)
    llm_model: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class AppSettings(Base):
    """Single-row, UI-editable overrides for `.env` search/account settings.

    A null/empty field falls back to the corresponding `.env` value at run time.
    """

    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    naukri_email: Mapped[str | None] = mapped_column(String(200))
    naukri_password: Mapped[str | None] = mapped_column(String(200))
    naukri_keywords: Mapped[str | None] = mapped_column(String(500))
    naukri_location: Mapped[str | None] = mapped_column(String(200))
    naukri_experience: Mapped[str | None] = mapped_column(String(50))
    linkedin_email: Mapped[str | None] = mapped_column(String(200))
    linkedin_password: Mapped[str | None] = mapped_column(String(200))
    linkedin_keywords: Mapped[str | None] = mapped_column(String(500))
    linkedin_location: Mapped[str | None] = mapped_column(String(200))
    telegram_min_score: Mapped[int | None] = mapped_column(Integer)
    telegram_top_n: Mapped[int | None] = mapped_column(Integer)
    llm_provider: Mapped[str | None] = mapped_column(String(50))
    llm_base_url: Mapped[str | None] = mapped_column(String(500))
    llm_api_key: Mapped[str | None] = mapped_column(String(500))
    llm_model: Mapped[str | None] = mapped_column(String(200))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )
