"""Tests for the semantic fit gate (offline — httpx is stubbed)."""

from __future__ import annotations

import json

import httpx
import pytest
from app.database.models import CandidateProfile, Job
from app.ranking.semantic_filter import (
    MAX_CONSECUTIVE_ERRORS,
    DecisionError,
    OllamaDecisionClient,
    semantic_filter,
)


def _profile() -> CandidateProfile:
    return CandidateProfile(
        name="Jane",
        years_experience=6,
        skills_json=["python", "postgresql"],
        domain="backend",
        desired_roles_json=["Backend Engineer"],
        preferred_locations_json=["Remote"],
        resume_text="Backend engineer.",
    )


def _job(job_id: int, title: str) -> Job:
    return Job(id=job_id, title=title, company="Acme", location="Remote", description="...")


def _stub(client: OllamaDecisionClient, handler) -> list[httpx.Request]:
    seen: list[httpx.Request] = []

    def _handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    client._client = httpx.Client(transport=httpx.MockTransport(_handle))
    return seen


# ------------------------------------------------------------------- client


def test_client_sends_noul_question_and_reads_probability():
    client = OllamaDecisionClient("http://localhost:11434/", "tev1:4b")
    seen = _stub(
        client,
        lambda r: httpx.Response(
            200, json={"answers": {"fit": {"type": "noul", "noul": 0.87}}, "usage": {}}
        ),
    )

    assert client({"candidate": "c", "job": "j"}) == pytest.approx(0.87)

    req = seen[0]
    assert str(req.url) == "http://localhost:11434/v1/systemone"
    body = json.loads(req.content)
    assert body["model"] == "tev1:4b"
    assert body["state"] == {"candidate": "c", "job": "j"}
    assert body["questions"]["fit"]["type"] == "noul"


def test_client_wraps_http_errors():
    client = OllamaDecisionClient("http://x", "missing")
    _stub(client, lambda r: httpx.Response(404, text="model not found"))
    with pytest.raises(DecisionError, match="pulled"):
        client({})


def test_client_wraps_malformed_answer():
    client = OllamaDecisionClient("http://x", "m")
    _stub(client, lambda r: httpx.Response(200, json={"answers": {}}))
    with pytest.raises(DecisionError, match="unusable"):
        client({})


# ------------------------------------------------------------------- filter


def test_drops_jobs_below_threshold_and_keeps_order():
    fits = {"Backend Engineer": 0.95, "Staff Nurse": 0.01, "Platform Engineer": 0.3}
    jobs = [_job(1, "Backend Engineer"), _job(2, "Staff Nurse"), _job(3, "Platform Engineer")]

    def scorer(state):
        return next(v for k, v in fits.items() if f"Title: {k}." in state["job"])

    keep, report = semantic_filter(_profile(), jobs, scorer=scorer, min_fit=0.1)

    assert [j.id for j in keep] == [1, 3]
    assert (report.considered, report.kept, report.dropped, report.errors) == (3, 2, 1, 0)
    assert report.as_dict["dropped_jobs"] == [
        {"job_id": 2, "title": "Staff Nurse", "company": "Acme", "fit": 0.01}
    ]


def test_state_carries_candidate_and_job():
    seen: list[dict] = []

    def scorer(state):
        seen.append(state)
        return 1.0

    semantic_filter(_profile(), [_job(1, "Backend Engineer")], scorer=scorer, min_fit=0.5)

    assert "python" in seen[0]["candidate"]
    assert "Backend Engineer" in seen[0]["candidate"]
    assert "Title: Backend Engineer." in seen[0]["job"]


def test_fails_open_on_errors():
    def scorer(state):
        raise DecisionError("down")

    jobs = [_job(i, f"Job {i}") for i in range(1, 3)]
    keep, report = semantic_filter(_profile(), jobs, scorer=scorer, min_fit=0.9)

    assert [j.id for j in keep] == [1, 2]
    assert report.errors == 2
    assert report.dropped == 0


def test_stops_calling_after_repeated_failures():
    calls = 0

    def scorer(state):
        nonlocal calls
        calls += 1
        raise DecisionError("down")

    jobs = [_job(i, f"Job {i}") for i in range(1, 11)]
    keep, report = semantic_filter(_profile(), jobs, scorer=scorer, min_fit=0.5)

    assert calls == MAX_CONSECUTIVE_ERRORS
    assert len(keep) == 10
    assert report.errors == 10
