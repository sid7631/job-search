"""Tests for the M10 hardened LinkedIn collector (offline — Playwright not launched)."""

from __future__ import annotations

import pytest
from app.collectors.base import RawJobPayload, SessionError
from app.collectors.linkedin import LinkedInCollector
from app.config import Settings
from app.database import repository as repo
from app.database.models import Run


class StubLinkedIn(LinkedInCollector):
    """LinkedIn collector with the live scrape replaced by canned data/errors."""

    def __init__(self, *, payloads=None, error=None, **kwargs):
        super().__init__(**kwargs)
        self._payloads = payloads or []
        self._error = error

    def _fetch_raw_jobs(self):
        if self._error is not None:
            raise self._error
        return self._payloads


def _start_run(scope) -> int:
    with scope() as s:
        return repo.start_run(s).id


# --------------------------------------------------------------------- happy path


def test_collect_writes_linkedin_raw_jobs(scope):
    run_id = _start_run(scope)
    payloads = [
        RawJobPayload(
            source_job_id="111",
            url="https://www.linkedin.com/jobs/view/111",
            title="Backend Engineer",
            company="Acme",
            location="Remote",
            description="Build things.",
            raw={"page_no": 1},
        )
    ]
    collector = StubLinkedIn(payloads=payloads, session_scope=scope)

    saved = collector.collect(run_id)

    assert len(saved) == 1
    with scope() as s:
        rows = repo.get_raw_jobs_for_run(s, run_id)
    assert rows[0].source == "linkedin"  # same raw_jobs contract as Naukri
    assert rows[0].run_id == run_id
    assert rows[0].source_job_id == "111"
    assert rows[0].raw_payload_json["title"] == "Backend Engineer"


# ----------------------------------------------------- dead session → alert, not crash


def test_dead_session_records_error_and_sends_reauth_alert(scope):
    run_id = _start_run(scope)
    alerts: list[int] = []
    collector = StubLinkedIn(
        error=SessionError("hit a checkpoint wall"),
        session_scope=scope,
        alert=lambda: alerts.append(1),
    )

    saved = collector.collect(run_id)

    assert saved == []  # graceful, not a crash
    assert alerts == [1]  # Telegram re-auth alert fired
    with scope() as s:
        run = s.get(Run, run_id)
        assert run.error_text is not None
        assert "checkpoint" in run.error_text
        assert repo.get_raw_jobs_for_run(s, run_id) == []


def test_alert_failure_still_returns_gracefully(scope):
    run_id = _start_run(scope)

    def boom() -> None:
        raise RuntimeError("telegram is down")

    collector = StubLinkedIn(error=SessionError("dead"), session_scope=scope, alert=boom)

    assert collector.collect(run_id) == []  # alert failure does not crash the run
    with scope() as s:
        assert "dead" in s.get(Run, run_id).error_text


def test_missing_credentials_is_a_session_error():
    collector = LinkedInCollector(settings=Settings(linkedin_email="", linkedin_password=""))
    with pytest.raises(SessionError):
        collector._fetch_raw_jobs()


# --------------------------------------------------------------------- helpers


def test_build_search_url_uses_config_and_paginates():
    collector = LinkedInCollector(
        settings=Settings(linkedin_keywords="backend engineer", linkedin_location="India")
    )
    first = collector._build_search_url(1)
    assert "keywords=backend+engineer" in first
    assert "location=India" in first
    assert "start=" not in first  # page 1 has no offset

    second = collector._build_search_url(2)
    assert "start=25" in second  # 25 results per page


def test_parse_card_extracts_title_company_location():
    # Real card text captured from LinkedIn's current jobs UI.
    a = LinkedInCollector._parse_card(
        [
            "Frontend Developer",
            "Unacademy",
            "Bengaluru, Karnataka, India (On-site)",
            "2 school alumni work here",
            "Promoted",
        ]
    )
    assert a == {
        "title": "Frontend Developer",
        "company": "Unacademy",
        "location": "Bengaluru, Karnataka, India (On-site)",
    }
    b = LinkedInCollector._parse_card(
        ["Frontend Engineer (Remote)", "Hire Feed", "APAC (Remote)", "Viewed"]
    )
    assert b["title"] == "Frontend Engineer (Remote)" and b["company"] == "Hire Feed"
    assert LinkedInCollector._parse_card(["only one"]) is None


def test_job_id_parsed_from_url():
    assert (
        LinkedInCollector._job_id_from_url("https://www.linkedin.com/jobs/view/3856201")
        == "3856201"
    )
    assert (
        LinkedInCollector._job_id_from_url(
            "https://www.linkedin.com/jobs/search/?currentJobId=999888&keywords=x"
        )
        == "999888"
    )
    assert LinkedInCollector._job_id_from_url(None) is None
