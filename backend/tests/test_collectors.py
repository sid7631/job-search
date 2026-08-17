"""Tests for the M3 collector layer (offline — Playwright is never launched)."""

from __future__ import annotations

import pytest
from app.collectors.base import (
    Collector,
    RawJobPayload,
    SessionError,
    random_delay,
    retry_with_backoff,
    safe_collect,
)
from app.collectors.naukri import NaukriCollector
from app.config import Settings
from app.database import repository as repo
from app.database.models import Run


class _StubNaukri(NaukriCollector):
    """Naukri collector with the live scrape replaced by canned data."""

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


# ----------------------------------------------------------------- happy path


def test_collect_writes_raw_jobs_tagged_with_run_and_source(scope):
    run_id = _start_run(scope)
    payloads = [
        RawJobPayload(
            source_job_id="J1",
            url="https://www.naukri.com/job-listings-sde-acme-12345",
            title="SDE III",
            company="Acme",
            location="Bengaluru",
            description="Build things.",
            raw={"page_no": 1},
        ),
        RawJobPayload(source_job_id="J2", url="https://x/2", title="Backend Eng", company="Globex"),
    ]
    collector = _StubNaukri(payloads=payloads, session_scope=scope)

    saved = collector.collect(run_id)

    assert len(saved) == 2
    with scope() as s:
        rows = repo.get_raw_jobs_for_run(s, run_id)
    assert len(rows) == 2
    first = rows[0]
    assert first.source == "naukri"
    assert first.run_id == run_id
    assert first.source_job_id == "J1"
    assert first.url.endswith("12345")
    assert first.raw_payload_json["title"] == "SDE III"
    assert first.raw_payload_json["company"] == "Acme"


# ------------------------------------------------------------- graceful failure


def test_bad_session_records_error_and_returns_empty(scope):
    run_id = _start_run(scope)
    collector = _StubNaukri(error=SessionError("login failed"), session_scope=scope)

    saved = collector.collect(run_id)

    assert saved == []
    with scope() as s:
        run = s.get(Run, run_id)
        assert run.source_errors_json
        assert "login failed" in str(run.source_errors_json)
        assert repo.get_raw_jobs_for_run(s, run_id) == []


class _LoginWallPage:
    """Minimal page stand-in that always looks like Naukri's login wall."""

    url = "https://www.naukri.com/nlogin/login"

    def goto(self, *a, **k): ...
    def wait_for_timeout(self, *a, **k): ...
    def query_selector(self, *a, **k):
        return None


def test_missing_credentials_is_a_session_error_only_when_login_required(tmp_path):
    settings = Settings(
        naukri_email="",
        naukri_password="",
        naukri_require_login=True,
        storage_state_dir=str(tmp_path),
    )
    collector = NaukriCollector(settings=settings)
    with pytest.raises(SessionError, match="NAUKRI_REQUIRE_LOGIN"):
        collector._ensure_session(None, _LoginWallPage())


def test_public_scrape_needs_no_credentials(tmp_path):
    # The default path: no login required, so _ensure_session is a no-op.
    settings = Settings(naukri_email="", naukri_password="", storage_state_dir=str(tmp_path))
    NaukriCollector(settings=settings)._ensure_session(None, None)


def test_safe_collect_isolates_unexpected_crash():
    class _Boom(Collector):
        source = "boom"

        def collect(self, run_id):
            raise RuntimeError("kaboom")

    assert safe_collect(_Boom(), 1) == []


# --------------------------------------------------------------------- helpers


def test_job_id_parsed_from_url():
    assert NaukriCollector._job_id_from_url("https://www.naukri.com/job-x-998877") == "998877"
    assert NaukriCollector._job_id_from_url("https://www.naukri.com/job-x-998877?src=a") == "998877"
    assert NaukriCollector._job_id_from_url(None) is None


def test_build_search_url_uses_config():
    collector = NaukriCollector(
        settings=Settings(
            naukri_keywords="frontend developer, react js", naukri_location="bangalore"
        )
    )
    assert collector._build_search_url(1) == (
        "https://www.naukri.com/frontend-developer-react-js-jobs-in-bangalore"
    )
    # Page 2 appends the SEO page suffix.
    assert collector._build_search_url(2).endswith("-in-bangalore-2")


def test_parse_card_extracts_fields():
    # Real card text captured from Naukri's current UI.
    lines = [
        "Royal Cyber",
        "3.3",
        "IT Services & Consulting",
        "1001-5000 employees",
        "26d ago",
        "Quick apply",
        "Frontend Developer- React JS",
        "Remote",
        "₹15L - ₹30L/year",
        "React.js, frontend, Reacts Js, Javascript, Redux",
        "6-11 Yrs",
    ]
    p = NaukriCollector._parse_card(lines)
    assert p is not None
    assert p["company"] == "Royal Cyber"
    assert p["title"] == "Frontend Developer- React JS"
    assert p["location"] == "Remote"
    assert p["salary"] == "₹15L - ₹30L/year"
    assert p["experience"] == "6-11 Yrs"
    assert "React.js" in p["skills"]

    # A description is synthesized from the fields (no detail page in this UI).
    desc = NaukriCollector._describe(p)
    assert "Royal Cyber" in desc and "React.js" in desc

    assert NaukriCollector._parse_card(["just one line"]) is None


def test_retry_with_backoff_retries_then_succeeds():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ValueError("transient")
        return "ok"

    result = retry_with_backoff(flaky, attempts=3, base_delay=0, sleep=lambda _: None)
    assert result == "ok"
    assert calls["n"] == 3


def test_retry_with_backoff_does_not_retry_session_error():
    calls = {"n": 0}

    def dead():
        calls["n"] += 1
        raise SessionError("dead")

    with pytest.raises(SessionError):
        retry_with_backoff(dead, attempts=5, base_delay=0, sleep=lambda _: None)
    assert calls["n"] == 1


def test_random_delay_stays_within_bounds():
    seen = {}
    random_delay(1.0, 2.0, sleep=lambda x: seen.update(x=x))
    assert 1.0 <= seen["x"] <= 2.0
