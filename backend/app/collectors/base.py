"""Collector interface shared by all job sources (M3).

A `Collector` turns a run into a list of `raw_jobs` rows. Failures are isolated:
`safe_collect` guarantees one source crashing never takes down the whole run, and
`SessionError` (dead session / login failure) is handled by the collector itself —
it records a run error and returns empty rather than throwing.
"""

from __future__ import annotations

import logging
import random
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.orm import Session

from app.database import repository as repo
from app.database.models import RawJob

logger = logging.getLogger(__name__)

SessionScope = Callable[[], AbstractContextManager[Session]]


class CollectorError(RuntimeError):
    """Base class for collector failures."""


class SessionError(CollectorError):
    """The session is dead or login failed — not retryable, not fatal to the run."""


@dataclass
class RawJobPayload:
    """One scraped job before it is persisted to `raw_jobs`."""

    source_job_id: str | None = None
    url: str | None = None
    title: str | None = None
    company: str | None = None
    location: str | None = None
    description: str | None = None
    raw: dict = field(default_factory=dict)


class Collector(ABC):
    """Per-source collector. Implementations write `raw_jobs` for a run."""

    #: Stable source key stored on every row (e.g. "naukri").
    source: str

    @abstractmethod
    def collect(self, run_id: int) -> list[RawJob]:
        """Scrape the source and persist results, returning the saved rows.

        Must not raise on a dead session / login failure: record a run error and
        return an empty list instead.
        """


def random_delay(
    min_seconds: float,
    max_seconds: float,
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Sleep a random duration in [min_seconds, max_seconds] to look human."""
    low, high = sorted((max(0.0, min_seconds), max(0.0, max_seconds)))
    sleep(random.uniform(low, high))


def retry_with_backoff[T](
    func: Callable[[], T],
    *,
    attempts: int = 3,
    base_delay: float = 1.0,
    exceptions: tuple[type[Exception], ...] = (Exception,),
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Call `func`, retrying transient failures with exponential backoff + jitter.

    `SessionError` is never retried — a dead session won't fix itself by waiting.
    """
    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            return func()
        except SessionError:
            raise
        except exceptions as exc:
            last_exc = exc
            if attempt == attempts - 1:
                break
            sleep(base_delay * (2**attempt) * random.uniform(0.8, 1.2))
    assert last_exc is not None
    raise last_exc


def storage_state_path(settings, source: str) -> Path:
    """Where a source's persisted browser session (cookies + localStorage) lives."""
    return Path(settings.storage_state_dir).expanduser() / f"{source}.json"


def load_storage_state(settings, source: str) -> str | None:
    """Return the saved session file for Playwright, or None if there isn't one.

    Reusing a session is what keeps LinkedIn calm: a brand-new cookie-less browser
    logging in every single night looks like a new device each time, which is
    precisely what triggers their security checkpoint.
    """
    path = storage_state_path(settings, source)
    if path.is_file() and path.stat().st_size > 0:
        return str(path)
    return None


def save_storage_state(context, settings, source: str) -> None:
    """Persist the browser session so the next run can skip the credential login."""
    path = storage_state_path(settings, source)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        context.storage_state(path=str(path))
        logger.info("%s: saved browser session to %s", source, path)
    except Exception:
        # A session we failed to save just means a fresh login next run.
        logger.exception("%s: could not save browser session", source)


def clear_storage_state(settings, source: str) -> None:
    """Delete a saved session (used when it is rejected as dead)."""
    path = storage_state_path(settings, source)
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.warning("%s: could not remove stale session %s", source, path)


def payload_to_dict(payload: RawJobPayload) -> dict:
    """Serialize a scraped payload into the `raw_jobs.raw_payload_json` shape.

    Source-agnostic so every collector writes the same contract (normalizer/dedup
    need no per-source persistence changes).
    """
    return {
        "source_job_id": payload.source_job_id,
        "url": payload.url,
        "title": payload.title,
        "company": payload.company,
        "location": payload.location,
        "description": payload.description,
        "raw": payload.raw,
    }


def persist_raw_jobs(
    session_scope: SessionScope,
    *,
    source: str,
    run_id: int,
    payloads: list[RawJobPayload],
) -> list[RawJob]:
    """Write scraped payloads to `raw_jobs`, tagged with their source and run."""
    saved: list[RawJob] = []
    with session_scope() as session:
        for payload in payloads:
            saved.append(
                repo.add_raw_job(
                    session,
                    source=source,
                    run_id=run_id,
                    source_job_id=payload.source_job_id,
                    url=payload.url,
                    raw_payload=payload_to_dict(payload),
                )
            )
    return saved


def record_collector_error(
    session_scope: SessionScope, run_id: int, message: str, *, source: str | None = None
) -> None:
    """Record a collector failure against its source, leaving the run's own status alone."""
    with session_scope() as session:
        repo.record_run_error(session, run_id, message, source=source)


def safe_collect(collector: Collector, run_id: int) -> list[RawJob]:
    """Run a collector with full isolation: any crash is logged and swallowed.

    This is the per-source safety net the orchestrator (M6) uses so one bad
    collector cannot abort the run.
    """
    source = getattr(collector, "source", "?")
    try:
        return collector.collect(run_id)
    except Exception:
        logger.exception("collector %r crashed; isolating failure", source)
        return []
