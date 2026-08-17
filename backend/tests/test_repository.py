"""Repository CRUD tests against an in-memory SQLite database.

The `session` fixture lives in `conftest.py`.
"""

from __future__ import annotations

import pytest
from app.database import repository as repo
from app.database.models import ApplicationStatus, RawJob, RunStatus
from sqlalchemy.orm import Session


def _make_job(session: Session, content_hash: str = "hash-1", **overrides):
    payload = dict(
        title="Senior Backend Engineer",
        company="Acme",
        location="Remote",
        source="naukri",
        url="https://example.com/jobs/1",
        skills=["python", "fastapi"],
        content_hash=content_hash,
    )
    payload.update(overrides)
    return repo.upsert_job(session, **payload)


# --------------------------------------------------------------------------- runs


def test_start_and_finish_run(session: Session):
    run = repo.start_run(session)
    assert run.id is not None
    assert run.status == RunStatus.RUNNING.value
    assert run.finished_at is None

    finished = repo.finish_run(
        session, run.id, status=RunStatus.SUCCESS, source_counts={"naukri": 12}
    )
    assert finished.status == RunStatus.SUCCESS.value
    assert finished.finished_at is not None
    assert finished.source_counts_json == {"naukri": 12}

    assert [r.id for r in repo.list_runs(session)] == [run.id]


def test_finish_unknown_run_raises(session: Session):
    with pytest.raises(ValueError):
        repo.finish_run(session, 999, status=RunStatus.FAILED)


# --------------------------------------------------------------------------- jobs


def test_upsert_job_inserts_then_updates_in_place(session: Session):
    job = _make_job(session)
    assert job.id is not None
    assert job.skills_json == ["python", "fastapi"]

    # Same content_hash → update, not a second row.
    again = _make_job(session, title="Staff Backend Engineer", description="new desc")
    assert again.id == job.id
    assert again.title == "Staff Backend Engineer"
    assert again.description == "new desc"

    # A different content_hash → a genuinely new row.
    other = _make_job(session, content_hash="hash-2", url="https://example.com/jobs/2")
    assert other.id != job.id


def test_get_jobs_for_run_links_through_raw_jobs_url(session: Session):
    run = repo.start_run(session)
    job = _make_job(session)  # url https://example.com/jobs/1
    _make_job(session, content_hash="hash-2", url="https://example.com/jobs/2")

    # Only job #1's URL was scraped in this run.
    session.add(RawJob(source="naukri", url="https://example.com/jobs/1", run_id=run.id))
    session.flush()

    jobs = repo.get_jobs_for_run(session, run.id)
    assert [j.id for j in jobs] == [job.id]


# ------------------------------------------------------------------------ matches


def test_save_match_upserts_per_job_and_run(session: Session):
    run = repo.start_run(session)
    job = _make_job(session)

    match = repo.save_match(
        session,
        job_id=job.id,
        run_id=run.id,
        score=70,
        llm_model="fake-model",
        pros=["good stack"],
        cons=["onsite"],
        reason="solid fit",
    )
    assert match.id is not None
    assert match.score == 70

    # Re-ranking the same (job, run) updates the existing row.
    updated = repo.save_match(
        session, job_id=job.id, run_id=run.id, score=88, llm_model="fake-model"
    )
    assert updated.id == match.id
    assert updated.score == 88


def test_get_today_matches_filters_and_orders(session: Session):
    run = repo.start_run(session)
    job_a = _make_job(session, content_hash="a", url="https://x/a")
    job_b = _make_job(session, content_hash="b", url="https://x/b")
    repo.save_match(session, job_id=job_a.id, run_id=run.id, score=40, llm_model="m")
    repo.save_match(session, job_id=job_b.id, run_id=run.id, score=90, llm_model="m")

    # Defaults to the latest run, ordered by score desc.
    matches = repo.get_today_matches(session)
    assert [m.score for m in matches] == [90, 40]
    assert matches[0].job.id == job_b.id  # eager-loaded join

    # min_score filter.
    high = repo.get_today_matches(session, min_score=50)
    assert [m.score for m in high] == [90]


def test_get_today_matches_empty_when_no_runs(session: Session):
    assert repo.get_today_matches(session) == []


# ------------------------------------------------------------------- applications


def test_create_application_is_one_per_job_and_stamps_applied_at(session: Session):
    job = _make_job(session)

    saved = repo.create_application(session, job_id=job.id)
    assert saved.status == ApplicationStatus.SAVED
    assert saved.applied_at is None

    # Tracking the same job again updates the existing application (no duplicate).
    applied = repo.create_application(session, job_id=job.id, status="APPLIED")
    assert applied.id == saved.id
    assert applied.status == ApplicationStatus.APPLIED
    assert applied.applied_at is not None


def test_update_application_status_and_notes(session: Session):
    job = _make_job(session)
    application = repo.create_application(session, job_id=job.id)

    updated = repo.update_application_status(
        session, application.id, status=ApplicationStatus.INTERVIEWING, notes="call booked"
    )
    assert updated.status == ApplicationStatus.INTERVIEWING
    assert updated.notes == "call booked"


def test_update_unknown_application_raises(session: Session):
    with pytest.raises(ValueError):
        repo.update_application_status(session, 999, status="APPLIED")


def test_list_applications_filters_by_status(session: Session):
    job_a = _make_job(session, content_hash="a", url="https://x/a")
    job_b = _make_job(session, content_hash="b", url="https://x/b")
    repo.create_application(session, job_id=job_a.id, status="APPLIED")
    repo.create_application(session, job_id=job_b.id, status="SAVED")

    assert len(repo.list_applications(session)) == 2
    applied = repo.list_applications(session, status="APPLIED")
    assert [a.job_id for a in applied] == [job_a.id]


# ------------------------------------------------------------------- ranking cache


def test_ranking_cache_miss_then_hit(session: Session):
    assert repo.get_cached_ranking(session, "missing") is None

    cached = repo.set_cached_ranking(
        session,
        content_hash="hash-1",
        score=82,
        llm_model="fake-model",
        pros=["remote"],
        cons=[],
        reason="great match",
    )
    assert cached.content_hash == "hash-1"

    hit = repo.get_cached_ranking(session, "hash-1")
    assert hit is not None
    assert hit.score == 82
    assert hit.pros_json == ["remote"]

    # Upsert by content_hash.
    again = repo.set_cached_ranking(
        session, content_hash="hash-1", score=95, llm_model="fake-model"
    )
    assert again.score == 95
    assert repo.get_cached_ranking(session, "hash-1").score == 95
