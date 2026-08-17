"""Tests for the M2 resume parser (offline — the LLM call is injected)."""

from __future__ import annotations

import docx
import pytest
from app.config import Settings
from app.database import repository as repo
from app.profiles.resume_parser import (
    ParsedResume,
    ResumeParseError,
    extract_text,
    parse_resume,
    parse_resume_text,
)
from pypdf import PdfWriter
from sqlalchemy.orm import Session


def _fake_llm(prompt: str) -> dict:
    """Stand-in LLM: returns a well-formed parsed object."""
    assert "RESUME:" in prompt
    return {
        "name": "Jane Doe",
        "years_experience": 6,
        "skills": ["python", "fastapi"],
        "companies": ["Acme", "Globex"],
        "domain": "backend",
        "preferred_locations": ["Remote", "Bengaluru"],
        "desired_roles": ["Senior Backend Engineer"],
    }


def _write_docx(path, *lines: str) -> str:
    document = docx.Document()
    for line in lines:
        document.add_paragraph(line)
    document.save(str(path))
    return str(path)


# --------------------------------------------------------------------- extraction


def test_extract_docx_round_trips_text(tmp_path):
    path = _write_docx(tmp_path / "resume.docx", "Jane Doe", "Senior Engineer at Acme")
    text = extract_text(path)
    assert "Jane Doe" in text
    assert "Acme" in text


def test_extract_pdf_returns_string(tmp_path):
    path = tmp_path / "resume.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    with open(path, "wb") as fh:
        writer.write(fh)
    assert isinstance(extract_text(path), str)


def test_extract_unsupported_type_raises(tmp_path):
    path = tmp_path / "resume.txt"
    path.write_text("hello")
    with pytest.raises(ResumeParseError):
        extract_text(path)


def test_extract_missing_file_raises(tmp_path):
    with pytest.raises(ResumeParseError):
        extract_text(tmp_path / "nope.pdf")


# --------------------------------------------------------------------- validation


def test_parse_resume_text_validates_into_schema():
    parsed = parse_resume_text("some resume text", llm=_fake_llm)
    assert isinstance(parsed, ParsedResume)
    assert parsed.name == "Jane Doe"
    assert parsed.years_experience == 6.0
    assert parsed.skills == ["python", "fastapi"]


def test_parse_resume_text_fails_loudly_on_junk():
    def junk_llm(prompt: str) -> dict:
        return {"years_experience": "a lifetime", "skills": "python"}

    with pytest.raises(ResumeParseError):
        parse_resume_text("some resume text", llm=junk_llm)


def test_parse_resume_text_rejects_empty_text():
    with pytest.raises(ResumeParseError):
        parse_resume_text("   ", llm=_fake_llm)


# ------------------------------------------------------------------- end-to-end


def test_parse_resume_populates_single_profile_row(session: Session, tmp_path):
    path = _write_docx(tmp_path / "resume.docx", "Jane Doe", "6 years backend at Acme")
    settings = Settings(llm_provider="openai", llm_api_key="k", llm_model="m")

    profile = parse_resume(session, path, settings=settings, llm=_fake_llm)

    assert profile.id is not None
    assert profile.name == "Jane Doe"
    assert profile.years_experience == 6.0
    assert profile.skills_json == ["python", "fastapi"]
    assert profile.domain == "backend"
    assert profile.preferred_locations_json == ["Remote", "Bengaluru"]
    assert profile.desired_roles_json == ["Senior Backend Engineer"]
    assert "Jane Doe" in profile.resume_text
    # companies has no column — it survives in raw_parsed_json.
    assert profile.raw_parsed_json["companies"] == ["Acme", "Globex"]


def test_parse_resume_is_idempotent(session: Session, tmp_path):
    path = _write_docx(tmp_path / "resume.docx", "Jane Doe")
    settings = Settings(llm_provider="openai", llm_api_key="k", llm_model="m")

    first = parse_resume(session, path, settings=settings, llm=_fake_llm)

    def updated_llm(prompt: str) -> dict:
        return {**_fake_llm(prompt), "years_experience": 7}

    second = parse_resume(session, path, settings=settings, llm=updated_llm)

    assert second.id == first.id  # same single row, updated in place
    assert second.years_experience == 7.0
    assert repo.get_candidate_profile(session).id == first.id
