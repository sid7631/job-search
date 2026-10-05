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
import time
from collections.abc import Callable
from urllib.parse import quote_plus

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
from app.database import repository as repo
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

# Where the posting body lives on /jobs/view/<id>, most specific first. LinkedIn
# renames these periodically — if enrichment starts returning nothing, check here.
_DETAIL_SELECTORS = (
    "#job-details",
    ".jobs-description__content",
    ".jobs-box__html-content",
    "[class*='jobs-description']",
    ".description__text",
)

# Postings can run very long; the ranking prompt only needs the substance.
MAX_DETAIL_CHARS = 8_000

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
        self._run_id: int | None = None

    # ------------------------------------------------------------------ public API

    def collect(self, run_id: int) -> list[RawJob]:
        """Scrape LinkedIn and persist; on a dead session, alert and return empty."""
        self._run_id = run_id
        try:
            payloads = self._fetch_raw_jobs()
        except SessionError as exc:
            logger.warning("linkedin session failure: %s", exc)
            record_collector_error(self._session_scope, run_id, str(exc), source=self.source)
            self._send_reauth_alert()
            return []
        return persist_raw_jobs(
            self._session_scope, source=self.source, run_id=run_id, payloads=payloads
        )

    def _send_reauth_alert(self) -> None:
        # A failed alert must not turn a graceful skip into a crash. An unconfigured
        # Telegram is an expected setup, not an incident — log it as a line, not a
        # stack trace, so it doesn't read like the run blew up.
        from app.notifications.telegram import TelegramError

        try:
            self._alert()
        except TelegramError as exc:
            logger.info("linkedin: re-auth alert not sent (%s)", exc)
        except Exception:
            logger.exception("failed to send LinkedIn re-auth alert")

    # --------------------------------------------------------------- scraping (live)

    def _fetch_raw_jobs(self) -> list[RawJobPayload]:
        """Entry point for the live scrape. Overridden in tests."""
        has_session = load_storage_state(self._settings, self.source) is not None
        has_creds = bool(self._settings.linkedin_email and self._settings.linkedin_password)
        if not has_session and not has_creds:
            raise SessionError(
                "LinkedIn has no saved session and no credentials. Either run "
                "`python -m app.main login --source linkedin` once, or set "
                "LINKEDIN_EMAIL / LINKEDIN_PASSWORD."
            )
        return self._scrape()

    def interactive_login(self, *, timeout_seconds: int = 300) -> bool:
        """Open a real browser, let a human log in, and save the session.

        This is the escape hatch for LinkedIn's security checkpoint: automation can
        fill a password but cannot solve an OTP or a "confirm it's you" challenge.
        Doing it by hand once and persisting the cookies means the nightly run never
        has to log in again — which is also what stops the checkpoint recurring.

        Returns True if a logged-in session was captured.
        """
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            # Always headed: the whole point is that a person drives this.
            browser = pw.chromium.launch(headless=False)
            context = self._new_context(browser)
            try:
                page = context.new_page()
                page.goto(LOGIN_URL, wait_until="domcontentloaded")
                if self._settings.linkedin_email:
                    # Pre-fill what we know; the human handles the rest.
                    try:
                        page.locator("input[type='email']").last.fill(self._settings.linkedin_email)
                        if self._settings.linkedin_password:
                            page.locator("input[type='password']").last.fill(
                                self._settings.linkedin_password
                            )
                    except Exception:  # noqa: BLE001 - pre-fill is a convenience only
                        pass

                print(
                    "\n  A browser window is open. Sign in to LinkedIn — solve any "
                    "OTP or\n  security challenge — until you reach your feed.\n"
                    f"  Waiting up to {timeout_seconds}s...\n"
                )
                deadline = time.monotonic() + timeout_seconds
                while time.monotonic() < deadline:
                    if not self._is_dead_session(page) and page.query_selector(_LOGGED_IN_MARKER):
                        save_storage_state(context, self._settings, self.source)
                        return True
                    page.wait_for_timeout(2000)
                logger.warning("linkedin: interactive login timed out")
                return False
            finally:
                context.close()
                browser.close()

    def _delay(self) -> None:
        """Aggressive, randomized inter-request delay (slower than other sources)."""
        mult = self._settings.linkedin_delay_multiplier
        random_delay(
            self._settings.collector_min_delay_seconds * mult,
            self._settings.collector_max_delay_seconds * mult,
        )

    def _new_context(self, browser):
        """Browser context seeded with the saved session, when we have one."""
        return browser.new_context(
            user_agent=_USER_AGENT,
            locale="en-US",
            viewport={"width": 1340, "height": 900},
            storage_state=load_storage_state(self._settings, self.source),
        )

    def _ensure_session(self, context, page) -> None:
        """Reuse the saved session if it still works; only log in when it doesn't.

        Logging in with credentials is what trips LinkedIn's checkpoint, so it is
        the fallback, not the default. A saved session that turns out to be dead is
        deleted so the next attempt starts clean rather than looping on it.
        """
        if load_storage_state(self._settings, self.source):
            page.goto(LINKEDIN_BASE + "/feed/", wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
            if not self._is_dead_session(page) and page.query_selector(_LOGGED_IN_MARKER):
                logger.info("linkedin: reusing saved session (no login needed)")
                return
            logger.info("linkedin: saved session is dead; falling back to credentials")
            clear_storage_state(self._settings, self.source)

        self._login_and_verify(page)
        # Persist immediately: even if the scrape later fails, the session is worth
        # keeping so the next run does not have to log in again.
        save_storage_state(context, self._settings, self.source)

    def _scrape(self) -> list[RawJobPayload]:
        from playwright.sync_api import sync_playwright

        payloads: list[RawJobPayload] = []
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=self._settings.collector_headless)
            context = self._new_context(browser)
            try:
                page = context.new_page()
                self._ensure_session(context, page)
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
                # Refresh the stored cookies so the session keeps rolling forward.
                save_storage_state(context, self._settings, self.source)
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
            # Most of these are LinkedIn pushing an "is this you?" prompt to the
            # phone. That clears on its own once approved, so wait for it inside the
            # run instead of failing and forcing a separate manual login.
            if not self._await_approval(page):
                raise SessionError(
                    "LinkedIn presented a security checkpoint and it was not approved in "
                    f"{self._settings.linkedin_approval_wait_seconds}s. Approve the prompt on "
                    "your phone during the next run, or run "
                    "`python -m app.main login --source linkedin` once."
                )
        if "/feed" not in url and page.query_selector(_LOGGED_IN_MARKER) is None:
            page.goto(LINKEDIN_BASE + "/feed/", wait_until="domcontentloaded")
            page.wait_for_timeout(2000)
            if self._is_dead_session(page) or page.query_selector(_LOGGED_IN_MARKER) is None:
                raise SessionError(
                    "LinkedIn login failed (check credentials, or a challenge blocked the login)."
                )

    def _await_approval(self, page) -> bool:
        """Hold the run open while a human approves LinkedIn's device prompt.

        LinkedIn's checkpoint is usually a push notification, not a dead end: the
        page redirects itself to the feed the moment it is approved. Polling for
        that keeps the whole flow inside the pipeline, which is the point — the
        nightly run should be able to recover without a separate manual step.
        """
        wait_seconds = self._settings.linkedin_approval_wait_seconds
        if wait_seconds <= 0:
            return False

        logger.warning(
            "linkedin: security checkpoint — approve the prompt on your phone. "
            "Waiting up to %ds...",
            wait_seconds,
        )
        self._notify_approval_needed(wait_seconds)
        self._set_attention(
            f"Approve the LinkedIn sign-in prompt on your phone "
            f"(waiting up to {max(1, wait_seconds // 60)} min)."
        )

        try:
            deadline = time.monotonic() + wait_seconds
            while time.monotonic() < deadline:
                page.wait_for_timeout(3000)
                if self._is_dead_session(page):
                    continue
                if page.query_selector(_LOGGED_IN_MARKER):
                    logger.info("linkedin: checkpoint approved; continuing")
                    return True
            return False
        finally:
            self._set_attention(None)

    def _set_attention(self, message: str | None) -> None:
        """Show (or clear) a needs-you banner on the dashboard for this run."""
        if self._run_id is None:
            return
        try:
            with self._session_scope() as session:
                repo.set_run_progress(
                    session, self._run_id, attention=message, clear_attention=message is None
                )
        except Exception:  # noqa: BLE001 - a banner must never break the scrape
            logger.debug("linkedin: could not update run attention", exc_info=True)

    def _notify_approval_needed(self, wait_seconds: int) -> None:
        """Ping Telegram so the prompt is noticed while the run is still waiting."""
        try:
            from app.notifications.telegram import TelegramNotifier

            if self._settings.telegram_bot_token and self._settings.telegram_chat_id:
                TelegramNotifier(self._settings).send(
                    "<b>🔐 LinkedIn needs approval</b>\n\n"
                    "Approve the sign-in prompt on your phone. The run is waiting "
                    f"up to {wait_seconds // 60} min."
                )
        except Exception:  # noqa: BLE001 - a failed ping must not break the wait
            logger.debug("linkedin: could not send approval ping", exc_info=True)

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
        """A one-line placeholder; the enrich stage replaces this with the real text."""
        parts = [f"{parsed['title']} at {parsed['company']}."]
        if parsed.get("location"):
            parts.append(f"Location: {parsed['location']}.")
        return " ".join(parts)

    # ------------------------------------------------------------ detail enrichment

    def fetch_details(self, urls: list[str]) -> dict[str, str]:
        """Open each `/jobs/view/<id>` page and return {url: full description}.

        Implements the `DetailFetcher` protocol for the enrich stage. Best-effort by
        contract: a login wall or a removed posting yields fewer entries, never an
        exception, so a bad fetch degrades ranking quality instead of failing the run.
        """
        if not urls:
            return {}
        if not (self._settings.linkedin_email and self._settings.linkedin_password):
            logger.info("linkedin: no credentials; skipping detail enrichment")
            return {}
        try:
            return self._scrape_details(urls)
        except SessionError as exc:
            logger.warning("linkedin: detail enrichment stopped (%s)", exc)
            return {}
        except Exception:
            logger.exception("linkedin: detail enrichment failed")
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
                        if self._is_dead_session(page):
                            raise SessionError("hit a login wall during detail enrichment.")
                        page.wait_for_timeout(2500)
                        text = self._extract_description(page)
                        if text:
                            out[url] = text
                    except SessionError:
                        raise
                    except Exception:  # noqa: BLE001 - one bad posting must not stop the batch
                        logger.warning("linkedin: could not read %s", url)
                    self._delay()
            finally:
                context.close()
                browser.close()
        logger.info("linkedin: read %d/%d detail pages", len(out), len(urls))
        return out

    @staticmethod
    def _extract_description(page) -> str | None:
        """Pull the posting body, expanding the "see more" collapse if present."""
        for label in ("See more", "Show more"):
            try:
                button = page.get_by_role("button", name=label).first
                if button.is_visible(timeout=1000):
                    button.click(timeout=2000)
                    page.wait_for_timeout(600)
                    break
            except Exception:  # noqa: BLE001 - the collapse is optional
                pass
        for selector in _DETAIL_SELECTORS:
            node = page.query_selector(selector)
            if node is None:
                continue
            text = (node.inner_text() or "").strip()
            if len(text) > 120:  # anything shorter is chrome, not a posting
                return text[:MAX_DETAIL_CHARS]
        return None

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
