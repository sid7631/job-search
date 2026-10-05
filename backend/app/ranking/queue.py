"""The triage queue behind the Today page.

The latest run's matches, minus everything you have already acted on, minus your
exclude list, with near-identical postings collapsed into one item. Big employers
post the same role many times ("Java Full Stack Developer - Pan India", "... MK",
"... (React)"); triaging each copy separately is the busywork this removes.

Triage turns a decision into an `Application` row, so it flows into the same
feedback loop the Pipeline board already feeds:
- save    -> SAVED
- apply   -> APPLIED (stamps `applied_at`)
- dismiss -> DROPPED with a reason the ranker learns from

Acting on an item applies to its collapsed duplicates too: dismissing dismisses them
all with the same reason; saving or applying marks the copies DROPPED/"duplicate",
which the feedback loop ignores.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from rapidfuzz.fuzz import token_set_ratio
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.database import repository as repo
from app.database.models import DISMISS_REASONS, Application, ApplicationStatus, JobMatch
from app.ranking.prefilter import is_excluded

TriageAction = Literal["save", "apply", "dismiss"]

# Titles at the same company this similar are treated as one role.
SIMILAR_TITLE_THRESHOLD = 85

_NOISE_RE = re.compile(r"[^a-z0-9+#. ]+")
_COMPANY_SUFFIX_RE = re.compile(
    r"\b(pvt|private|ltd|limited|inc|llp|technologies|technology|services|solutions)\b"
)


def _norm_company(company: str | None) -> str:
    text = _NOISE_RE.sub(" ", (company or "").lower())
    return " ".join(_COMPANY_SUFFIX_RE.sub(" ", text).split())


def _norm_title(title: str | None) -> str:
    return " ".join(_NOISE_RE.sub(" ", (title or "").lower()).split())


@dataclass
class QueueItem:
    """One role to triage: the best-scoring posting plus its collapsed copies."""

    lead: JobMatch
    similar: list[JobMatch] = field(default_factory=list)

    @property
    def job_ids(self) -> list[int]:
        return [self.lead.job_id] + [m.job_id for m in self.similar]


@dataclass
class Queue:
    items: list[QueueItem]
    #: Matches in the run before anything was hidden.
    total_matches: int = 0
    #: Already acted on (tracked or dismissed).
    triaged: int = 0
    #: Hidden by the exclude list.
    excluded: int = 0
    run_id: int | None = None


def _group(matches: list[JobMatch]) -> list[QueueItem]:
    """Collapse same-company, near-identical titles. Input must be best-first."""
    items: list[QueueItem] = []
    by_company: dict[str, list[QueueItem]] = {}
    for match in matches:
        company = _norm_company(match.job.company)
        title = _norm_title(match.job.title)
        bucket = by_company.setdefault(company, [])
        for item in bucket:
            if token_set_ratio(title, _norm_title(item.lead.job.title)) >= SIMILAR_TITLE_THRESHOLD:
                item.similar.append(match)
                break
        else:
            item = QueueItem(lead=match)
            bucket.append(item)
            items.append(item)
    return items


def build_queue(session: Session, *, exclude_terms: list[str] | None = None) -> Queue:
    """The latest run's untriaged matches, grouped, best first."""
    latest = repo.get_latest_run_with_matches(session)
    if latest is None:
        return Queue(items=[])
    matches = repo.get_today_matches(session, run_id=latest.id)
    acted = {a.job_id for a in repo.list_applications(session)}

    pending: list[JobMatch] = []
    triaged = excluded = 0
    for match in matches:
        if match.job_id in acted:
            triaged += 1
        elif is_excluded(match.job.title, exclude_terms or []):
            excluded += 1
        else:
            pending.append(match)

    return Queue(
        items=_group(pending),
        total_matches=len(matches),
        triaged=triaged,
        excluded=excluded,
        run_id=latest.id,
    )


def triage(
    session: Session,
    *,
    job_id: int,
    action: TriageAction,
    reason: str | None = None,
    similar_ids: list[int] | None = None,
) -> list[Application]:
    """Record a triage decision for a job and its collapsed duplicates."""
    if action == "dismiss":
        if reason is not None and reason not in DISMISS_REASONS:
            raise ValueError(f"unknown dismiss reason '{reason}'")
        reason = reason or "other"
        status = ApplicationStatus.DROPPED
    elif action == "save":
        status = ApplicationStatus.SAVED
    elif action == "apply":
        status = ApplicationStatus.APPLIED
    else:
        raise ValueError(f"unknown triage action '{action}'")

    created = [
        repo.create_application(
            session,
            job_id=job_id,
            status=status,
            dismiss_reason=reason if action == "dismiss" else None,
        )
    ]
    for other in similar_ids or []:
        if other == job_id:
            continue
        created.append(
            repo.create_application(
                session,
                job_id=other,
                status=ApplicationStatus.DROPPED,
                dismiss_reason=reason if action == "dismiss" else "duplicate",
            )
        )
    return created


def undo_triage(session: Session, job_ids: list[int]) -> int:
    """Forget triage decisions so the jobs return to the queue. Returns rows removed."""
    if not job_ids:
        return 0
    result = session.execute(delete(Application).where(Application.job_id.in_(job_ids)))
    session.flush()
    return result.rowcount or 0
