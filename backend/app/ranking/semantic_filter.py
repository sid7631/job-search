"""Semantic fit gate between the keyword pre-filter and the LLM ranker.

The keyword pre-filter (`prefilter`) is deliberately generous: it can only match
words, so "Platform Engineer" vs "Backend Engineer" or a thin card with no skills
both get through. The ranker then spends a full generative call on each.

This stage asks a small local *decision* model one yes/no question per job — "is
this a plausible fit for the candidate?" — through Ollama's System One endpoint
(`POST /v1/systemone`, Ollama >= 0.35). It returns a probability, not text, so a
call is one forward pass and costs a fraction of a ranking call.

**This is a filter, not a scorer.** The fit probability never reaches the match
score — that stays the ranker's judgement alone (see `ranking_service`).

**It fails open.** Any error (Ollama down, model not pulled, malformed reply) keeps
the job. A broken gate must degrade to "rank everything", never to "rank nothing".

Docs: https://docs.ollama.com/capabilities/decision
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.database.models import CandidateProfile, Job

logger = logging.getLogger(__name__)

# The description is the bulk of the state; decision models have small contexts and
# the opening of a posting (role summary, requirements) carries the signal.
MAX_DESCRIPTION_CHARS = 3_000
MAX_RESUME_CHARS = 1_500
# How many dropped jobs to list in the run's counts so the gate can be audited.
MAX_DROPPED_LISTED = 25
# After this many failures in a row, stop calling and keep the rest: the endpoint is
# down, and waiting out a timeout per job would stall the run for nothing.
MAX_CONSECUTIVE_ERRORS = 3

FIT_QUESTION: dict[str, Any] = {
    "type": "noul",
    "instructions": "Is this job a plausible fit worth a closer look for this candidate?",
    "criteria": {
        "false": "Clearly the wrong field, seniority or skill set for this candidate",
        "true": "Plausibly relevant to the candidate's skills, experience and desired roles",
    },
}

# A pluggable fit call: (state) -> probability of fit in [0, 1].
FitScorer = Callable[[dict[str, Any]], float]


class DecisionError(RuntimeError):
    """Raised when the decision endpoint fails or returns an unusable answer."""


class OllamaDecisionClient:
    """Minimal client for Ollama's `/v1/systemone` decision endpoint."""

    def __init__(self, base_url: str, model: str, *, timeout: float = 60.0):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._client = httpx.Client(timeout=timeout)

    def __call__(self, state: dict[str, Any]) -> float:
        payload = {"model": self.model, "state": state, "questions": {"fit": FIT_QUESTION}}
        try:
            response = self._client.post(f"{self.base_url}/v1/systemone", json=payload)
            response.raise_for_status()
            answer = response.json()["answers"]["fit"]
            return float(answer["noul"])
        except httpx.HTTPStatusError as exc:
            hint = " — is the model pulled?" if exc.response.status_code == 404 else ""
            raise DecisionError(
                f"decision API error: {exc.response.status_code} {exc.response.text}{hint}"
            ) from exc
        except httpx.ConnectError as exc:
            raise DecisionError(
                f"Ollama unreachable at {self.base_url}: {exc}. Is it running (>= 0.35)?"
            ) from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise DecisionError(f"decision API returned an unusable answer: {exc}") from exc
        except httpx.HTTPError as exc:
            raise DecisionError(f"decision API call failed: {exc}") from exc

    def close(self) -> None:
        self._client.close()


def _join(values: list | None) -> str:
    items = [str(v) for v in (values or []) if str(v).strip()]
    return ", ".join(items) if items else "(none specified)"


def candidate_state(profile: CandidateProfile) -> str:
    """A compact candidate summary — shared by every job's state."""
    years = profile.years_experience if profile.years_experience is not None else "unknown"
    resume = (profile.resume_text or "").strip()[:MAX_RESUME_CHARS]
    return (
        f"Years of experience: {years}. Domain: {profile.domain or 'unknown'}. "
        f"Skills: {_join(profile.skills_json)}. "
        f"Desired roles: {_join(profile.desired_roles_json)}. "
        f"Preferred locations: {_join(profile.preferred_locations_json)}.\n"
        f"Résumé excerpt: {resume}"
    )


def job_state(job: Job) -> str:
    description = (job.effective_description or "").strip()[:MAX_DESCRIPTION_CHARS]
    return (
        f"Title: {job.title}. Company: {job.company}. Location: {job.location or 'unknown'}. "
        f"Skills: {_join(job.skills_json)}.\n"
        f"Description: {description or '(none)'}"
    )


@dataclass
class SemanticFilterReport:
    """What the gate decided, surfaced in `runs.source_counts`."""

    considered: int = 0
    kept: int = 0
    dropped: int = 0
    errors: int = 0
    dropped_jobs: list[dict[str, Any]] = field(default_factory=list)

    @property
    def as_dict(self) -> dict:
        return {
            "considered": self.considered,
            "kept": self.kept,
            "dropped": self.dropped,
            "errors": self.errors,
            "dropped_jobs": self.dropped_jobs[:MAX_DROPPED_LISTED],
        }


def semantic_filter(
    profile: CandidateProfile,
    jobs: list[Job],
    *,
    scorer: FitScorer,
    min_fit: float,
) -> tuple[list[Job], SemanticFilterReport]:
    """Keep jobs whose fit probability is >= `min_fit`, preserving input order.

    A job whose call fails is kept (fail open) and counted in `errors`.
    """
    report = SemanticFilterReport(considered=len(jobs))
    candidate = candidate_state(profile)
    keep: list[Job] = []
    consecutive_errors = 0

    for job in jobs:
        if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
            report.errors += 1
            keep.append(job)
            continue
        try:
            fit = scorer({"candidate": candidate, "job": job_state(job)})
        except DecisionError as exc:
            report.errors += 1
            consecutive_errors += 1
            logger.warning("semantic filter: keeping job %s, call failed: %s", job.id, exc)
            if consecutive_errors == MAX_CONSECUTIVE_ERRORS:
                logger.warning("semantic filter: giving up after repeated failures; keeping all")
            keep.append(job)
            continue
        consecutive_errors = 0
        if fit >= min_fit:
            keep.append(job)
        else:
            report.dropped_jobs.append(
                {"job_id": job.id, "title": job.title, "company": job.company, "fit": round(fit, 3)}
            )

    report.kept = len(keep)
    report.dropped = report.considered - report.kept
    if report.dropped:
        logger.info(
            "semantic filter: kept %d/%d (dropped %d below fit %.2f): %s",
            report.kept,
            report.considered,
            report.dropped,
            min_fit,
            "; ".join(f"{d['title']} @ {d['company']} ({d['fit']})" for d in report.dropped_jobs),
        )
    return keep, report
