# AI Job Hunter — Build Requirements & Handoff Spec

**Owner:** Single user (personal use)
**Purpose:** A personal AI recruiter that collects jobs, ranks them against my resume, pushes daily picks to Telegram, and gives me a React dashboard to triage and track applications.

This document is the source of truth for handoff to **Claude Code**. It is divided into independent **modules (M0–M10)**. Each module has a scope, a task checklist, and a definition of done. Build in order where dependencies exist; modules marked *parallel-safe* can be built independently once M0–M1 are done.

---

## Locked Technical Decisions

These are settled — do not re-litigate during the build.

| Concern | Decision | Notes |
|---|---|---|
| Backend | **Python 3.12 + FastAPI** | Thin JSON API only. No server-side rendering. |
| Frontend | **React (Vite + TypeScript)** | SPA. Plain React + a component lib (shadcn/ui or MUI). |
| Database | **SQLite** (single file) | One user; cron writes at 8 AM, I read during the day — no real concurrency. Migration path to Postgres documented in M1 but NOT built now. |
| ORM / DB access | **SQLAlchemy 2.x + Alembic** | Alembic so the SQLite→Postgres swap is painless later. |
| Scraping | **Playwright (Python)** | Persisted `storage_state`. Naukri first, LinkedIn second. |
| Embeddings / pgvector | **NOT in scope for v1** | Daily new-job volume is low (50–300). Send deduped jobs straight to the LLM. Revisit only if volume forces it. |
| LLM ranking | **Any provider** (Ollama local/cloud, OpenAI, Anthropic, Groq, … — configurable) | Structured/JSON output enforced. Results cached by job content hash. |
| Notifications | **Telegram Bot** | Daily push of top picks. |
| Scheduler | **APScheduler** (in-process) or system cron | Pick APScheduler so the whole app runs as one process. |
| Config / secrets | **`.env` + pydantic-settings** | No secrets in code or DB. |
| Deployment | **Docker Compose** | Single Ubuntu VPS, 2 CPU / 4 GB. |

**Repo shape:** monorepo with `/backend` (Python) and `/frontend` (React), one `docker-compose.yml` at root.

---

## Architecture (v1)

```text
APScheduler (08:00) ──► Collectors (Playwright) ──► raw_jobs (SQLite)
                                                        │
                                                        ▼
                                            Normalizer ──► jobs
                                                        │
                                                        ▼
                                        Dedup (exact + fuzzy/rapidfuzz)
                                                        │
                                                        ▼
                              LLM Ranking (configurable, cached by job hash) ──► job_matches
                                                        │
                                          ┌─────────────┴─────────────┐
                                          ▼                           ▼
                                  Telegram (daily push)        FastAPI ◄── React UI
                                                                     │
                                                              applications (my tracked state)
```

**Key data principle:** `job_matches` = the AI's opinion (regenerated each run). `applications` = my action (permanent, hand-edited in the UI). Never conflate them.

---

## Module Overview & Progress Tracker

Update the status column as work completes. Suggested statuses: `TODO` / `IN PROGRESS` / `DONE` / `BLOCKED`.

| ID | Module | Depends on | Parallel-safe | Status |
|----|--------|-----------|---------------|--------|
| M0 | Project scaffolding & tooling | — | — | DONE |
| M1 | Database layer & schema | M0 | — | DONE |
| M2 | Profile / resume parsing | M1 | yes | DONE |
| M3 | Naukri collector | M1 | yes | DONE |
| M4 | Normalizer + deduplication | M1, M3 | — | DONE |
| M5 | LLM ranking engine (cached) | M1, M2, M4 | — | DONE |
| M6 | Orchestration & scheduler | M3, M4, M5 | — | DONE |
| M7 | Telegram notifier | M5 | yes | DONE |
| M8 | FastAPI backend (JSON API) | M1, M5 | — | DONE |
| M9 | React dashboard (UI) | M8 | — | DONE |
| M10 | LinkedIn collector (hardened) | M3, M4 | yes | DONE |
| M11 | Dockerization & deployment | all | — | DONE |

**Recommended build order:** M0 → M1 → (M2 ∥ M3) → M4 → M5 → (M6 ∥ M7 ∥ M8) → M9 → M10 → M11.

---

## M0 — Project Scaffolding & Tooling

**Scope:** Get a runnable empty monorepo with linting, formatting, env handling, and a README so every later module drops into a known structure.

**Tasks**
- [ ] Create monorepo: `/backend`, `/frontend`, root `README.md`, root `docker-compose.yml` (stub).
- [ ] Backend: Python 3.12, `uv` or `poetry` for deps, `ruff` + `black`, `pytest` configured.
- [ ] Backend folder layout (see below), all packages with `__init__.py` and a `main.py` that runs and exits cleanly.
- [ ] `pydantic-settings` config module reading from `.env`; provide `.env.example` listing every key (`LLM_PROVIDER`, `LLM_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `NAUKRI_EMAIL`, `NAUKRI_PASSWORD`, `LINKEDIN_*`, `DB_URL`, `RUN_HOUR`).
- [ ] Frontend: Vite + React + TypeScript scaffold, ESLint + Prettier, a component lib installed (shadcn/ui preferred), renders a placeholder page.
- [ ] Root `README.md`: how to run backend, frontend, and the daily pipeline locally.

**Backend layout**
```text
backend/app/
├── collectors/      (naukri.py, linkedin.py, base.py)
├── normalizer/      (normalizer.py)
├── dedupe/          (dedupe.py)
├── ranking/         (ranking_service.py, prompt.py, cache.py)
├── notifications/   (telegram.py)
├── profiles/        (resume_parser.py)
├── database/        (models.py, connection.py, repository.py)
├── api/             (routes_matches.py, routes_applications.py, routes_runs.py)
├── scheduler/       (pipeline.py, jobs.py)
├── config.py
└── main.py          (CLI entrypoints: `run-pipeline`, `serve-api`, `start-scheduler`)
```

**Definition of done:** `python -m app.main --help` shows the three entrypoints; `npm run dev` serves the placeholder; `.env.example` is complete; lint passes on both sides.

---

## M1 — Database Layer & Schema

**Scope:** All tables, SQLAlchemy models, Alembic migrations, and a thin repository layer. This is the contract every other module builds against.

**Tables**
```sql
candidate_profile(id, name, years_experience, skills_json, domain,
                  preferred_locations_json, desired_roles_json,
                  resume_text, raw_parsed_json, created_at, updated_at)

raw_jobs(id, source, source_job_id, url, raw_payload_json, scraped_at, run_id)

jobs(id, title, company, location, description, skills_json, source,
     url, content_hash, created_at)               -- content_hash = stable hash of normalized title+company+location

job_matches(id, job_id, run_id, score, pros_json, cons_json, reason,
            llm_model, created_at)                 -- the AI's opinion, regenerated per run

applications(id, job_id, status, applied_at, notes, updated_at, created_at)
            -- status enum: SAVED | APPLIED | INTERVIEWING | REJECTED | OFFER | DROPPED
            -- my action; created when I act on a match in the UI

ranking_cache(content_hash, score, pros_json, cons_json, reason, llm_model, created_at)
            -- so an unchanged job is never re-ranked across runs

runs(id, started_at, finished_at, status, source_counts_json, error_text)
```

**Tasks**
- [ ] SQLAlchemy 2.x models for all tables above.
- [ ] Alembic initialized; first migration creates the full schema.
- [ ] `connection.py` builds engine/session from `DB_URL` (SQLite default).
- [ ] `repository.py` with typed helpers: `upsert_job`, `get_jobs_for_run`, `save_match`, `get_today_matches`, `create_application`, `update_application_status`, `list_applications`, `start_run`, `finish_run`, `get_cached_ranking`, `set_cached_ranking`.
- [ ] Seed/migration note documenting the exact SQLite→Postgres swap (change `DB_URL`, re-run migrations).
- [ ] Unit tests for repository CRUD against an in-memory SQLite.

**Definition of done:** `alembic upgrade head` builds the DB; repository tests pass.

---

## M2 — Profile / Resume Parsing  *(parallel-safe)*

**Scope:** Parse my resume once into a structured `candidate_profile` row.

**Tasks**
- [ ] Accept a PDF/DOCX resume path; extract text.
- [ ] Use the LLM to extract: years_experience, skills[], companies[], domain, preferred_locations[], desired_roles[].
- [ ] Store both the structured fields and `raw_parsed_json` + `resume_text` in `candidate_profile`.
- [ ] CLI: `python -m app.main parse-resume --path resume.pdf` (idempotent — updates the single profile row).
- [ ] Validate output against a pydantic schema; fail loudly if the LLM returns junk.

**Definition of done:** Running the CLI on a real resume populates one `candidate_profile` row with sane structured fields.

---

## M3 — Naukri Collector  *(parallel-safe)*

**Scope:** Playwright collector for Naukri (chosen first — far easier than LinkedIn). Writes to `raw_jobs`.

**Tasks**
- [ ] `base.py` defines a `Collector` interface: `collect(run_id) -> list[RawJob]`, with per-source isolation (one collector failing must not crash the run).
- [ ] Naukri login using `.env` creds; persist `storage_state` to disk; reuse session if valid.
- [ ] Search by configurable params (keywords, location, experience) read from config.
- [ ] Paginate results; for each job capture title, company, location, url, source_job_id, full description, raw payload.
- [ ] Randomized delays + retry/backoff; respect a configurable max pages.
- [ ] On session-dead / login-failure: write a `runs` error and return empty (don't throw).
- [ ] Write all results to `raw_jobs` tagged with `run_id` and `source="naukri"`.

**Definition of done:** A manual `collect` run logs in, scrapes N pages, and `raw_jobs` fills with valid rows; a forced bad-session run fails gracefully with a recorded error.

---

## M4 — Normalizer + Deduplication

**Scope:** Turn `raw_jobs` into clean `jobs`, removing duplicates. **No embeddings** — exact + fuzzy only.

**Tasks**
- [ ] Normalizer maps each source's raw payload to the common `jobs` schema (title, company, location, description, skills[]).
- [ ] Skill extraction from description (LLM or keyword list — keep it cheap; LLM optional).
- [ ] Compute `content_hash` from normalized title+company+location.
- [ ] **Exact dedup:** by url, source_job_id, and content_hash.
- [ ] **Fuzzy dedup:** `rapidfuzz` on (title + company); merge if score above a configurable threshold (e.g. token_sort_ratio > 90). Example: "Amazon SDE III" vs "Amazon Senior Software Engineer III" → same role.
- [ ] Only insert genuinely new `jobs`; link back to `raw_jobs`.

**Definition of done:** Given a `raw_jobs` set with planted duplicates, `jobs` contains exactly the unique roles; thresholds are config-driven and unit-tested.

---

## M5 — LLM Ranking Engine (Cached)

**Scope:** Score each new job against the profile via the configured LLM, with structured output and content-hash caching so unchanged jobs are never re-ranked.

**Tasks**
- [ ] `prompt.py`: builds the ranking prompt (candidate profile + job description) and **requires JSON output**: `{ score: 0-100, pros: [], cons: [], reason: "" }`.
- [ ] Enforce schema with the provider's JSON mode where supported; validate with pydantic; retry once on malformed output.
- [ ] **Cache:** before ranking, check `ranking_cache` by `content_hash`; on hit, reuse. On miss, call LLM and write cache.
- [ ] Batch calls where the SDK allows; otherwise concurrency-limited async.
- [ ] Write one `job_matches` row per job for the current `run_id`.
- [ ] **Single scoring source:** the LLM score IS the match score. Do NOT average it with a separate rule-based skill/experience/location formula (that double-counts). Deterministic signals may be used only as cheap pre-filters before ranking, never blended into the final score.

**Definition of done:** New jobs get scored once and cached; re-running the pipeline on the same jobs makes zero new LLM calls; `job_matches` is populated with valid structured results.

---

## M6 — Orchestration & Scheduler

**Scope:** The daily run that ties collectors → normalize → dedup → rank → notify, wrapped in run-tracking.

**Tasks**
- [ ] `pipeline.py`: single function `run_pipeline()` that creates a `runs` row, executes each stage, records per-source counts, and marks success/failure.
- [ ] Each collector wrapped so one failure is logged and skipped, not fatal.
- [ ] APScheduler job at `RUN_HOUR` (default 08:00, configurable, timezone Asia/Kolkata).
- [ ] CLI `run-pipeline` to trigger manually; `start-scheduler` to run the daemon.
- [ ] Idempotent: re-running for the same day is safe (caching + upserts handle it).

**Definition of done:** `run-pipeline` executes end-to-end, writes a complete `runs` row, and triggers the Telegram push; scheduler fires at the configured hour.

---

## M7 — Telegram Notifier  *(parallel-safe)*

**Scope:** Daily push of the top matches.

**Tasks**
- [ ] Telegram bot client using token + chat id from `.env`.
- [ ] Format top N (configurable, default 10) matches for today's run: rank, company, title, score, apply link.
- [ ] Include a summary line ("X new high-quality matches found").
- [ ] Send on pipeline success; on pipeline failure send a short "run failed" alert instead.

**Definition of done:** A test invocation delivers a formatted message to my Telegram; failure path sends an alert.

---

## M8 — FastAPI Backend (JSON API)

**Scope:** Thin JSON API the React UI consumes. No HTML, no auth needed for v1 (single user, local/VPS behind a firewall — note this assumption).

**Endpoints**
- [ ] `GET /api/matches?date=&min_score=` — ranked matches (joins `jobs` + latest `job_matches`), newest run by default.
- [ ] `GET /api/matches/{job_id}` — full detail (description, pros, cons, reason).
- [ ] `POST /api/applications` — create/track an application from a match (`{job_id, status}`).
- [ ] `GET /api/applications?status=` — list my tracked applications.
- [ ] `PATCH /api/applications/{id}` — update status / notes.
- [ ] `GET /api/runs` — recent runs for the debug/health view.
- [ ] `POST /api/run-now` — manually trigger a pipeline run (returns run_id).
- [ ] CORS configured for the frontend dev origin; pydantic response models for every endpoint; OpenAPI docs available at `/docs`.

**Definition of done:** All endpoints return typed JSON; `/docs` is browsable; a smoke test hits each route.

---

## M9 — React Dashboard (UI)

**Scope:** The reason React is in scope. Three views. Clean, fast, single-user.

**Stack:** Vite + React + TS, shadcn/ui (or MUI), TanStack Query for data fetching, React Router for views.

**Views & tasks**
- [ ] **Matches (home):** today's ranked jobs as cards — score badge, title, company, location, top pros/cons. Sort by score; filter by min score. Each card: "Apply" (opens job url) and "Track" (creates an application, default status `APPLIED` or `SAVED`).
- [ ] **Match detail:** drawer/modal with full description, full pros/cons, LLM reason, and the track button.
- [ ] **Pipeline (applications tracker):** Kanban or grouped table by status (SAVED / APPLIED / INTERVIEWING / REJECTED / OFFER / DROPPED). Drag-or-dropdown to change status; editable notes; shows applied_at.
- [ ] **Runs / Health:** table of recent runs (time, status, per-source counts, errors) + a "Run now" button hitting `POST /api/run-now`.
- [ ] Shared: API client wrapping the M8 endpoints; loading/empty/error states; responsive layout.

**Definition of done:** I can open the app, see today's ranked matches, click Track to move a job into my pipeline, change its status, add notes, and trigger a manual run — all persisting via the API.

---

## M10 — LinkedIn Collector (Hardened)  *(parallel-safe, do after M4)*

**Scope:** Add LinkedIn as a second source. Treat scraping fragility as the main risk.

**Tasks**
- [ ] Implement against the `Collector` interface from M3.
- [ ] Persist `storage_state`; detect dead sessions and send a Telegram "re-auth needed" alert instead of failing silently.
- [ ] Aggressive randomized delays + backoff; conservative page limits.
- [ ] Evaluate and document a fallback: LinkedIn filtered job-search URLs / RSS or a paid aggregator API, since raw LinkedIn scraping breaks often and violates ToS — note the risk explicitly in the README.
- [ ] Same `raw_jobs` output contract as Naukri so normalizer/dedup need no changes.

**Definition of done:** LinkedIn jobs flow into the same pipeline; a dead session produces a Telegram alert, not a crashed run.

---

## M11 — Dockerization & Deployment

**Scope:** One-command local run and a documented VPS deploy.

**Tasks**
- [ ] Backend Dockerfile (Python 3.12 + Playwright browsers installed).
- [ ] Frontend Dockerfile (build static, serve via nginx) or serve built assets from FastAPI.
- [ ] `docker-compose.yml`: services for `app` (API + scheduler) and `frontend`; SQLite file on a mounted volume; `.env` wired in.
- [ ] Persist Playwright `storage_state` and the SQLite DB on named volumes.
- [ ] README deploy section: Ubuntu VPS (2 CPU / 4 GB), `docker compose up -d`, how to run `parse-resume` once, how to view logs.

**Definition of done:** `docker compose up` brings up the API, scheduler, and UI locally; documented steps reproduce it on a fresh VPS.

---

## Out of Scope for v1 (future phases — keep the door open, don't build)

- Embeddings + pgvector similarity search (add only if daily volume makes LLM ranking slow/costly).
- Auto resume tailoring per job.
- Auto cover-letter generation.
- One-click / semi-automated apply.
- Multi-user / auth / hosting beyond myself.

---

## How to Use This With Claude Code

- Hand it **one module at a time**, in the recommended order. Each module is self-contained with its own definition of done.
- After each module, update the **Progress Tracker** table status.
- The **Locked Technical Decisions** and **schema (M1)** are the shared contract — if Claude Code proposes deviating, that's a decision to make deliberately, not drift into.
- Suggested first command: *"Build M0 exactly as specified in this doc. Stop at its definition of done and show me the tree."*
