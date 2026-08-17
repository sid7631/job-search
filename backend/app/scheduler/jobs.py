"""APScheduler wiring (M6).

Registers the daily pipeline job at `RUN_HOUR` (default 08:00) in the configured
timezone (default Asia/Kolkata) and runs it as an in-process blocking daemon.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.schedulers.base import BaseScheduler
from apscheduler.schedulers.blocking import BlockingScheduler

from app.config import Settings, get_settings
from app.scheduler.pipeline import run_pipeline

logger = logging.getLogger(__name__)

JOB_ID = "daily-pipeline"
CATCH_UP_JOB_ID = "startup-catch-up"


def _ran_successfully_today(settings: Settings) -> bool:
    """True if a run already finished successfully today, in the local timezone."""
    from zoneinfo import ZoneInfo

    from app.database import connection
    from app.database import repository as repo
    from app.database.models import RunStatus

    tz = ZoneInfo(settings.timezone)
    today = datetime.now(tz).date()
    with connection.session_scope() as session:
        run = repo.get_run_for_date(session, today)
        return run is not None and run.status == RunStatus.SUCCESS.value


def catch_up_if_missed(settings: Settings | None = None) -> bool:
    """Run the pipeline now if today's scheduled run was missed.

    A cron trigger only fires while the process is alive. Close the laptop over
    `RUN_HOUR`, or restart the API afterwards, and the day is silently skipped —
    APScheduler's `misfire_grace_time` only covers an hour. This is called on
    startup so a machine that was asleep still gets its daily run.

    Returns True if a catch-up run was started.
    """
    from zoneinfo import ZoneInfo

    settings = settings or get_settings()
    now = datetime.now(ZoneInfo(settings.timezone))
    if now.hour < settings.run_hour:
        logger.info("catch-up: today's %02d:00 run has not come round yet", settings.run_hour)
        return False
    if _ran_successfully_today(settings):
        logger.info("catch-up: a run already succeeded today; nothing to do")
        return False

    logger.info("catch-up: today's %02d:00 run was missed — running now", settings.run_hour)
    run_pipeline()
    return True


def build_scheduler(
    settings: Settings | None = None, *, scheduler: BaseScheduler | None = None
) -> BaseScheduler:
    """Return a scheduler with the daily pipeline job registered at RUN_HOUR."""
    settings = settings or get_settings()
    scheduler = scheduler or BlockingScheduler(timezone=settings.timezone)
    scheduler.add_job(
        run_pipeline,
        trigger="cron",
        hour=settings.run_hour,
        minute=0,
        id=JOB_ID,
        name="Daily job pipeline",
        replace_existing=True,
        coalesce=True,
        misfire_grace_time=3600,
    )
    return scheduler


def _schedule_catch_up(scheduler: BaseScheduler) -> None:
    """Queue a one-shot catch-up a few seconds after start, off the startup path."""
    scheduler.add_job(
        catch_up_if_missed,
        trigger="date",
        run_date=datetime.now() + timedelta(seconds=10),
        id=CATCH_UP_JOB_ID,
        name="Catch up a missed daily run",
        replace_existing=True,
    )


def start_background_scheduler(settings: Settings | None = None) -> BackgroundScheduler:
    """Start a non-blocking scheduler (for running alongside the API in one process)."""
    settings = settings or get_settings()
    scheduler = build_scheduler(settings, scheduler=BackgroundScheduler(timezone=settings.timezone))
    _schedule_catch_up(scheduler)
    scheduler.start()
    logger.info(
        "background scheduler started; daily pipeline at %02d:00 %s",
        settings.run_hour,
        settings.timezone,
    )
    return scheduler


def start_scheduler(settings: Settings | None = None) -> None:
    """Start the blocking scheduler daemon (runs until interrupted)."""
    settings = settings or get_settings()
    scheduler = build_scheduler(settings)
    _schedule_catch_up(scheduler)
    logger.info(
        "scheduler starting; daily pipeline at %02d:00 %s",
        settings.run_hour,
        settings.timezone,
    )
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("scheduler shutting down")
        scheduler.shutdown()
