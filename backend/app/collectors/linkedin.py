"""LinkedIn Playwright collector — hardened (M10, revised for the live site).

Same `Collector` contract + raw_jobs payload shape as Naukri. LinkedIn specifics:
- Runs **headed** (like Naukri) and logs in fresh from `.env` creds each run. The
  login form has React dynamic ids and a hidden duplicate form, so we target the
  **visible** (last) email/password fields and the "Sign in" button.
- A dead session / security checkpoint raises a **Telegram "re-auth needed" alert**
  (not just a silent run error), since LinkedIn frequently challenges automated logins.
- Conservative: few pages (`LINKEDIN_MAX_PAGES`) and slower delays
  (`LINKEDIN_DELAY_MULTIPLIER`).

Job cards (`li[data-occludable-job-id]`) expose the job id and a `/jobs/view/<id>`
URL, so unlike Naukri we get a real url + source_job_id. Card fields are parsed from
text (`_parse_card`, pure/tested). ⚠️ Against LinkedIn's ToS and fragile — see README.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from urllib.parse import quote_plus

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

LINKEDIN_BASE = "https://www.linkedin.com"
LOGIN_URL = "https://www.linkedin.com/login"
JOBS_SEARCH = "https://www.linkedin.com/jobs/search/"
RESULTS_PER_PAGE = 25
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
_LOGGED_IN_MARKER = ".global-nav, #global-nav, [data-test-global-nav]"

# Each result is an <li data-occludable-job-id="…"> with a /jobs/view/<id> link.
_CARD_JS = r"""() => {
  const cards = [...document.querySelectorAll("li[data-occludable-job-id]")];
  return cards.map(c => {
    const a = c.querySelector("a[href*='/jobs/view/']");
    return {
      jobId: c.getAttribute('data-occludable-job-id'),
      href: a ? a.getAttribute('href') : null,
      lines: (c.innerText || '').split('\n').map(x => x.trim()).filter(Boolean),
    };
  });
}"""

# Lines on a card that aren't the job's title/company/location.
_CARD_NOISE = {
    "promoted",
    "viewed",
    "easy apply",
    "actively recruiting",
    "be an early applicant",
    "new",
    "verified",
    "saved",
    "reposted",
}

# LinkedIn job ids appear as /jobs/view/<id> or currentJobId=<id>.
_JOB_ID_RE = re.compile(r"(?:/jobs/view/|currentJobId=)(\d+)")


def _default_reauth_alert(settings: Settings) -> Callable[[], None]:
    """Build the default re-auth alert: a Telegram message via the M7 notifier."""

    def alert() -> None:
        from app.notifications.telegram import TelegramNotifier

        TelegramNotifier(settings).notify_reauth("LinkedIn")

    return alert


class LinkedInCollector(Collector):
    """Collects jobs from LinkedIn into `raw_jobs`, hardened against dead sessions."""

    source = "linkedin"

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        session_scope: SessionScope | None = None,
        alert: Callable[[], None] | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._session_scope: SessionScope = session_scope or connection.session_scope
        self._alert = alert or _default_reauth_alert(self._settings)

    # ------------------------------------------------------------------ public API

    def collect(self, run_id: int) -> list[RawJob]:
        """Scrape LinkedIn and persist; on a dead session, alert and return empty."""
        try:
            payloads = self._fetch_raw_jobs()
        except SessionError as exc:
            logger.warning("linkedin session failure: %s", exc)
            record_collector_error(self._session_scope, run_id, f"linkedin: {exc}")
            self._send_reauth_alert()
            return []
        return persist_raw_jobs(
            self._session_scope, source=self.source, run_id=run_id, payloads=payloads
        )

    def _send_reauth_alert(self) -> None:
        # A failed alert must not turn a graceful skip into a crash.
        try:
            self._alert()
        except Exception:
            logger.exception("failed to send LinkedIn re-auth alert")

    # --------------------------------------------------------------- scraping (live)

    def _fetch_raw_jobs(self) -> list[RawJobPayload]:
        """Entry point for the live scrape. Overridden in tests."""
        if not (self._settings.linkedin_email and self._settings.linkedin_password):
            raise SessionError(
                "LinkedIn credentials are not configured (set LINKEDIN_EMAIL / LINKEDIN_PASSWORD)."
            )
        return self._scrape()

    def _delay(self) -> None:
        """Aggressive, randomized inter-request delay (slower than other sources)."""
        mult = self._settings.linkedin_delay_multiplier
        random_delay(
            self._settings.collector_min_delay_seconds * mult,
            self._settings.collector_max_delay_seconds * mult,
        )

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
                for page_no in range(1, self._settings.linkedin_max_pages + 1):
                    page.goto(self._build_search_url(page_no), wait_until="domcontentloaded")
                    if self._is_dead_session(page):
                        raise SessionError("hit a login/checkpoint wall mid-scrape; session dead.")
                    page.wait_for_timeout(5000)
                    cards = self._extract_cards(page, page_no)
                    if not cards:
                        break
                    payloads.extend(cards)
                    self._delay()
            finally:
                context.close()
                browser.close()
        logger.info("linkedin: scraped %d jobs", len(payloads))
        return payloads

    def _login_and_verify(self, page) -> None:
        try:
            page.goto(LOGIN_URL, wait_until="domcontentloaded")
            # The visible form is the last email/password pair (a hidden duplicate exists).
            page.locator("input[type='email']").last.fill(self._settings.linkedin_email)
            page.locator("input[type='password']").last.fill(self._settings.linkedin_password)
            page.get_by_role("button", name="Sign in", exact=True).last.click()
            try:
                page.wait_for_load_state("networkidle", timeout=25000)
            except Exception:  # noqa: BLE001 - networkidle can time out on a live SPA
                pass
            page.wait_for_timeout(5000)
        except Exception as exc:  # noqa: BLE001 - any login interaction failure is a dead session
            raise SessionError(f"LinkedIn login interaction failed: {exc}") from exc

        url = page.url.lower()
        if any(k in url for k in ("checkpoint", "challenge", "add-phone")):
            raise SessionError(
                "LinkedIn presented a security checkpoint/challenge — manual re-auth needed."
            )
        if "/feed" not in url and page.query_selector(_LOGGED_IN_MARKER) is None:
            page.goto(LINKEDIN_BASE + "/feed/", wait_until="domcontentloaded")
            page.wait_for_timeout(2000)
            if self._is_dead_session(page) or page.query_selector(_LOGGED_IN_MARKER) is None:
                raise SessionError(
                    "LinkedIn login failed (check credentials, or a challenge blocked the login)."
                )

    @staticmethod
    def _is_dead_session(page) -> bool:
        url = page.url.lower()
        return any(k in url for k in ("/login", "checkpoint", "challenge", "authwall"))

    def _extract_cards(self, page, page_no: int) -> list[RawJobPayload]:
        for _ in range(5):  # the list lazy-loads as you scroll
            page.mouse.wheel(0, 2500)
            page.wait_for_timeout(800)
        rows = page.evaluate(_CARD_JS)
        results: list[RawJobPayload] = []
        for row in rows:
            parsed = self._parse_card(row.get("lines") or [])
            if parsed is None:
                continue
            job_id = row.get("jobId") or self._job_id_from_url(row.get("href"))
            url = f"{LINKEDIN_BASE}/jobs/view/{job_id}/" if job_id else None
            results.append(
                RawJobPayload(
                    source_job_id=job_id,
                    url=url,
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
        """Parse a LinkedIn job card's text into title/company/location (pure/testable)."""
        clean: list[str] = []
        for ln in lines:
            low = ln.strip().lower()
            if not low or low in _CARD_NOISE:
                continue
            if any(w in low for w in ("alumni", "school", "connection", "applicant")):
                continue
            clean.append(ln.strip())
        if len(clean) < 2:
            return None
        return {
            "title": clean[0],
            "company": clean[1],
            "location": clean[2] if len(clean) > 2 else None,
        }

    @staticmethod
    def _describe(parsed: dict) -> str:
        parts = [f"{parsed['title']} at {parsed['company']}."]
        if parsed.get("location"):
            parts.append(f"Location: {parsed['location']}.")
        return " ".join(parts)

    def _build_search_url(self, page_no: int) -> str:
        keywords = quote_plus(self._settings.linkedin_keywords.strip())
        location = quote_plus(self._settings.linkedin_location.strip())
        params = [f"keywords={keywords}"]
        if location:
            params.append(f"location={location}")
        start = (page_no - 1) * RESULTS_PER_PAGE
        if start:
            params.append(f"start={start}")
        return f"{JOBS_SEARCH}?" + "&".join(params)

    @staticmethod
    def _job_id_from_url(url: str | None) -> str | None:
        if not url:
            return None
        match = _JOB_ID_RE.search(url)
        return match.group(1) if match else None
