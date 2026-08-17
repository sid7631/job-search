"""Pipeline orchestration (M6).

`run_pipeline()` ties the daily run together: create a `runs` row, collect (each
source isolated so one failure is skipped, not fatal), normalize + dedup, rank, then
notify — and mark the run success/failure with per-source counts.

The notify step calls a `Notifier`. The default is M7's `TelegramNotifier`; a logging
`NullNotifier` remains available for tests / Telegram-less setups.

Idempotent: re-running for the same day creates a fresh run but adds no duplicate
jobs (content-hash upserts) and makes no new LLM calls (the ranking cache handles it).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from typing import Protocol

from sqlalchemy.orm import Session

from app.collectors.base import Collector, safe_collect
from app.collectors.enrich import EnrichReport, enrich_jobs
from app.config import Settings
from app.database import connection
from app.database import repository as repo
from app.database.models import Job, RunStatus
from app.normalizer.normalizer import DedupeReport, normalize_and_dedupe
from app.ranking.prefilter import PrefilterReport, shortlist
from app.ranking.ranking_service import RankingReport, rank_run

logger = logging.getLogger(__name__)

SessionScope = Callable[[], AbstractContextManager[Session]]


class Notifier(Protocol):
    """What the pipeline needs from a notifier (implemented by M7's Telegram one)."""

    def notify_success(self, run_id: int) -> None: ...

    def notify_failure(self, run_id: int, error: str) -> None: ...

    #: Optional — a notifier that predates source warnings is simply not called.
    def notify_source_warning(self, run_id: int, sources: list[str]) -> None: ...


class NullNotifier:
    """Fallback notifier when Telegram is unconfigured: logs instead of sending."""

    def notify_success(self, run_id: int) -> None:
        logger.info("[notify] run %s succeeded (Telegram not configured)", run_id)

    def notify_failure(self, run_id: int, error: str) -> None:
        logger.warning("[notify] run %s failed: %s (Telegram not configured)", run_id, error)

    def notify_source_warning(self, run_id: int, sources: list[str]) -> None:
        logger.warning("[notify] run %s: no jobs from %s", run_id, ", ".join(sources))


@dataclass
class PipelineResult:
    """Outcome of one pipeline run."""

    run_id: int
    status: str
    source_counts: dict = field(default_factory=dict)
    dedupe: DedupeReport | None = None
    prefilter: PrefilterReport | None = None
    enrich: EnrichReport | None = None
    ranking: RankingReport | None = None
    error: str | None = None


def _default_collectors(settings: Settings, session_scope: SessionScope) -> list[Collector]:
    """The collectors the daily run uses (each isolated by `safe_collect`)."""
    from app.collectors.linkedin import LinkedInCollector
    from app.collectors.naukri import NaukriCollector

    return [
        NaukriCollector(settings=settings, session_scope=session_scope),
        LinkedInCollector(settings=settings, session_scope=session_scope),
    ]


def _default_notifier(settings: Settings) -> Notifier:
    """The Telegram notifier (M7). Falls back to logging if Telegram is unconfigured."""
    from app.notifications.telegram import TelegramNotifier

    if settings.telegram_bot_token and settings.telegram_chat_id:
        return TelegramNotifier(settings)
    logger.info("Telegram not configured; using NullNotifier (no push will be sent)")
    return NullNotifier()


def _shortlist(
    job_ids: list[int],
    *,
    session_scope: SessionScope,
    settings: Settings,
) -> tuple[list[Job], PrefilterReport]:
    """Cheap deterministic filter over this run's jobs, best-guess first.

    Returns detached jobs (loaded then expunged) so later stages can read them
    outside a session.
    """
    if not job_ids:
        return [], PrefilterReport()
    with session_scope() as session:
        profile = repo.get_candidate_profile(session)
        if profile is None:
            raise RuntimeError("no candidate profile found; run `parse-resume` first.")
        jobs = repo.get_jobs_by_ids(session, job_ids)
        keep, report = shortlist(
            profile,
            jobs,
            max_jobs=settings.prefilter_max_jobs,
            min_score=settings.prefilter_min_score,
        )
        for job in keep:
            session.expunge(job)
    return keep, report


def _enrich(
    jobs: list[Job],
    *,
    session_scope: SessionScope,
    settings: Settings,
    collectors: list[Collector],
) -> EnrichReport:
    """Fetch real descriptions for the shortlist, reusing the collectors as fetchers."""
    fetchers = [c for c in collectors if hasattr(c, "fetch_details")]
    return enrich_jobs(jobs, fetchers=fetchers, session_scope=session_scope, settings=settings)


def _safe_notify(fn: Callable[..., None], *args) -> None:
    """A notifier failure must never undo a successful run."""
    try:
        fn(*args)
    except Exception:
        logger.exception("notifier failed")


def run_pipeline(
    *,
    run_id: int | None = None,
    session_scope: SessionScope | None = None,
    settings: Settings | None = None,
    collectors: list[Collector] | None = None,
    notifier: Notifier | None = None,
    llm: Callable[..., dict] | None = None,
    skill_extractor: Callable[[str], list[str]] | None = None,
) -> PipelineResult:
    """Run the full daily pipeline once, wrapped in run-tracking.

    If `run_id` is given (e.g. by `POST /api/run-now`) the existing run is used;
    otherwise a new `runs` row is created.
    """
    session_scope = session_scope or connection.session_scope
    if settings is None:
        # .env defaults overlaid with the UI-editable Settings-page overrides.
        from app.runtime_config import effective_settings

        with session_scope() as session:
            settings = effective_settings(session)
    if collectors is None:
        collectors = _default_collectors(settings, session_scope)
    notifier = notifier or _default_notifier(settings)

    if run_id is None:
        with session_scope() as session:
            run_id = repo.start_run(session).id

    try:
        # Stage 1 — collect (each source isolated; one failure is skipped, not fatal).
        collected: dict[str, int] = {}
        for collector in collectors:
            saved = safe_collect(collector, run_id)
            collected[collector.source] = collected.get(collector.source, 0) + len(saved)

        # A source that scrapes zero jobs is usually a broken selector, not a quiet
        # market — surface it instead of finishing SUCCESS with an empty digest.
        dead_sources = [name for name, count in collected.items() if count == 0]

        # Stage 2 — normalize + dedup.
        dedupe = normalize_and_dedupe(
            run_id,
            session_scope=session_scope,
            settings=settings,
            skill_extractor=skill_extractor,
        )

        # Stage 3 — cheap deterministic shortlist, so the LLM budget is spent on
        # plausible roles and the enrich stage only opens pages worth opening.
        shortlist_jobs, prefilter_report = _shortlist(
            dedupe.job_ids, session_scope=session_scope, settings=settings
        )

        # Stage 4 — fetch the real posting text for the shortlist. Best-effort: a
        # failure here degrades ranking quality, it never fails the run.
        enrich_report = _enrich(
            shortlist_jobs,
            session_scope=session_scope,
            settings=settings,
            collectors=collectors,
        )

        # Stage 5 — rank the shortlist (cached; LLM score is the match score). We pass
        # job ids explicitly because jobs aren't linked to a run by URL (sources like
        # Naukri's current UI expose no per-card URL).
        ranking = rank_run(
            run_id,
            job_ids=[job.id for job in shortlist_jobs],
            session_scope=session_scope,
            settings=settings,
            llm=llm,
        )

        counts = {
            "collected": collected,
            "raw_jobs": sum(collected.values()),
            "jobs_inserted": dedupe.inserted,
            "duplicates_dropped": dedupe.duplicates_dropped,
            "prefilter": prefilter_report.as_dict,
            "enrich": enrich_report.as_dict,
            "matches_written": ranking.matches_written,
            "cache_hits": ranking.cache_hits,
            "llm_calls": ranking.llm_calls,
        }
        if dead_sources:
            counts["sources_with_no_jobs"] = dead_sources

        with session_scope() as session:
            repo.finish_run(session, run_id, status=RunStatus.SUCCESS, source_counts=counts)
    except Exception as exc:  # noqa: BLE001 - any stage failure marks the run FAILED
        logger.exception("pipeline run %s failed", run_id)
        error = str(exc)
        with session_scope() as session:
            repo.finish_run(session, run_id, status=RunStatus.FAILED, error_text=error)
        _safe_notify(notifier.notify_failure, run_id, error)
        return PipelineResult(run_id=run_id, status=RunStatus.FAILED.value, error=error)

    # Stage 6 — notify (outside the try: a notify error must not flip the run to FAILED).
    warn = getattr(notifier, "notify_source_warning", None)
    if dead_sources and warn is not None:
        _safe_notify(warn, run_id, dead_sources)
    _safe_notify(notifier.notify_success, run_id)
    logger.info("pipeline run %s succeeded: %s", run_id, counts)
    return PipelineResult(
        run_id=run_id,
        status=RunStatus.SUCCESS.value,
        source_counts=counts,
        dedupe=dedupe,
        prefilter=prefilter_report,
        enrich=enrich_report,
        ranking=ranking,
    )
