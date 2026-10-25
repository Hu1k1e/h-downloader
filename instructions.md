# Agent Operating Guide

This document defines how the AI agent must operate when modifying or building this project.

The agent must always follow both:

- instructions.md → defines how the system should operate
- project_specs.md → defines what the project is

The agent must read both files before taking action.

---

# 1. Always Understand the Project First

Before writing any code, the agent must:

1. Read project_specs.md
2. Inspect the repository structure
3. Identify:
   - backend architecture
   - router structure
   - services layer
   - orchestration logic
   - database structure
   - frontend architecture
   - configuration and environment handling
4. Explain how the system currently works
5. Wait for approval before performing major architectural changes

The agent must never start coding blindly.

---

# 2. Project Structure

The repository follows this structure:

```
backend/
    main.py              FastAPI app, startup (migrations, orphan recovery, background loops), optional API auth
    config.py            environment variables / constants
    database.py          engine, table-driven migrations, settings accessor
    models.py            SQLModel tables + API schemas (DownloadJob, AppSettings, LogEntry, JobStatus)
    orchestrator.py      per-job search/download pipeline (movie + TV), duplicate-run guard
    sync.py              background loops + manual sync/import logic (Radarr/Sonarr/qBittorrent reconciliation)
    db_logger.py         log_action(): console + DB log entries
    routers/
        jobs.py          job CRUD, triggers, sync endpoints (thin: delegates to sync.py / orchestrator.py)
        settings.py      settings read/write + connection tests
        webhook.py       Jellyseerr / Radarr / Sonarr webhooks
        logs.py          system log API
    services/            one module per external system + pure rules
        reconcile.py     PURE Radarr/Sonarr -> job state rules (the single source of status decisions)
        radarr.py  sonarr.py  tmdb.py  qbittorrent.py  downloader.py
        einthusan.py  tamilmv.py  bollyzone.py  fmovies.py  llm.py

frontend/            Vite + React (src/pages, src/components, src/api.js, src/hooks.js)
tests/               pytest suite (run with `pytest`; uses a throwaway data dir and fake services)
docker-compose.yml  Dockerfile  requirements.txt  requirements-dev.txt
```

---

## Backend

The backend is a Python API service responsible for:

- API endpoints
- orchestration logic
- job execution
- webhook handling
- configuration management
- database interaction

---

## Routers Layer

Location: backend/routers/

Routers expose HTTP endpoints.

Routers must remain thin.

They should:

- validate requests
- call services
- return responses

Routers must not contain business logic.

---

## Services Layer

Location: backend/services/

This layer contains business logic.

Examples:

- configuration loading
- job orchestration
- database interaction
- synchronization logic
- workflow execution

---

## Frontend

Location: frontend/

The frontend is a Vite web application responsible for:

- UI rendering
- calling backend APIs
- displaying job state
- handling user interaction

---

# 3. Architecture Principles

The system follows a layered architecture:

Frontend  
↓  
Routers (API Layer)  
↓  
Services (Business Logic)  
↓  
Database / External Systems

The agent must preserve this architecture.

---

# 4. Development Rules

## Rule 1 — Read First

Before modifying code, always read:

- instructions.md
- project_specs.md
- relevant modules

---

## Rule 2 — Do Not Mix Responsibilities

Routers must never contain:

- database queries
- heavy logic
- orchestration logic

These belong in the services layer.

---

## Rule 3 — Modify the Smallest Scope

When implementing changes:

1. Identify the minimal change required
2. Implement it
3. Verify that existing behavior is preserved

Avoid unnecessary rewrites.

---

## Rule 4 — Build in Small Steps

Never implement multiple major systems at once.

Instead:

1. Implement one feature
2. Test locally
3. Validate behavior
4. Move to the next feature

---

## Rule 5 — Configuration Handling

All configuration must come from:

.env  
docker-compose.yml

Secrets must never be hardcoded.

---

## Rule 6 — Logging

Errors must never fail silently.

Important operations should log:

- request received
- job started
- job completed
- failure reason

---

## Rule 7 — Tests

Run `pytest` before every push (CI runs it too and will not publish the image if it fails).
Status decisions belong in `services/reconcile.py` and must be covered by `tests/test_reconcile.py`;
never re-implement "what state is this movie in?" in a router, webhook or loop.

---

# 5. Docker Environment

The system runs using:

docker-compose.yml  
Dockerfile

The agent must ensure:

- containers build correctly
- environment variables load properly
- services start reliably

---

# 6. When Something Breaks

If an error occurs:

1. Identify the root cause
2. Fix the underlying issue
3. Prevent the failure from recurring
4. Test again

Never apply superficial fixes.

---

# 7. Response Format

When responding, always follow this format.

Plan  
(3–7 bullet points explaining the approach)

What I need from you  
(only if something is required)

Next Action  
(one clear next step)

Errors  
(explain clearly if something failed)

---

# 8. Core Principles

Understand before building.

Change the smallest possible scope.

- Never assume file structures.
- **Always update `instructions.md` and `project_specs.md` with implementation changes and updates. This should always happen with implementation history and architecture changes.**

### Architecture & Patterns.

Keep architecture clean.

Prevent silent failures.

Build reliable systems.

---

# 9. Push to GitHub — Rules

Before pushing to GitHub, the agent must always:

1. Read `instructions.md` (this file)
2. Read `project_specs.md`
3. Read the implementation history in `project_specs.md` to understand what was previously done

When pushing code:

- The `docker-compose.yml` committed to the repository must always be a **template** with placeholder values (e.g. `your_radarr_api_key_here`, `YOUR_SERVER_IP`)
- The real `docker-compose.yml` with actual keys must **never** be committed
- The `.env` file must **never** be committed (it is covered by `.gitignore`)
- The `*.db` and `*.sqlite` files must **never** be committed (covered by `.gitignore`)
- Always verify the committed `docker-compose.yml` has no real secrets before pushing
- Use `git diff --staged` or review changed files before committing

Push process:

```
git add <changed files>
git commit -m "type(scope): short description"
git push
```

The GitHub Actions workflow at `.github/workflows/docker.yml` automatically builds and pushes the Docker image to GHCR on every push to `main`.

---

# 10. Background Architecture

`main.py` runs a startup recovery (`recover_orphaned_jobs()`: nothing is running yet, so jobs left in
`searching` or in one of our own direct downloads are reset) and then 4 concurrent background loops:

1. **`active_job_tracker_loop()`** — Every 5s. For every `searching` / `downloading` / `importing` job: mirrors
   Radarr/Sonarr queue progress, tracks qBittorrent torrents (progress, ETA, file filtering, stall removal,
   completion → `importing`), resolves `importing` → `done`, and triggers a fallback search when a download died.
   A missing queue item is always re-checked with fresh data. A download already seen in the queue (size/progress known)
   that vanishes becomes `movie_missing` immediately; a fresh grab not yet listed gets 60s (QUEUE_GRACE) to appear.
   Every ~30s it also adopts Radarr grabs it doesn't know about yet.
2. **`discovery_tracker_loop()`** — Every `missing_search_interval_hours` (default 24h). Retries *monitored*
   MOVIE_MISSING/SKIPPED/NOT_FOUND/FAILED jobs via `run_discovery_batch()` (respects the auto-search toggles).
3. **`radarr_state_sync_loop()`** — Every 60s. Full reconciliation with Radarr via `reconcile_job()`.
4. **`sonarr_state_sync_loop()`** — Every 60s. Same for Sonarr episodes.

Radarr/Sonarr are the source of truth for existence, monitored flag, file presence and queue state. Manual sync (`/jobs/{id}/sync` and `/jobs/sync-all`) and manual triggers (`force=True`) bypass queue grace and native deferral so users can immediately reconcile state and force custom source searches. A failed sync is
recorded (`/api/sync/status`, `DownloadJob.sync_error`) and shown in the UI instead of silently leaving stale data.

## Auto-Search Toggles

`enable_radarr_auto_search` / `enable_sonarr_auto_search` (Settings > Automation) gate every *automatic* custom-source
search: webhook delayed search, fallbacks after a failed/removed *arr download, and discovery. A skipped search must
always be written to System Logs (`sync.log_auto_search_disabled`), never only to the console. Manual triggers ignore them.
One-time value fixes go in `database._run_data_migrations()` (bump `models.DATA_VERSION`).

## New Release Grace Period

The `new_release_grace_hours` setting (default 48h) defers recently-released movies/episodes from the discovery loop, giving Radarr/Sonarr time to find quality releases through their indexers before H-Downloader grabs whatever is available on custom sources. Set to 0 to disable.

## Download Sources

- **Einthusan** (`services/einthusan.py`) — Direct MP4/M3U8 downloads for movies
- **1TamilMV** (`services/tamilmv.py`) — Magnet links → qBittorrent for movies and TV
- **BollyZone** (`services/bollyzone.py`) — Magnet links → qBittorrent for TV

Priority order is configurable via `movie_download_sources_priority` and `tv_download_sources_priority`.

## Delayed Search

When a movie/show arrives via webhook, `delayed_search()` waits `search_delay_seconds` (default 120s) polling Radarr every 10s. If Radarr grabs natively, H-Downloader defers. If not, it triggers custom source search.

---

---

Implementation history lives in `project_specs.md`.
