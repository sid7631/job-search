"""CLI entrypoints for the AI Job Hunter.

Run `python -m app.main --help` to see the available commands:

    parse-resume      Parse a PDF/DOCX resume into the single candidate_profile row.
    collect           Run a single source collector once (manual collect run).
    notify-test       Send a test message to Telegram (sample picks or failure alert).
    run-pipeline      Run the daily collect → normalize → dedup → rank → notify pipeline once.
    serve-api         Start the FastAPI JSON API that the React dashboard consumes.
    start-scheduler   Start the in-process APScheduler daemon that fires the pipeline daily.

All commands are implemented: `parse-resume` (M2), `collect` (M3), `notify-test`
(M7), `run-pipeline` / `start-scheduler` (M6), and `serve-api` (M8).
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence


def _cmd_parse_resume(args: argparse.Namespace) -> int:
    """Parse a resume into the single candidate_profile row (idempotent)."""
    # Imported lazily so `--help` and the stub commands stay light.
    from app.database.connection import session_scope
    from app.profiles.resume_parser import ResumeParseError, parse_resume

    try:
        with session_scope() as session:
            profile = parse_resume(session, args.path)
            summary = (
                f"[parse-resume] profile #{profile.id} updated: "
                f"name={profile.name!r}, years={profile.years_experience}, "
                f"skills={len(profile.skills_json)}, roles={len(profile.desired_roles_json)}."
            )
    except ResumeParseError as exc:
        print(f"[parse-resume] failed: {exc}", file=sys.stderr)
        return 1
    print(summary)
    return 0


def _cmd_collect(args: argparse.Namespace) -> int:
    """Run one source collector under a fresh run (manual collect run, M3/M10)."""
    from app.collectors.linkedin import LinkedInCollector
    from app.collectors.naukri import NaukriCollector
    from app.database import repository as repo
    from app.database.connection import session_scope
    from app.database.models import Run, RunStatus
    from app.runtime_config import effective_settings

    # Effective settings, not raw `.env`: the search terms may be derived from the
    # résumé or overridden on the Settings page, and a bare `.env` read loses both.
    with session_scope() as session:
        settings = effective_settings(session)

    collectors = {"naukri": NaukriCollector, "linkedin": LinkedInCollector}
    collector = collectors[args.source](settings=settings)

    with session_scope() as session:
        run_id = repo.start_run(session).id

    saved = collector.collect(run_id)

    with session_scope() as session:
        run = session.get(Run, run_id)
        error = run.error_text or "; ".join(
            f"{k}: {v}" for k, v in (run.source_errors_json or {}).items()
        )
        repo.finish_run(
            session,
            run_id,
            status=RunStatus.FAILED if error else RunStatus.SUCCESS,
            source_counts={args.source: len(saved)},
        )

    print(f"[collect] run #{run_id}: {args.source} saved {len(saved)} raw job(s).")
    if error:
        print(f"[collect] run recorded an error: {error.strip()}", file=sys.stderr)
        return 1
    return 0


def _cmd_notify_test(args: argparse.Namespace) -> int:
    """Send a test message to Telegram (M7): sample picks, or a failure alert."""
    from app.notifications.telegram import TelegramError, TelegramNotifier

    notifier = TelegramNotifier()
    try:
        if args.failure:
            notifier.notify_failure(0, "Test failure alert from `notify-test`.")
            print("[notify-test] failure alert sent to Telegram.")
        else:
            notifier.send_sample()
            print("[notify-test] sample picks message sent to Telegram.")
    except TelegramError as exc:
        print(f"[notify-test] failed: {exc}", file=sys.stderr)
        return 1
    return 0


def _cmd_run_pipeline(args: argparse.Namespace) -> int:
    """Trigger a single end-to-end pipeline run (M6)."""
    from app.scheduler.pipeline import run_pipeline

    result = run_pipeline()
    print(f"[run-pipeline] run #{result.run_id} {result.status}: {result.source_counts}")
    if result.status != "SUCCESS":
        print(f"[run-pipeline] error: {result.error}", file=sys.stderr)
        return 1
    return 0


def _cmd_serve_api(args: argparse.Namespace) -> int:
    """Serve the FastAPI JSON API (M8). Docs at /docs."""
    import uvicorn

    print(f"[serve-api] serving on http://{args.host}:{args.port} (docs at /docs).")
    uvicorn.run("app.api.app:app", host=args.host, port=args.port, reload=args.reload)
    return 0


def _cmd_start_scheduler(args: argparse.Namespace) -> int:
    """Start the APScheduler daemon (M6); blocks until interrupted."""
    from app.config import get_settings
    from app.scheduler.jobs import start_scheduler

    settings = get_settings()
    print(
        f"[start-scheduler] daily pipeline scheduled at {settings.run_hour:02d}:00 "
        f"{settings.timezone}. Press Ctrl+C to stop."
    )
    start_scheduler(settings)
    return 0


def _cmd_install_schedule(args: argparse.Namespace) -> int:
    """Write a macOS LaunchAgent so the scheduler survives logout/reboot."""
    from app.scheduler.launchd import LABEL, install

    path = install()
    print(f"[install-schedule] wrote {path}")
    print("\nActivate it with:")
    print(f"  launchctl unload {path} 2>/dev/null; launchctl load {path}")
    print(f"\nCheck it is running:  launchctl list | grep {LABEL}")
    print(f"Remove it later:      launchctl unload {path} && rm {path}")
    print("\nNote: the scrapers need a real desktop session (headed Chrome), so this")
    print("runs at login — not as a system daemon on a headless box.")
    return 0


def _cmd_catch_up(args: argparse.Namespace) -> int:
    """Run the pipeline if today's scheduled run was missed (no-op otherwise)."""
    from app.scheduler.jobs import catch_up_if_missed

    ran = catch_up_if_missed()
    print("[catch-up] ran a missed pipeline" if ran else "[catch-up] nothing to do")
    return 0


def _cmd_login(args: argparse.Namespace) -> int:
    """Open a browser for a one-time manual login and save the session."""
    from app.collectors.linkedin import LinkedInCollector
    from app.collectors.naukri import NaukriCollector
    from app.database.connection import session_scope
    from app.runtime_config import effective_settings

    with session_scope() as session:
        settings = effective_settings(session)
    collector = (
        NaukriCollector(settings=settings)
        if args.source == "naukri"
        else LinkedInCollector(settings=settings)
    )
    ok = collector.interactive_login(timeout_seconds=args.timeout)
    if ok:
        print(f"[login] {args.source}: session saved. Future runs will reuse it.")
        return 0
    print(
        f"[login] {args.source}: did not reach a logged-in page in time.",
        file=sys.stderr,
    )
    return 1


def build_parser() -> argparse.ArgumentParser:
    """Construct the top-level argument parser with all subcommands."""
    parser = argparse.ArgumentParser(
        prog="app.main",
        description="AI Job Hunter — personal AI recruiter CLI.",
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>", required=True)

    p_parse = sub.add_parser(
        "parse-resume",
        help="Parse a PDF/DOCX resume into the single candidate_profile row.",
    )
    p_parse.add_argument("--path", required=True, help="Path to the resume (.pdf or .docx).")
    p_parse.set_defaults(func=_cmd_parse_resume)

    p_collect = sub.add_parser(
        "collect",
        help="Run a single source collector once (manual collect run).",
    )
    p_collect.add_argument(
        "--source",
        choices=["naukri", "linkedin"],
        default="naukri",
        help="Source to collect (default: naukri).",
    )
    p_collect.set_defaults(func=_cmd_collect)

    p_notify = sub.add_parser(
        "notify-test",
        help="Send a test message to Telegram (sample picks, or --failure alert).",
    )
    p_notify.add_argument(
        "--failure", action="store_true", help="Send the failure-alert message instead of picks."
    )
    p_notify.set_defaults(func=_cmd_notify_test)

    p_run = sub.add_parser(
        "run-pipeline",
        help="Run the daily collect→normalize→dedup→rank→notify pipeline once.",
    )
    p_run.set_defaults(func=_cmd_run_pipeline)

    p_serve = sub.add_parser(
        "serve-api",
        help="Start the FastAPI JSON API for the React dashboard.",
    )
    p_serve.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1).")
    p_serve.add_argument("--port", type=int, default=8000, help="Bind port (default: 8000).")
    p_serve.add_argument("--reload", action="store_true", help="Enable auto-reload (dev).")
    p_serve.set_defaults(func=_cmd_serve_api)

    p_sched = sub.add_parser(
        "start-scheduler",
        help="Start the in-process APScheduler daemon (fires the pipeline daily).",
    )
    p_sched.set_defaults(func=_cmd_start_scheduler)

    p_install = sub.add_parser(
        "install-schedule",
        help="Write a macOS LaunchAgent so the scheduler restarts at login/after a crash.",
    )
    p_install.set_defaults(func=_cmd_install_schedule)

    p_login = sub.add_parser(
        "login",
        help="Open a browser to log in by hand once and save the session (fixes checkpoints).",
    )
    p_login.add_argument(
        "--source", choices=["naukri", "linkedin"], required=True, help="Which site to log in to."
    )
    p_login.add_argument(
        "--timeout", type=int, default=300, help="Seconds to wait for you to finish (default 300)."
    )
    p_login.set_defaults(func=_cmd_login)

    p_catch = sub.add_parser(
        "catch-up",
        help="Run the pipeline now if today's scheduled run was missed.",
    )
    p_catch.set_defaults(func=_cmd_catch_up)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint. Returns a process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
