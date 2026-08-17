"""Tests for the M5 cached LLM ranking engine (offline — the LLM is injected)."""

from __future__ import annotations

import threading

import pytest
from app.config import Settings
from app.database import repository as repo
from app.database.models import Job
from app.ranking import cache
from app.ranking.prompt import (
    RankingResult,
    build_ranking_prompt,
    profile_fingerprint,
    ranking_cache_key,
)
from app.ranking.ranking_service import RankingError, rank_run
from sqlalchemy.orm import Session


class CountingLLM:
    """A fake LLM call that counts invocations (thread-safe)."""

    def __init__(self, result: dict | None = None):
        self.calls = 0
        self._lock = threading.Lock()
        self._result = result or {
            "score": 80,
            "pros": ["good stack"],
            "cons": ["onsite"],
            "reason": "fit",
        }

    def __call__(self, prompt: str) -> dict:
        with self._lock:
            self.calls += 1
        return dict(self._result)


def _settings(**kw) -> Settings:
    base = dict(
        llm_provider="openai",
        llm_model="fake-model",
        llm_api_key="k",
        ranking_max_concurrency=2,
    )
    base.update(kw)
    return Settings(**base)


def _seed_profile(session: Session) -> None:
    repo.upsert_candidate_profile(
        session,
        name="Jane",
        years_experience=6,
        skills=["python", "fastapi"],
        domain="backend",
        preferred_locations=["Remote"],
        desired_roles=["Backend Engineer"],
        resume_text="...",
        raw_parsed_json={},
    )


def _seed_jobs(session: Session, run_id: int, n: int = 2) -> None:
    """Insert n jobs and matching raw_jobs so get_jobs_for_run links them by url."""
    for i in range(n):
        url = f"https://x/{i}"
        repo.upsert_job(
            session,
            title=f"Backend Engineer {i}",
            company="Acme",
            location="Remote",
            description="Python and FastAPI role.",
            skills=["python", "fastapi"],
            source="naukri",
            url=url,
            content_hash=f"hash-{i}",
        )
        repo.add_raw_job(session, source="naukri", run_id=run_id, url=url, raw_payload={})


# ----------------------------------------------------------------- prompt + schema


def test_prompt_includes_profile_and_job_and_requires_json():
    job = Job(
        title="Senior Backend Engineer",
        company="Acme",
        location="Remote",
        description="Build APIs in Python.",
        skills_json=["python"],
        source="naukri",
        url="u",
        content_hash="h",
    )

    class _P:
        name = "Jane"
        years_experience = 6
        domain = "backend"
        skills_json = ["python", "fastapi"]
        desired_roles_json = ["Backend Engineer"]
        preferred_locations_json = ["Remote"]
        resume_text = "Jane Doe. Led the payments rewrite at Acme, 40M req/day."

    prompt = build_ranking_prompt(_P(), job)
    assert "Senior Backend Engineer" in prompt
    assert "Jane" in prompt
    assert '"score"' in prompt and '"pros"' in prompt and '"reason"' in prompt
    # The ranker sees the full résumé, not just the extracted summary fields.
    assert "payments rewrite" in prompt


def test_ranking_result_rejects_out_of_range_score():
    with pytest.raises(ValueError):
        RankingResult(score=150)
    ok = RankingResult(score=72)
    assert ok.pros == [] and ok.reason == ""


# --------------------------------------------------------------------- cache


def test_cache_round_trip(session: Session):
    assert cache.get_cached(session, "miss") is None
    result = RankingResult(score=88, pros=["remote"], cons=[], reason="great")
    cache.store(session, "hash-1", result, "fake-model")

    hit = cache.get_cached(session, "hash-1")
    assert hit is not None
    assert hit.result.score == 88
    assert hit.result.pros == ["remote"]
    assert hit.llm_model == "fake-model"


# ------------------------------------------------------------------- end-to-end


def test_rank_run_scores_caches_and_writes_matches(scope):
    with scope() as s:
        _seed_profile(s)
        run_id = repo.start_run(s).id
        _seed_jobs(s, run_id, n=3)

    llm = CountingLLM()
    report = rank_run(run_id, session_scope=scope, settings=_settings(), llm=llm)

    assert report.jobs == 3
    assert report.cache_hits == 0
    assert report.llm_calls == 3
    assert llm.calls == 3
    assert report.matches_written == 3

    with scope() as s:
        matches = repo.get_today_matches(s, run_id=run_id)
        assert len(matches) == 3
        # The LLM score IS the match score — no blending.
        assert all(m.score == 80 for m in matches)
        assert all(m.llm_model == "fake-model" for m in matches)
        # Cache was populated for every job, keyed by résumé + model + prompt version.
        profile = repo.get_candidate_profile(s)
        job = repo.get_jobs_for_run(s, run_id)[0]
        key = ranking_cache_key(
            job, profile_fp=profile_fingerprint(profile), model=_settings().llm_model
        )
        assert cache.get_cached(s, key) is not None


def test_rerun_on_same_jobs_makes_zero_new_llm_calls(scope):
    with scope() as s:
        _seed_profile(s)
        run1 = repo.start_run(s).id
        _seed_jobs(s, run1, n=2)

    llm = CountingLLM()
    rank_run(run1, session_scope=scope, settings=_settings(), llm=llm)
    assert llm.calls == 2

    # A second run over the same jobs (same content_hash) — all cache hits.
    with scope() as s:
        run2 = repo.start_run(s).id
        # Same urls → get_jobs_for_run(run2) returns the same jobs.
        for i in range(2):
            repo.add_raw_job(s, source="naukri", run_id=run2, url=f"https://x/{i}", raw_payload={})

    report2 = rank_run(run2, session_scope=scope, settings=_settings(), llm=llm)
    assert llm.calls == 2  # zero new LLM calls
    assert report2.cache_hits == 2
    assert report2.llm_calls == 0

    with scope() as s:
        assert len(repo.get_today_matches(s, run_id=run2)) == 2


def test_no_profile_raises(scope):
    with scope() as s:
        run_id = repo.start_run(s).id
        _seed_jobs(s, run_id, n=1)

    with pytest.raises(RankingError):
        rank_run(run_id, session_scope=scope, settings=_settings(), llm=CountingLLM())


# ----------------------------------------------------------- malformed handling


def test_retry_once_on_malformed_then_succeeds(scope):
    with scope() as s:
        _seed_profile(s)
        run_id = repo.start_run(s).id
        _seed_jobs(s, run_id, n=1)

    class FlakyLLM:
        def __init__(self):
            self.calls = 0

        def __call__(self, prompt: str) -> dict:
            self.calls += 1
            if self.calls == 1:
                return {"score": "not a number"}  # malformed
            return {"score": 75, "pros": [], "cons": [], "reason": "ok"}

    llm = FlakyLLM()
    report = rank_run(run_id, session_scope=scope, settings=_settings(), llm=llm)
    assert llm.calls == 2  # initial + one retry
    assert report.matches_written == 1
    with scope() as s:
        assert repo.get_today_matches(s, run_id=run_id)[0].score == 75


def test_persistent_malformed_raises(scope):
    with scope() as s:
        _seed_profile(s)
        run_id = repo.start_run(s).id
        _seed_jobs(s, run_id, n=1)

    def junk_llm(prompt: str) -> dict:
        return {"score": "garbage"}

    with pytest.raises(RankingError):
        rank_run(run_id, session_scope=scope, settings=_settings(), llm=junk_llm)
