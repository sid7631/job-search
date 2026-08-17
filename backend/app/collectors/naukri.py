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
import time

from app.collectors.base import (
    Collector,
    RawJobPayload,
    SessionError,
    SessionScope,
    clear_storage_state,
    load_storage_state,
    persist_raw_jobs,
    random_delay,
    record_collector_error,
    save_storage_state,
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

# The public search-results page ("classic SRP"). Verified against the live site:
# each result is a `div.srp-jobtuple-wrapper` carrying a real per-job link
# (`https://www.naukri.com/job-listings-<slug>-<id>`), structured fields and a
# description snippet — all without logging in.
#
# The logged-in "TopTier" UI renders rounded tiles with no per-card URL, which is
# why this collector deliberately scrapes logged-out: a job you cannot link to is a
# job you cannot apply to later, and no login means no OTP/captcha to fail on.
_CARD_SELECTOR = "div.srp-jobtuple-wrapper"

# Where the posting body lives on a job-listings page, most specific first.
_DETAIL_SELECTORS = (
    "section.job-desc",
    "div.dang-inner-html",
    "section.styles_job-desc-container__txpYf",
    "[class*='job-desc']",
    "[class*='JDC']",
)

# Postings can run very long; the ranking prompt only needs the substance.
MAX_DETAIL_CHARS = 8_000
_CARD_JS = r"""() => {
  const text = (r, sel) => {
    const e = r.querySelector(sel); return e ? e.innerText.trim() : null; };
  const rows = [...document.querySelectorAll('div.srp-jobtuple-wrapper')];
  const seen = new Set(); const out = [];
  for (const r of rows) {
    const a = r.querySelector('a.title') || r.querySelector("a[href*='job-listings']");
    const url = a ? a.href : null;
    // The same tuple is rendered twice (wrapper + inner); key on the URL.
    if (url && seen.has(url)) continue;
    if (url) seen.add(url);
    out.push({
      url: url,
      title: text(r, 'a.title'),
      company: text(r, 'a.comp-name') || text(r, 'span.comp-name'),
      location: text(r, 'span.locWdth') || text(r, "[class*='loc']"),
      experience: text(r, 'span.expwdth') || text(r, "[class*='exp']"),
      salary: text(r, 'span.sal-wrap') || text(r, "span[class*='sal']"),
      summary: text(r, 'span.job-desc'),
      posted: text(r, 'span.job-post-day'),
      skills: [...r.querySelectorAll('ul.tags-gt li')].map(e => e.innerText.trim()).filter(Boolean),
    });
  }
  return out;
}"""

# Trailing numeric id in .../job-listings-<slug>-<id>
_JOB_ID_RE = re.compile(r"-(\d{6,})(?:\?|/|$)")


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
            record_collector_error(self._session_scope, run_id, str(exc), source=self.source)
            return []
        return persist_raw_jobs(
            self._session_scope, source=self.source, run_id=run_id, payloads=payloads
        )

    # --------------------------------------------------------------- scraping (live)

    def _fetch_raw_jobs(self) -> list[RawJobPayload]:
        """Entry point for the live scrape. Overridden in tests.

        Needs no credentials: the public search-results page carries everything we
        want, including per-job URLs. Logging in is opt-in (`NAUKRI_REQUIRE_LOGIN`)
        because an automated login is what triggers Naukri's OTP/captcha challenge.
        """
        return self._scrape()

    def _new_context(self, browser):
        """Browser context seeded with the saved session, when we have one."""
        return browser.new_context(
            user_agent=_USER_AGENT,
            locale="en-US",
            viewport={"width": 1340, "height": 900},
            storage_state=load_storage_state(self._settings, self.source),
        )

    def _ensure_session(self, context, page) -> None:
        """Reuse a saved session, or log in — but only when a login is asked for.

        The public results page needs no session at all, so by default this does
        nothing and the scrape proceeds logged-out.
        """
        if not self._settings.naukri_require_login:
            return
        if load_storage_state(self._settings, self.source):
            page.goto(HOMEPAGE, wait_until="domcontentloaded")
            page.wait_for_timeout(2500)
            if not self._is_login_wall(page):
                logger.info("naukri: reusing saved session (no login needed)")
                return
            logger.info("naukri: saved session is dead; falling back to credentials")
            clear_storage_state(self._settings, self.source)

        if not (self._settings.naukri_email and self._settings.naukri_password):
            raise SessionError(
                "NAUKRI_REQUIRE_LOGIN is set but no credentials are configured "
                "(set NAUKRI_EMAIL / NAUKRI_PASSWORD, or unset NAUKRI_REQUIRE_LOGIN "
                "to scrape the public results page)."
            )
        self._login_and_verify(page)
        save_storage_state(context, self._settings, self.source)

    def interactive_login(self, *, timeout_seconds: int = 300) -> bool:
        """Open a real browser, let a human log in, and save the session.

        Naukri sometimes answers an automated login with an OTP or captcha; a person
        can clear that once and the nightly run then rides the saved cookies.
        """
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=False)
            context = self._new_context(browser)
            try:
                page = context.new_page()
                page.goto(LOGIN_URL, wait_until="domcontentloaded")
                if self._settings.naukri_email:
                    try:
                        page.fill("#usernameField", self._settings.naukri_email)
                        if self._settings.naukri_password:
                            page.fill("#passwordField", self._settings.naukri_password)
                    except Exception:  # noqa: BLE001 - pre-fill is a convenience only
                        pass

                print(
                    "\n  A browser window is open. Sign in to Naukri — solve any OTP "
                    "or captcha —\n  until you reach your homepage.\n"
                    f"  Waiting up to {timeout_seconds}s...\n"
                )
                deadline = time.monotonic() + timeout_seconds
                while time.monotonic() < deadline:
                    if not self._is_login_wall(page):
                        save_storage_state(context, self._settings, self.source)
                        return True
                    page.wait_for_timeout(2000)
                logger.warning("naukri: interactive login timed out")
                return False
            finally:
                context.close()
                browser.close()

    def _scrape(self) -> list[RawJobPayload]:
        from playwright.sync_api import sync_playwright

        payloads: list[RawJobPayload] = []
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=self._settings.collector_headless)
            context = self._new_context(browser)
            try:
                page = context.new_page()
                self._ensure_session(context, page)
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
                save_storage_state(context, self._settings, self.source)
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

    def fetch_details(self, urls: list[str]) -> dict[str, str]:
        """Open each job-listings page and return {url: full description}.

        Implements the `DetailFetcher` protocol. Best-effort by contract: a removed
        or gated posting is skipped, never raised, so enrichment can only improve
        ranking quality and never fail a run.
        """
        if not urls:
            return {}
        try:
            return self._scrape_details(urls)
        except Exception:
            logger.exception("naukri: detail enrichment failed")
            return {}

    def _scrape_details(self, urls: list[str]) -> dict[str, str]:
        from playwright.sync_api import sync_playwright

        out: dict[str, str] = {}
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=self._settings.collector_headless)
            context = self._new_context(browser)
            try:
                page = context.new_page()
                self._ensure_session(context, page)
                for url in urls:
                    try:
                        page.goto(url, wait_until="domcontentloaded")
                        page.wait_for_timeout(2000)
                        text = self._extract_description(page)
                        if text:
                            out[url] = text
                    except Exception:  # noqa: BLE001 - one bad posting must not stop the batch
                        logger.warning("naukri: could not read %s", url)
                    random_delay(
                        self._settings.collector_min_delay_seconds,
                        self._settings.collector_max_delay_seconds,
                    )
            finally:
                context.close()
                browser.close()
        logger.info("naukri: read %d/%d detail pages", len(out), len(urls))
        return out

    @staticmethod
    def _extract_description(page) -> str | None:
        """Pull the posting body from a job-listings page."""
        for selector in _DETAIL_SELECTORS:
            node = page.query_selector(selector)
            if node is None:
                continue
            text = (node.inner_text() or "").strip()
            if len(text) > 120:  # shorter than this is page chrome, not a posting
                return text[:MAX_DETAIL_CHARS]
        return None

    def _extract_cards(self, page, page_no: int) -> list[RawJobPayload]:
        # The results list lazy-loads on scroll — nudge it a few times.
        for _ in range(6):
            page.mouse.wheel(0, 4000)
            page.wait_for_timeout(700)
        rows: list[dict] = page.evaluate(_CARD_JS)
        results: list[RawJobPayload] = []
        for row in rows:
            if not (row.get("title") and row.get("company")):
                continue
            url = row.get("url") or None
            results.append(
                RawJobPayload(
                    source_job_id=self._job_id_from_url(url),
                    url=url,
                    title=row["title"],
                    company=row["company"],
                    location=row.get("location"),
                    description=self._describe(row),
                    raw={"page_no": page_no, **row},
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
        """Build the card-level description; the enrich stage replaces it with the
        full posting once the detail page has been read."""
        parts = [f"{parsed['title']} at {parsed['company']}."]
        if parsed.get("location"):
            parts.append(f"Location: {parsed['location']}.")
        if parsed.get("experience"):
            parts.append(f"Experience required: {parsed['experience']}.")
        if parsed.get("salary"):
            parts.append(f"Salary: {parsed['salary']}.")
        if parsed.get("skills"):
            parts.append("Key skills: " + ", ".join(parsed["skills"]) + ".")
        # The SRP already carries a real snippet of the posting — far better signal
        # than the synthesized line above, so keep it.
        if parsed.get("summary"):
            parts.append(str(parsed["summary"]))
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
