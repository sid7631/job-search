"""Deduplication (M4): exact + fuzzy, no embeddings.

Pure logic — no database access. `find_duplicate` resolves one normalized candidate
to an already-known job (an existing DB row or one accepted earlier in the same batch),
or None if it is genuinely new:

- **Exact**: same `url`, same `content_hash`, or same `(source, source_job_id)`.
- **Fuzzy**: `rapidfuzz.token_sort_ratio` over a normalized `title + company` string,
  at or above a configurable threshold.

The normalizer uses this so a re-scraped job maps back to its existing row (no
duplicate inserted) while still being included in the run's ranked set.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from rapidfuzz.fuzz import token_sort_ratio

_WHITESPACE = re.compile(r"\s+")


def _normalize_text(value: str | None) -> str:
    """Lowercase, trim, and collapse internal whitespace."""
    return _WHITESPACE.sub(" ", (value or "").strip().lower())


def fuzzy_key(title: str | None, company: str | None) -> str:
    """The normalized string fuzzy matching compares (title + company)."""
    return _normalize_text(f"{title or ''} {company or ''}")


def fuzzy_ratio(
    title_a: str | None,
    company_a: str | None,
    title_b: str | None,
    company_b: str | None,
) -> float:
    """token_sort_ratio (0-100) between two (title, company) pairs."""
    return token_sort_ratio(fuzzy_key(title_a, company_a), fuzzy_key(title_b, company_b))


@dataclass(frozen=True)
class ExistingKey:
    """The dedup-relevant fields of an already-known job (DB row or batch sibling)."""

    title: str
    company: str
    url: str | None = None
    content_hash: str | None = None
    id: int | None = None
    source: str | None = None
    source_job_id: str | None = None


class Candidate(Protocol):
    """Structural type for a normalized job being deduplicated."""

    source: str
    title: str
    company: str
    url: str | None
    content_hash: str
    source_job_id: str | None


def find_duplicate(
    candidate: Candidate,
    existing: Sequence[ExistingKey],
    *,
    fuzzy_threshold: float,
) -> ExistingKey | None:
    """Return the known job the candidate duplicates, or None if it's new."""
    # Exact matches first.
    for key in existing:
        if candidate.url and key.url and candidate.url == key.url:
            return key
        if (
            candidate.content_hash
            and key.content_hash
            and candidate.content_hash == key.content_hash
        ):
            return key
        if (
            candidate.source_job_id
            and key.source_job_id
            and candidate.source == key.source
            and candidate.source_job_id == key.source_job_id
        ):
            return key

    # Fuzzy fallback on title + company.
    candidate_key = fuzzy_key(candidate.title, candidate.company)
    for key in existing:
        if token_sort_ratio(candidate_key, fuzzy_key(key.title, key.company)) >= fuzzy_threshold:
            return key
    return None
