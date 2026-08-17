"""Thin repository layer — the typed CRUD surface every other module builds on.

Every helper takes an explicit `Session` so callers control the transaction
boundary (the API opens one per request; the pipeline opens one per run). Helpers
`flush()` to populate primary keys but never `commit()` — that is the caller's job
(see `connection.session_scope`).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.database.models import (
    Application,
    ApplicationStatus,
    AppSettings,
    CandidateProfile,
    Job,
    JobMatch,
    RankingCache,
    RawJob,
    Run,
    RunStatus,
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _as_application_status(value: ApplicationStatus | str) -> ApplicationStatus:
    """Coerce a string/enum into a validated `ApplicationStatus`."""
    return value if isinstance(value, ApplicationStatus) else ApplicationStatus(value)


def _as_run_status(value: RunStatus | str) -> str:
    """Coerce a string/enum into a validated run-status string."""
    if isinstance(value, RunStatus):
        return value.value
    return RunStatus(value).value


# ------------------------------------------------------------------- app settings


def get_app_settings(session: Session) -> AppSettings | None:
    """Return the single UI-editable settings row, or None if never saved."""
    return session.scalar(select(AppSettings).order_by(AppSettings.id).limit(1))


def upsert_app_settings(session: Session, **fields) -> AppSettings:
    """Create or update the single settings row with the given override fields."""
    row = get_app_settings(session)
    if row is None:
        row = AppSettings()
        session.add(row)
    for key, value in fields.items():
        setattr(row, key, value)
    session.flush()
    return row


# --------------------------------------------------------------- candidate profile


def get_candidate_profile(session: Session) -> CandidateProfile | None:
    """Return the single candidate profile (lowest id), or None if not parsed yet."""
    return session.scalar(select(CandidateProfile).order_by(CandidateProfile.id).limit(1))


def upsert_candidate_profile(
    session: Session,
    *,
    name: str | None = None,
    years_experience: float | None = None,
    skills: Sequence[str] | None = None,
    domain: str | None = None,
    preferred_locations: Sequence[str] | None = None,
    desired_roles: Sequence[str] | None = None,
    resume_text: str | None = None,
    raw_parsed_json: dict | None = None,
) -> CandidateProfile:
    """Insert or update the single candidate profile row (idempotent per the M2 CLI)."""
    profile = get_candidate_profile(session)
    if profile is None:
        profile = CandidateProfile()
        session.add(profile)
    profile.name = name
    profile.years_experience = years_experience
    profile.skills_json = list(skills or [])
    profile.domain = domain
    profile.preferred_locations_json = list(preferred_locations or [])
    profile.desired_roles_json = list(desired_roles or [])
    profile.resume_text = resume_text
    profile.raw_parsed_json = raw_parsed_json
    session.flush()
    return profile


# --------------------------------------------------------------------------- jobs


def upsert_job(
    session: Session,
    *,
    title: str,
    company: str,
    content_hash: str,
    source: str,
    location: str | None = None,
    description: str | None = None,
    skills: Sequence[str] | None = None,
    url: str | None = None,
    run_id: int | None = None,
) -> Job:
    """Insert a job, or update the existing one with the same `content_hash`.

    Never touches `detail_text` / `detail_fetched_at`: the nightly re-scrape rewrites
    the thin card `description`, and enrichment must survive that.
    """
    job = session.scalar(select(Job).where(Job.content_hash == content_hash))
    if job is None:
        job = Job(content_hash=content_hash)
        # Set once, on first sight, so "new today" stays true on later re-scrapes.
        job.first_seen_run_id = run_id
        session.add(job)
    job.title = title
    job.company = company
    job.source = source
    job.location = location
    job.description = description
    job.skills_json = list(skills or [])
    job.url = url
    session.flush()
    return job


def set_job_detail(
    session: Session,
    job_id: int,
    *,
    detail_text: str | None,
) -> Job | None:
    """Store a fetched detail-page description and stamp the attempt.

    The stamp is written even when `detail_text` is None so a posting whose page
    cannot be read (expired, gated) is not re-fetched on every subsequent run.
    """
    job = session.get(Job, job_id)
    if job is None:
        return None
    if detail_text:
        job.detail_text = detail_text
    job.detail_fetched_at = _utcnow()
    session.flush()
    return job


def list_jobs(session: Session) -> list[Job]:
    """Return every stored job (used as the existing set for deduplication)."""
    return list(session.scalars(select(Job).order_by(Job.id)))


def get_jobs_by_ids(session: Session, ids: Sequence[int]) -> list[Job]:
    """Return jobs for the given ids, preserving the id order."""
    if not ids:
        return []
    rows = list(session.scalars(select(Job).where(Job.id.in_(list(ids)))))
    by_id = {job.id: job for job in rows}
    return [by_id[i] for i in ids if i in by_id]


def get_jobs_for_run(session: Session, run_id: int) -> list[Job]:
    """Return the jobs seen in a run.

    `jobs` carries no `run_id` (per the schema), so the link is made through
    `raw_jobs` on the shared `url`: every job whose URL was scraped in this run.
    """
    stmt = (
        select(Job)
        .join(RawJob, RawJob.url == Job.url)
        .where(RawJob.run_id == run_id)
        .order_by(Job.id)
        .distinct()
    )
    return list(session.scalars(stmt))


# ----------------------------------------------------------------------- raw jobs


def add_raw_job(
    session: Session,
    *,
    source: str,
    run_id: int,
    source_job_id: str | None = None,
    url: str | None = None,
    raw_payload: dict | None = None,
) -> RawJob:
    """Insert one raw, untouched scraped payload tagged with its run and source."""
    raw = RawJob(
        source=source,
        run_id=run_id,
        source_job_id=source_job_id,
        url=url,
        raw_payload_json=raw_payload or {},
    )
    session.add(raw)
    session.flush()
    return raw


def get_raw_jobs_for_run(session: Session, run_id: int) -> list[RawJob]:
    """Return the raw jobs scraped in a run, in insertion order."""
    stmt = select(RawJob).where(RawJob.run_id == run_id).order_by(RawJob.id)
    return list(session.scalars(stmt))


# ------------------------------------------------------------------------ matches


def save_match(
    session: Session,
    *,
    job_id: int,
    run_id: int,
    score: int,
    llm_model: str,
    pros: Sequence[str] | None = None,
    cons: Sequence[str] | None = None,
    reason: str | None = None,
) -> JobMatch:
    """Insert (or update) the single `job_matches` row for this (job, run)."""
    match = session.scalar(
        select(JobMatch).where(JobMatch.job_id == job_id, JobMatch.run_id == run_id)
    )
    if match is None:
        match = JobMatch(job_id=job_id, run_id=run_id)
        session.add(match)
    match.score = score
    match.llm_model = llm_model
    match.pros_json = list(pros or [])
    match.cons_json = list(cons or [])
    match.reason = reason
    session.flush()
    return match


def get_latest_run(session: Session) -> Run | None:
    """Return the most recently started run, or None if there are none."""
    return session.scalar(select(Run).order_by(Run.started_at.desc(), Run.id.desc()).limit(1))


def get_run_for_date(session: Session, day: date) -> Run | None:
    """Return the most recent run that started on the given calendar day."""
    stmt = (
        select(Run)
        .where(func.date(Run.started_at) == day)
        .order_by(Run.started_at.desc(), Run.id.desc())
        .limit(1)
    )
    return session.scalar(stmt)


def get_latest_match_for_job(session: Session, job_id: int) -> JobMatch | None:
    """Return the most recent match for a job (across runs), or None."""
    stmt = (
        select(JobMatch)
        .where(JobMatch.job_id == job_id)
        .order_by(JobMatch.run_id.desc(), JobMatch.id.desc())
        .limit(1)
    )
    return session.scalar(stmt)


def get_today_matches(
    session: Session,
    *,
    run_id: int | None = None,
    min_score: int | None = None,
) -> list[JobMatch]:
    """Return matches for a run (latest run if `run_id` is None), highest score first.

    Each match has its `job` eagerly loaded so the API can join without N+1 queries.
    """
    if run_id is None:
        latest = get_latest_run(session)
        if latest is None:
            return []
        run_id = latest.id

    stmt = (
        select(JobMatch)
        .where(JobMatch.run_id == run_id)
        .options(selectinload(JobMatch.job))
        .order_by(JobMatch.score.desc(), JobMatch.id)
    )
    if min_score is not None:
        stmt = stmt.where(JobMatch.score >= min_score)
    return list(session.scalars(stmt))


# ------------------------------------------------------------------- applications


def _sync_applied_at(application: Application) -> None:
    """Stamp `applied_at` the first time a job reaches APPLIED."""
    if application.status == ApplicationStatus.APPLIED and application.applied_at is None:
        application.applied_at = _utcnow()


def create_application(
    session: Session,
    *,
    job_id: int,
    status: ApplicationStatus | str = ApplicationStatus.SAVED,
    notes: str | None = None,
) -> Application:
    """Track a job (one application per job): create it, or update if it exists."""
    application = session.scalar(select(Application).where(Application.job_id == job_id))
    if application is None:
        application = Application(job_id=job_id)
        session.add(application)
    application.status = _as_application_status(status)
    if notes is not None:
        application.notes = notes
    _sync_applied_at(application)
    session.flush()
    return application


def update_application_status(
    session: Session,
    application_id: int,
    *,
    status: ApplicationStatus | str | None = None,
    notes: str | None = None,
) -> Application:
    """Update an application's status and/or notes."""
    application = session.get(Application, application_id)
    if application is None:
        raise ValueError(f"application {application_id} not found")
    if status is not None:
        application.status = _as_application_status(status)
        _sync_applied_at(application)
    if notes is not None:
        application.notes = notes
    session.flush()
    return application


def list_applications(
    session: Session, *, status: ApplicationStatus | str | None = None
) -> list[Application]:
    """List tracked applications, newest-updated first, optionally filtered by status."""
    stmt = select(Application).order_by(Application.updated_at.desc(), Application.id.desc())
    if status is not None:
        stmt = stmt.where(Application.status == _as_application_status(status))
    return list(session.scalars(stmt))


# --------------------------------------------------------------------------- runs


def start_run(session: Session) -> Run:
    """Open a new run row (status RUNNING) and return it."""
    run = Run(status=RunStatus.RUNNING.value)
    session.add(run)
    session.flush()
    return run


def finish_run(
    session: Session,
    run_id: int,
    *,
    status: RunStatus | str,
    source_counts: dict | None = None,
    error_text: str | None = None,
) -> Run:
    """Close a run: stamp `finished_at`, set final status, counts, and any error."""
    run = session.get(Run, run_id)
    if run is None:
        raise ValueError(f"run {run_id} not found")
    run.finished_at = _utcnow()
    run.status = _as_run_status(status)
    if source_counts is not None:
        run.source_counts_json = source_counts
    if error_text is not None:
        run.error_text = error_text
    session.flush()
    return run


def record_run_error(
    session: Session, run_id: int, error_text: str, *, source: str | None = None
) -> Run:
    """Record a problem on a run without marking it finished.

    With `source`, this is an isolated per-source failure: it lands in
    `source_errors_json` and leaves `error_text` alone, so one dead scraper never
    makes an otherwise successful run look failed. Without it, the message is
    appended to `error_text` as before.
    """
    run = session.get(Run, run_id)
    if run is None:
        raise ValueError(f"run {run_id} not found")
    if source:
        errors = dict(run.source_errors_json or {})
        errors[source] = error_text
        run.source_errors_json = errors
    else:
        run.error_text = f"{run.error_text}\n{error_text}" if run.error_text else error_text
    session.flush()
    return run


def list_runs(session: Session, *, limit: int = 50) -> list[Run]:
    """Return recent runs, newest first (for the debug/health view)."""
    stmt = select(Run).order_by(Run.started_at.desc(), Run.id.desc()).limit(limit)
    return list(session.scalars(stmt))


# ------------------------------------------------------------------- ranking cache


def get_cached_ranking(session: Session, content_hash: str) -> RankingCache | None:
    """Return the cached ranking for a content hash, or None on a miss."""
    return session.get(RankingCache, content_hash)


def set_cached_ranking(
    session: Session,
    *,
    content_hash: str,
    score: int,
    llm_model: str,
    pros: Sequence[str] | None = None,
    cons: Sequence[str] | None = None,
    reason: str | None = None,
) -> RankingCache:
    """Insert or update the cached ranking for a content hash."""
    cached = session.get(RankingCache, content_hash)
    if cached is None:
        cached = RankingCache(content_hash=content_hash)
        session.add(cached)
    cached.score = score
    cached.llm_model = llm_model
    cached.pros_json = list(pros or [])
    cached.cons_json = list(cons or [])
    cached.reason = reason
    session.flush()
    return cached
