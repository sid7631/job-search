"""Ranking prompt + the structured output contract (M5).

`build_ranking_prompt` assembles the candidate profile and a job into a prompt that
*requires* JSON output `{ score: 0-100, pros: [], cons: [], reason: "" }`. That shape
is also the `RankingResult` pydantic schema every LLM response is validated against.

The prompt carries both the *structured* profile (a cheap distillation small models
lean on) and the *full résumé text*, so the ranker can weigh context no extracted
field captures: project scale, tenure pattern, seniority of the actual work.

`ranking_cache_key` defines when a judgement may be reused. It covers everything the
prompt is built from — job, résumé, model, prompt version — because a cache keyed on
the job alone would keep serving scores computed against a résumé you have replaced.
"""

from __future__ import annotations

import hashlib
import json

from pydantic import BaseModel, Field

from app.database.models import CandidateProfile, Job

# Bump when the wording below changes enough to invalidate stored judgements.
PROMPT_VERSION = "3"

# The résumé is repeated on every job's prompt, so it dominates token cost on a big
# run. A few thousand characters covers a normal résumé; the tail of a very long one
# is the least relevant part (oldest roles).
MAX_RESUME_CHARS_IN_PROMPT = 6_000


class RankingResult(BaseModel):
    """The structured judgement the LLM must return for a single job."""

    score: int = Field(ge=0, le=100)
    pros: list[str] = Field(default_factory=list)
    cons: list[str] = Field(default_factory=list)
    reason: str = ""


def _bullets(values: list | None) -> str:
    items = [str(v) for v in (values or []) if str(v).strip()]
    return ", ".join(items) if items else "(none specified)"


def _resume_excerpt(profile: CandidateProfile) -> str:
    """The résumé text as sent to the ranker, truncated to a sane prompt budget."""
    text = (profile.resume_text or "").strip()
    return text[:MAX_RESUME_CHARS_IN_PROMPT]


def profile_fingerprint(profile: CandidateProfile) -> str:
    """Hash of every candidate input the prompt uses.

    Changing the résumé (or anything parsed out of it) must produce a different
    fingerprint, so stale judgements fall out of the cache instead of persisting.
    """
    payload = json.dumps(
        {
            "name": profile.name,
            "years": profile.years_experience,
            "domain": profile.domain,
            "skills": sorted(profile.skills_json or []),
            "roles": sorted(profile.desired_roles_json or []),
            "locations": sorted(profile.preferred_locations_json or []),
            "resume": _resume_excerpt(profile),
        },
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def ranking_cache_key(
    job: Job, *, profile_fp: str, model: str | None, feedback_fp: str = ""
) -> str:
    """Key a cached judgement by everything that can change it.

    `job.content_hash` identifies the *posting* (title/company/location) and is what
    de-duplication runs on; it deliberately ignores the description. Ranking does
    read the description and skills, so they are folded in here — otherwise a job
    that the enrich stage just gave a real description to would keep the score it
    got from its one-line card summary.
    """
    basis = "|".join(
        [
            PROMPT_VERSION,
            job.content_hash,
            hashlib.sha256((job.effective_description or "").encode("utf-8")).hexdigest(),
            ",".join(sorted(str(s) for s in (job.skills_json or []))),
            profile_fp,
            model or "",
            feedback_fp,
        ]
    )
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def build_ranking_prompt(profile: CandidateProfile, job: Job, *, feedback_block: str = "") -> str:
    """Build the ranking prompt for one candidate/job pair (requires JSON output)."""
    years = profile.years_experience if profile.years_experience is not None else "(unknown)"
    resume = _resume_excerpt(profile)
    return (
        "You are a meticulous technical recruiter scoring how well a single job "
        "matches a candidate. Judge holistically on skills, seniority/experience, "
        "domain, and location fit.\n\n"
        "Return ONLY a JSON object (no prose, no markdown) with exactly these keys:\n"
        '  "score": integer 0-100 (overall match; 100 = perfect fit),\n'
        '  "pros": array of short strings (why it fits),\n'
        '  "cons": array of short strings (gaps or mismatches),\n'
        '  "reason": string (one or two sentences summarising the score).\n\n'
        f"{feedback_block}"
        "=== CANDIDATE ===\n"
        f"Name: {profile.name or '(unknown)'}\n"
        f"Years of experience: {years}\n"
        f"Primary domain: {profile.domain or '(unknown)'}\n"
        f"Skills: {_bullets(profile.skills_json)}\n"
        f"Desired roles: {_bullets(profile.desired_roles_json)}\n"
        f"Preferred locations: {_bullets(profile.preferred_locations_json)}\n\n"
        "=== CANDIDATE RESUME (full text) ===\n"
        f"{resume or '(resume text unavailable — judge on the summary above)'}\n\n"
        "=== JOB ===\n"
        f"Title: {job.title}\n"
        f"Company: {job.company}\n"
        f"Location: {job.location or '(unspecified)'}\n"
        f"Skills: {_bullets(job.skills_json)}\n"
        f"Description:\n{job.effective_description or '(no description provided)'}\n"
    )
