"""Application configuration loaded from environment / `.env`.

Every secret and tunable lives here. No secrets in code or the database.
See `.env.example` for the full list of keys.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed settings sourced from environment variables / `.env`."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- LLM (ranking + resume parsing) ---
    # See `app.llm_client.PROVIDERS` for the full list: openai, anthropic, ollama,
    # ollama_cloud, groq, deepseek, mistral, openrouter, together, xai, lmstudio,
    # openai_compatible. Blank base_url/model fall back to the provider's defaults.
    llm_provider: str = "ollama"
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""

    # --- Telegram notifier ---
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    telegram_top_n: int = 10
    telegram_min_score: int = 0
    # Push only jobs first seen in this run, so a job you have not acted on is not
    # re-sent every night. Failures and the daily summary are unaffected.
    telegram_only_new: bool = True

    # --- Naukri collector ---
    naukri_email: str = ""
    naukri_password: str = ""
    naukri_keywords: str = ""
    naukri_location: str = ""
    naukri_experience: str = ""
    # Naukri's public results page has everything we need, including per-job URLs.
    # Logging in switches to the "TopTier" UI (no per-card URL) and invites an
    # OTP/captcha challenge, so it is off by default.
    naukri_require_login: bool = False

    # --- LinkedIn collector ---
    # Scraping LinkedIn is fragile and against their ToS — see the README. The
    # defaults are deliberately conservative (few pages, slow), and a dead session
    # raises a Telegram re-auth alert rather than crashing the run.
    linkedin_email: str = ""
    linkedin_password: str = ""
    linkedin_keywords: str = ""
    linkedin_location: str = ""
    linkedin_max_pages: int = 3
    linkedin_delay_multiplier: float = 1.75
    # LinkedIn answers an automated login by pushing an "is this you?" prompt to the
    # phone. Approving it takes a human a moment, so the pipeline waits rather than
    # giving up — set to 0 to fail fast instead of holding the run open.
    linkedin_approval_wait_seconds: int = 180

    # --- Collector behaviour (shared) ---
    collector_max_pages: int = 5
    # Headed by default: Naukri's Akamai bot-block 403s headless browsers. Needs a display.
    collector_headless: bool = False
    collector_min_delay_seconds: float = 1.5
    collector_max_delay_seconds: float = 4.0
    collector_max_retries: int = 3
    storage_state_dir: str = "./.playwright"

    # --- Normalizer / deduplication ---
    dedupe_fuzzy_threshold: float = 90.0

    # --- LLM ranking ---
    ranking_max_concurrency: int = 4

    # --- Pre-filter (cheap, deterministic; runs before any LLM call) ---
    # Cap on jobs sent to the LLM per run. 0 disables the cap (rank everything).
    prefilter_max_jobs: int = 50
    # Drop jobs scoring below this (0-100). 0 keeps everything the cap allows.
    prefilter_min_score: float = 0.0

    # --- Detail enrichment (fetch the real posting before ranking) ---
    enrich_enabled: bool = True
    # Cap on detail pages opened per run — each is a real page load with a delay.
    enrich_max_jobs: int = 30

    # --- Feedback loop ---
    # Feed recent tracked decisions into the ranking prompt so it learns your taste.
    feedback_enabled: bool = True
    feedback_max_examples: int = 8

    # --- API ---
    # Comma-separated list of allowed CORS origins (the React dev server).
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # --- Database ---
    db_url: str = "sqlite:///./job_hunter.db"

    # --- Scheduler ---
    run_hour: int = 8
    timezone: str = "Asia/Kolkata"
    # When true, `serve-api` also starts the daily scheduler in-process (the Docker
    # `app` service sets this so one container is "API + scheduler").
    enable_scheduler: bool = False


@lru_cache
def get_settings() -> Settings:
    """Return a cached `Settings` instance."""
    return Settings()
