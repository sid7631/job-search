# AI Job Hunter — User Guide (run it natively on your Mac)

Your personal AI recruiter: it logs into Naukri + LinkedIn, scrapes jobs matching your
search, dedups them, scores each 0–100 against your résumé with Gemini, (optionally)
pushes the top picks to Telegram, and gives you a dashboard to triage and track.

> **Why native, not Docker?** Naukri/LinkedIn block *headless* browsers, so scraping
> must run in a **visible (headed) browser on your machine**. The Docker image is
> headless and **can't scrape** — so for real use, run everything natively (below).
> Repo lives at `~/Documents/github/job_search`. All backend commands run from
> `backend/` via `uv run …`.

---

## ⚡ TL;DR — the commands you'll use

```bash
cd ~/Documents/github/job_search

# start the API + dashboard (leave these running)
( cd backend  && uv run python -m app.main serve-api --port 8000 ) &
( cd frontend && npm run dev ) &                       # dashboard → http://localhost:5173

# run a scrape+rank now (Chrome windows open — Naukri, then LinkedIn)
cd backend && uv run python -m app.main run-pipeline

# …or run it automatically every day at RUN_HOUR:
cd backend && uv run python -m app.main start-scheduler
```

Open **http://localhost:5173**. Done. From the dashboard you can **upload a résumé**
(Profile page) and **run a scrape** (the **Run** button in the header) — no CLI needed
for day-to-day use. The CLI commands below are equivalents / fallbacks.

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
# --- Gemini (résumé parsing + job ranking) ---
GEMINI_API_KEY=...                 # aistudio.google.com → Get API key
LLM_MODEL=gemini-2.0-flash         # higher free rate limit than 3.5-flash

# --- Telegram (optional daily digest) ---
TELEGRAM_BOT_TOKEN=...             # @BotFather → /newbot
TELEGRAM_CHAT_ID=                  # YOUR numeric id (see §4) — not the bot name

# --- Naukri ---
NAUKRI_EMAIL=you@example.com
NAUKRI_PASSWORD=...
NAUKRI_KEYWORDS=frontend developer, react js
NAUKRI_LOCATION=bangalore
NAUKRI_EXPERIENCE=10

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
> `.env`, applied on the next run). Or edit `NAUKRI_*` / `LINKEDIN_*` in `.env`. The
> collectors log in fresh every run, so the next run uses the new account.

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
it logs in, scrapes, dedups, and ranks against your résumé in the background. CLI
equivalent:

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
  Click a card for the full reasoning. **Apply** opens the posting (LinkedIn jobs only —
  Naukri's new UI exposes no link). **Track** adds it to your pipeline.
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
- **Naukri = no Apply link / no full description** (new UI hides both; a summary is built
  from the card). **LinkedIn = has Apply links.** Track + ranking work for both.
- **LinkedIn may challenge** an automated login (OTP/captcha) — then you'll get a Telegram
  "re-auth needed" alert and that source is skipped for the run. Try again later.
- **Gemini free tier is small** (`gemini-3.5-flash` ≈ 5 req/min, `2.0-flash` ≈ 15, plus a
  daily cap). A first run of many new jobs can exhaust it. The ranker retries per-minute
  rate-limits automatically; if the **daily** quota hits 0, wait for reset or enable
  billing on the key. Unchanged jobs are cached, so later runs are cheap.
- **No auth on the API/UI** — fine on localhost; don't expose ports 8000/5173 publicly.

---

## 7. Troubleshooting

| Symptom | Fix |
|---|---|
| Matches page empty | No successful run yet, or ranking failed. Run `run-pipeline`; check the Runs tab for the error. |
| Run FAILED: "no candidate profile" | Run `parse-resume` first. |
| Run FAILED: credentials not configured | Fill `NAUKRI_*` / `LINKEDIN_*` in `.env`. |
| Run FAILED: 429 / quota / `limit: 0` | Gemini free quota spent — wait for daily reset or enable billing; consider a flash-lite model. |
| Naukri/LinkedIn "login failed" or "Access Denied" | Make sure `COLLECTOR_HEADLESS=false`; check creds; LinkedIn may need you to log in once manually if it's challenging automation. |
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
uv run python -m app.main serve-api --port 8000         # JSON API + dashboard backend
uv run python -m app.main start-scheduler               # daily run at RUN_HOUR
uv run python -m app.main notify-test [--failure]       # test Telegram
uv run alembic upgrade head                             # (re)build the DB
uv run pytest                                           # run the test suite
```

The database is `backend/job_hunter.db` (delete it + `alembic upgrade head` to reset).
