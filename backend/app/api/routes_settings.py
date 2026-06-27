"""Settings API routes — view/edit search + account settings from the dashboard.

Stored as DB overrides on top of `.env` (see `runtime_config.effective_settings`),
so changes take effect on the next pipeline run without restarting anything.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import SessionDep
from app.api.schemas import SettingsOut, SettingsUpdate
from app.config import Settings
from app.database import repository as repo
from app.runtime_config import effective_settings

router = APIRouter(prefix="/api", tags=["settings"])


def _to_out(s: Settings) -> SettingsOut:
    return SettingsOut(
        naukri_email=s.naukri_email,
        naukri_password_set=bool(s.naukri_password),
        naukri_keywords=s.naukri_keywords,
        naukri_location=s.naukri_location,
        naukri_experience=s.naukri_experience,
        linkedin_email=s.linkedin_email,
        linkedin_password_set=bool(s.linkedin_password),
        linkedin_keywords=s.linkedin_keywords,
        linkedin_location=s.linkedin_location,
        telegram_min_score=s.telegram_min_score,
        telegram_top_n=s.telegram_top_n,
    )


@router.get("/settings", response_model=SettingsOut)
def get_settings_route(session: SessionDep) -> SettingsOut:
    """Return the current effective settings (DB overrides on top of .env)."""
    return _to_out(effective_settings(session))


@router.put("/settings", response_model=SettingsOut)
def update_settings_route(body: SettingsUpdate, session: SessionDep) -> SettingsOut:
    """Save settings overrides. Blank password fields leave the password unchanged."""
    fields = body.model_dump(exclude_unset=True)
    # Don't overwrite a stored password with a blank value.
    fields = {
        k: v for k, v in fields.items() if not (k.endswith("password") and (v is None or v == ""))
    }
    if fields:
        repo.upsert_app_settings(session, **fields)
    return _to_out(effective_settings(session))
