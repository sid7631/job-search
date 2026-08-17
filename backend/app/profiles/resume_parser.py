"""Resume parser (M2).

Extracts text from a PDF/DOCX resume, asks the configured LLM for structured fields,
validates the result against a pydantic schema (fails loudly on junk), and upserts the single
`candidate_profile` row. The LLM call is injectable so the logic is testable offline.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import repository as repo
from app.database.models import CandidateProfile
from app.llm_client import LLMClient, LLMError
from app.runtime_config import effective_settings

logger = logging.getLogger(__name__)

# A pluggable LLM call: (prompt) -> parsed JSON object.
LLMCallable = Callable[[str], dict]

# Guard against pathological input (a 200-page PDF, an OCR dump). Beyond this the
# tail is dropped: a resume's most recent — and most relevant — roles come first,
# and an oversized prompt silently overflows small local context windows instead.
MAX_RESUME_CHARS = 20_000

# Nobody has a 70-year career. Catches the classic failure where the model reads
# "since 2019" and returns the calendar year as a duration, which would otherwise
# poison the seniority judgement in every single ranking.
MAX_YEARS_EXPERIENCE = 70


class ResumeParseError(RuntimeError):
    """Raised when the resume cannot be read or the LLM returns unusable output."""


def _clean_list(values: list[str]) -> list[str]:
    """Strip blanks and case-insensitive duplicates, keeping first-seen order/casing."""
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        text = str(value).strip()
        if not text or text.lower() in seen:
            continue
        seen.add(text.lower())
        out.append(text)
    return out


class ParsedResume(BaseModel):
    """Structured fields the LLM must extract from a resume.

    `companies` has no dedicated column in `candidate_profile`; it is preserved in
    `raw_parsed_json` alongside the rest of the structured output.
    """

    name: str | None = None
    years_experience: float | None = Field(default=None, ge=0, le=MAX_YEARS_EXPERIENCE)
    skills: list[str] = Field(default_factory=list)
    companies: list[str] = Field(default_factory=list)
    domain: str | None = None
    preferred_locations: list[str] = Field(default_factory=list)
    desired_roles: list[str] = Field(default_factory=list)

    @field_validator("skills", "companies", "preferred_locations", "desired_roles")
    @classmethod
    def _tidy(cls, value: list[str]) -> list[str]:
        """LLMs happily emit blanks and near-duplicates; these lists feed the ranker."""
        return _clean_list(value)

    @field_validator("name", "domain")
    @classmethod
    def _blank_to_none(cls, value: str | None) -> str | None:
        return value.strip() or None if isinstance(value, str) else value


# --------------------------------------------------------------------- extraction


def extract_text(path: str | Path) -> str:
    """Extract plain text from a PDF or DOCX resume, capped at `MAX_RESUME_CHARS`."""
    p = Path(path)
    if not p.exists():
        raise ResumeParseError(f"resume not found: {p}")
    suffix = p.suffix.lower()
    if suffix == ".pdf":
        text = _extract_pdf(p)
    elif suffix == ".docx":
        text = _extract_docx(p)
    else:
        raise ResumeParseError(f"unsupported resume type '{suffix}' (use .pdf or .docx)")

    if len(text) > MAX_RESUME_CHARS:
        logger.warning(
            "resume text is %d chars; truncating to %d to fit the model's context",
            len(text),
            MAX_RESUME_CHARS,
        )
        text = text[:MAX_RESUME_CHARS]
    return text


def _extract_pdf(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def _extract_docx(path: Path) -> str:
    """Extract body text in reading order, including tables, headers and footers.

    `document.paragraphs` alone silently drops every table cell — and two-column /
    grid resume templates put most of their content (skills, dates, employers) in
    tables, so a table-based resume would otherwise parse as almost empty without
    raising anything. Contact details often live in the header, too.
    """
    import docx

    document = docx.Document(str(path))
    parts: list[str] = []
    for section in document.sections:
        parts.extend(_docx_block_text(section.header))
    parts.extend(_docx_block_text(document))
    for section in document.sections:
        parts.extend(_docx_block_text(section.footer))
    return "\n".join(part for part in parts if part.strip())


def _docx_block_text(parent) -> list[str]:
    """Walk a docx container's paragraphs and tables in document order."""
    from docx.oxml.table import CT_Tbl
    from docx.oxml.text.paragraph import CT_P
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    # Document exposes its body as `.element.body`; headers/footers/cells as `._element`.
    # Compare against None explicitly: lxml elements are falsy when they have no
    # children, so `or` would discard the body of an empty section.
    element = getattr(getattr(parent, "element", None), "body", None)
    if element is None:
        element = getattr(parent, "_element", None)
    if element is None:
        return []

    out: list[str] = []
    for child in element.iterchildren():
        if isinstance(child, CT_P):
            out.append(Paragraph(child, parent).text)
        elif isinstance(child, CT_Tbl):
            for row in Table(child, parent).rows:
                # Tab-separate cells so a skills grid reads as one line, not one word
                # per line, and recurse for the nested tables some templates use.
                cells = ["\n".join(_docx_block_text(cell)).strip() for cell in row.cells]
                out.append("\t".join(cell for cell in cells if cell))
    return out


# ------------------------------------------------------------------------- prompt


def build_prompt(resume_text: str, *, today: date | None = None) -> str:
    """Build the extraction prompt that requires strict JSON output.

    `today` is stated explicitly because resumes date roles as "2019 - Present";
    without it the model has no reliable way to turn that into a number of years.
    """
    today = today or date.today()
    return (
        "You are parsing a candidate's resume. Extract the following fields and "
        "return ONLY a JSON object (no prose, no markdown) with exactly these keys:\n"
        '  "name": string or null,\n'
        '  "years_experience": number or null,\n'
        '  "skills": array of strings,\n'
        '  "companies": array of strings (employers, most recent first),\n'
        '  "domain": string or null (primary domain, e.g. "backend", "data", "ML"),\n'
        '  "preferred_locations": array of strings,\n'
        '  "desired_roles": array of strings.\n\n'
        "Rules:\n"
        f"- Today's date is {today.isoformat()}. Treat 'Present' / 'Current' as today "
        "when calculating durations.\n"
        '- "years_experience" is the TOTAL length of professional work in years as a '
        "single number (e.g. 7.5), NOT a calendar year and NOT a range. Exclude "
        "internships and education. If roles overlap, count elapsed time once.\n"
        '- "skills" are concrete technologies, languages, frameworks and tools. '
        "Exclude soft skills. Do not repeat the same skill twice.\n"
        '- "desired_roles" are the job titles this candidate should be matched to. '
        "If the resume states a target or objective, use it; otherwise infer them "
        "from the most recent titles and seniority (e.g. a Senior Backend Engineer "
        "maps to 'Senior Backend Engineer', 'Backend Engineer', 'Staff Engineer').\n"
        '- "preferred_locations" are stated relocation/work preferences; if none are '
        "stated, use the candidate's current or most recent location.\n"
        "- For every other field, use null or [] when it is genuinely absent. "
        "Do not invent employers, skills or names.\n\n"
        "RESUME:\n"
        f"{resume_text}"
    )


# ----------------------------------------------------------------------------- llm


def _extract_with(caller: LLMCallable, resume_text: str) -> ParsedResume:
    """Call the LLM and validate, retrying once on malformed output.

    Mirrors the ranking engine: small local models intermittently return prose or a
    near-miss shape, and one retry turns a failed upload into a successful one.
    """
    prompt = build_prompt(resume_text)
    last_exc: Exception | None = None
    for _attempt in range(2):  # initial try + one retry
        try:
            return ParsedResume.model_validate(caller(prompt))
        except ValidationError as exc:
            last_exc = exc
            logger.warning("resume parse returned an unusable shape; retrying once")
        except LLMError as exc:
            # A config or transport failure will not fix itself on a retry.
            raise ResumeParseError(f"LLM call failed: {exc}") from exc
    raise ResumeParseError(f"LLM output failed schema validation twice: {last_exc}")


# --------------------------------------------------------------------------- parse


def parse_resume_text(
    resume_text: str,
    *,
    llm: LLMCallable | None = None,
    settings: Settings | None = None,
) -> ParsedResume:
    """Run the LLM over resume text and validate it into a `ParsedResume`.

    Pass `settings` (normally from `effective_settings`) so the Settings page's
    provider overrides are honoured; otherwise `.env` alone is used.
    """
    if not resume_text.strip():
        raise ResumeParseError(
            "no text could be extracted from the resume. If it is a scanned or "
            "image-only PDF, export a text-based PDF or upload a .docx instead."
        )

    if llm is not None:
        return _extract_with(llm, resume_text)
    # Own the client so its connection pool is closed rather than leaked per upload.
    with LLMClient.from_settings(settings or get_settings()) as client:
        return _extract_with(client, resume_text)


def parse_resume(
    session: Session,
    path: str | Path,
    *,
    settings: Settings | None = None,
    llm: LLMCallable | None = None,
) -> CandidateProfile:
    """Parse a resume file and upsert the single `candidate_profile` row.

    Idempotent: re-running updates the existing profile rather than adding rows.
    Uses DB overrides (if any) on top of `.env` so UI settings take effect.
    """
    settings = effective_settings(session, base=settings or get_settings())
    resume_text = extract_text(path)
    parsed = parse_resume_text(resume_text, llm=llm, settings=settings)
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
