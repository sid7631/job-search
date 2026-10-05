"""Settings API routes — view/edit search + account settings from the dashboard.

Stored as DB overrides on top of `.env` (see `runtime_config.effective_settings`),
so changes take effect on the next pipeline run without restarting anything.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import SessionDep
from app.api.schemas import (
    LLMProviderOut,
    LLMTestIn,
    LLMTestOut,
    SettingsOut,
    SettingsUpdate,
)
from app.config import Settings, get_settings
from app.database import repository as repo
from app.llm_client import PROVIDER_LIST, LLMError, check_llm, resolve_provider
from app.runtime_config import DERIVABLE_FIELDS, derived_defaults, effective_settings

router = APIRouter(prefix="/api", tags=["settings"])


def _to_out(s: Settings, derived: dict[str, str], auto: list[str]) -> SettingsOut:
    spec = resolve_provider(s.llm_provider)
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
        # Report the resolved provider, so a retired value in `.env` shows what
        # is actually in use rather than a name the dropdown can't display.
        llm_provider=spec.key,
        llm_base_url=s.llm_base_url,
        llm_model=s.llm_model,
        llm_api_key_set=bool(s.llm_api_key),
        llm_effective_base_url=s.llm_base_url or spec.base_url,
        llm_effective_model=s.llm_model or spec.default_model,
        llm_requires_key=spec.requires_key,
        exclude_keywords=s.exclude_keywords,
        derived_from_resume=derived,
        auto_fields=auto,
    )


def _settings_out(session) -> SettingsOut:
    """Build the response, flagging which search fields the résumé is filling."""
    derived = derived_defaults(session)
    base = get_settings()
    row = repo.get_app_settings(session)

    auto: list[str] = []
    for field in DERIVABLE_FIELDS:
        manual = getattr(row, field, None) if row is not None else None
        env_value = getattr(base, field, None)
        has_manual = isinstance(manual, str) and manual.strip()
        has_env = isinstance(env_value, str) and env_value.strip()
        if not has_manual and not has_env and derived.get(field):
            auto.append(field)

    return _to_out(effective_settings(session), derived, auto)


@router.get("/settings", response_model=SettingsOut)
def get_settings_route(session: SessionDep) -> SettingsOut:
    """Return the effective settings (résumé defaults, .env, then DB overrides)."""
    return _settings_out(session)


@router.put("/settings", response_model=SettingsOut)
def update_settings_route(body: SettingsUpdate, session: SessionDep) -> SettingsOut:
    """Save settings overrides. Blank password fields leave the password unchanged."""
    fields = body.model_dump(exclude_unset=True)
    # Don't overwrite a stored password or API key with a blank value.
    fields = {
        k: v
        for k, v in fields.items()
        if not (k.endswith(("password", "api_key")) and (v is None or v == ""))
    }
    if fields:
        repo.upsert_app_settings(session, **fields)
    return _settings_out(session)


@router.get("/settings/llm/providers", response_model=list[LLMProviderOut])
def list_llm_providers() -> list[LLMProviderOut]:
    """List selectable LLM providers and their defaults (drives the UI dropdown)."""
    return [
        LLMProviderOut(
            key=spec.key,
            label=spec.label,
            default_base_url=spec.base_url,
            default_model=spec.default_model,
            requires_key=spec.requires_key,
            docs_url=spec.docs_url,
        )
        for spec in PROVIDER_LIST
    ]


@router.post("/settings/llm/test", response_model=LLMTestOut)
def test_llm_route(session: SessionDep, body: LLMTestIn | None = None) -> LLMTestOut:
    """Send one throwaway prompt to the provider and report the result.

    Values in `body` override the saved settings for this call only — nothing is
    written — so the Settings page can test a key that is typed but not yet saved.
    An omitted or blank field falls back to what is saved.

    Always 200: a failure is reported in the body so the UI can show the provider's
    own error text (bad key, model not found, Ollama not running, ...).
    """
    settings = effective_settings(session)
    if body is not None:
        overrides = {
            field: value.strip()
            for field, value in body.model_dump().items()
            if isinstance(value, str) and value.strip()
        }
        if overrides:
            settings = settings.model_copy(update=overrides)

    spec = resolve_provider(settings.llm_provider)
    try:
        model = check_llm(settings)
    except LLMError as exc:
        return LLMTestOut(
            ok=False,
            provider=spec.key,
            model=settings.llm_model or spec.default_model,
            detail=str(exc),
        )
    return LLMTestOut(ok=True, provider=spec.key, model=model)
