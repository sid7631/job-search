"""Smoke tests for the M0 CLI scaffold."""

from __future__ import annotations

import pytest
from app.main import build_parser, main


def test_parser_exposes_entrypoints():
    parser = build_parser()
    sub = next(a for a in parser._actions if a.dest == "command")
    assert set(sub.choices) == {
        "parse-resume",
        "collect",
        "notify-test",
        "run-pipeline",
        "serve-api",
        "start-scheduler",
        "install-schedule",
        "catch-up",
        "login",
    }


def test_parse_resume_requires_path():
    with pytest.raises(SystemExit):
        main(["parse-resume"])


def test_no_command_errors():
    with pytest.raises(SystemExit):
        main([])
