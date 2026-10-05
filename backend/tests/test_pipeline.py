"""Tests for the M6 orchestration pipeline and scheduler wiring (offline)."""

from __future__ import annotations

from app.collectors.base import Collector, RawJobPayload
from app.collectors.naukri import NaukriCollector
from app.config import Settings
from app.database import repository as repo
from app.database.models import Run
from app.scheduler.jobs import JOB_ID, build_scheduler
from app.scheduler.pipeline import NullNotifier, run_pipeline


class StubNaukri(NaukriCollector):
    """Naukri collector with canned payloads (persists via the injected scope)."""

    def __init__(self, payloads, **kwargs):
        super().__init__(**kwargs)
        self._payloads = payloads

    def _fetch_raw_jobs(self):
        return self._payloads


class CrashCollector(Collector):
    source = "boom"

    def collect(self, run_id):
        raise RuntimeError("collector exploded")


class SpyNotifier:
    def __init__(self):
        self.success: list[int] = []
        self.failure: list[tuple[int, str]] = []

    def notify_success(self, run_id):
        self.success.append(run_id)

    def notify_failure(self, run_id, error):
        self.failure.append((run_id, error))


class CountingLLM:
    def __init__(self):
        self.calls = 0

    def __call__(self, prompt: str) -> dict:
        self.calls += 1
        return {"score": 85, "pros": ["fit"], "cons": [], "reason": "good"}


def _settings(**kw) -> Settings:
    base = dict(
        llm_provider="openai",
        llm_model="fake-model",
        llm_api_key="k",
        ranking_max_concurrency=2,
        dedupe_fuzzy_threshold=90.0,
        semantic_filter_enabled=False,
    )
    base.update(kw)
    return Settings(**base)


def _seed_profile(session) -> None:
    repo.upsert_candidate_profile(
        session,
        name="Jane",
        years_experience=6,
        skills=["python"],
        domain="backend",
        preferred_locations=["Remote"],
        desired_roles=["Backend Engineer"],
        resume_text="...",
        raw_parsed_json={},
    )


# Deliberately distinct roles so fuzzy dedup does not merge them.
_ROLES = [
    ("Senior Backend Engineer", "Acme"),
    ("Data Scientist", "Globex"),
    ("DevOps Engineer", "Initech"),
    ("Frontend Engineer", "Umbrella"),
    ("Machine Learning Engineer", "Stark"),
]


def _payloads(n: int) -> list[RawJobPayload]:
    return [
        RawJobPayload(
            source_job_id=str(i),
            url=f"https://x/{i}",
            title=_ROLES[i][0],
            company=_ROLES[i][1],
            location="Remote",
            description="Python role.",
            raw={},
        )
        for i in range(n)
    ]


# ------------------------------------------------------------------- end-to-end


def test_run_pipeline_end_to_end(scope):
    with scope() as s:
        _seed_profile(s)
    settings = _settings()
    llm = CountingLLM()
    notifier = SpyNotifier()
    collector = StubNaukri(_payloads(3), session_scope=scope, settings=settings)

    result = run_pipeline(
        session_scope=scope, settings=settings, collectors=[collector], notifier=notifier, llm=llm
    )

    assert result.status == "SUCCESS"
    assert result.source_counts["collected"] == {"naukri": 3}
    assert result.source_counts["raw_jobs"] == 3
    assert result.source_counts["jobs_inserted"] == 3
    assert result.source_counts["matches_written"] == 3
    assert notifier.success == [result.run_id]
    assert notifier.failure == []

    with scope() as s:
        run = s.get(Run, result.run_id)
        assert run.status == "SUCCESS"
        assert run.finished_at is not None
        assert run.source_counts_json["matches_written"] == 3
        assert len(repo.list_jobs(s)) == 3
        assert len(repo.get_today_matches(s, run_id=result.run_id)) == 3


def test_semantic_filter_gates_ranking_when_enabled(scope):
    with scope() as s:
        _seed_profile(s)
    settings = _settings(semantic_filter_enabled=True, semantic_filter_min_fit=0.5)
    llm = CountingLLM()
    collector = StubNaukri(_payloads(3), session_scope=scope, settings=settings)

    def scorer(state):
        return 0.9 if "Backend" in state["job"] else 0.05

    result = run_pipeline(
        session_scope=scope,
        settings=settings,
        collectors=[collector],
        notifier=SpyNotifier(),
        llm=llm,
        fit_scorer=scorer,
    )

    assert result.status == "SUCCESS"
    assert llm.calls == 1
    assert result.source_counts["matches_written"] == 1
    gate = result.source_counts["semantic_filter"]
    assert (gate["considered"], gate["kept"], gate["dropped"]) == (3, 1, 2)


def test_semantic_filter_off_by_default(scope):
    with scope() as s:
        _seed_profile(s)
    # Explicit: `Settings()` also reads a developer's local `.env`.
    settings = _settings(semantic_filter_enabled=False)
    collector = StubNaukri(_payloads(2), session_scope=scope, settings=settings)

    def scorer(state):
        raise AssertionError("gate must not run when disabled")

    result = run_pipeline(
        session_scope=scope,
        settings=settings,
        collectors=[collector],
        notifier=SpyNotifier(),
        llm=CountingLLM(),
        fit_scorer=scorer,
    )

    assert result.source_counts["matches_written"] == 2
    assert "semantic_filter" not in result.source_counts


def test_failing_collector_is_isolated_not_fatal(scope):
    with scope() as s:
        _seed_profile(s)
    settings = _settings()
    notifier = SpyNotifier()
    good = StubNaukri(_payloads(2), session_scope=scope, settings=settings)

    result = run_pipeline(
        session_scope=scope,
        settings=settings,
        collectors=[CrashCollector(), good],
        notifier=notifier,
        llm=CountingLLM(),
    )

    assert result.status == "SUCCESS"  # the crash was isolated
    assert result.source_counts["collected"] == {"boom": 0, "naukri": 2}
    assert notifier.success == [result.run_id]
    with scope() as s:
        assert len(repo.list_jobs(s)) == 2


def test_pipeline_failure_marks_failed_and_alerts(scope):
    # No profile seeded → ranking raises → run marked FAILED, failure alert sent.
    settings = _settings()
    notifier = SpyNotifier()
    collector = StubNaukri(_payloads(1), session_scope=scope, settings=settings)

    result = run_pipeline(
        session_scope=scope, settings=settings, collectors=[collector], notifier=notifier
    )

    assert result.status == "FAILED"
    assert result.error
    assert notifier.success == []
    assert notifier.failure and notifier.failure[0][0] == result.run_id

    with scope() as s:
        run = s.get(Run, result.run_id)
        assert run.status == "FAILED"
        assert run.error_text


def test_pipeline_rerun_is_idempotent(scope):
    with scope() as s:
        _seed_profile(s)
    settings = _settings()
    llm = CountingLLM()
    payloads = _payloads(2)

    first = run_pipeline(
        session_scope=scope,
        settings=settings,
        collectors=[StubNaukri(payloads, session_scope=scope, settings=settings)],
        notifier=NullNotifier(),
        llm=llm,
    )
    assert first.source_counts["jobs_inserted"] == 2
    assert llm.calls == 2

    second = run_pipeline(
        session_scope=scope,
        settings=settings,
        collectors=[StubNaukri(payloads, session_scope=scope, settings=settings)],
        notifier=NullNotifier(),
        llm=llm,
    )
    assert second.status == "SUCCESS"
    assert second.source_counts["jobs_inserted"] == 0  # no duplicate jobs
    assert second.source_counts["llm_calls"] == 0  # cache hits → no new LLM calls
    assert llm.calls == 2

    with scope() as s:
        assert len(repo.list_jobs(s)) == 2


# --------------------------------------------------------------------- scheduler


def test_scheduler_registers_job_at_run_hour():
    scheduler = build_scheduler(_settings(run_hour=6, timezone="Asia/Kolkata"))
    jobs = scheduler.get_jobs()
    assert len(jobs) == 1
    assert jobs[0].id == JOB_ID
    assert "hour='6'" in str(jobs[0].trigger)


def test_scheduler_default_run_hour_is_eight():
    scheduler = build_scheduler(_settings())
    assert "hour='8'" in str(scheduler.get_jobs()[0].trigger)


# ----------------------------------------------------- in-process scheduler (M11)


def test_background_scheduler_starts_and_registers_job():
    from app.scheduler.jobs import start_background_scheduler

    scheduler = start_background_scheduler(_settings(run_hour=7))
    try:
        assert scheduler.running
        # A one-shot catch-up job is registered alongside the daily cron job.
        job = scheduler.get_job(JOB_ID)
        assert job is not None
        assert "hour='7'" in str(job.trigger)
    finally:
        scheduler.shutdown(wait=False)


def test_api_lifespan_starts_scheduler_only_when_enabled(monkeypatch):
    import app.scheduler.jobs as jobs
    from app.api.app import create_app
    from fastapi.testclient import TestClient

    calls: list[str] = []

    class _FakeScheduler:
        def shutdown(self, wait: bool = False) -> None:
            calls.append("shutdown")

    monkeypatch.setattr(
        jobs, "start_background_scheduler", lambda s: (calls.append("start"), _FakeScheduler())[1]
    )

    # Disabled (default): the lifespan must not start a scheduler.
    with TestClient(create_app(_settings(enable_scheduler=False))):
        pass
    assert calls == []

    # Enabled: started on boot, shut down on exit.
    with TestClient(create_app(_settings(enable_scheduler=True))):
        pass
    assert calls == ["start", "shutdown"]
