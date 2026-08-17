"""Normalizer (M4): turn `raw_jobs` into clean, deduplicated `jobs`.

Three responsibilities:
1. Map each source's raw payload to the common jobs schema.
2. Extract skills from the description (cheap keyword list; LLM is optional and
   pluggable via `skill_extractor`).
3. Compute a stable `content_hash` from normalized title + company + location.

The orchestration (`normalize_and_dedupe`) reads a run's raw jobs, runs exact +
fuzzy dedup (see `app.dedupe`), and inserts only genuinely new jobs. Jobs link
back to `raw_jobs` implicitly through the shared `url`/`source` (the M1 `jobs`
schema carries no FK), which is how `repository.get_jobs_for_run` traces them.
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import connection
from app.database import repository as repo
from app.dedupe.dedupe import ExistingKey, _normalize_text, find_duplicate

logger = logging.getLogger(__name__)

SessionScope = Callable[[], AbstractContextManager[Session]]
SkillExtractor = Callable[[str], list[str]]

# Cheap, dependency-free skill detection. Extend freely; LLM extraction is optional.
DEFAULT_SKILLS: tuple[str, ...] = (
    "python",
    "java",
    "javascript",
    "typescript",
    "go",
    "golang",
    "rust",
    "c++",
    "c#",
    "react",
    "angular",
    "vue",
    "node",
    "node.js",
    "fastapi",
    "django",
    "flask",
    "spring",
    "sql",
    "postgresql",
    "postgres",
    "mysql",
    "mongodb",
    "redis",
    "elasticsearch",
    "aws",
    "gcp",
    "azure",
    "docker",
    "kubernetes",
    "terraform",
    "kafka",
    "spark",
    "machine learning",
    "deep learning",
    "nlp",
    "pytorch",
    "tensorflow",
    "pandas",
    "rest",
    "graphql",
    "grpc",
    "microservices",
    "ci/cd",
    "git",
)


@dataclass
class NormalizedJob:
    """A raw payload mapped to the common jobs schema, with hash and skills."""

    source: str
    title: str
    company: str
    location: str | None
    description: str | None
    skills: list[str]
    url: str | None
    source_job_id: str | None
    content_hash: str


@dataclass
class DedupeReport:
    """Counts from one normalize + dedup pass."""

    raw_jobs: int = 0
    normalized: int = 0
    inserted: int = 0
    skipped_unmappable: int = 0
    duplicates_dropped: int = 0
    job_ids: list[int] = field(default_factory=list)


# ----------------------------------------------------------------- content hashing


def compute_content_hash(title: str, company: str, location: str | None) -> str:
    """Stable hash of normalized title + company + location."""
    basis = "|".join(_normalize_text(part) for part in (title, company, location))
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


# -------------------------------------------------------------------- skill extract


def extract_skills(text: str | None, *, keywords: tuple[str, ...] = DEFAULT_SKILLS) -> list[str]:
    """Keyword-match skills from free text. Cheap and deterministic.

    Uses word boundaries so "go" doesn't match "golang" and trailing punctuation
    ("Docker.") is handled, while skill tokens with symbols (c++, node.js) still match.
    """
    haystack = _normalize_text(text)
    if not haystack:
        return []
    found = [
        kw for kw in keywords if re.search(rf"(?<!\w){re.escape(kw)}(?!\w)", haystack) is not None
    ]
    # Preserve first-seen order while de-duplicating.
    return list(dict.fromkeys(found))


# ----------------------------------------------------------------- source mapping


def _map_common(payload: dict) -> dict:
    """Map the shared collector payload shape to common job fields.

    Naukri and LinkedIn both emit this shape (see `collectors.base.payload_to_dict`),
    so they share one mapper.
    """
    return {
        "title": payload.get("title"),
        "company": payload.get("company"),
        "location": payload.get("location"),
        "description": payload.get("description"),
        "url": payload.get("url"),
        "source_job_id": payload.get("source_job_id"),
    }


# Per-source payload → common-field mappers.
_MAPPERS: dict[str, Callable[[dict], dict]] = {
    "naukri": _map_common,
    "linkedin": _map_common,
}


def normalize_payload(
    source: str,
    payload: dict,
    *,
    skill_extractor: SkillExtractor | None = None,
) -> NormalizedJob | None:
    """Map one raw payload to a `NormalizedJob`, or None if it can't be mapped."""
    mapper = _MAPPERS.get(source)
    if mapper is None:
        logger.warning("no normalizer mapping for source %r; skipping", source)
        return None

    fields = mapper(payload or {})
    title = (fields.get("title") or "").strip()
    company = (fields.get("company") or "").strip()
    if not title or not company:
        return None  # cannot form a content hash without a title and company

    location = fields.get("location")
    description = fields.get("description")
    extractor = skill_extractor or extract_skills
    skills = extractor(f"{title}\n{description or ''}")

    return NormalizedJob(
        source=source,
        title=title,
        company=company,
        location=location,
        description=description,
        skills=skills,
        url=fields.get("url"),
        source_job_id=fields.get("source_job_id"),
        content_hash=compute_content_hash(title, company, location),
    )


# -------------------------------------------------------------------- orchestration


def normalize_and_dedupe(
    run_id: int,
    *,
    session_scope: SessionScope | None = None,
    settings: Settings | None = None,
    skill_extractor: SkillExtractor | None = None,
) -> DedupeReport:
    """Normalize a run's raw jobs and resolve each to a job row (existing or new).

    Existing jobs are never duplicated — a re-scraped job maps back to its row — and
    `job_ids` includes every job seen this run (new *and* existing) so the ranker
    re-affirms them all (cache makes re-ranking free) and the dashboard stays populated.
    """
    session_scope = session_scope or connection.session_scope
    settings = settings or get_settings()
    report = DedupeReport()

    with session_scope() as session:
        raw_jobs = repo.get_raw_jobs_for_run(session, run_id)
        report.raw_jobs = len(raw_jobs)

        candidates: list[NormalizedJob] = []
        for raw in raw_jobs:
            normalized = normalize_payload(
                raw.source, raw.raw_payload_json, skill_extractor=skill_extractor
            )
            if normalized is None:
                report.skipped_unmappable += 1
            else:
                candidates.append(normalized)
        report.normalized = len(candidates)

        # Known jobs = everything already in the DB, growing as we accept new ones.
        known: list[ExistingKey] = [
            ExistingKey(
                id=j.id, title=j.title, company=j.company, url=j.url, content_hash=j.content_hash
            )
            for j in repo.list_jobs(session)
        ]

        seen_ids: list[int] = []
        for nj in candidates:
            match = find_duplicate(nj, known, fuzzy_threshold=settings.dedupe_fuzzy_threshold)
            if match is not None and match.id is not None:
                if match.id not in seen_ids:
                    seen_ids.append(match.id)
                continue
            job = repo.upsert_job(
                session,
                title=nj.title,
                company=nj.company,
                location=nj.location,
                description=nj.description,
                skills=nj.skills,
                source=nj.source,
                url=nj.url,
                content_hash=nj.content_hash,
                run_id=run_id,
            )
            report.inserted += 1
            seen_ids.append(job.id)
            known.append(
                ExistingKey(
                    id=job.id,
                    title=nj.title,
                    company=nj.company,
                    url=nj.url,
                    content_hash=nj.content_hash,
                    source=nj.source,
                    source_job_id=nj.source_job_id,
                )
            )

        report.job_ids = seen_ids
        report.duplicates_dropped = report.normalized - len(seen_ids)

    logger.info(
        "normalize run %s: raw=%d normalized=%d new=%d seen=%d",
        run_id,
        report.raw_jobs,
        report.normalized,
        report.inserted,
        len(report.job_ids),
    )
    return report
