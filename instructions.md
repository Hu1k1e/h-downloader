# Agent Operating Guide

This document defines how the AI agent must operate when modifying or building this project.

The agent must always follow both:

- instructions.md â†’ defines how the system should operate
- project_specs.md â†’ defines what the project is

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

backend/
    routers/
        jobs.py
        settings.py
        webhook.py

    services/
        config.py
        database.py
        models.py
        orchestrator.py
        sync.py

    main.py

frontend/
    src/
    public/
    dist/

docker-compose.yml
Dockerfile
requirements.txt

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
â†“  
Routers (API Layer)  
â†“  
Services (Business Logic)  
â†“  
Database / External Systems

The agent must preserve this architecture.

---

# 4. Development Rules

## Rule 1 â€” Read First

Before modifying code, always read:

- instructions.md
- project_specs.md
- relevant modules

---

## Rule 2 â€” Do Not Mix Responsibilities

Routers must never contain:

- database queries
- heavy logic
- orchestration logic

These belong in the services layer.

---

## Rule 3 â€” Modify the Smallest Scope

When implementing changes:

1. Identify the minimal change required
2. Implement it
3. Verify that existing behavior is preserved

Avoid unnecessary rewrites.

---

## Rule 4 â€” Build in Small Steps

Never implement multiple major systems at once.

Instead:

1. Implement one feature
2. Test locally
3. Validate behavior
4. Move to the next feature

---

## Rule 5 â€” Configuration Handling

All configuration must come from:

.env  
docker-compose.yml

Secrets must never be hardcoded.

---

## Rule 6 â€” Logging

Errors must never fail silently.

Important operations should log:

- request received
- job started
- job completed
- failure reason

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
(3â€“7 bullet points explaining the approach)

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

# 9. Push to GitHub â€” Rules

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

The system runs 4 concurrent background loops launched at startup in `main.py`:

1. **`active_job_tracker_loop()`** — Every 5s. Tracks qBittorrent and Radarr/Sonarr native download progress. Triggers fallback if Radarr downloads fail.
2. **`discovery_tracker_loop()`** — Every `missing_search_interval_hours` (default 24h). Retries searching for MOVIE_MISSING/SKIPPED/NOT_FOUND/FAILED jobs via `run_discovery_batch()`.
3. **`radarr_state_sync_loop()`** — Every 60s. Full state reconciliation with Radarr. Creates, updates, or removes jobs based on Radarr's current library.
4. **`sonarr_state_sync_loop()`** — Every 60s. Full state reconciliation with Sonarr for TV episodes.

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

## 2026-05-17 — Radarr Status Sync Fix

**Problem diagnosed:**
- The `Sync Requests` button called `POST /api/jobs/sync` which enqueues `sync_jellyseerr_requests()` as a FastAPI `BackgroundTask`.
- The endpoint returns `{"status": "sync_started"}` immediately. The frontend then waited 1 second and re-fetched.
- The sync function runs asynchronously in the background (can take 10-30s+ for many jobs), so re-fetch always saw stale data.
- Additionally, each `is_movie_in_radarr()` call fetches ALL Radarr movies via a separate HTTP request (N+1 problem).
- The 2-hour grace period in Step 3 prevented a freshly-deleted movie from becoming `MOVIE_MISSING` for 2 hours.

**Fix implemented:**
1. Added `sync_radarr_status(session, settings)` to `backend/sync.py`:
   - Makes ONE `GET /api/v3/movie` call to Radarr
   - Builds a `tmdb_id -> movie` dict
   - Iterates all local jobs and updates `DONE` / `MOVIE_MISSING` / `monitored` / deleted statuses inline
   - No 2-hour grace period (user explicitly triggered sync)
   - Does not trigger Einthusan downloads (that remains the scheduler's job)
   - Returns `{"updated": N, "deleted": N, "unchanged": N}`

2. Added `POST /api/jobs/sync-radarr` endpoint to `backend/routers/jobs.py`:
   - Calls `sync_radarr_status()` inline (NOT as a background task)
   - Awaits completion before responding
   - UI sees fully-updated DB state the moment the request returns

3. Updated `frontend/src/api.js`:
   - Added `syncRadarrStatus()` -> `POST /api/jobs/sync-radarr`

4. Updated `frontend/src/pages/Movies.jsx` `syncJellyseerr()` function:
   - Now calls `await api.syncRadarrStatus()` first (synchronous, result immediately in DB)
   - Then fires `api.syncJellyseerr()` in the background (no await) for Jellyseerr new request pickup
   - Then calls `await fetchMovies()` — sees correct statuses immediately
   - Removed 1-second arbitrary `setTimeout` delay

**Files changed:**
- `backend/sync.py`
- `backend/routers/jobs.py`
- `frontend/src/api.js`
- `frontend/src/pages/Movies.jsx`
- `instructions.md`

---

## 2026-08-14 — FMovies Native PyNaCl API Extraction

**Problem diagnosed:**
- The previously implemented Playwright headless browser approach for `f-movies.org` was slow, consumed significant memory, and was ultimately blocked by Cloudflare and iframe protections on the `f-movies.org` embed servers (like `embos.top` and `vidlink.pro`).

**Fix implemented:**
1. Discovered that the primary `vidlink.pro` embed API uses an `XSalsa20` / AES encrypted token to protect its API endpoints.
2. Removed **Playwright** entirely from the Dockerfile and `requirements.txt` to streamline build times and memory usage.
3. Implemented a native Python port of the encryption using `PyNaCl` to dynamically generate time-based authorization tokens.
4. Rewrote `backend/services/fmovies.py` to use `httpx` to query the `vidlink.pro` API natively, bypassing all JavaScript execution and Cloudflare challenges, reducing stream extraction time from 15+ seconds down to ~500ms.

**Files changed:**
- `Dockerfile`
- `requirements.txt`
- `backend/services/fmovies.py`
- `instructions.md`
