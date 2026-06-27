"""LLM ranking engine (M5).

For each job seen in a run:
1. Look up `ranking_cache` by `content_hash`. On a hit, reuse it — no LLM call.
2. On a miss, call Gemini (JSON mode), validate against `RankingResult` (retry once
   on malformed output), and write the cache.
3. Write one `job_matches` row per job for the run.

Cache misses are ranked with a concurrency-limited thread pool (the Gemini SDK has
no batch endpoint).

**Single scoring source:** the LLM `score` IS the match score. It is never averaged
with a rule-based skill/experience/location formula — that would double-count.
Deterministic signals may only be used as cheap pre-filters *before* ranking.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import AbstractContextManager
from dataclasses import dataclass, field

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import connection
from app.database import repository as repo
from app.database.models import Job
from app.ranking import cache
from app.ranking.prompt import RankingResult, build_ranking_prompt

logger = logging.getLogger(__name__)

SessionScope = Callable[[], AbstractContextManager[Session]]
# A pluggable LLM call: (prompt, *, model, api_key) -> parsed JSON object.
LLMCallable = Callable[..., dict]


class RankingError(RuntimeError):
    """Raised when ranking cannot proceed or the LLM keeps returning junk."""


@dataclass
class _Item:
    """Per-job working state through the three phases."""

    job_id: int
    content_hash: str
    prompt: str | None  # set only for cache misses
    result: RankingResult | None
    llm_model: str | None
    from_cache: bool


@dataclass
class RankingReport:
    """Counts from one ranking pass."""

    jobs: int = 0
    cache_hits: int = 0
    llm_calls: int = 0
    matches_written: int = 0
    job_ids: list[int] = field(default_factory=list)


def rank_run(
    run_id: int,
    *,
    jobs: list[Job] | None = None,
    job_ids: list[int] | None = None,
    session_scope: SessionScope | None = None,
    settings: Settings | None = None,
    llm: LLMCallable | None = None,
) -> RankingReport:
    """Rank a run's jobs, using and filling the content-hash cache.

    The job set is, in order of precedence: an explicit `jobs` list, jobs loaded by
    `job_ids` (what the pipeline passes — the normalizer's output for this run), or
    `get_jobs_for_run(run_id)`.
    """
    session_scope = session_scope or connection.session_scope
    settings = settings or get_settings()
    report = RankingReport()

    # Phase 1 — load profile + jobs, split into cache hits and misses.
    with session_scope() as session:
        profile = repo.get_candidate_profile(session)
        if profile is None:
            raise RankingError("no candidate profile found; run `parse-resume` first.")
        if jobs is not None:
            job_list: list[Job] = jobs
        elif job_ids is not None:
            job_list = repo.get_jobs_by_ids(session, job_ids)
        else:
            job_list = repo.get_jobs_for_run(session, run_id)

        items: list[_Item] = []
        for job in job_list:
            hit = cache.get_cached(session, job.content_hash)
            if hit is not None:
                items.append(_Item(job.id, job.content_hash, None, hit.result, hit.llm_model, True))
            else:
                items.append(
                    _Item(
                        job.id,
                        job.content_hash,
                        build_ranking_prompt(profile, job),
                        None,
                        settings.llm_model,
                        False,
                    )
                )

    report.jobs = len(items)
    report.cache_hits = sum(1 for it in items if it.from_cache)

    # Phase 2 — call the LLM for misses, concurrency-limited (outside any session).
    misses = [it for it in items if not it.from_cache]
    if misses:
        computed = _rank_misses(misses, settings, llm)
        for it in misses:
            it.result = computed[it.job_id]
        report.llm_calls = len(misses)

    # Phase 3 — persist new cache entries and one job_match per job.
    with session_scope() as session:
        for it in items:
            assert it.result is not None
            if not it.from_cache:
                cache.store(session, it.content_hash, it.result, it.llm_model or settings.llm_model)
            repo.save_match(
                session,
                job_id=it.job_id,
                run_id=run_id,
                score=it.result.score,  # the LLM score IS the match score — no blending
                pros=it.result.pros,
                cons=it.result.cons,
                reason=it.result.reason,
                llm_model=it.llm_model or settings.llm_model,
            )
            report.job_ids.append(it.job_id)
    report.matches_written = len(report.job_ids)

    logger.info(
        "rank run %s: jobs=%d cache_hits=%d llm_calls=%d",
        run_id,
        report.jobs,
        report.cache_hits,
        report.llm_calls,
    )
    return report


def _rank_misses(
    misses: list[_Item], settings: Settings, llm: LLMCallable | None
) -> dict[int, RankingResult]:
    """Rank cache-miss jobs with a bounded thread pool; returns job_id -> result."""
    caller = llm or _call_gemini
    workers = max(1, settings.ranking_max_concurrency)

    def work(item: _Item) -> tuple[int, RankingResult]:
        assert item.prompt is not None
        return item.job_id, _rank_one(item.prompt, caller, settings)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return dict(pool.map(work, misses))


def _rank_one(prompt: str, caller: LLMCallable, settings: Settings) -> RankingResult:
    """Call the LLM and validate, retrying once on malformed output."""
    last_exc: ValidationError | None = None
    for _attempt in range(2):  # initial try + one retry
        raw = caller(prompt, model=settings.llm_model, api_key=settings.gemini_api_key)
        try:
            return RankingResult.model_validate(raw)
        except ValidationError as exc:
            last_exc = exc
    raise RankingError(f"LLM returned malformed ranking twice: {last_exc}")


def _is_rate_limit(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(k in text for k in ("429", "resource_exhausted", "quota", "rate limit"))


def _call_gemini(prompt: str, *, model: str, api_key: str) -> dict:
    """Call Gemini in JSON mode and return the parsed object.

    Retries on rate-limit (429) so free-tier per-minute quotas slow a run down
    instead of failing it.
    """
    if not api_key:
        raise RankingError("GEMINI_API_KEY is not set; cannot rank jobs.")

    import google.generativeai as genai

    genai.configure(api_key=api_key)
    gemini = genai.GenerativeModel(model)
    config = {"response_mime_type": "application/json", "temperature": 0}

    last_exc: Exception | None = None
    for attempt in range(6):
        try:
            response = gemini.generate_content(prompt, generation_config=config)
            return json.loads(response.text)
        except (ValueError, AttributeError) as exc:
            raise RankingError(f"Gemini did not return valid JSON: {exc}") from exc
        except Exception as exc:  # noqa: BLE001 - classify rate limits vs. real errors
            if _is_rate_limit(exc) and attempt < 5:
                wait = 8 * (attempt + 1)
                logger.warning("Gemini rate-limited (attempt %d); waiting %ds", attempt + 1, wait)
                time.sleep(wait)
                last_exc = exc
                continue
            raise RankingError(f"Gemini call failed: {exc}") from exc
    raise RankingError(f"Gemini rate limit did not clear: {last_exc}")
