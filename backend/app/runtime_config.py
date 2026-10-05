"""Effective settings = résumé-derived defaults, `.env`, then UI-editable DB overrides.

Three layers, lowest precedence first:

1. **Résumé-derived** search terms (`profiles.search_terms`) — so a freshly parsed
   résumé produces a working search with nothing to configure.
2. **`.env`** — the operator's defaults.
3. **`app_settings`** (the dashboard's Settings page) — an explicit manual override.

A blank value at any layer falls through to the one below, so setting a field by hand
always wins and is never overwritten by a later résumé parse.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import repository as repo
from app.profiles.search_terms import derive_search_terms

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
    "llm_provider",
    "llm_base_url",
    "llm_api_key",
    "llm_model",
    "exclude_keywords",
)

# Fields the résumé can fill in when nothing else has set them.
DERIVABLE_FIELDS: tuple[str, ...] = (
    "naukri_keywords",
    "naukri_location",
    "naukri_experience",
    "linkedin_keywords",
    "linkedin_location",
)


def _is_blank(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def derived_defaults(session: Session) -> dict[str, str]:
    """The search terms the parsed résumé implies (empty before any résumé)."""
    return derive_search_terms(repo.get_candidate_profile(session))


def effective_settings(session: Session, base: Settings | None = None) -> Settings:
    """Return the settings the pipeline should actually run with."""
    base = base or get_settings()
    updates: dict[str, object] = {}

    # Layer 1 — résumé-derived, only where `.env` left the field blank.
    derived = derived_defaults(session)
    for field in DERIVABLE_FIELDS:
        if _is_blank(getattr(base, field, None)) and derived.get(field):
            updates[field] = derived[field]

    # Layer 3 — explicit Settings-page overrides beat everything above.
    row = repo.get_app_settings(session)
    if row is not None:
        for field in OVERRIDE_FIELDS:
            value = getattr(row, field, None)
            if value is None or (isinstance(value, str) and not value.strip()):
                continue
            updates[field] = value

    return base.model_copy(update=updates) if updates else base
