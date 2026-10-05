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
from app.ranking.prefilter import PrefilterReport, parse_exclude_terms, shortlist
from app.ranking.ranking_service import RankingReport, rank_run
from app.ranking.semantic_filter import (
    FitScorer,
    OllamaDecisionClient,
    SemanticFilterReport,
    semantic_filter,
)

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
    semantic: SemanticFilterReport | None = None
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
            exclude_terms=parse_exclude_terms(settings.exclude_keywords),
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


def _semantic_filter(
    jobs: list[Job],
    *,
    session_scope: SessionScope,
    settings: Settings,
    fit_scorer: FitScorer | None,
) -> tuple[list[int], SemanticFilterReport | None]:
    """Drop clear mismatches with a local decision model. Returns kept job ids.

    Jobs are reloaded so the gate reads the description the enrich stage just
    stored (the shortlist objects are detached and predate it). Disabled -> no-op.
    """
    job_ids = [job.id for job in jobs]
    if not settings.semantic_filter_enabled or not job_ids:
        return job_ids, None

    with session_scope() as session:
        profile = repo.get_candidate_profile(session)
        fresh = repo.get_jobs_by_ids(session, job_ids)
        for job in fresh:
            session.expunge(job)
        if profile is not None:
            session.expunge(profile)
    if profile is None:
        return job_ids, None

    client = None
    if fit_scorer is None:
        client = OllamaDecisionClient(
            settings.semantic_filter_base_url, settings.semantic_filter_model
        )
        fit_scorer = client
    try:
        keep, report = semantic_filter(
            profile, fresh, scorer=fit_scorer, min_fit=settings.semantic_filter_min_fit
        )
    finally:
        if client is not None:
            client.close()
    return [job.id for job in keep], report


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
    fit_scorer: FitScorer | None = None,
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

    def progress(stage: str, detail: str | None = None) -> None:
        """Publish the live stage for the dashboard. Never allowed to break a run."""
        try:
            with session_scope() as session:
                repo.set_run_progress(session, run_id, stage=stage, detail=detail)
        except Exception:  # noqa: BLE001
            logger.debug("could not record run progress", exc_info=True)

    try:
        # Stage 1 — collect (each source isolated; one failure is skipped, not fatal).
        collected: dict[str, int] = {}
        for collector in collectors:
            progress("collect", f"Collecting from {collector.source}")
            saved = safe_collect(collector, run_id)
            collected[collector.source] = collected.get(collector.source, 0) + len(saved)

        # A source that scrapes zero jobs is usually a broken selector, not a quiet
        # market — surface it instead of finishing SUCCESS with an empty digest.
        dead_sources = [name for name, count in collected.items() if count == 0]

        # Stage 2 — normalize + dedup.
        progress("dedupe", f"{sum(collected.values())} postings collected; removing duplicates")
        dedupe = normalize_and_dedupe(
            run_id,
            session_scope=session_scope,
            settings=settings,
            skill_extractor=skill_extractor,
        )

        # Stage 3 — cheap deterministic shortlist, so the LLM budget is spent on
        # plausible roles and the enrich stage only opens pages worth opening.
        progress("shortlist", f"{len(dedupe.job_ids)} unique jobs; shortlisting")
        shortlist_jobs, prefilter_report = _shortlist(
            dedupe.job_ids, session_scope=session_scope, settings=settings
        )

        # Stage 4 — fetch the real posting text for the shortlist. Best-effort: a
        # failure here degrades ranking quality, it never fails the run.
        progress("enrich", f"Reading full postings for {len(shortlist_jobs)} shortlisted jobs")
        enrich_report = _enrich(
            shortlist_jobs,
            session_scope=session_scope,
            settings=settings,
            collectors=collectors,
        )

        # Stage 5 — optional semantic gate: a local decision model drops the clear
        # mismatches the keyword shortlist let through. Fails open (keeps the job).
        if settings.semantic_filter_enabled:
            progress("gate", f"Checking fit of {len(shortlist_jobs)} jobs with a local model")
        rank_ids, semantic_report = _semantic_filter(
            shortlist_jobs,
            session_scope=session_scope,
            settings=settings,
            fit_scorer=fit_scorer,
        )

        # Stage 6 — rank the shortlist (cached; LLM score is the match score). We pass
        # job ids explicitly because jobs aren't linked to a run by URL (sources like
        # Naukri's current UI expose no per-card URL).
        progress("rank", f"Scoring {len(rank_ids)} jobs against your résumé")
        ranking = rank_run(
            run_id,
            job_ids=rank_ids,
            session_scope=session_scope,
            settings=settings,
            llm=llm,
            on_progress=lambda done, total: progress("rank", f"Scored {done} of {total} new jobs"),
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
        if semantic_report is not None:
            counts["semantic_filter"] = semantic_report.as_dict
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

    # Stage 7 — notify (outside the try: a notify error must not flip the run to FAILED).
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
        semantic=semantic_report,
        ranking=ranking,
    )
