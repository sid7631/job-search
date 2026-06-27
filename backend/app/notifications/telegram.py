"""Telegram notifier (M7): daily push of the top matches.

Conforms to the `Notifier` protocol the pipeline (M6) calls:
- `notify_success(run_id)` formats the top N matches for the run and pushes them.
- `notify_failure(run_id, error)` sends a short "run failed" alert instead.

Message formatting is pure and testable; the actual HTTP send is injectable
(`sender`) so tests never hit the network. Messages use Telegram HTML parse mode.
"""

from __future__ import annotations

import html
import logging
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass

import httpx
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import connection
from app.database import repository as repo

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org"

Sender = Callable[[str], None]
SessionScope = Callable[[], AbstractContextManager[Session]]


class TelegramError(RuntimeError):
    """Raised when a Telegram message cannot be sent."""


# --------------------------------------------------------------------- formatting


def _apply_link(url: str | None) -> str:
    if not url:
        return "(no link)"
    return f'<a href="{html.escape(url, quote=True)}">Apply</a>'


def format_matches_message(matches: Sequence, *, top_n: int) -> str:
    """Format the daily picks: a summary line plus rank/company/title/score/link."""
    count = len(matches)
    noun = "match" if count == 1 else "matches"
    header = f"<b>🎯 {count} new high-quality {noun} found</b>"
    if count == 0:
        return f"{header}\n\nNothing crossed the bar today."

    lines = [header, ""]
    for rank, match in enumerate(matches[:top_n], start=1):
        job = match.job
        company = html.escape(job.company or "")
        title = html.escape(job.title or "")
        lines.append(
            f"{rank}. <b>{company}</b> — {title}\n   Score {match.score} · {_apply_link(job.url)}"
        )
    return "\n".join(lines)


def format_failure_message(run_id: int, error: str) -> str:
    """Format the short alert sent when a pipeline run fails."""
    detail = html.escape(str(error))[:500]
    return f"⚠️ <b>Pipeline run #{run_id} failed</b>\n{detail}"


def format_reauth_message(source: str) -> str:
    """Format the alert sent when a collector's saved session is dead."""
    name = html.escape(source)
    return (
        f"🔑 <b>{name} re-auth needed</b>\n"
        f"The saved {name} session looks dead. Log in and refresh storage_state so "
        f"collection can resume on the next run."
    )


# ------------------------------------------------------------------------- sample


@dataclass
class _SampleJob:
    title: str
    company: str
    url: str | None


@dataclass
class _SampleMatch:
    score: int
    job: _SampleJob


def build_sample_matches() -> list[_SampleMatch]:
    """A couple of fake matches so `notify-test` can verify delivery without a run."""
    return [
        _SampleMatch(
            92, _SampleJob("Senior Backend Engineer", "Acme", "https://example.com/jobs/1")
        ),
        _SampleMatch(81, _SampleJob("Platform Engineer", "Globex", "https://example.com/jobs/2")),
    ]


# ------------------------------------------------------------------------ notifier


def _http_sender(settings: Settings) -> Sender:
    """Build a sender that posts to the Telegram Bot API."""

    def send(text: str) -> None:
        if not (settings.telegram_bot_token and settings.telegram_chat_id):
            raise TelegramError(
                "Telegram is not configured (set TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID)."
            )
        url = f"{TELEGRAM_API}/bot{settings.telegram_bot_token}/sendMessage"
        try:
            response = httpx.post(
                url,
                json={
                    "chat_id": settings.telegram_chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
                timeout=15.0,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise TelegramError(f"Telegram send failed: {exc}") from exc

    return send


class TelegramNotifier:
    """Sends daily picks / failure alerts to Telegram."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        session_scope: SessionScope | None = None,
        sender: Sender | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._session_scope: SessionScope = session_scope or connection.session_scope
        self._sender: Sender = sender or _http_sender(self._settings)

    def send(self, text: str) -> None:
        """Send a raw message (raises `TelegramError` on failure)."""
        self._sender(text)

    def notify_success(self, run_id: int) -> None:
        """Push the run's top matches."""
        min_score = self._settings.telegram_min_score or None
        with self._session_scope() as session:
            matches = repo.get_today_matches(session, run_id=run_id, min_score=min_score)
        self.send(format_matches_message(matches, top_n=self._settings.telegram_top_n))

    def notify_failure(self, run_id: int, error: str) -> None:
        """Send a short failure alert."""
        self.send(format_failure_message(run_id, error))

    def notify_reauth(self, source: str) -> None:
        """Alert that a collector's session is dead and needs a manual re-login."""
        self.send(format_reauth_message(source))

    def send_sample(self) -> None:
        """Send a sample picks message (for `notify-test`)."""
        self.send(
            format_matches_message(build_sample_matches(), top_n=self._settings.telegram_top_n)
        )
