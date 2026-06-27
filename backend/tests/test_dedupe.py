"""Tests for the pure deduplication logic (M4)."""

from __future__ import annotations

from app.dedupe.dedupe import ExistingKey, find_duplicate, fuzzy_key, fuzzy_ratio
from app.normalizer.normalizer import NormalizedJob, compute_content_hash


def _cand(title, company, *, location="Bengaluru", url=None, source_job_id=None, source="naukri"):
    return NormalizedJob(
        source=source,
        title=title,
        company=company,
        location=location,
        description=None,
        skills=[],
        url=url,
        source_job_id=source_job_id,
        content_hash=compute_content_hash(title, company, location),
    )


# --------------------------------------------------------------------- exact match


def test_find_duplicate_by_content_hash():
    job = _cand("Backend Engineer", "Acme")
    existing = [ExistingKey(id=7, title="x", company="y", content_hash=job.content_hash)]
    assert find_duplicate(job, existing, fuzzy_threshold=101).id == 7


def test_find_duplicate_by_url():
    job = _cand("Backend Engineer", "Acme", url="https://x/1")
    existing = [ExistingKey(id=3, title="Other", company="Co", url="https://x/1")]
    assert find_duplicate(job, existing, fuzzy_threshold=101).id == 3


def test_find_duplicate_by_source_job_id():
    job = _cand("Backend Engineer", "Acme", source_job_id="J9")
    existing = [ExistingKey(id=5, title="x", company="y", source="naukri", source_job_id="J9")]
    assert find_duplicate(job, existing, fuzzy_threshold=101).id == 5
    # Different source → not a match.
    other = [ExistingKey(id=6, title="x", company="y", source="linkedin", source_job_id="J9")]
    assert find_duplicate(job, other, fuzzy_threshold=101) is None


def test_find_duplicate_none_when_new():
    job = _cand("Backend Engineer", "Acme", url="https://x/new")
    existing = [ExistingKey(id=1, title="Data Scientist", company="Globex", url="https://x/1")]
    assert find_duplicate(job, existing, fuzzy_threshold=101) is None


# --------------------------------------------------------------------- fuzzy match


def test_fuzzy_key_and_ratio_basics():
    assert fuzzy_key("  Senior   Engineer ", "Acme") == "senior engineer acme"
    assert fuzzy_ratio("Backend Engineer", "Acme", "Backend Engineer", "Acme") == 100.0


def test_find_duplicate_is_fuzzy_threshold_driven():
    job = _cand("Data Scientist,", "Globex", url="u2")  # comma → different content_hash
    existing = [
        ExistingKey(id=9, title="Data Scientist", company="Globex", url="u1", content_hash="h")
    ]
    ratio = fuzzy_ratio("Data Scientist,", "Globex", "Data Scientist", "Globex")
    assert 90 <= ratio < 100

    # At/under the ratio → matched to the existing job.
    assert find_duplicate(job, existing, fuzzy_threshold=ratio - 0.5).id == 9
    # Above the ratio → treated as new.
    assert find_duplicate(job, existing, fuzzy_threshold=ratio + 0.5) is None
