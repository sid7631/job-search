"""APScheduler wiring (M6).

Registers the daily pipeline job at `RUN_HOUR` (default 08:00) in the configured
timezone (default Asia/Kolkata) and runs it as an in-process blocking daemon.
"""

from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.schedulers.base import BaseScheduler
from apscheduler.schedulers.blocking import BlockingScheduler

from app.config import Settings, get_settings
from app.scheduler.pipeline import run_pipeline

logger = logging.getLogger(__name__)

JOB_ID = "daily-pipeline"


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


def start_background_scheduler(settings: Settings | None = None) -> BackgroundScheduler:
    """Start a non-blocking scheduler (for running alongside the API in one process)."""
    settings = settings or get_settings()
    scheduler = build_scheduler(settings, scheduler=BackgroundScheduler(timezone=settings.timezone))
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
