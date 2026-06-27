"""FastAPI application factory (M8).

A thin JSON API the React dashboard consumes — no HTML, no server-side rendering.

**No auth in v1.** This assumes a single user running locally or on a VPS behind a
firewall. Do not expose this API to the public internet without adding auth.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    routes_applications,
    routes_matches,
    routes_profile,
    routes_runs,
    routes_settings,
)
from app.config import Settings, get_settings

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the FastAPI app with CORS and the three routers."""
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        # Optionally run the daily scheduler in-process (Docker `app` service).
        scheduler = None
        if settings.enable_scheduler:
            from app.scheduler.jobs import start_background_scheduler

            scheduler = start_background_scheduler(settings)
        try:
            yield
        finally:
            if scheduler is not None:
                scheduler.shutdown(wait=False)

    app = FastAPI(
        title="AI Job Hunter API",
        version="0.1.0",
        description="Personal AI recruiter — JSON API for the React dashboard.",
        lifespan=lifespan,
    )

    origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(routes_matches.router)
    app.include_router(routes_applications.router)
    app.include_router(routes_runs.router)
    app.include_router(routes_profile.router)
    app.include_router(routes_settings.router)
    return app


# Module-level app for `uvicorn app.api.app:app`.
app = create_app()
