"""Taste feedback for the ranker (M11).

Every job you track carries a judgement the ranker never saw: applying to something
is a stronger endorsement than the résumé alone can express, and dropping something
says the score was wrong. This module turns those tracked decisions into a compact
block of examples for the ranking prompt.

Only *your* actions count as signal. `REJECTED` is the company's decision, not yours,
so it is ignored — you presumably still wanted that job.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.database import repository as repo
from app.database.models import DISMISS_REASONS, ApplicationStatus

# Your actions, split by what they say about the *job*, not about the outcome.
_POSITIVE = (ApplicationStatus.APPLIED, ApplicationStatus.INTERVIEWING, ApplicationStatus.OFFER)
_NEGATIVE = (ApplicationStatus.DROPPED,)


@dataclass
class Feedback:
    """Recent tracked decisions, ready to render into a prompt."""

    liked: list[str] = field(default_factory=list)
    disliked: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.liked or self.disliked)

    def fingerprint(self) -> str:
        """Stable representation, so changed feedback invalidates cached judgements."""
        return "|".join(["+" + t for t in self.liked] + ["-" + t for t in self.disliked])


def _label(application) -> str | None:
    job = application.job
    if job is None:
        return None
    location = f", {job.location}" if job.location else ""
    return f"{job.title} at {job.company}{location}"


def load_feedback(session: Session, *, limit: int = 8) -> Feedback:
    """Read the most recently updated tracked applications into a `Feedback`.

    `limit` applies per side, keeping the block small — it is prepended to every
    job's prompt, so it must stay cheap.
    """
    feedback = Feedback()
    if limit <= 0:
        return feedback

    # `list_applications` is already newest-updated first.
    for application in repo.list_applications(session):
        status = application.status
        bucket = (
            feedback.liked
            if status in _POSITIVE
            else feedback.disliked
            if status in _NEGATIVE
            else None
        )
        if bucket is None or len(bucket) >= limit:
            continue
        # A duplicate was dismissed because you acted on its twin, not on taste.
        if application.dismiss_reason == "duplicate":
            continue
        label = _label(application)
        if label and application.dismiss_reason in DISMISS_REASONS:
            label = f"{label} (reason: {DISMISS_REASONS[application.dismiss_reason]})"
        if label and label not in bucket:
            bucket.append(label)
    return feedback


def render_feedback(feedback: Feedback) -> str:
    """Render the feedback block for the ranking prompt (empty string if none)."""
    if not feedback:
        return ""
    lines = ["=== CANDIDATE'S PAST DECISIONS (learn their taste) ==="]
    if feedback.liked:
        lines.append("Applied to / pursued — score similar roles higher:")
        lines += [f"  + {t}" for t in feedback.liked]
    if feedback.disliked:
        lines.append("Saw and deliberately passed on — score similar roles lower:")
        lines += [f"  - {t}" for t in feedback.disliked]
    lines.append(
        "Treat these as preference signal, not as hard rules; the résumé and the "
        "job description still decide the score."
    )
    return "\n".join(lines) + "\n\n"
