# AI Job Hunter — User Guide (run it natively on your Mac)

Your personal AI recruiter: it scrapes jobs matching your search from Naukri and LinkedIn,
dedups them, scores each 0–100 against your résumé with an LLM of your choice, (optionally)
pushes the top picks to Telegram, and gives you a dashboard to triage and track.

> **Why native, not Docker?** Naukri/LinkedIn block *headless* browsers, so scraping
> must run in a **visible (headed) browser on your machine**. The Docker image is
> headless and **can't scrape** — so for real use, run everything natively (below).
> Repo lives at `~/Documents/github/job_search`. All backend commands run from
> `backend/` via `uv run …`.

---

## ⚡ TL;DR

```bash
cd ~/Documents/github/job_search
./jobhunter            # sets up anything missing, then opens http://localhost:8000
```

First launch opens a setup wizard (AI model → résumé → search terms → first run). After
that, everything is in the app: **Today** to triage new roles with the keyboard,
**Applications** to track them, **Settings → Daily run** to schedule it. The CLI
commands below are equivalents and fallbacks; `./jobhunter help` lists the shortcuts.

---

## 1. One-time setup

You only do this once.

```bash
cd ~/Documents/github/job_search/backend

# 1a. Python deps + the headed browser (Chromium) the scrapers use
uv sync
uv run playwright install chromium

# 1b. Build the local database
uv run alembic upgrade head

# 1c. Frontend deps
cd ../frontend && npm install
```

You also need **Google Chrome installed** (the scrapers launch a real Chrome window).

### Secrets & settings — `backend/.env`

Everything lives in `backend/.env` (gitignored — never put secrets in `.env.example`).
The important keys:

```dotenv
# --- LLM (résumé parsing + job ranking) ---
# Free + private: run Ollama locally (`brew install ollama; ollama pull llama3.2`).
LLM_PROVIDER=ollama                # or ollama_cloud | openai | anthropic | groq |
                                   # deepseek | mistral | openrouter | together | xai |
                                   # lmstudio | openai_compatible
LLM_API_KEY=                       # leave blank for local ollama / lmstudio
LLM_MODEL=                         # blank = provider default (ollama -> llama3.2)
LLM_BASE_URL=                      # blank = provider default; required for openai_compatible

# --- Telegram (optional daily digest) ---
TELEGRAM_BOT_TOKEN=...             # @BotFather → /newbot
TELEGRAM_CHAT_ID=                  # YOUR numeric id (see §4) — not the bot name

# --- Naukri ---
# Default (NAUKRI_REQUIRE_LOGIN=false) uses the public results page and needs no login.
# Set NAUKRI_REQUIRE_LOGIN=true to use the logged-in UI (no per-job URLs, more OTP/captcha risk).
NAUKRI_EMAIL=you@example.com
NAUKRI_PASSWORD=...
NAUKRI_KEYWORDS=frontend developer, react js
NAUKRI_LOCATION=bangalore
NAUKRI_EXPERIENCE=10
NAUKRI_REQUIRE_LOGIN=false

# --- LinkedIn ---
LINKEDIN_EMAIL=you@example.com
LINKEDIN_PASSWORD=...
LINKEDIN_KEYWORDS=frontend developer react
LINKEDIN_LOCATION=Bangalore

# --- behaviour ---
COLLECTOR_HEADLESS=false           # MUST stay false (headless is 403-blocked)
RUN_HOUR=8                         # daily scheduler time (Asia/Kolkata)
```

> **Switching accounts / changing search:** easiest from the dashboard's **Settings**
> page (keywords, location, experience, email, password — stored in your DB, overriding
> `.env`, applied on the next run). Or edit `NAUKRI_*` / `LINKEDIN_*` in `.env`. Collectors
> reuse a saved session when one exists; refresh it with
> `uv run python -m app.main login --source naukri|linkedin` after a password change or checkpoint.

### Load your résumé (one-time, and whenever it changes)

**Easiest: the dashboard → Profile page → "Upload résumé"** (PDF or DOCX). It parses with
the LLM and updates your profile in place. Or via CLI:

```bash
cd ~/Documents/github/job_search/backend
uv run python -m app.main parse-resume --path ~/Downloads/resume.pdf
# → "[parse-resume] profile #1 updated: name='…', years=…, skills=N, roles=M."
```

---

## 2. Start the app (each session)

Two long-running processes. Start them, leave them running:

```bash
cd ~/Documents/github/job_search

# API (serves the dashboard's data from the local DB)
( cd backend && uv run python -m app.main serve-api --port 8000 ) &

# Dashboard (proxies /api → the API)
( cd frontend && npm run dev ) &
```

- Dashboard: **http://localhost:5173**
- API docs: **http://localhost:8000/docs**

To stop them later: `pkill -f "app.main serve-api"; pkill -f vite`

---

## 3. Run the pipeline (get fresh jobs)

**On demand — easiest is the dashboard:** click **Run** in the header (on any page), or
**Run now** on the **Runs** tab. A Chrome window opens for Naukri, then one for LinkedIn;
it scrapes, dedups, and ranks against your résumé in the background. CLI equivalent:

```bash
cd ~/Documents/github/job_search/backend
uv run python -m app.main run-pipeline
```

**Automatically, every day** at `RUN_HOUR` — keep this running (e.g. in its own
terminal tab). A Chrome window opens for each daily run:

```bash
cd ~/Documents/github/job_search/backend
uv run python -m app.main start-scheduler
```

Only a single source, if you want:

```bash
uv run python -m app.main collect --source naukri     # or: linkedin
```

---

## 4. Telegram digest (optional)

The bot can't message itself — it needs **your** chat id.

1. Open Telegram, message your bot (e.g. `hi`).
2. Get your id:
   ```bash
   cd ~/Documents/github/job_search/backend
   uv run python -c "import httpx; from app.config import Settings as S; s=S(); \
   print(httpx.get(f'https://api.telegram.org/bot{s.telegram_bot_token}/getUpdates').json())"
   ```
   Find `\"chat\":{\"id\": <NUMBER>` → that's your `TELEGRAM_CHAT_ID`.
3. Put it in `.env`. Test it:
   ```bash
   uv run python -m app.main notify-test            # sample picks
   uv run python -m app.main notify-test --failure  # failure alert
   ```

Once set, every successful run pushes the top picks; failed runs send an alert.

---

## 5. Using the dashboard — http://localhost:5173

- **Matches (home):** today's ranked jobs as cards — score badge (lime ≥85 / amber
  70–84 / grey below), title, company, location, top pros/cons. Filter by min score.
  Click a card for the full reasoning. **Apply** opens the posting (LinkedIn always;
  Naukri when `NAUKRI_REQUIRE_LOGIN=false`). **Track** adds it to your pipeline.
- **Pipeline:** board by status (Saved → Applied → Interviewing → Offer / Rejected /
  Dropped). Change status from the dropdown, add notes, see when you applied.
- **Runs:** history of runs (counts, status, errors) + the **Run now** button.
- **Profile:** your parsed résumé (name, experience, skills, roles, locations) and an
  **Upload résumé** button to refresh it.
- **Settings:** edit search keywords/location/experience and the Naukri/LinkedIn
  accounts (and Telegram tuning) — saved to your DB, used on the next run.
- **Run** (header, every page): triggers a scrape+rank in the background.

> **Jobs persist.** A run never deletes jobs — it adds new ones and re-affirms existing
> ones (no duplicates). The Matches page reflects the latest run; tracked jobs stay in
> your Pipeline regardless.

---

## 6. Known limitations & realities

- **Headed only.** Scraping needs a visible browser on your residential IP. Don't set
  `COLLECTOR_HEADLESS=true`, and don't run scraping on a headless server/VPS.
- **Fragile scrapers.** Naukri/LinkedIn are parsed from the live page; a site redesign
  will break a collector. It fails *gracefully* (records the error, 0 jobs, no crash) —
  the fix is refreshing the selectors.
- **Naukri default = public results page with per-job URLs**, which is what makes Apply
  work and lets the enrich stage fetch full descriptions for the shortlist (the cards
  themselves are only snippets, and enrich is capped at `ENRICH_MAX_JOBS`). Set
  `NAUKRI_REQUIRE_LOGIN=true` to use the logged-in UI instead — no URLs, so no Apply and
  no enrichment, plus more OTP/captcha risk. **LinkedIn = has Apply links.** Track +
  ranking work for both.
- **LinkedIn may challenge** an automated login (OTP/captcha) — then you'll get a Telegram
  "re-auth needed" alert and that source is skipped for the run. Use
  `uv run python -m app.main login --source linkedin` to log in manually once and reuse that session.
- **Hosted-provider free tiers are small** (often a few requests/minute plus a daily cap).
  A first run of many new jobs can exhaust one. The ranker retries per-minute rate-limits
  automatically; if the **daily** quota hits 0, wait for reset, enable billing, or switch
  to local Ollama. Unchanged jobs are cached, so later runs are cheap.
- **The daily run is `collect → dedup → pre-filter → enrich → rank → notify`.** The
  pre-filter is cheap string matching that shortlists jobs worth an LLM call; enrich
  then opens the real job pages for that shortlist (search cards carry almost no
  text). Only the shortlist is scored, so `PREFILTER_MAX_JOBS` is your main cost dial.
- **Optional semantic gate (local Ollama only).** Set `SEMANTIC_FILTER_ENABLED=true`
  (after `ollama pull tev1:4b`) and a small decision model drops obvious mismatches
  between enrich and rank — roughly a second per job versus a full ranking call. Check
  `semantic_filter.dropped_jobs` in the run's counts before raising
  `SEMANTIC_FILTER_MIN_FIT` above its cautious 0.1 default.
- **Keep it running across sleep/reboot**: `uv run python -m app.main install-schedule`
  writes a macOS LaunchAgent that restarts the scheduler at login and after a crash. It
  does *not* activate it for you — it prints a `launchctl unload …; launchctl load …`
  line, and the agent only runs once you paste that in. Verify with
  `launchctl list | grep jobhunter`. It's a per-user agent, so it needs you logged in
  (the scrapers need a real desktop session). If the Mac was asleep at `RUN_HOUR`, the
  run is caught up ~10s after the scheduler next starts, or run `catch-up` by hand.
- **Switching provider** is easiest on the dashboard's **Settings → AI Provider** panel —
  pick a provider, leave Base URL / Model blank for its defaults, Save, then hit
  **Test connection** to confirm it answers before the next run.
- **No auth on the API/UI** — fine on localhost; don't expose ports 8000/5173 publicly.

---

## 7. Troubleshooting

| Symptom | Fix |
|---|---|
| Matches page empty | No successful run yet, or ranking failed. Run `run-pipeline`; check the Runs tab for the error. |
| Run FAILED: "no candidate profile" | Run `parse-resume` first. |
| Run FAILED: credentials not configured | Only login-mode sources need creds: fill `LINKEDIN_*`, and `NAUKRI_*` only if you set `NAUKRI_REQUIRE_LOGIN=true` (the default Naukri path needs none). |
| `install-schedule` ran but nothing fires | It only writes the plist. Run the `launchctl load …` line it printed, then check `launchctl list \| grep jobhunter`. |
| Run FAILED: 429 / quota / `limit: 0` | Provider quota spent — wait for reset, enable billing, or switch to local Ollama. |
| Run FAILED: "unreachable ... Is the local server running?" | Start Ollama (`ollama serve`) and pull the model (`ollama pull llama3.2`). |
| Run FAILED: "An API key is required" | Set `LLM_API_KEY` in `.env` or the Settings page (local `ollama`/`lmstudio` need none). |
| Naukri/LinkedIn "login failed" or "Access Denied" | Make sure `COLLECTOR_HEADLESS=false`; check creds; run `uv run python -m app.main login --source naukri\|linkedin` to refresh the saved session. |
| 0 jobs scraped after a site change | The collector's text parser needs refreshing for the new markup. |
| No Telegram messages | `TELEGRAM_CHAT_ID` must be your numeric id (§4), not the bot name. |
| Changed `.env`, nothing changed | Restart the API: `pkill -f "app.main serve-api"` then start it again. |

---

## 8. Command reference (from `backend/`)

```bash
uv run python -m app.main --help                       # list commands
uv run python -m app.main parse-resume --path FILE      # load/refresh your résumé
uv run python -m app.main run-pipeline                  # scrape + dedup + rank now (headed)
uv run python -m app.main collect --source naukri       # one source only
uv run python -m app.main login --source linkedin       # one-time manual login; saves session
uv run python -m app.main serve-api --port 8000         # JSON API + dashboard backend
uv run python -m app.main start-scheduler               # daily run at RUN_HOUR
uv run python -m app.main install-schedule              # write the LaunchAgent (then run the
                                                        #   launchctl load line it prints)
uv run python -m app.main catch-up                      # run now if today's run was missed
uv run python -m app.main notify-test [--failure]       # test Telegram
uv run alembic upgrade head                             # (re)build the DB
uv run pytest                                           # run the test suite
```

The database is `backend/job_hunter.db` (delete it + `alembic upgrade head` to reset).
