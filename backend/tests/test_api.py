"""Smoke tests for the M8 JSON API — hits every route via TestClient (in-memory DB)."""

from __future__ import annotations

import pytest
from app.api.app import create_app
from app.api.deps import get_pipeline_runner, get_session
from app.database import repository as repo
from app.database.models import Run
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def api(db_engine: Engine):
    """A TestClient with the DB session and pipeline runner overridden for tests."""
    factory = sessionmaker(bind=db_engine, expire_on_commit=False)

    def override_session():
        session = factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    triggered: list[int] = []
    app = create_app()
    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_pipeline_runner] = lambda: triggered.append
    return TestClient(app), factory, triggered


def _seed(factory) -> dict:
    """Seed a run with two ranked jobs; returns useful ids."""
    with factory() as s:
        run_id = repo.start_run(s).id
        ids = {}
        for i, score in enumerate([60, 95]):
            job = repo.upsert_job(
                s,
                title=f"Role {i}",
                company=f"Co {i}",
                location="Remote",
                description=f"Description {i}",
                skills=["python"],
                source="naukri",
                url=f"https://x/{i}",
                content_hash=f"h{i}",
            )
            repo.save_match(
                s,
                job_id=job.id,
                run_id=run_id,
                score=score,
                llm_model="fake-model",
                pros=["good"],
                cons=["bad"],
                reason="because",
            )
            ids[f"job{i}"] = job.id
        repo.finish_run(s, run_id, status="SUCCESS", source_counts={"naukri": 2})
        s.commit()
        ids["run_id"] = run_id
    return ids


# ------------------------------------------------------------------------ matches


def test_list_matches_and_min_score(api):
    client, factory, _ = api
    _seed(factory)

    resp = client.get("/api/matches")
    assert resp.status_code == 200
    body = resp.json()
    assert [m["score"] for m in body] == [95, 60]  # ordered by score desc
    assert body[0]["title"] == "Role 1"
    assert body[0]["company"] == "Co 1"
    assert body[0]["url"] == "https://x/1"
    assert body[0]["pros"] == ["good"]

    filtered = client.get("/api/matches", params={"min_score": 90}).json()
    assert [m["score"] for m in filtered] == [95]


def test_match_detail(api):
    client, factory, _ = api
    ids = _seed(factory)

    resp = client.get(f"/api/matches/{ids['job1']}")
    assert resp.status_code == 200
    detail = resp.json()
    assert detail["job_id"] == ids["job1"]
    assert detail["description"] == "Description 1"
    assert detail["skills"] == ["python"]
    assert detail["reason"] == "because"
    assert detail["score"] == 95


def test_match_detail_404(api):
    client, _, _ = api
    assert client.get("/api/matches/9999").status_code == 404


# ------------------------------------------------------------------- applications


def test_application_crud(api):
    client, factory, _ = api
    ids = _seed(factory)

    created = client.post("/api/applications", json={"job_id": ids["job0"], "status": "APPLIED"})
    assert created.status_code == 201
    app_id = created.json()["id"]
    assert created.json()["status"] == "APPLIED"
    assert created.json()["job"]["title"] == "Role 0"

    listed = client.get("/api/applications").json()
    assert len(listed) == 1

    filtered = client.get("/api/applications", params={"status": "SAVED"}).json()
    assert filtered == []

    patched = client.patch(
        f"/api/applications/{app_id}", json={"status": "INTERVIEWING", "notes": "call booked"}
    )
    assert patched.status_code == 200
    assert patched.json()["status"] == "INTERVIEWING"
    assert patched.json()["notes"] == "call booked"


def test_application_404s(api):
    client, _, _ = api
    assert client.post("/api/applications", json={"job_id": 9999}).status_code == 404
    assert client.patch("/api/applications/9999", json={"status": "APPLIED"}).status_code == 404


# --------------------------------------------------------------------- runs


def test_list_runs(api):
    client, factory, _ = api
    _seed(factory)
    resp = client.get("/api/runs")
    assert resp.status_code == 200
    runs = resp.json()
    assert len(runs) == 1
    assert runs[0]["status"] == "SUCCESS"
    assert runs[0]["source_counts"] == {"naukri": 2}


def test_run_now_triggers_background(api):
    client, factory, triggered = api
    resp = client.post("/api/run-now")
    assert resp.status_code == 202
    run_id = resp.json()["run_id"]
    assert resp.json()["status"] == "started"
    # The background runner was scheduled with the new run id.
    assert triggered == [run_id]
    # And the run row exists.
    with factory() as s:
        assert s.get(Run, run_id) is not None


# --------------------------------------------------------------------- profile


def test_profile_get_and_upload_validation(api):
    client, factory, _ = api
    assert client.get("/api/profile").json() is None  # none yet

    with factory() as s:
        repo.upsert_candidate_profile(
            s,
            name="Jane",
            years_experience=5,
            skills=["python"],
            domain="backend",
            preferred_locations=["Remote"],
            desired_roles=["Engineer"],
            resume_text="x",
            raw_parsed_json={},
        )
        s.commit()

    body = client.get("/api/profile").json()
    assert body["name"] == "Jane"
    assert body["skills"] == ["python"]

    # A non-PDF/DOCX upload is rejected before any LLM call.
    resp = client.post(
        "/api/profile/resume", files={"file": ("resume.txt", b"hello", "text/plain")}
    )
    assert resp.status_code == 415


# --------------------------------------------------------------------- settings


def test_settings_get_and_update(api):
    client, _, _ = api

    base = client.get("/api/settings").json()
    assert "naukri_keywords" in base
    assert "naukri_password" not in base  # never leaked
    assert "naukri_password_set" in base

    updated = client.put(
        "/api/settings",
        json={
            "naukri_keywords": "data engineer",
            "naukri_location": "pune",
            "telegram_top_n": 5,
            "llm_provider": "ollama",
            "llm_model": "llama3.2",
            "llm_base_url": "http://localhost:11434/v1",
        },
    ).json()
    assert updated["naukri_keywords"] == "data engineer"
    assert updated["naukri_location"] == "pune"
    assert updated["telegram_top_n"] == 5
    assert updated["llm_provider"] == "ollama"
    assert updated["llm_model"] == "llama3.2"
    assert updated["llm_base_url"] == "http://localhost:11434/v1"

    # Persisted across requests.
    assert client.get("/api/settings").json()["naukri_keywords"] == "data engineer"


def test_settings_rejects_unknown_llm_provider(api):
    client, _, _ = api
    resp = client.put("/api/settings", json={"llm_provider": "gemini"})
    assert resp.status_code == 422


def test_llm_providers_endpoint(api):
    client, _, _ = api
    providers = client.get("/api/settings/llm/providers").json()
    keys = {p["key"] for p in providers}
    assert {"openai", "anthropic", "ollama", "ollama_cloud"} <= keys
    assert "gemini" not in keys
    local = next(p for p in providers if p["key"] == "ollama")
    assert local["requires_key"] is False
    assert local["default_base_url"] == "http://localhost:11434/v1"


def test_llm_test_endpoint_reports_failure_without_raising(api):
    client, _, _ = api
    # A provider that needs a key but has none: fails config validation offline,
    # so the endpoint must report ok=False in the body rather than 500.
    client.put("/api/settings", json={"llm_provider": "openai", "llm_model": "gpt-4o-mini"})
    body = client.post("/api/settings/llm/test", json={}).json()
    assert body["ok"] is False
    assert "API key is required" in body["detail"]


def test_llm_test_uses_unsaved_body_values_and_saves_nothing(api):
    client, _, _ = api
    client.put("/api/settings", json={"llm_provider": "openai", "llm_model": "gpt-4o-mini"})

    # An unsaved provider in the body is what gets tested: `openai_compatible` with
    # no base URL fails config validation offline, unlike the saved `openai`.
    body = client.post(
        "/api/settings/llm/test",
        json={"llm_provider": "openai_compatible", "llm_model": "m", "llm_api_key": "typed"},
    ).json()
    assert body["ok"] is False
    assert body["provider"] == "openai_compatible"
    assert "base URL is required" in body["detail"]

    # Nothing was persisted by the test call.
    saved = client.get("/api/settings").json()
    assert saved["llm_provider"] == "openai"
    assert saved["llm_api_key_set"] is False


# --------------------------------------------------------------------- docs


def test_openapi_and_docs_browsable(api):
    client, _, _ = api
    assert client.get("/openapi.json").status_code == 200
    paths = client.get("/openapi.json").json()["paths"]
    for route in ("/api/matches", "/api/applications", "/api/runs", "/api/run-now", "/api/profile"):
        assert route in paths
    assert client.get("/docs").status_code == 200
