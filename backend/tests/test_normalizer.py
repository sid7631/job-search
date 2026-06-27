"""Tests for the normalizer and the end-to-end normalize + dedup pass (M4)."""

from __future__ import annotations

from app.config import Settings
from app.database import repository as repo
from app.dedupe.dedupe import fuzzy_ratio
from app.normalizer.normalizer import (
    compute_content_hash,
    extract_skills,
    normalize_and_dedupe,
    normalize_payload,
)


def _naukri_payload(title, company, *, location="Bengaluru", url=None, source_job_id=None, desc=""):
    return {
        "source_job_id": source_job_id,
        "url": url,
        "title": title,
        "company": company,
        "location": location,
        "description": desc,
        "raw": {},
    }


def _add_raw(session, run_id, **kwargs):
    payload = _naukri_payload(**kwargs)
    return repo.add_raw_job(
        session,
        source="naukri",
        run_id=run_id,
        source_job_id=payload["source_job_id"],
        url=payload["url"],
        raw_payload=payload,
    )


# ----------------------------------------------------------------- content hashing


def test_content_hash_is_normalization_stable():
    a = compute_content_hash("Senior  Backend Engineer", "Acme", "Bengaluru")
    b = compute_content_hash("senior backend engineer", "  ACME ", "bengaluru")
    assert a == b


def test_content_hash_changes_with_location():
    a = compute_content_hash("Backend Engineer", "Acme", "Bengaluru")
    b = compute_content_hash("Backend Engineer", "Acme", "Remote")
    assert a != b


# -------------------------------------------------------------------- skill extract


def test_extract_skills_finds_known_keywords():
    text = "Looking for a Python developer with FastAPI and Docker. SQL and AWS a plus."
    skills = extract_skills(text)
    assert {"python", "fastapi", "docker", "sql", "aws"} <= set(skills)
    assert "java" not in skills


def test_extract_skills_empty_text():
    assert extract_skills("") == []
    assert extract_skills(None) == []


# ----------------------------------------------------------------- payload mapping


def test_normalize_payload_maps_naukri_fields():
    payload = _naukri_payload(
        "Senior Backend Engineer",
        "Acme",
        url="https://x/1",
        source_job_id="J1",
        desc="Python and Docker.",
    )
    nj = normalize_payload("naukri", payload)
    assert nj is not None
    assert nj.title == "Senior Backend Engineer"
    assert nj.company == "Acme"
    assert nj.url == "https://x/1"
    assert nj.source_job_id == "J1"
    assert "python" in nj.skills and "docker" in nj.skills
    assert nj.content_hash == compute_content_hash("Senior Backend Engineer", "Acme", "Bengaluru")


def test_normalize_payload_skips_when_missing_required_fields():
    assert normalize_payload("naukri", _naukri_payload("", "Acme")) is None
    assert normalize_payload("naukri", _naukri_payload("Engineer", "")) is None


def test_normalize_payload_unknown_source_returns_none():
    assert normalize_payload("monster", _naukri_payload("Eng", "Acme")) is None


def test_normalize_payload_maps_linkedin_source():
    # LinkedIn (M10) shares the common payload shape, so the same mapper applies.
    payload = _naukri_payload(
        "Backend Engineer", "Acme", url="https://lnkd.in/1", source_job_id="L1"
    )
    nj = normalize_payload("linkedin", payload)
    assert nj is not None
    assert nj.source == "linkedin"
    assert nj.title == "Backend Engineer"
    assert nj.source_job_id == "L1"


# ------------------------------------------------------------------- end-to-end


def _plant_duplicates(scope) -> int:
    """A raw_jobs set with planted exact + fuzzy duplicates → 2 unique roles."""
    with scope() as s:
        run_id = repo.start_run(s).id
        # Role A — three rows that should collapse to one.
        _add_raw(
            s, run_id, title="Senior Backend Engineer", company="Acme", url="u1", source_job_id="1"
        )
        _add_raw(
            s, run_id, title="Senior Backend Engineer", company="Acme", url="u1", source_job_id="1b"
        )  # dup url
        _add_raw(
            s, run_id, title="Senior Backend Engineer", company="Acme", url="u3", source_job_id="3"
        )  # dup hash
        # Role B — two rows that only fuzzy-match (comma → different hash/url/id).
        _add_raw(
            s,
            run_id,
            title="Data Scientist",
            company="Globex",
            location="Remote",
            url="u4",
            source_job_id="4",
        )
        _add_raw(
            s,
            run_id,
            title="Data Scientist,",
            company="Globex",
            location="Remote",
            url="u5",
            source_job_id="5",
        )
    return run_id


def test_normalize_and_dedupe_keeps_only_unique_roles(scope):
    run_id = _plant_duplicates(scope)
    ratio = fuzzy_ratio("Data Scientist,", "Globex", "Data Scientist", "Globex")
    assert 90 <= ratio < 100

    settings = Settings(dedupe_fuzzy_threshold=ratio - 0.5)  # merges the fuzzy pair
    report = normalize_and_dedupe(run_id, session_scope=scope, settings=settings)

    assert report.raw_jobs == 5
    assert report.inserted == 2
    assert report.duplicates_dropped == 3
    with scope() as s:
        jobs = repo.list_jobs(s)
    assert {j.title for j in jobs} == {"Senior Backend Engineer", "Data Scientist"}


def test_threshold_above_ratio_keeps_fuzzy_pair_separate(scope):
    run_id = _plant_duplicates(scope)
    ratio = fuzzy_ratio("Data Scientist,", "Globex", "Data Scientist", "Globex")

    settings = Settings(dedupe_fuzzy_threshold=min(100.0, ratio + 0.5))  # does NOT merge
    report = normalize_and_dedupe(run_id, session_scope=scope, settings=settings)

    assert report.inserted == 3  # the fuzzy pair stays distinct
    with scope() as s:
        assert len(repo.list_jobs(s)) == 3


def test_normalize_is_idempotent_across_reruns(scope):
    run_id = _plant_duplicates(scope)
    settings = Settings(dedupe_fuzzy_threshold=90.0)

    first = normalize_and_dedupe(run_id, session_scope=scope, settings=settings)
    second = normalize_and_dedupe(run_id, session_scope=scope, settings=settings)

    assert first.inserted == 2
    assert second.inserted == 0  # everything already exists; no new rows, no duplicates
    # …but the re-run still resolves to the existing jobs, so they get re-ranked and the
    # dashboard stays populated (persistence: jobs are never dropped on a new run).
    assert sorted(second.job_ids) == sorted(first.job_ids)
    assert len(second.job_ids) == 2
    with scope() as s:
        assert len(repo.list_jobs(s)) == 2  # no duplicates created
