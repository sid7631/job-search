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
    gemini_api_key: str = ""
    llm_model: str = "gemini-1.5-flash"

    # --- Telegram notifier ---
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    telegram_top_n: int = 10
    telegram_min_score: int = 0

    # --- Naukri collector ---
    naukri_email: str = ""
    naukri_password: str = ""
    naukri_keywords: str = ""
    naukri_location: str = ""
    naukri_experience: str = ""

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
