"""Resume parser (M2).

Extracts text from a PDF/DOCX resume, asks Gemini for structured fields, validates
the result against a pydantic schema (fails loudly on junk), and upserts the single
`candidate_profile` row. The LLM call is injectable so the logic is testable offline.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import repository as repo
from app.database.models import CandidateProfile

# A pluggable LLM call: (prompt, *, model, api_key) -> parsed JSON object.
LLMCallable = Callable[..., dict]


class ResumeParseError(RuntimeError):
    """Raised when the resume cannot be read or the LLM returns unusable output."""


class ParsedResume(BaseModel):
    """Structured fields the LLM must extract from a resume.

    `companies` has no dedicated column in `candidate_profile`; it is preserved in
    `raw_parsed_json` alongside the rest of the structured output.
    """

    name: str | None = None
    years_experience: float | None = Field(default=None, ge=0)
    skills: list[str] = Field(default_factory=list)
    companies: list[str] = Field(default_factory=list)
    domain: str | None = None
    preferred_locations: list[str] = Field(default_factory=list)
    desired_roles: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------- extraction


def extract_text(path: str | Path) -> str:
    """Extract plain text from a PDF or DOCX resume."""
    p = Path(path)
    if not p.exists():
        raise ResumeParseError(f"resume not found: {p}")
    suffix = p.suffix.lower()
    if suffix == ".pdf":
        return _extract_pdf(p)
    if suffix == ".docx":
        return _extract_docx(p)
    raise ResumeParseError(f"unsupported resume type '{suffix}' (use .pdf or .docx)")


def _extract_pdf(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def _extract_docx(path: Path) -> str:
    import docx

    document = docx.Document(str(path))
    return "\n".join(paragraph.text for paragraph in document.paragraphs)


# ------------------------------------------------------------------------- prompt


def build_prompt(resume_text: str) -> str:
    """Build the extraction prompt that requires strict JSON output."""
    return (
        "You are parsing a candidate's resume. Extract the following fields and "
        "return ONLY a JSON object (no prose, no markdown) with exactly these keys:\n"
        '  "name": string or null,\n'
        '  "years_experience": number or null (total years of professional experience),\n'
        '  "skills": array of strings,\n'
        '  "companies": array of strings (employers, most recent first),\n'
        '  "domain": string or null (primary domain, e.g. "backend", "data", "ML"),\n'
        '  "preferred_locations": array of strings,\n'
        '  "desired_roles": array of strings (target job titles).\n'
        "Use null or [] when a field is genuinely absent. Do not invent values.\n\n"
        "RESUME:\n"
        f"{resume_text}"
    )


# -------------------------------------------------------------------------- gemini


def _call_gemini(prompt: str, *, model: str, api_key: str) -> dict:
    """Call Gemini in JSON mode and return the parsed object."""
    if not api_key:
        raise ResumeParseError("GEMINI_API_KEY is not set; cannot parse the resume.")

    import google.generativeai as genai

    genai.configure(api_key=api_key)
    gemini = genai.GenerativeModel(model)
    response = gemini.generate_content(
        prompt,
        generation_config={"response_mime_type": "application/json", "temperature": 0},
    )
    try:
        return json.loads(response.text)
    except (ValueError, AttributeError) as exc:
        raise ResumeParseError(f"Gemini did not return valid JSON: {exc}") from exc


# --------------------------------------------------------------------------- parse


def parse_resume_text(
    resume_text: str,
    *,
    model: str,
    api_key: str,
    llm: LLMCallable | None = None,
) -> ParsedResume:
    """Run the LLM over resume text and validate it into a `ParsedResume`."""
    if not resume_text.strip():
        raise ResumeParseError("no text could be extracted from the resume.")

    caller = llm or _call_gemini
    raw = caller(build_prompt(resume_text), model=model, api_key=api_key)
    try:
        return ParsedResume.model_validate(raw)
    except ValidationError as exc:
        raise ResumeParseError(f"LLM output failed schema validation: {exc}") from exc


def parse_resume(
    session: Session,
    path: str | Path,
    *,
    settings: Settings | None = None,
    llm: LLMCallable | None = None,
) -> CandidateProfile:
    """Parse a resume file and upsert the single `candidate_profile` row.

    Idempotent: re-running updates the existing profile rather than adding rows.
    """
    settings = settings or get_settings()
    resume_text = extract_text(path)
    parsed = parse_resume_text(
        resume_text,
        model=settings.llm_model,
        api_key=settings.gemini_api_key,
        llm=llm,
    )
    return repo.upsert_candidate_profile(
        session,
        name=parsed.name,
        years_experience=parsed.years_experience,
        skills=parsed.skills,
        domain=parsed.domain,
        preferred_locations=parsed.preferred_locations,
        desired_roles=parsed.desired_roles,
        resume_text=resume_text,
        raw_parsed_json=parsed.model_dump(),
    )
