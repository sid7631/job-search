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
from app.config import Settings
from app.database import connection
from app.database import repository as repo
from app.database.models import RunStatus
from app.normalizer.normalizer import DedupeReport, normalize_and_dedupe
from app.ranking.ranking_service import RankingReport, rank_run

logger = logging.getLogger(__name__)

SessionScope = Callable[[], AbstractContextManager[Session]]


class Notifier(Protocol):
    """What the pipeline needs from a notifier (implemented by M7's Telegram one)."""

    def notify_success(self, run_id: int) -> None: ...

    def notify_failure(self, run_id: int, error: str) -> None: ...


class NullNotifier:
    """Default notifier until M7 lands: logs instead of sending."""

    def notify_success(self, run_id: int) -> None:
        logger.info("[notify] run %s succeeded (Telegram notifier arrives in M7)", run_id)

    def notify_failure(self, run_id: int, error: str) -> None:
        logger.warning(
            "[notify] run %s failed: %s (Telegram notifier arrives in M7)", run_id, error
        )


@dataclass
class PipelineResult:
    """Outcome of one pipeline run."""

    run_id: int
    status: str
    source_counts: dict = field(default_factory=dict)
    dedupe: DedupeReport | None = None
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

        # Stage 2 — normalize + dedup.
        dedupe = normalize_and_dedupe(
            run_id,
            session_scope=session_scope,
            settings=settings,
            skill_extractor=skill_extractor,
        )

        # Stage 3 — rank the jobs the normalizer produced (cached; LLM score is the
        # match score). We pass job ids explicitly because jobs aren't linked to a run
        # by URL (sources like Naukri's current UI expose no per-card URL).
        ranking = rank_run(
            run_id,
            job_ids=dedupe.job_ids,
            session_scope=session_scope,
            settings=settings,
            llm=llm,
        )

        counts = {
            "collected": collected,
            "raw_jobs": sum(collected.values()),
            "jobs_inserted": dedupe.inserted,
            "duplicates_dropped": dedupe.duplicates_dropped,
            "matches_written": ranking.matches_written,
            "cache_hits": ranking.cache_hits,
            "llm_calls": ranking.llm_calls,
        }

        with session_scope() as session:
            repo.finish_run(session, run_id, status=RunStatus.SUCCESS, source_counts=counts)
    except Exception as exc:  # noqa: BLE001 - any stage failure marks the run FAILED
        logger.exception("pipeline run %s failed", run_id)
        error = str(exc)
        with session_scope() as session:
            repo.finish_run(session, run_id, status=RunStatus.FAILED, error_text=error)
        _safe_notify(notifier.notify_failure, run_id, error)
        return PipelineResult(run_id=run_id, status=RunStatus.FAILED.value, error=error)

    # Stage 4 — notify (outside the try: a notify error must not flip the run to FAILED).
    _safe_notify(notifier.notify_success, run_id)
    logger.info("pipeline run %s succeeded: %s", run_id, counts)
    return PipelineResult(
        run_id=run_id,
        status=RunStatus.SUCCESS.value,
        source_counts=counts,
        dedupe=dedupe,
        ranking=ranking,
    )
