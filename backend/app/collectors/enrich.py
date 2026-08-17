"""Detail-page enrichment (M11).

Search-result cards carry almost no text — LinkedIn's synthesized description is
literally "<title> at <company>. Location: <x>." — so ranking a card is asking the
model to judge fit from one sentence. This stage opens the real posting for the
shortlisted jobs and stores its text on `jobs.detail_text`.

It runs *after* the pre-filter and *before* ranking, so only jobs worth an LLM call
cost a page load. Results are permanent: `upsert_job` never overwrites `detail_text`,
and `detail_fetched_at` stops a job being re-fetched every night.

Enrichment is strictly best-effort. Every failure mode — no URL for the source, a
dead session, a removed posting — degrades to the card description rather than
failing the run.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy.orm import Session

from app.config import Settings
from app.database import repository as repo
from app.database.models import Job

logger = logging.getLogger(__name__)

SessionScope = Callable[[], AbstractContextManager[Session]]


class DetailFetcher(Protocol):
    """A source's ability to read full descriptions for a batch of job URLs."""

    source: str

    def fetch_details(self, urls: list[str]) -> dict[str, str]:
        """Return {url: description} for whatever could be read. Never raises."""
        ...


@dataclass
class EnrichReport:
    """What the enrich stage managed to do, surfaced in `runs.source_counts`."""

    eligible: int = 0
    attempted: int = 0
    enriched: int = 0
    skipped_no_url: int = 0

    @property
    def as_dict(self) -> dict:
        return {
            "eligible": self.eligible,
            "attempted": self.attempted,
            "enriched": self.enriched,
            "skipped_no_url": self.skipped_no_url,
        }


def needs_detail(job: Job) -> bool:
    """True if this job has a page we have not read yet."""
    return bool(job.url) and job.detail_fetched_at is None


def enrich_jobs(
    jobs: list[Job],
    *,
    fetchers: list[DetailFetcher],
    session_scope: SessionScope,
    settings: Settings,
) -> EnrichReport:
    """Fetch and store detail-page text for `jobs`, grouped by source.

    Returns a report; the caller re-reads the jobs to see the new text.
    """
    report = EnrichReport()
    if not settings.enrich_enabled:
        logger.info("enrichment disabled (ENRICH_ENABLED=false); ranking on card text")
        return report

    pending = [job for job in jobs if needs_detail(job)]
    report.skipped_no_url = sum(1 for job in jobs if not job.url and job.detail_fetched_at is None)
    report.eligible = len(pending)
    if not pending:
        return report

    limit = settings.enrich_max_jobs
    if limit > 0:
        # `jobs` arrives pre-filter-ordered (best cheap score first), so the cap keeps
        # the most promising postings rather than an arbitrary slice.
        pending = pending[:limit]
    report.attempted = len(pending)

    by_source: dict[str, list[Job]] = {}
    for job in pending:
        by_source.setdefault(job.source, []).append(job)

    fetcher_by_source = {f.source: f for f in fetchers}
    for source, source_jobs in by_source.items():
        fetcher = fetcher_by_source.get(source)
        if fetcher is None:
            logger.info(
                "no detail fetcher for source %r; leaving %d job(s) on card text",
                source,
                len(source_jobs),
            )
            continue
        urls = [job.url for job in source_jobs if job.url]
        try:
            found = fetcher.fetch_details(urls)
        except Exception:
            # A detail fetch is an optimisation; never let it fail the run.
            logger.exception("detail fetch crashed for source %r", source)
            continue

        with session_scope() as session:
            for job in source_jobs:
                text = found.get(job.url or "")
                # Stamp even on a miss, so an unreadable posting is not retried nightly.
                repo.set_job_detail(session, job.id, detail_text=text)
                if text:
                    report.enriched += 1

    logger.info(
        "enrich: %d/%d shortlisted jobs gained a real description",
        report.enriched,
        report.attempted,
    )
    return report
