"""Search terms derived from the parsed résumé (M11).

The collectors need a keyword phrase, a location and a years-of-experience filter.
Typing those by hand duplicates what the résumé already says — and then drifts from
it, which is worse than useless: a full-stack candidate quietly scraping "python
backend engineer" gets a feed of jobs they never asked for.

So these are derived from `candidate_profile` and used wherever the user has not set
the field explicitly. Precedence is always **Settings page > `.env` > derived**, so a
manual value is never overwritten (see `runtime_config.effective_settings`).

Pure functions over a profile: no I/O, no settings, no LLM.
"""

from __future__ import annotations

import re

from app.database.models import CandidateProfile

# Stripped from a job title before it becomes a search keyword: the seniority is
# already expressed by the experience filter, and baking it into the query throws
# away perfectly good postings that phrase the level differently.
_SENIORITY_WORDS = (
    "senior",
    "sr",
    "junior",
    "jr",
    "lead",
    "principal",
    "staff",
    "chief",
    "head",
    "director",
    "vp",
    "associate",
)

# Location entries that identify a country rather than a searchable city. Naukri
# slugifies the location straight into its URL path, so "Bangalore, India" would
# become ".../jobs-in-bangalore-india" and match nothing.
_COUNTRY_ONLY = {"india", "usa", "us", "uk", "remote", "anywhere"}

_WORD_RE = re.compile(r"[a-zA-Z0-9+#.]+")


def _strip_seniority(title: str) -> str:
    """Drop leading seniority qualifiers from a job title."""
    words = _WORD_RE.findall(title or "")
    while words and words[0].lower().strip(".") in _SENIORITY_WORDS:
        words = words[1:]
    return " ".join(words).strip()


def derive_keywords(profile: CandidateProfile) -> str:
    """The search phrase to look for, best-effort from the résumé.

    Prefers the candidate's top target role, since that is what a job board's
    keyword search is built around. Falls back to domain + strongest skill, then to
    the skills alone, so a sparse profile still produces a usable query.
    """
    for role in profile.desired_roles_json or []:
        cleaned = _strip_seniority(str(role))
        if cleaned:
            return cleaned.lower()

    skills = [str(s).strip() for s in (profile.skills_json or []) if str(s).strip()]
    domain = (profile.domain or "").strip().lower()
    if domain and skills:
        return f"{skills[0].lower()} {domain}"
    if domain:
        return f"{domain} engineer"
    if skills:
        return " ".join(s.lower() for s in skills[:2])
    return ""


def derive_location(profile: CandidateProfile) -> str:
    """The city to search in — the city part only, not "City, Country"."""
    for entry in profile.preferred_locations_json or []:
        # "Bangalore, India" -> "Bangalore"; a bare "India" is not searchable.
        city = str(entry).split(",")[0].strip()
        if city and city.lower() not in _COUNTRY_ONLY:
            return city
    return ""


def derive_experience(profile: CandidateProfile) -> str:
    """Years of experience as the whole-number string the job boards expect."""
    years = profile.years_experience
    if years is None or years < 0:
        return ""
    return str(int(round(years)))


def derive_search_terms(profile: CandidateProfile | None) -> dict[str, str]:
    """Return the settings fields this profile can fill, keyed by setting name.

    Blank values are omitted so a caller can treat the result as "everything the
    résumé knows" and leave the rest alone.
    """
    if profile is None:
        return {}
    keywords = derive_keywords(profile)
    location = derive_location(profile)
    experience = derive_experience(profile)

    derived = {
        "naukri_keywords": keywords,
        "naukri_location": location,
        "naukri_experience": experience,
        "linkedin_keywords": keywords,
        "linkedin_location": location,
    }
    return {field: value for field, value in derived.items() if value}
