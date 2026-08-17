"""Deterministic pre-filter that runs *before* the LLM (M11).

The LLM is the expensive step — one call per uncached job, and on a local model that
is seconds each. This module scores every job with cheap, explainable string work and
hands the ranker a shortlist, so the model spends its budget on plausible roles.

**This is a filter, not a scorer.** The pre-filter score never contributes to the
match score shown in the UI — that remains the LLM's judgement alone (see
`ranking_service`). Mixing the two would double-count the same signals.

Shortlisting is deliberately generous: it drops the obvious mismatches (a Cardiology
Nurse role in a backend engineer's feed) rather than trying to pick winners.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from app.database.models import CandidateProfile, Job

logger = logging.getLogger(__name__)

# Title words that signal a seniority mismatch for an experienced candidate.
_JUNIOR_MARKERS = ("intern", "internship", "trainee", "fresher", "graduate", "apprentice")

_WORD_RE = re.compile(r"[a-z0-9+#.]+")


def _tokens(text: str | None) -> set[str]:
    return set(_WORD_RE.findall((text or "").lower()))


@dataclass
class PrefilterScore:
    """One job's cheap relevance score, with the reason kept for the run log."""

    job_id: int
    score: float
    reason: str


@dataclass
class PrefilterReport:
    """What the pre-filter decided, surfaced in `runs.source_counts`."""

    considered: int = 0
    shortlisted: int = 0
    dropped: int = 0

    @property
    def as_dict(self) -> dict:
        return {
            "considered": self.considered,
            "shortlisted": self.shortlisted,
            "dropped": self.dropped,
        }


def score_job(profile: CandidateProfile, job: Job) -> PrefilterScore:
    """Score one job 0-100 on title, skill and location overlap with the profile.

    Pure and deterministic — no LLM, no I/O.
    """
    title_tokens = _tokens(job.title)
    profile_skills = {s.lower() for s in (profile.skills_json or []) if s}
    job_skills = {str(s).lower() for s in (job.skills_json or []) if s}
    text_tokens = title_tokens | _tokens(job.effective_description)

    reasons: list[str] = []
    score = 0.0

    # 1. Desired-role overlap — the strongest cheap signal we have.
    role_words: set[str] = set()
    for role in profile.desired_roles_json or []:
        role_words |= _tokens(role)
    role_words -= {"engineer", "developer", "senior", "staff", "lead"}  # too generic alone
    if role_words:
        hit = len(role_words & title_tokens)
        if hit:
            score += min(40.0, 20.0 * hit)
            reasons.append(f"title matches desired role ({hit})")

    # 2. Domain in the title (e.g. "backend" for a backend candidate).
    domain_words = _tokens(profile.domain) - {"stack"}
    if domain_words and domain_words & title_tokens:
        score += 15.0
        reasons.append("title matches domain")

    # 3. Skill overlap, counted against title + description so a rich posting wins.
    if profile_skills:
        overlap = {s for s in profile_skills if s in job_skills or s in text_tokens}
        if overlap:
            share = len(overlap) / len(profile_skills)
            score += min(35.0, 70.0 * share)
            reasons.append(f"{len(overlap)} skill overlap")

    # 4. Location preference.
    location_words = set()
    for loc in profile.preferred_locations_json or []:
        location_words |= _tokens(loc)
    location_words -= {"india"}  # matches nearly everything in this market
    if location_words:
        job_loc = _tokens(job.location)
        if location_words & job_loc or "remote" in job_loc:
            score += 10.0
            reasons.append("location matches")

    # 5. Penalise clear seniority mismatches for an experienced candidate.
    years = profile.years_experience or 0
    penalised = years >= 4 and any(marker in title_tokens for marker in _JUNIOR_MARKERS)
    if penalised:
        score -= 40.0
        reasons.append("junior/intern role")

    # An unscored job is not necessarily bad — it may simply be a thin card we have
    # not enriched yet — so give it a floor that keeps it reachable by the LLM. A
    # job we actively penalised is different: it must stay below the neutral ones,
    # or the penalty is erased and ranks it alongside an unknown.
    if score <= 0:
        score = 0.0 if penalised else 5.0
        if not penalised:
            reasons.append("no strong signal (floor)")

    return PrefilterScore(
        job_id=job.id, score=min(100.0, score), reason="; ".join(reasons) or "no signal"
    )


def shortlist(
    profile: CandidateProfile,
    jobs: list[Job],
    *,
    max_jobs: int,
    min_score: float,
) -> tuple[list[Job], PrefilterReport]:
    """Return the jobs worth spending an LLM call on, best cheap-score first.

    `max_jobs <= 0` disables the cap; `min_score <= 0` disables the threshold. With
    both disabled the pre-filter is a no-op pass-through (but still ordered), which
    is the escape hatch if it ever hides something it should not.
    """
    report = PrefilterReport(considered=len(jobs))
    if not jobs:
        return [], report

    scored = sorted((score_job(profile, job) for job in jobs), key=lambda s: s.score, reverse=True)
    if min_score > 0:
        scored = [s for s in scored if s.score >= min_score]
    if max_jobs > 0:
        scored = scored[:max_jobs]

    by_id = {job.id: job for job in jobs}
    keep = [by_id[s.job_id] for s in scored if s.job_id in by_id]
    report.shortlisted = len(keep)
    report.dropped = report.considered - report.shortlisted

    if report.dropped:
        logger.info(
            "prefilter: %d/%d jobs shortlisted (dropped %d below the bar)",
            report.shortlisted,
            report.considered,
            report.dropped,
        )
    return keep, report
