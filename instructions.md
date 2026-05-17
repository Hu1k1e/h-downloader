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

---

## 2026-05-17 � Radarr Status Sync Fix

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
   - Then calls `await fetchMovies()` � sees correct statuses immediately
   - Removed 1-second arbitrary `setTimeout` delay

**Files changed:**
- `backend/sync.py`
- `backend/routers/jobs.py`
- `frontend/src/api.js`
- `frontend/src/pages/Movies.jsx`
- `instructions.md`
