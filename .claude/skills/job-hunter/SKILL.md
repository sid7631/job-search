---
name: job-hunter
description: Work with the user's job-search tracker through the job-hunter MCP server. Use when the user asks to sync job emails / check Gmail for application updates, prepare for an application or interview, review how their job search is going, go through today's job queue, or start a job run. Triggers include "check my job emails", "update my applications from Gmail", "prep me for the X interview", "how is my job search going", "what should I apply to today".
---

# Job Hunter

The user runs a local job tracker (this repo). The `job-hunter` MCP server exposes it:

| Tool | Use |
| - | - |
| `get_profile` | Résumé text, skills, experience, desired roles |
| `get_queue` | Untriaged roles from the latest run, best first, with `similar_job_ids` |
| `get_job` | Full posting, AI score/pros/cons, tracking status |
| `list_applications` / `find_applications` | Tracked jobs; fuzzy match by company (+ title) |
| `search_jobs` | Any job in the DB, tracked or not |
| `triage_job` | save / apply / dismiss (with reason) — same as the Today page |
| `update_application` | Change status and/or append a dated note |
| `track_job` | Start tracking a job found via `search_jobs` |
| `application_stats` | Funnel, response rate, pass reasons |
| `run_status` / `start_run` | Live pipeline progress; start a scrape (opens a browser on their Mac) |

Statuses: `SAVED → APPLIED → INTERVIEWING → OFFER`, or `REJECTED` (company said no) /
`DROPPED` (user passed). **Never change a status from an inference without showing the
user first** — batch proposals, ask once, then apply.

If the MCP tools are missing, tell the user to open this repo in Claude Code (it reads
`.mcp.json`) or add the server to Claude Desktop (see `backend/app/mcp_server.py`).

## Workflow: sync applications from Gmail

Uses Claude's Gmail connector — no Google API keys on the app side. If no Gmail tools
are available, say so and point the user to connect Gmail in Claude's settings.

1. Search recent mail (default last 14 days, or since the last sync noted in an
   application's notes) with a query like:
   `newer_than:14d (application OR applied OR interview OR assessment OR "next steps" OR unfortunately OR offer) -category:promotions`
   Also include common ATS/job-site senders: greenhouse.io, lever.co, myworkdayjobs.com,
   ashbyhq.com, smartrecruiters.com, naukri.com, linkedin.com (jobs-noreply).
2. Read each candidate thread and classify it:
   - `applied` — confirmation that an application was received
   - `interview` — invite to interview / screening call / assessment
   - `rejected` — "unfortunately", "not moving forward", position filled
   - `offer` — offer or verbal offer
   - `ignore` — job alerts, newsletters, recommendations ("jobs you may like")
   Job-alert digests are the most common false positive: they list many companies and
   are never about one application. Skip them.
3. For each non-ignored email, identify company and role, then `find_applications`.
   - match ≥ 80 → that application.
   - lower, or nothing → `search_jobs`; if the job exists but is untracked, propose
     `track_job`; if it is not in the DB at all, just report it.
4. Show one table: email date · company · role · detected event · current status →
   proposed status · confidence. Only propose forward moves (never move OFFER back to
   APPLIED because of an old confirmation email).
5. After the user confirms (all, or a subset), call `update_application` with the new
   status and a short note, e.g. `Interview invite from Priya for Thu 10am (Gmail, 3 Oct)`.
   Keep notes factual; no email bodies, no personal data beyond names and times.
6. Summarize what changed and anything that needs a reply from the user (interview slots
   to confirm, assessments with deadlines).

This works well as a daily scheduled task in the Claude desktop app ("every weekday at
9am, sync my job emails and tell me what changed") — suggest it once if the user likes
the result.

## Workflow: prepare for an application or interview

1. Resolve the job: `find_applications` / `search_jobs` by what the user said, then
   `get_job` (full posting) and `get_profile` (résumé).
2. Produce, grounded strictly in the résumé text (never invent experience):
   - **Fit in one paragraph** — why they are credible for this role.
   - **Lead with** — 3–5 résumé achievements most relevant to this posting, rewritten as
     bullets in the posting's language.
   - **Gaps and how to handle them** — each `cons` item and anything the posting requires
     that the résumé lacks, with an honest framing or a quick way to close it.
   - **Likely questions** — technical and behavioural, specific to the stack and domain,
     with a one-line pointer to the résumé story that answers each.
   - **Questions to ask them** — 3–4 that show they read the posting.
3. Offer to save a short version to the application notes via `update_application`.

## Workflow: review progress

1. `application_stats`, plus `list_applications` for detail if needed.
2. Report: applications sent, response rate, interviews, what is waiting (and for how
   long), and the top pass reasons from triage.
3. Turn patterns into concrete changes the user can make in the dashboard:
   - pass reasons dominated by "wrong tech stack" → suggest exclude words (Profile →
     "Never show jobs with these words") and sharper search keywords;
   - many applications with no response after 7+ days → suggest following up, list them;
   - interviews concentrated in one source or role type → suggest leaning into it.

## Workflow: today's queue

1. `get_queue` (default 20). Present a short ranked list: score · title · company ·
   one-line reason · number of grouped duplicates.
2. Give an opinion on which to apply to, save, or skip, based on `get_profile`.
3. Record decisions with `triage_job` only after the user agrees, passing
   `similar_job_ids` and a dismiss `reason` (`wrong_stack`, `too_junior`, `too_senior`,
   `location`, `company`, `other`). Reasons teach the ranker, so pick the honest one.

## Starting a run

`start_run` scrapes job sites in a visible browser on the user's Mac and may need them to
approve a LinkedIn sign-in on their phone. Tell them that before starting, then poll
`run_status` (every ~30s is plenty) and relay any `progress.attention` message.
