"""Tests for the MCP server tools (called directly against the in-memory DB)."""

from __future__ import annotations

import asyncio

import pytest
from app import mcp_server
from app.database import repository as repo


@pytest.fixture(autouse=True)
def _db(scope, monkeypatch):
    monkeypatch.setattr(mcp_server.connection, "session_scope", scope)


def _seed(scope) -> dict[str, int]:
    with scope() as s:
        run_id = repo.start_run(s).id
        ids = {}
        for i, (title, company, score) in enumerate(
            [("Backend Engineer", "Razorpay Software Pvt Ltd", 90), ("Data Analyst", "Acme", 40)]
        ):
            job = repo.upsert_job(
                s, title=title, company=company, source="naukri", content_hash=f"h{i}"
            )
            repo.save_match(s, job_id=job.id, run_id=run_id, score=score, llm_model="m", reason="r")
            ids[title] = job.id
        repo.finish_run(s, run_id, status="SUCCESS")
    return ids


def test_tools_are_registered():
    names = {t.name for t in asyncio.run(mcp_server.server.list_tools())}
    assert {
        "get_profile",
        "get_queue",
        "get_job",
        "find_applications",
        "update_application",
        "triage_job",
        "application_stats",
        "start_run",
    } <= names


def test_queue_triage_and_find(scope):
    ids = _seed(scope)
    queue = mcp_server.get_queue()
    assert [i["title"] for i in queue["items"]] == ["Backend Engineer", "Data Analyst"]

    mcp_server.triage_job(ids["Backend Engineer"], "apply")
    assert mcp_server.get_queue()["remaining"] == 1

    found = mcp_server.find_applications("Razorpay")
    assert found[0]["job"]["title"] == "Backend Engineer"
    assert found[0]["match"] >= 80


def test_update_application_appends_dated_notes(scope):
    ids = _seed(scope)
    app_id = mcp_server.track_job(ids["Data Analyst"])["application_id"]

    mcp_server.update_application(app_id, note="Recruiter replied")
    result = mcp_server.update_application(app_id, status="INTERVIEWING", note="Call on Thu")

    assert result["status"] == "INTERVIEWING"
    lines = result["notes"].splitlines()
    assert len(lines) == 2
    assert lines[0].startswith("[20") and lines[0].endswith("Recruiter replied")


def test_stats_and_missing_ids(scope):
    ids = _seed(scope)
    mcp_server.triage_job(ids["Backend Engineer"], "apply")
    mcp_server.triage_job(ids["Data Analyst"], "dismiss", reason="wrong_stack")

    stats = mcp_server.application_stats()
    assert stats["applications_sent"] == 1
    assert stats["pass_reasons"] == {"wrong tech stack": 1}
    assert "error" in mcp_server.get_job(999)
    assert "error" in mcp_server.update_application(999, status="OFFER")


def test_start_run_refuses_when_one_is_active(scope):
    with scope() as s:
        repo.start_run(s)
    assert mcp_server.start_run()["started"] is False
