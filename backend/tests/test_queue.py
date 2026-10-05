"""Tests for the triage queue, triage actions, run progress and the Today routes."""

from __future__ import annotations

import pytest
from app.api.app import create_app
from app.api.deps import get_session
from app.database import repository as repo
from app.database.models import Application, ApplicationStatus
from app.ranking import queue as tq
from app.ranking.feedback import load_feedback, render_feedback
from app.ranking.prefilter import is_excluded, parse_exclude_terms, shortlist
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

JOBS = [
    # (title, company, score)
    ("Java Full Stack Developer - Pan India", "Infosys Limited", 85),
    ("Java Full Stack Developer MK", "Infosys", 70),
    ("Java Full Stack Developer (React)", "Infosys", 65),
    ("Data Engineer", "Infosys", 60),
    ("Senior Backend Engineer", "Razorpay", 90),
    ("SAP Fiori Developer", "Randstad", 40),
]


def _seed(session) -> dict[str, int]:
    run_id = repo.start_run(session).id
    ids: dict[str, int] = {}
    for i, (title, company, score) in enumerate(JOBS):
        job = repo.upsert_job(
            session,
            title=title,
            company=company,
            source="naukri",
            content_hash=f"h{i}",
            url=f"https://x/{i}",
            run_id=run_id,
        )
        repo.save_match(session, job_id=job.id, run_id=run_id, score=score, llm_model="m")
        ids[title] = job.id
    repo.finish_run(session, run_id, status="SUCCESS")
    session.flush()
    return ids


# ------------------------------------------------------------------- queue


def test_queue_collapses_same_company_duplicates(session):
    ids = _seed(session)
    q = tq.build_queue(session)

    leads = [item.lead.job.title for item in q.items]
    assert leads == [
        "Senior Backend Engineer",
        "Java Full Stack Developer - Pan India",
        "Data Engineer",
        "SAP Fiori Developer",
    ]
    infosys = q.items[1]
    assert sorted(infosys.job_ids) == sorted(
        [
            ids["Java Full Stack Developer - Pan India"],
            ids["Java Full Stack Developer MK"],
            ids["Java Full Stack Developer (React)"],
        ]
    )
    assert q.total_matches == 6


def test_queue_hides_triaged_and_excluded(session):
    ids = _seed(session)
    repo.create_application(session, job_id=ids["Senior Backend Engineer"])

    q = tq.build_queue(session, exclude_terms=parse_exclude_terms("sap"))

    titles = [item.lead.job.title for item in q.items]
    assert "Senior Backend Engineer" not in titles
    assert "SAP Fiori Developer" not in titles
    assert (q.triaged, q.excluded) == (1, 1)


def test_queue_ignores_a_run_still_in_progress(session):
    _seed(session)
    repo.start_run(session)  # newer RUNNING run with no matches yet
    assert len(tq.build_queue(session).items) == 4


# ------------------------------------------------------------------ triage


def test_apply_marks_duplicates_and_feedback_skips_them(session):
    ids = _seed(session)
    lead = ids["Java Full Stack Developer - Pan India"]
    dupes = [ids["Java Full Stack Developer MK"], ids["Java Full Stack Developer (React)"]]

    tq.triage(session, job_id=lead, action="apply", similar_ids=dupes)

    apps = {a.job_id: a for a in session.query(Application)}
    assert apps[lead].status == ApplicationStatus.APPLIED
    assert apps[lead].applied_at is not None
    assert all(apps[d].status == ApplicationStatus.DROPPED for d in dupes)
    assert all(apps[d].dismiss_reason == "duplicate" for d in dupes)

    feedback = load_feedback(session)
    assert len(feedback.liked) == 1
    assert feedback.disliked == []


def test_dismiss_reason_reaches_the_ranker(session):
    ids = _seed(session)
    tq.triage(session, job_id=ids["Data Engineer"], action="dismiss", reason="wrong_stack")

    block = render_feedback(load_feedback(session))
    assert "Data Engineer at Infosys (reason: wrong tech stack)" in block


def test_dismiss_rejects_unknown_reason(session):
    ids = _seed(session)
    with pytest.raises(ValueError):
        tq.triage(session, job_id=ids["Data Engineer"], action="dismiss", reason="vibes")


def test_undo_returns_jobs_to_queue(session):
    ids = _seed(session)
    job = ids["Data Engineer"]
    tq.triage(session, job_id=job, action="dismiss", reason="other")
    assert tq.undo_triage(session, [job]) == 1
    assert job in {jid for item in tq.build_queue(session).items for jid in item.job_ids}


def test_reason_cleared_when_status_moves_off_dropped(session):
    ids = _seed(session)
    app = tq.triage(session, job_id=ids["Data Engineer"], action="dismiss", reason="location")[0]
    repo.update_application_status(session, app.id, status="SAVED")
    assert app.dismiss_reason is None


# ----------------------------------------------------------------- exclude


def test_exclude_is_whole_word():
    terms = parse_exclude_terms("Java, sap fiori")
    assert is_excluded("Senior Java Developer", terms)
    assert is_excluded("SAP Fiori Full Stack", terms)
    assert not is_excluded("JavaScript Engineer", terms)
    assert not is_excluded("SAP Basis Admin", terms)


def test_shortlist_applies_exclude_terms(session):
    _seed(session)
    profile = repo.upsert_candidate_profile(
        session,
        name="J",
        years_experience=6,
        skills=["python"],
        domain="backend",
        preferred_locations=[],
        desired_roles=["Backend Engineer"],
        resume_text="",
        raw_parsed_json={},
    )
    keep, report = shortlist(
        profile, repo.list_jobs(session), max_jobs=0, min_score=0, exclude_terms=["java"]
    )
    assert report.excluded == 3
    assert all("Java" not in j.title for j in keep)


# ---------------------------------------------------------------- progress


def test_run_progress_and_attention(session):
    run = repo.start_run(session)
    repo.set_run_progress(session, run.id, stage="collect", detail="naukri")
    repo.set_run_progress(session, run.id, attention="Approve on phone")
    assert run.progress_json["stage"] == "collect"
    assert run.progress_json["attention"] == "Approve on phone"

    repo.set_run_progress(session, run.id, clear_attention=True)
    assert "attention" not in run.progress_json
    assert repo.get_active_run(session).id == run.id


# --------------------------------------------------------------------- API


@pytest.fixture
def client(db_engine):
    factory = sessionmaker(bind=db_engine, expire_on_commit=False)

    def override():
        s = factory()
        try:
            yield s
            s.commit()
        finally:
            s.close()

    app = create_app()
    app.dependency_overrides[get_session] = override
    return TestClient(app), factory


def test_queue_triage_undo_routes(client):
    api, factory = client
    with factory() as s:
        ids = _seed(s)
        s.commit()

    body = api.get("/api/queue").json()
    assert len(body["items"]) == 4
    assert "duplicate" not in body["dismiss_reasons"]
    infosys = body["items"][1]
    assert len(infosys["similar"]) == 2

    resp = api.post(
        "/api/triage",
        json={
            "job_id": infosys["match"]["job_id"],
            "action": "dismiss",
            "reason": "wrong_stack",
            "similar_ids": [m["job_id"] for m in infosys["similar"]],
        },
    )
    assert resp.status_code == 204
    assert len(api.get("/api/queue").json()["items"]) == 3

    bad = api.post("/api/triage", json={"job_id": ids["Data Engineer"], "action": "nope"})
    assert bad.status_code == 422

    api.post("/api/triage/undo", json={"job_ids": [infosys["match"]["job_id"]]})
    assert len(api.get("/api/queue").json()["items"]) == 4


def test_current_run_route(client):
    api, factory = client
    with factory() as s:
        _seed(s)
        active = repo.start_run(s)
        repo.set_run_progress(s, active.id, stage="rank", detail="Scored 3 of 10")
        s.commit()

    body = api.get("/api/runs/current").json()
    assert body["active"]["progress"]["detail"] == "Scored 3 of 10"
    assert body["last"]["status"] == "SUCCESS"


def test_exclude_keywords_round_trip(client):
    api, _ = client
    resp = api.put("/api/settings", json={"exclude_keywords": "java, sap"})
    assert resp.json()["exclude_keywords"] == "java, sap"
