"""Profile API routes — view the parsed profile and upload a résumé from the UI."""

from __future__ import annotations

import os
import tempfile
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.api.deps import SessionDep
from app.api.schemas import ProfileOut
from app.database import repository as repo
from app.profiles.resume_parser import ResumeParseError, parse_resume

router = APIRouter(prefix="/api", tags=["profile"])

# Resumes are a few hundred KB; the cap stops an oversized upload being read whole
# into memory. The API has no auth, so it must not be trivially OOM-able.
MAX_RESUME_BYTES = 10 * 1024 * 1024


@router.get("/profile", response_model=ProfileOut | None)
def get_profile(session: SessionDep) -> ProfileOut | None:
    """Return the candidate profile, or null if no résumé has been parsed yet."""
    profile = repo.get_candidate_profile(session)
    return ProfileOut.from_profile(profile) if profile else None


@router.post("/profile/resume", response_model=ProfileOut)
def upload_resume(session: SessionDep, file: Annotated[UploadFile, File()]) -> ProfileOut:
    """Upload a PDF/DOCX résumé; parse it with the LLM and update the profile."""
    suffix = os.path.splitext(file.filename or "")[1].lower()
    if suffix not in (".pdf", ".docx"):
        raise HTTPException(status_code=415, detail="Upload a .pdf or .docx file.")

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        written = 0
        while chunk := file.file.read(1024 * 1024):
            written += len(chunk)
            if written > MAX_RESUME_BYTES:
                tmp.close()
                os.unlink(tmp.name)
                raise HTTPException(
                    status_code=413,
                    detail=f"Résumé is larger than {MAX_RESUME_BYTES // (1024 * 1024)} MB.",
                )
            tmp.write(chunk)
        path = tmp.name
    try:
        profile = parse_resume(session, path)
    except ResumeParseError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        os.unlink(path)
    return ProfileOut.from_profile(profile)
