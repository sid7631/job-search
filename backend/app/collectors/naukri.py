"""Naukri Playwright collector — for Naukri's current "TopTier" UI (M3, revised).

Reality of scraping Naukri (verified 2026-06):
- The site is behind Akamai bot protection: **headless is 403-blocked**, so the
  collector runs **headed** (`COLLECTOR_HEADLESS=false`). That means it needs a real
  desktop session — run it on a machine with a display, not a headless server.
- It logs in fresh from the `.env` credentials on every run (no persisted session),
  so switching accounts is just editing `.env`.
- The results page is a React/Tailwind app with no stable selectors or clean JSON,
  so each card is parsed from its **text content** (`_parse_card`, a pure function),
  which is sturdier than the utility-class soup but will still need upkeep if Naukri
  redesigns. There is no per-card job URL in this UI, so `url`/`source_job_id` are
  None and a description is synthesized from the card fields for ranking.

`_fetch_raw_jobs()` is the only part that touches Playwright; tests override it.
"""

from __future__ import annotations

import logging
import re

from app.collectors.base import (
    Collector,
    RawJobPayload,
    SessionError,
    SessionScope,
    persist_raw_jobs,
    random_delay,
    record_collector_error,
)
from app.config import Settings, get_settings
from app.database import connection
from app.database.models import RawJob

logger = logging.getLogger(__name__)

NAUKRI_BASE = "https://www.naukri.com"
LOGIN_URL = "https://www.naukri.com/nlogin/login"
HOMEPAGE = "https://www.naukri.com/mnjuser/homepage"
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# A job card in the current UI: a clickable rounded tile. We further filter by text
# (must contain an experience "Yrs" line and a posted "… ago" line).
_CARD_SELECTOR = "div.cursor-pointer.rounded-3xl"
_CARD_JS = r"""() => {
  const cards = [...document.querySelectorAll('div.cursor-pointer.rounded-3xl')]
    .filter(d => { const t = d.innerText || '';
      return /\bYrs?\b/.test(t) && /ago/i.test(t) && t.length > 60 && t.length < 1000; });
  const seen = new Set(); const out = [];
  for (const c of cards) {
    const key = (c.innerText || '').slice(0, 60);
    if (seen.has(key)) continue;
    seen.add(key);
    out.push((c.innerText || '').split('\n').map(x => x.trim()).filter(Boolean));
  }
  return out;
}"""

# Job ids aren't exposed in this UI, but keep the helper for any future URL-bearing source.
_JOB_ID_RE = re.compile(r"-(\d+)(?:\?|$)")


class NaukriCollector(Collector):
    """Collects jobs from Naukri into `raw_jobs` (headed, fresh login each run)."""

    source = "naukri"

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        session_scope: SessionScope | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._session_scope: SessionScope = session_scope or connection.session_scope

    # ------------------------------------------------------------------ public API

    def collect(self, run_id: int) -> list[RawJob]:
        """Scrape Naukri and persist to `raw_jobs`; never throws on session death."""
        try:
            payloads = self._fetch_raw_jobs()
        except SessionError as exc:
            logger.warning("naukri session failure: %s", exc)
            record_collector_error(self._session_scope, run_id, f"naukri: {exc}")
            return []
        return persist_raw_jobs(
            self._session_scope, source=self.source, run_id=run_id, payloads=payloads
        )

    # --------------------------------------------------------------- scraping (live)

    def _fetch_raw_jobs(self) -> list[RawJobPayload]:
        """Entry point for the live scrape. Overridden in tests."""
        if not (self._settings.naukri_email and self._settings.naukri_password):
            raise SessionError(
                "Naukri credentials are not configured (set NAUKRI_EMAIL / NAUKRI_PASSWORD)."
            )
        return self._scrape()

    def _scrape(self) -> list[RawJobPayload]:
        from playwright.sync_api import sync_playwright

        payloads: list[RawJobPayload] = []
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=self._settings.collector_headless)
            context = browser.new_context(
                user_agent=_USER_AGENT, locale="en-US", viewport={"width": 1340, "height": 900}
            )
            try:
                page = context.new_page()
                self._login_and_verify(page)
                for page_no in range(1, self._settings.collector_max_pages + 1):
                    page.goto(self._build_search_url(page_no), wait_until="domcontentloaded")
                    if self._is_login_wall(page):
                        raise SessionError("hit a login wall mid-scrape; session is dead.")
                    page.wait_for_timeout(4000)
                    cards = self._extract_cards(page, page_no)
                    if not cards:
                        break
                    payloads.extend(cards)
                    random_delay(
                        self._settings.collector_min_delay_seconds,
                        self._settings.collector_max_delay_seconds,
                    )
            finally:
                context.close()
                browser.close()
        logger.info("naukri: scraped %d jobs", len(payloads))
        return payloads

    def _login_and_verify(self, page) -> None:
        """Log in with the .env creds and confirm the session is real."""
        try:
            page.goto(LOGIN_URL, wait_until="domcontentloaded")
            page.fill("#usernameField", self._settings.naukri_email)
            page.fill("#passwordField", self._settings.naukri_password)
            page.click("button[type='submit']")
            try:
                page.wait_for_load_state("networkidle", timeout=25000)
            except Exception:  # noqa: BLE001 - networkidle can time out on a live SPA
                pass
            page.wait_for_timeout(3000)
        except Exception as exc:  # noqa: BLE001 - any login interaction failure is a dead session
            raise SessionError(f"Naukri login interaction failed: {exc}") from exc

        # Verify: a logged-in session can reach the member homepage without redirect.
        page.goto(HOMEPAGE, wait_until="domcontentloaded")
        page.wait_for_timeout(2000)
        if self._is_login_wall(page):
            raise SessionError(
                "Naukri login failed (redirected to login — check credentials, or an "
                "OTP/captcha challenge blocked the automated login)."
            )

    @staticmethod
    def _is_login_wall(page) -> bool:
        return "login" in page.url.lower() or page.query_selector("#passwordField") is not None

    def _extract_cards(self, page, page_no: int) -> list[RawJobPayload]:
        # The results list lazy-loads on scroll — nudge it a few times.
        for _ in range(6):
            page.mouse.wheel(0, 4000)
            page.wait_for_timeout(700)
        rows: list[list[str]] = page.evaluate(_CARD_JS)
        results: list[RawJobPayload] = []
        for lines in rows:
            parsed = self._parse_card(lines)
            if parsed is None:
                continue
            results.append(
                RawJobPayload(
                    source_job_id=None,  # not exposed in this UI
                    url=None,
                    title=parsed["title"],
                    company=parsed["company"],
                    location=parsed["location"],
                    description=self._describe(parsed),
                    raw={"page_no": page_no, **parsed},
                )
            )
        return results

    @staticmethod
    def _parse_card(lines: list[str]) -> dict | None:
        """Parse a Naukri card's text lines into structured fields (pure / testable).

        Observed line order: company, rating, industry…, "<n> ago", "Quick apply",
        TITLE, LOCATION, SALARY, SKILLS, EXPERIENCE.
        """
        lines = [ln.strip() for ln in lines if ln and ln.strip()]
        if len(lines) < 3:
            return None
        company = lines[0]
        ago_idx = next((i for i, ln in enumerate(lines) if re.search(r"\bago\b", ln, re.I)), None)
        rest = lines[ago_idx + 1 :] if ago_idx is not None else lines[1:]
        rest = [ln for ln in rest if ln.lower() not in ("quick apply", "apply", "save")]
        if not rest:
            return None
        title = rest[0]
        location = rest[1] if len(rest) > 1 else None
        salary: str | None = None
        experience: str | None = None
        skills: list[str] = []
        for ln in rest[2:]:
            if re.search(r"\bYrs?\b", ln):
                experience = ln
            elif "₹" in ln or "disclosed" in ln.lower() or "lpa" in ln.lower():
                salary = ln
            elif "," in ln and not skills:
                skills = [s.strip() for s in ln.split(",") if s.strip()]
        return {
            "title": title,
            "company": company,
            "location": location,
            "salary": salary,
            "experience": experience,
            "skills": skills,
        }

    @staticmethod
    def _describe(parsed: dict) -> str:
        """Synthesize a description from card fields (no detail page in this UI)."""
        parts = [f"{parsed['title']} at {parsed['company']}."]
        if parsed.get("location"):
            parts.append(f"Location: {parsed['location']}.")
        if parsed.get("experience"):
            parts.append(f"Experience required: {parsed['experience']}.")
        if parsed.get("salary"):
            parts.append(f"Salary: {parsed['salary']}.")
        if parsed.get("skills"):
            parts.append("Key skills: " + ", ".join(parsed["skills"]) + ".")
        return " ".join(parts)

    def _build_search_url(self, page_no: int) -> str:
        keywords = self._slugify(self._settings.naukri_keywords) or "jobs"
        location = self._slugify(self._settings.naukri_location)
        url = f"{NAUKRI_BASE}/{keywords}-jobs"
        if location:
            url += f"-in-{location}"
        if page_no > 1:
            url += f"-{page_no}"
        return url

    @staticmethod
    def _slugify(text: str) -> str:
        return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", (text or "").lower())).strip("-")

    @staticmethod
    def _job_id_from_url(url: str | None) -> str | None:
        if not url:
            return None
        match = _JOB_ID_RE.search(url)
        return match.group(1) if match else None
