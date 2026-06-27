"""Effective settings = `.env` defaults overlaid with UI-editable DB overrides.

The `app_settings` table (edited from the dashboard's Settings page) overrides the
corresponding `.env` values at run time. A null/blank override falls back to `.env`.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import repository as repo

# Fields the Settings page can override (must exist on both AppSettings and Settings).
OVERRIDE_FIELDS: tuple[str, ...] = (
    "naukri_email",
    "naukri_password",
    "naukri_keywords",
    "naukri_location",
    "naukri_experience",
    "linkedin_email",
    "linkedin_password",
    "linkedin_keywords",
    "linkedin_location",
    "telegram_min_score",
    "telegram_top_n",
)


def effective_settings(session: Session, base: Settings | None = None) -> Settings:
    """Return `.env` settings with any non-blank DB overrides applied."""
    base = base or get_settings()
    row = repo.get_app_settings(session)
    if row is None:
        return base

    overrides: dict[str, object] = {}
    for field in OVERRIDE_FIELDS:
        value = getattr(row, field, None)
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        overrides[field] = value
    return base.model_copy(update=overrides) if overrides else base
