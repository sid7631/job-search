"""Tests for the M7 Telegram notifier (offline — the HTTP send is injected)."""

from __future__ import annotations

import pytest
from app.config import Settings
from app.database import repository as repo
from app.notifications.telegram import (
    TelegramError,
    TelegramNotifier,
    _http_sender,
    build_sample_matches,
    format_failure_message,
    format_matches_message,
    format_reauth_message,
)


class SpySender:
    def __init__(self):
        self.texts: list[str] = []

    def __call__(self, text: str) -> None:
        self.texts.append(text)


def _settings(**kw) -> Settings:
    base = dict(
        telegram_bot_token="t", telegram_chat_id="c", telegram_top_n=10, telegram_min_score=0
    )
    base.update(kw)
    return Settings(**base)


# --------------------------------------------------------------------- formatting


def test_format_matches_message_has_summary_rank_company_title_score_link():
    matches = build_sample_matches()  # scores 92, 81
    text = format_matches_message(matches, top_n=10)

    assert "2 new high-quality matches found" in text
    assert "1. <b>Acme</b> — Senior Backend Engineer" in text
    assert "2. <b>Globex</b> — Platform Engineer" in text
    assert "Score 92" in text
    assert '<a href="https://example.com/jobs/1">Apply</a>' in text


def test_format_matches_message_singular_and_empty():
    one = format_matches_message(build_sample_matches()[:1], top_n=10)
    assert "1 new high-quality match found" in one  # singular

    empty = format_matches_message([], top_n=10)
    assert "0 new high-quality matches found" in empty
    assert "Nothing crossed the bar" in empty


def test_format_matches_message_respects_top_n():
    text = format_matches_message(build_sample_matches(), top_n=1)
    assert "1. <b>Acme</b>" in text
    assert "2. <b>Globex</b>" not in text  # capped
    assert "2 new high-quality matches found" in text  # summary still counts all


def test_format_failure_message():
    text = format_failure_message(7, "boom happened")
    assert "Pipeline run #7 failed" in text
    assert "boom happened" in text


# ----------------------------------------------------------------- notifier (DB)


def _seed_run_with_matches(session, scores: list[int]) -> int:
    run_id = repo.start_run(session).id
    for i, score in enumerate(scores):
        job = repo.upsert_job(
            session,
            title=f"Role {i}",
            company=f"Co {i}",
            location="Remote",
            description="",
            skills=[],
            source="naukri",
            url=f"https://x/{i}",
            content_hash=f"h{i}",
        )
        repo.save_match(session, job_id=job.id, run_id=run_id, score=score, llm_model="m")
    return run_id


def test_notify_success_sends_formatted_picks(scope):
    with scope() as s:
        run_id = _seed_run_with_matches(s, [40, 90, 70])

    sender = SpySender()
    notifier = TelegramNotifier(_settings(), session_scope=scope, sender=sender)
    notifier.notify_success(run_id)

    assert len(sender.texts) == 1
    text = sender.texts[0]
    assert "3 new high-quality matches found" in text
    # Ordered by score desc → top match is score 90.
    assert "1. <b>Co 1</b> — Role 1" in text
    assert "Score 90" in text


def test_notify_success_min_score_filters_summary(scope):
    with scope() as s:
        run_id = _seed_run_with_matches(s, [40, 90, 70])

    sender = SpySender()
    notifier = TelegramNotifier(
        _settings(telegram_min_score=60), session_scope=scope, sender=sender
    )
    notifier.notify_success(run_id)

    text = sender.texts[0]
    assert "2 new high-quality matches found" in text  # only scores >= 60
    assert "Role 0" not in text  # score 40 filtered out


def test_notify_failure_sends_alert(scope):
    sender = SpySender()
    notifier = TelegramNotifier(_settings(), session_scope=scope, sender=sender)
    notifier.notify_failure(11, "ranking exploded")

    assert len(sender.texts) == 1
    assert "Pipeline run #11 failed" in sender.texts[0]
    assert "ranking exploded" in sender.texts[0]


def test_format_reauth_message():
    text = format_reauth_message("LinkedIn")
    assert "LinkedIn re-auth needed" in text


def test_notify_reauth_sends_alert(scope):
    sender = SpySender()
    notifier = TelegramNotifier(_settings(), session_scope=scope, sender=sender)
    notifier.notify_reauth("LinkedIn")
    assert "re-auth needed" in sender.texts[0]


def test_send_sample(scope):
    sender = SpySender()
    notifier = TelegramNotifier(_settings(), session_scope=scope, sender=sender)
    notifier.send_sample()
    assert "high-quality" in sender.texts[0]


# --------------------------------------------------------------- default sender


def test_http_sender_raises_when_unconfigured():
    sender = _http_sender(Settings(telegram_bot_token="", telegram_chat_id=""))
    with pytest.raises(TelegramError):
        sender("hello")
