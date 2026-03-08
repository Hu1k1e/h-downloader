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
3. Read the implementation log at the bottom of this file to understand what was previously done

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

# 10. Implementation Log

The agent must always read this section before starting any work to understand what was previously implemented.

---

## 2026-02-22 — Deployment Simplification

**Changes made:**
- Removed `env_file: .env` from `docker-compose.yml` — replaced with inline `environment:` block to fix Portainer compatibility
- Removed external `media-network` requirement from `docker-compose.yml` — Docker will use default network automatically
- Updated `README.md` Quick Start section to embed the docker-compose template and `.env` block directly so users can deploy without cloning the repo
- Removed GHCR authentication requirement from README (repo and package are now public)

**Files changed:**
- `docker-compose.yml`
- `README.md`

---

## 2026-02-22 — MOVIE_MISSING Status and UI Polish

**Changes made:**
- Added `MOVIE_MISSING` status to `JobStatus` enum in `backend/models.py`
- Modified `sync.py` to detect when a `DONE` job's file is deleted from disk → marks as `MOVIE_MISSING`, unmonitored
- Added red dot indicator to movie poster cards for `MOVIE_MISSING` state in `Movies.jsx`
- Added CSS `.poster-monitored-dot--missing` class for red glow in `index.css`
- Removed emoji icons from sidebar navigation items in `Sidebar.jsx`

**Files changed:**
- `backend/models.py`
- `backend/sync.py`
- `frontend/src/pages/Movies.jsx`
- `frontend/src/index.css`
- `frontend/src/components/Sidebar.jsx`

---

## 2026-02-26 — Einthusan Search Accuracy Improvement

**Changes made:**
- Replaced `fuzz.partial_ratio` with `fuzz.token_set_ratio` for title matching in `einthusan.py`
- Raised the minimum match score threshold from 55 to 85
- Added proper year extraction using regex (`\b(19\d{2}|20\d{2})\b`) from card text
- Year matches within ±1 year receive a +15 score bonus; wrong years receive a -40 penalty
- Used `isinstance(year, int)` to safely handle `Optional[int]` year parameter

**Files changed:**
- `backend/services/einthusan.py`

---

## 2026-02-26 — Radarr RescanMovie Trigger

**Changes made:**
- Replaced `DownloadedMoviesScan` command with `RescanMovie` command in `radarr.py`
- `RescanMovie` uses the Radarr movie ID directly, scanning the movie's specific folder
- Updated `orchestrator.py` to fetch the Radarr movie ID after download and call `trigger_rescan`
- Root cause: `DownloadedMoviesScan` is for staging directories; files placed directly in Radarr's media folder were being ignored by it

**Files changed:**
- `backend/services/radarr.py`
- `backend/orchestrator.py`

---

## 2026-02-26 — Sync Grace Period + Jobs Path Column

**Changes made:**
- Added a 2-hour grace period in `sync.py` before marking a `DONE` job as `MOVIE_MISSING`
  - Root cause: large files can take time for Radarr to import; sync was flagging them as missing during that window
- Added `Path` column to the Jobs table in `Jobs.jsx` showing the file destination path
  - Column truncates with ellipsis; full path visible on hover via `title` attribute

**Files changed:**
- `backend/sync.py`
- `frontend/src/pages/Jobs.jsx`

---

## 2026-03-07 — Instructions Update

**Changes made:**
- Added Section 9 (Push to GitHub Rules) to `instructions.md`
- Added Section 10 (Implementation Log) to `instructions.md` with all previous changes documented
- Verified `docker-compose.yml` in repo is a clean template (no secrets)
- Pushed all accumulated changes to GitHub; GHCR build triggered automatically via GitHub Actions

**Files changed:**
- `instructions.md`
---

## 2026-03-07  Search Fix + Frontend Revamp

**Backend:**
- Removed `-40` year mismatch penalty in `einthusan.py`  was falsely rejecting valid movies (e.g. Guppy 2015 Malayalam)
- Year mismatch no longer penalises; only correct year receives +15 bonus
- Added 6 additional fallback card selectors for Einthusan layout variations
- Added DEBUG-level logging for all candidate cards and match scores

**Frontend:**
- `ui.jsx`: Added `movie_missing`  'File Missing' badge; removed emojis from all badge labels; fixed null safety on `ProgressBar`
- `Dashboard.jsx`: Trigger button in header; language badge on active downloads; accent colour for active count; movie_missing coloured red in activity log
- `Jobs.jsx`: Path column shows filename only; `movie_missing` jobs can be retried
- `Settings.jsx`: Removed emojis from all section titles
- `index.css`: Added purple token for movie_missing badge; stat card lifts on hover with green top border; removed duplicate `btn-danger` rule

**Files changed:**
- `backend/services/einthusan.py`
- `frontend/src/components/ui.jsx`
- `frontend/src/pages/Dashboard.jsx`
- `frontend/src/pages/Jobs.jsx`
- `frontend/src/pages/Settings.jsx`
- `frontend/src/index.css`
- `instructions.md`
