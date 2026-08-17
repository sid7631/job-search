# AI Job Hunter

A personal AI recruiter. It scrapes roles matching your search from Naukri and LinkedIn,
de-duplicates them, scores each one 0–100 against **your résumé** with an LLM (any
provider — Ollama, OpenAI, Anthropic, Groq, …), optionally pushes the day's top picks to
Telegram, and gives you a React dashboard to triage and track applications.

Single-user, runs on your own machine. You bring the accounts (Naukri / LinkedIn), the
résumé, and an LLM — a local Ollama model costs nothing, or plug in any hosted provider.
It does the searching and ranking for you every day.

---

## What it actually does (the flow in one picture)

```
            your résumé (PDF/DOCX)                  your search (.env / Settings page)
                    │                                          │
                    ▼                                          ▼
            ┌──────────────┐                       ┌──────────────────────┐
            │ parse-resume │                       │  collectors:         │
            │ (LLM → DB)   │                       │  Naukri + LinkedIn   │  ← real Chrome window
            └──────┬───────┘                       └──────────┬───────────┘     opens (logs in if needed)
                   │  candidate_profile                       │  raw jobs
                   │                                          ▼
                   │                              ┌──────────────────────┐
                   │                              │ normalize + dedup    │
                   │                              └──────────┬───────────┘
                   │                                         │  unique jobs
                   │                                         ▼
                   │                              ┌──────────────────────┐
                   │                              │ pre-filter (cheap,   │
                   │                              │ no LLM) → shortlist  │
                   │                              └──────────┬───────────┘
                   │                                         │  shortlist only
                   │                                         ▼
                   │                              ┌──────────────────────┐
                   │                              │ enrich: open the     │  ← Chrome again, to
                   │                              │ real job pages       │     read full postings
                   │                              └──────────┬───────────┘
                   │                                         │  full descriptions
                   └──────────────► ┌───────────────────────▼──────────┐
                                    │ rank (LLM: score 0–100 + reasons) │
                                    └───────────────────┬───────────────┘
                                                        │  matches
                          ┌─────────────────────────────┼─────────────────────┐
                          ▼                                                     ▼
                  ┌───────────────┐                                   ┌──────────────────┐
                  │ Telegram push │ (optional)                        │ React dashboard  │
                  │ top picks     │                                   │ triage & track   │
                  └───────────────┘                                   └──────────────────┘
```

One command — `run-pipeline` — runs the whole **collect → normalize → dedup → pre-filter
→ enrich → rank → notify** chain. The dashboard's **Run** button does the same thing.
Everything else (`serve-api`, the dashboard) is just there to *view* what a run produced.

The two middle stages are what keep it cheap: the **pre-filter** is deterministic string
matching that shortlists jobs worth an LLM call, and **enrich** then opens the real job
pages for that shortlist only (search cards carry almost no text). `PREFILTER_MAX_JOBS`
is therefore the main cost dial — it caps how many jobs reach the model per run.

---

## Example flow (first run, start to finish)

This is the whole thing, native on your Mac. (Native, not Docker — see
[Why native?](#why-native-not-docker) below.)

```bash
cd ~/Documents/github/job_search

# 1. One-time setup: deps, the headed browser, and the local database
cd backend
uv sync
uv run playwright install chromium
uv run alembic upgrade head

# 2. Configure: copy the template and fill in your secrets + search
cp .env.example .env
#    edit .env → LLM_PROVIDER / LLM_API_KEY, NAUKRI_*, LINKEDIN_* (optional), TELEGRAM_* (optional),
#    NAUKRI_KEYWORDS / NAUKRI_LOCATION / NAUKRI_EXPERIENCE, and keep COLLECTOR_HEADLESS=false

# 3. Teach it who you are: parse your résumé into the profile (one time)
uv run python -m app.main parse-resume --path ~/Downloads/resume.pdf

# 4. Start the dashboard backend + frontend (leave these two running)
uv run python -m app.main serve-api --port 8000 &      # JSON API on :8000
cd ../frontend && npm install && npm run dev &          # dashboard on :5173

# 5. Run a scrape+rank now. A real Chrome window opens (Naukri, then LinkedIn),
#    scrapes, dedups, and ranks against your résumé.
cd ../backend && uv run python -m app.main run-pipeline
```

Then open **http://localhost:5173**:

1. **Matches** — today's jobs as cards, each with a 0–100 score badge and the LLM's
   pros/cons. Filter by minimum score; click a card for the full reasoning.
2. **Track** the ones worth pursuing → they move to your **Pipeline** board
   (Saved → Applied → Interviewing → Offer / Rejected).
3. **Runs** — history of every run, with counts and any errors, plus a **Run now** button.
4. **Profile / Settings** — re-upload your résumé, or change keywords / location /
   accounts without touching the CLI.

After the first run, day-to-day you don't need the CLI at all: hit **Run** in the
dashboard header, or let the scheduler do it automatically (step below).

**Run it automatically every day** at `RUN_HOUR` (default 08:00 Asia/Kolkata) — keep
this running in its own terminal tab:

```bash
cd backend && uv run python -m app.main start-scheduler
```

> 📖 **The full walkthrough — setup, Telegram, the dashboard, troubleshooting — lives in
> [`USER_GUIDE.md`](./USER_GUIDE.md).** Read that next; this README is the overview.

---

## Why native, not Docker?

Naukri and LinkedIn **block headless browsers** (you get 403 / "Access Denied"). Scraping
has to run in a **visible Chrome window on your own machine / residential IP**. The Docker
image is headless, so it **can serve the API/UI but cannot scrape**. For real use, run
everything natively as shown above. (`docker compose` is still in the repo for the
API/dashboard-only case — see the bottom of this file — but it won't fetch jobs.)

---

## Repo shape

```text
.
├── backend/            Python 3.12 + FastAPI (CLI + pipeline + scheduler + JSON API)
│   ├── app/
│   │   ├── collectors/     Naukri + LinkedIn scrapers (Playwright, headed)
│   │   ├── normalizer/     clean + de-duplicate raw jobs
│   │   ├── ranking/        pre-filter + LLM scoring (any provider) + cache + prompt
│   │   ├── profiles/       résumé parsing → candidate_profile
│   │   ├── notifications/  Telegram digest
│   │   ├── scheduler/      pipeline orchestration + daily APScheduler job
│   │   ├── api/            FastAPI routes the dashboard consumes
│   │   └── main.py         the CLI (every command below)
│   ├── tests/          pytest suite
│   ├── pyproject.toml  deps + ruff/black/pytest config (managed with uv)
│   └── .env.example    every config key the app reads
├── frontend/           Vite + React + TypeScript SPA (shadcn/ui, Tailwind)
├── docker-compose.yml  API/UI-only topology (cannot scrape — see "Why native?")
├── USER_GUIDE.md       the detailed how-to-use guide
└── requirements.md     source-of-truth build spec
```

## Prerequisites

- **Python 3.12** and [**uv**](https://docs.astral.sh/uv/) (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- **Node.js 20+** and npm
- **Google Chrome** installed (the scrapers launch a real Chrome window)
- **An LLM.** Either:
  - **Ollama** running locally — free, no API key ([ollama.com](https://ollama.com), then `ollama pull llama3.2`), or
  - an API key for a hosted provider: OpenAI, Anthropic, Ollama Cloud, Groq, DeepSeek,
    Mistral, OpenRouter, Together, xAI, or any OpenAI-compatible endpoint.

## CLI reference

All commands run from `backend/` via `uv run`:

```bash
uv run python -m app.main --help                   # list commands
uv run python -m app.main parse-resume --path FILE  # load/refresh your résumé (PDF/DOCX)
uv run python -m app.main run-pipeline              # collect → dedup → pre-filter → enrich → rank → notify (headed)
uv run python -m app.main collect --source naukri   # run a single collector (naukri | linkedin)
uv run python -m app.main login --source linkedin   # one-time manual login; saves session
uv run python -m app.main serve-api --port 8000     # JSON API + dashboard backend
uv run python -m app.main start-scheduler           # run the pipeline daily at RUN_HOUR
uv run python -m app.main install-schedule          # write the macOS LaunchAgent (then run the
                                                    #   launchctl load line it prints)
uv run python -m app.main catch-up                  # run now if today's scheduled run was missed
uv run python -m app.main notify-test [--failure]   # send a test Telegram message
```

Quality gates:

```bash
uv run ruff check .          # lint
uv run black --check .       # formatting
uv run pytest                # tests
```

Frontend (from `frontend/`):

```bash
npm install && npm run dev   # dashboard on http://localhost:5173
npm run lint                 # ESLint
npm run build                # type-check + production build
```

## Configuration

All config and secrets come from `backend/.env` (loaded via pydantic-settings; gitignored).
Copy `backend/.env.example`, which lists every key. The ones that matter most:

| Key | What it's for |
|---|---|
| `LLM_PROVIDER` | `ollama` (default, local) \| `ollama_cloud` \| `openai` \| `anthropic` \| `groq` \| `deepseek` \| `mistral` \| `openrouter` \| `together` \| `xai` \| `lmstudio` \| `openai_compatible` |
| `LLM_API_KEY` | key for the chosen provider — not needed for local `ollama` / `lmstudio` |
| `LLM_MODEL` | blank = provider default (e.g. `llama3.2`, `gpt-4o-mini`) |
| `LLM_BASE_URL` | blank = provider default; required only for `openai_compatible` |
| `NAUKRI_EMAIL` / `NAUKRI_PASSWORD` | Naukri login (only needed when `NAUKRI_REQUIRE_LOGIN=true`) |
| `NAUKRI_KEYWORDS` / `NAUKRI_LOCATION` / `NAUKRI_EXPERIENCE` | your search |
| `NAUKRI_REQUIRE_LOGIN` | `false` (default) scrapes the public results page with per-job URLs; `true` logs in but gets no URLs |
| `LINKEDIN_EMAIL` / `LINKEDIN_PASSWORD` | LinkedIn login (optional second source) |
| `PREFILTER_MAX_JOBS` | cap on jobs sent to the LLM per run (default 50; 0 = no cap) |
| `PREFILTER_MIN_SCORE` | drop jobs below this cheap relevance score before ranking (default 0 = keep all) |
| `ENRICH_ENABLED` / `ENRICH_MAX_JOBS` | open the real job pages before ranking (default on, 30) |
| `FEEDBACK_ENABLED` | feed your own tracking decisions into the ranker — applied/interviewing/offer as positives, dropped as negatives (default true; `REJECTED` is the company's call, so it's ignored) |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | optional daily digest (your *numeric* chat id) |
| `TELEGRAM_ONLY_NEW` | push only roles first seen in this run (default true) |
| `COLLECTOR_HEADLESS` | **keep `false`** — headless is 403-blocked |
| `RUN_HOUR` | daily scheduler hour (default 8, `Asia/Kolkata`) |
| `DB_URL` | SQLite path (default `backend/job_hunter.db`) |

> **Changing your search or switching accounts** is easiest from the dashboard's
> **Settings** page (keywords, location, experience, accounts — stored in the DB,
> overriding `.env`, applied on the next run). Collectors reuse a saved session when
> one exists; use `uv run python -m app.main login --source naukri|linkedin` to
> refresh a session after a password change or checkpoint.

## Sources & the LinkedIn risk

Two collectors feed the pipeline, each isolated so one failing never aborts a run:

- **Naukri** (`NAUKRI_*`) — the primary source. By default it scrapes the public
  results page, which carries real per-job URLs and needs no login; the cards themselves
  are only snippets, so the enrich stage follows those URLs to read the full postings.
  Set `NAUKRI_REQUIRE_LOGIN=true` to use the logged-in "TopTier" UI instead — it exposes
  no per-job URL (so nothing to apply to, and nothing to enrich) and carries a higher
  risk of OTP/captcha.
- **LinkedIn** (`LINKEDIN_*`) — optional second source, **off unless credentials are set**,
  and deliberately conservative (`LINKEDIN_MAX_PAGES=3`, slower randomized delays). Has
  real Apply links. A challenged/blocked login sends a Telegram "re-auth needed" alert and
  skips, rather than crashing the run. Use `uv run python -m app.main login --source linkedin`
  to log in manually once and reuse that session.

> ⚠️ **Raw LinkedIn scraping is fragile and violates LinkedIn's Terms of Service.** Markup
> changes often, and automated logins can trigger checkpoints / CAPTCHAs / restrictions.
> Treat it as best-effort. To reduce risk, leave `LINKEDIN_*` blank and rely on Naukri, or
> implement a guest-URL / paid-aggregator fallback against the `Collector` interface
> (`app/collectors/base.py`) and register it in `scheduler/pipeline._default_collectors`.

## Docker (API + dashboard only — cannot scrape)

`docker compose` brings up the FastAPI API, the in-process scheduler, and the UI behind
nginx, with the SQLite DB and Playwright state on named volumes. **It runs headless, so it
will not fetch jobs** (see [Why native?](#why-native-not-docker)). Use it only if you want
to host the dashboard for data scraped elsewhere.

```bash
cp backend/.env.example backend/.env     # fill in keys
docker compose up -d --build             # first build installs Chromium (a few minutes)
docker compose logs -f app               # API + scheduler logs
docker compose down                      # stop (volumes / your data are kept)
```

- Dashboard: <http://localhost:5173> · API docs: <http://localhost:8000/docs>
- The API has **no auth** (single-user assumption) — keep ports 8000/5173 off the public
  internet, or put them behind a reverse proxy / VPN.
</content>
</invoke>
