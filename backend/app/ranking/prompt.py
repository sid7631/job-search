"""Ranking prompt + the structured output contract (M5).

`build_ranking_prompt` assembles the candidate profile and a job into a prompt that
*requires* JSON output `{ score: 0-100, pros: [], cons: [], reason: "" }`. That shape
is also the `RankingResult` pydantic schema every LLM response is validated against.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.database.models import CandidateProfile, Job


class RankingResult(BaseModel):
    """The structured judgement the LLM must return for a single job."""

    score: int = Field(ge=0, le=100)
    pros: list[str] = Field(default_factory=list)
    cons: list[str] = Field(default_factory=list)
    reason: str = ""


def _bullets(values: list | None) -> str:
    items = [str(v) for v in (values or []) if str(v).strip()]
    return ", ".join(items) if items else "(none specified)"


def build_ranking_prompt(profile: CandidateProfile, job: Job) -> str:
    """Build the ranking prompt for one candidate/job pair (requires JSON output)."""
    years = profile.years_experience if profile.years_experience is not None else "(unknown)"
    return (
        "You are a meticulous technical recruiter scoring how well a single job "
        "matches a candidate. Judge holistically on skills, seniority/experience, "
        "domain, and location fit.\n\n"
        "Return ONLY a JSON object (no prose, no markdown) with exactly these keys:\n"
        '  "score": integer 0-100 (overall match; 100 = perfect fit),\n'
        '  "pros": array of short strings (why it fits),\n'
        '  "cons": array of short strings (gaps or mismatches),\n'
        '  "reason": string (one or two sentences summarising the score).\n\n'
        "=== CANDIDATE ===\n"
        f"Name: {profile.name or '(unknown)'}\n"
        f"Years of experience: {years}\n"
        f"Primary domain: {profile.domain or '(unknown)'}\n"
        f"Skills: {_bullets(profile.skills_json)}\n"
        f"Desired roles: {_bullets(profile.desired_roles_json)}\n"
        f"Preferred locations: {_bullets(profile.preferred_locations_json)}\n\n"
        "=== JOB ===\n"
        f"Title: {job.title}\n"
        f"Company: {job.company}\n"
        f"Location: {job.location or '(unspecified)'}\n"
        f"Skills: {_bullets(job.skills_json)}\n"
        f"Description:\n{job.description or '(no description provided)'}\n"
    )
