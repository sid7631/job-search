"""MCP server: lets Claude read and act on your job hunt.

Exposes the same data the dashboard shows — profile, triage queue, job details,
tracked applications, runs — as MCP tools, so Claude (Desktop or Code) can:

- sync application statuses from Gmail through Claude's own Gmail connector, with
  no Google Cloud project or API keys on this side,
- prepare you for an application or interview from the posting and your résumé,
- review what is working across your applications.

It talks to the SQLite database directly (no need for `serve-api` to be running)
and speaks MCP over stdio. Register it with Claude Code via the repo's `.mcp.json`,
or in Claude Desktop with:

    {"mcpServers": {"job-hunter": {"command": "uv", "args":
      ["--directory", "/path/to/job-search/backend", "run", "python", "-m",
       "app.mcp_server"]}}}

Never write to stdout here: it carries the MCP protocol.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from rapidfuzz import fuzz
from sqlalchemy import select

from app.database import connection
from app.database import repository as repo
from app.database.models import DISMISS_REASONS, Application, ApplicationStatus, Job
from app.ranking import queue as triage_queue
from app.ranking.prefilter import parse_exclude_terms
from app.runtime_config import effective_settings

logging.basicConfig(stream=sys.stderr, level=logging.WARNING)

BACKEND_DIR = Path(__file__).resolve().parents[1]
MAX_DESCRIPTION_CHARS = 8_000

READ = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)

server = MCPServer(
    name="job-hunter",
    title="Job Hunter",
    instructions=(
        "The user's personal job-search tracker. Jobs are scraped daily from Naukri and "
        "LinkedIn and scored 0-100 against their résumé. Applications move through "
        "SAVED -> APPLIED -> INTERVIEWING -> OFFER, or end as REJECTED (company's "
        "decision) or DROPPED (user passed). Confirm with the user before changing an "
        "application's status based on an inference (e.g. from an email)."
    ),
)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _job_summary(job: Job | None) -> dict[str, Any] | None:
    if job is None:
        return None
    return {
        "job_id": job.id,
        "title": job.title,
        "company": job.company,
        "location": job.location,
        "url": job.url,
        "source": job.source,
    }


def _application(app: Application) -> dict[str, Any]:
    return {
        "application_id": app.id,
        "status": app.status.value,
        "applied_at": _iso(app.applied_at),
        "updated_at": _iso(app.updated_at),
        "dismiss_reason": app.dismiss_reason,
        "notes": app.notes,
        "job": _job_summary(app.job),
    }


# ----------------------------------------------------------------------- read


@server.tool(annotations=READ)
def get_profile() -> dict[str, Any]:
    """The candidate's parsed résumé profile: experience, skills, roles, résumé text."""
    with connection.session_scope() as session:
        p = repo.get_candidate_profile(session)
        if p is None:
            return {"error": "No résumé uploaded yet. Upload one in the dashboard."}
        return {
            "name": p.name,
            "years_experience": p.years_experience,
            "domain": p.domain,
            "skills": p.skills_json or [],
            "desired_roles": p.desired_roles_json or [],
            "preferred_locations": p.preferred_locations_json or [],
            "resume_text": p.resume_text,
        }


@server.tool(annotations=READ)
def get_queue(limit: int = 20) -> dict[str, Any]:
    """Untriaged roles from the latest run, best match first, duplicates grouped.

    Each item has the score, the AI's one-line reason, pros/cons and the ids of
    near-identical postings at the same company (`similar_job_ids`).
    """
    with connection.session_scope() as session:
        settings = effective_settings(session)
        q = triage_queue.build_queue(
            session, exclude_terms=parse_exclude_terms(settings.exclude_keywords)
        )
        items = [
            {
                **_job_summary(item.lead.job),
                "score": item.lead.score,
                "reason": item.lead.reason,
                "pros": item.lead.pros_json or [],
                "cons": item.lead.cons_json or [],
                "similar_job_ids": [m.job_id for m in item.similar],
            }
            for item in q.items[: max(1, limit)]
        ]
        return {
            "remaining": len(q.items),
            "already_triaged": q.triaged,
            "hidden_by_exclude_list": q.excluded,
            "items": items,
        }


@server.tool(annotations=READ)
def get_job(job_id: int) -> dict[str, Any]:
    """Full posting text, skills, the latest AI score with pros/cons, and tracking status."""
    with connection.session_scope() as session:
        job = session.get(Job, job_id)
        if job is None:
            return {"error": f"No job with id {job_id}."}
        match = repo.get_latest_match_for_job(session, job_id)
        app = repo.get_application_for_job(session, job_id)
        description = job.effective_description or ""
        return {
            **_job_summary(job),
            "skills": job.skills_json or [],
            "description": description[:MAX_DESCRIPTION_CHARS],
            "description_is_full_posting": bool(job.detail_text),
            "score": match.score if match else None,
            "reason": match.reason if match else None,
            "pros": (match.pros_json or []) if match else [],
            "cons": (match.cons_json or []) if match else [],
            "application": _application(app) if app else None,
        }


@server.tool(annotations=READ)
def list_applications(
    status: Literal["SAVED", "APPLIED", "INTERVIEWING", "REJECTED", "OFFER", "DROPPED"]
    | None = None,
) -> list[dict[str, Any]]:
    """Tracked applications, most recently updated first, optionally by status."""
    with connection.session_scope() as session:
        return [_application(a) for a in repo.list_applications(session, status=status)]


@server.tool(annotations=READ)
def find_applications(company: str, title: str | None = None, limit: int = 5) -> list[dict]:
    """Fuzzy-find tracked applications by company (and optionally job title).

    Use this to match an email from a recruiter or ATS ("Your application to Acme
    Corp…") to the right application. Results include a 0-100 `match` confidence;
    treat anything under ~80 as uncertain and ask the user.
    """
    with connection.session_scope() as session:
        scored = []
        for app in repo.list_applications(session):
            job = app.job
            if job is None:
                continue
            score = fuzz.WRatio(company.lower(), (job.company or "").lower())
            if title:
                score = 0.7 * score + 0.3 * fuzz.token_set_ratio(
                    title.lower(), (job.title or "").lower()
                )
            scored.append((score, app))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [{"match": round(s), **_application(a)} for s, a in scored[: max(1, limit)]]


@server.tool(annotations=READ)
def application_stats() -> dict[str, Any]:
    """Funnel numbers for a progress review: counts by status, response rate,
    why jobs were passed on, and which companies and sources have responded."""
    with connection.session_scope() as session:
        apps = repo.list_applications(session)
        by_status = Counter(a.status.value for a in apps)
        sent = [a for a in apps if a.applied_at is not None]
        responded = [
            a
            for a in sent
            if a.status
            in (ApplicationStatus.INTERVIEWING, ApplicationStatus.OFFER, ApplicationStatus.REJECTED)
        ]
        engaged = (ApplicationStatus.INTERVIEWING, ApplicationStatus.OFFER)
        reasons = Counter(
            DISMISS_REASONS.get(a.dismiss_reason, a.dismiss_reason)
            for a in apps
            if a.dismiss_reason and a.dismiss_reason != "duplicate"
        )
        return {
            "by_status": dict(by_status),
            "applications_sent": len(sent),
            "responses": len(responded),
            "response_rate": round(len(responded) / len(sent), 2) if sent else None,
            "interviews_by_source": dict(
                Counter(
                    a.job.source
                    for a in apps
                    if a.job and a.status in engaged
                )
            ),
            "pass_reasons": dict(reasons.most_common()),
            "awaiting_reply": [
                _application(a) for a in apps if a.status == ApplicationStatus.APPLIED
            ],
        }


@server.tool(annotations=READ)
def run_status() -> dict[str, Any]:
    """The pipeline run in progress (with live stage), and the last finished one."""
    with connection.session_scope() as session:
        active = repo.get_active_run(session)
        finished = [r for r in repo.list_runs(session, limit=5) if r.status != "RUNNING"]

        def view(run):
            return {
                "run_id": run.id,
                "status": run.status,
                "started_at": _iso(run.started_at),
                "finished_at": _iso(run.finished_at),
                "progress": run.progress_json or {},
                "counts": run.source_counts_json or {},
                "source_errors": run.source_errors_json or {},
                "error": run.error_text,
            }

        return {
            "active": view(active) if active else None,
            "last": view(finished[0]) if finished else None,
        }


# ---------------------------------------------------------------------- write


@server.tool(annotations=WRITE)
def triage_job(
    job_id: int,
    action: Literal["save", "apply", "dismiss"],
    reason: Literal["wrong_stack", "too_junior", "too_senior", "location", "company", "other"]
    | None = None,
    similar_job_ids: list[int] | None = None,
) -> dict[str, Any]:
    """Record a decision on a queue item, exactly like the dashboard's Today page.

    `dismiss` takes a reason, which teaches the ranker. Pass the item's
    `similar_job_ids` so its duplicates follow the decision.
    """
    with connection.session_scope() as session:
        if session.get(Job, job_id) is None:
            return {"error": f"No job with id {job_id}."}
        apps = triage_queue.triage(
            session, job_id=job_id, action=action, reason=reason, similar_ids=similar_job_ids
        )
        return {"recorded": [_application(a) for a in apps]}


@server.tool(annotations=WRITE)
def update_application(
    application_id: int,
    status: Literal["SAVED", "APPLIED", "INTERVIEWING", "REJECTED", "OFFER", "DROPPED"]
    | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    """Move an application to a new status and/or add a dated note.

    Notes are appended (never overwritten), stamped with today's date, so the
    history of what happened stays readable — e.g. "Interview invite from Priya,
    Thu 10am (via Gmail)".
    """
    with connection.session_scope() as session:
        app = session.get(Application, application_id)
        if app is None:
            return {"error": f"No application with id {application_id}."}
        notes = None
        if note:
            stamp = datetime.now(UTC).strftime("%Y-%m-%d")
            line = f"[{stamp}] {note.strip()}"
            notes = f"{app.notes.rstrip()}\n{line}" if app.notes else line
        repo.update_application_status(session, application_id, status=status, notes=notes)
        return _application(app)


@server.tool(annotations=WRITE)
def track_job(
    job_id: int,
    status: Literal["SAVED", "APPLIED", "INTERVIEWING", "REJECTED", "OFFER"] = "APPLIED",
) -> dict[str, Any]:
    """Start tracking a job that is in the database but not yet tracked
    (e.g. an email shows the user applied to something they never triaged)."""
    with connection.session_scope() as session:
        if session.get(Job, job_id) is None:
            return {"error": f"No job with id {job_id}."}
        return _application(repo.create_application(session, job_id=job_id, status=status))


@server.tool(annotations=READ)
def search_jobs(query: str, limit: int = 10) -> list[dict[str, Any]]:
    """Find jobs in the database by company or title (tracked or not)."""
    q = query.lower()
    with connection.session_scope() as session:
        jobs = list(session.scalars(select(Job)))
        scored = sorted(
            (
                (max(fuzz.WRatio(q, j.company.lower()), fuzz.WRatio(q, j.title.lower())), j)
                for j in jobs
            ),
            key=lambda pair: pair[0],
            reverse=True,
        )
        return [{"match": round(s), **_job_summary(j)} for s, j in scored[: max(1, limit)]]


@server.tool(annotations=WRITE)
def start_run() -> dict[str, Any]:
    """Start a pipeline run (scrape, dedupe, score) in the background.

    A browser window opens on the user's Mac for the scrape. Check progress with
    `run_status`. Refuses if a run is already going.
    """
    with connection.session_scope() as session:
        active = repo.get_active_run(session)
        if active is not None:
            return {"started": False, "reason": f"Run #{active.id} is already in progress."}
    log_dir = BACKEND_DIR / "logs"
    log_dir.mkdir(exist_ok=True)
    with open(log_dir / "mcp-run.log", "ab") as log:
        subprocess.Popen(  # noqa: S603 - fixed argv, no user input
            [sys.executable, "-m", "app.main", "run-pipeline"],
            cwd=BACKEND_DIR,
            stdout=log,
            stderr=log,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
    return {"started": True, "hint": "Poll run_status for progress."}


def main() -> None:
    server.run("stdio")


if __name__ == "__main__":
    main()
