# Project Specifications

---

# 1. Project Overview

This project is a full-stack system consisting of:

- Python backend
- Vite frontend
- Docker deployment environment

The system manages jobs, synchronization processes, configuration-driven workflows, and media discovery/downloading through API endpoints and background services.

The next stage of this project is focused on **Radarr state reconciliation and sync controls**.

This stage must implement:

1. checking whether a movie has been deleted from Radarr
2. updating the app status correctly if the movie no longer exists in Radarr
3. adding a **Sync** button on each movie card
4. adding a **Sync All** button
5. syncing and correcting the displayed movie status:
   - available
   - movie missing
   - downloading
6. fixing monitored-state persistence so toggled monitored values do not revert incorrectly

This stage is not a visual redesign or full project revamp. Those earlier stages are already complete. This stage is specifically about **state correctness**, **Radarr synchronization**, and **frontend controls for manual reconciliation**.

---

# 2. System Components

## Backend

Location:

backend/

The backend is responsible for:

- API endpoints
- job orchestration
- synchronization tasks
- webhook processing
- configuration management
- database interaction
- media discovery / matching / download workflows
- search logic and result validation
- Radarr synchronization
- Radarr state reconciliation
- monitored state persistence
- status correction after Radarr changes

---

### Routers

Location:

backend/routers/

These files define API endpoints.

Examples:

jobs.py  
settings.py  
webhook.py  

Responsibilities:

- receive requests
- validate input
- call service logic
- return responses

Routers must remain thin.

Additional responsibilities for this stage may include endpoints for:

- syncing a single movie with Radarr
- syncing all movies with Radarr
- toggling monitored status
- fetching refreshed Radarr-derived status

Routers must not contain reconciliation logic directly.

---

### Services

Location:

backend/services/

This layer contains the core application logic.

Modules include:

config.py  
database.py  
models.py  
orchestrator.py  
sync.py  

This layer may also include or be extended to include:

- Radarr API client service
- movie reconciliation service
- monitored toggle service
- queue / download-state inspection service
- status derivation logic

Responsibilities:

- configuration management
- job orchestration
- database operations
- synchronization logic
- system workflows
- content matching and validation
- download decision logic
- Radarr state reconciliation
- monitored state synchronization
- movie status derivation

---

### Application Entry Point

backend/main.py

Responsible for:

- starting the server
- loading routers
- initializing services
- application startup

---

## Frontend

Location:

frontend/

The frontend is a Vite web application.

Responsibilities:

- rendering the user interface
- communicating with backend APIs
- displaying jobs, tasks, results, and status
- handling user interactions
- presenting search, match, and download flows clearly
- displaying current movie status accurately
- allowing manual sync actions from the UI

Key folders:

frontend/src/  
frontend/public/  
frontend/dist/

---

# 3. Radarr Synchronization Stage Requirement

This stage adds **movie state reconciliation with Radarr**.

The application currently has incorrect state behavior in at least two cases:

1. when a movie is deleted from Radarr, the app does not update the movie status correctly
2. when a movie is toggled to monitored, it is automatically reverting back to unmonitored

These issues indicate that local application state and Radarr state are not being synchronized correctly.

The system must be updated so that Radarr is treated as the source of truth for Radarr-managed movie state.

---

## 3.1 Required Behavior

The system must correctly detect and reflect whether a movie:

- exists in Radarr
- has been deleted from Radarr
- is monitored or unmonitored in Radarr
- has an existing downloaded file
- is currently downloading
- is missing and not downloading

The app must no longer display stale movie state after manual changes or Radarr-side deletions.

---

## 3.2 Frontend Controls Requirement

Each movie card must include a:

- **Sync** button

This button must trigger synchronization for that specific movie only.

The UI must also include a:

- **Sync All** button

This button must trigger synchronization for all movies currently represented by the application, or for the currently scoped dataset if the app already uses filtered/sectioned views.

These sync actions must refresh the displayed status based on live Radarr data.

---

## 3.3 Statuses to Sync and Display

The system must synchronize and correctly display the following statuses:

- available
- movie missing
- downloading

It must also correctly handle the condition where the movie is no longer present in Radarr.

If needed internally, the backend may use a more explicit status model such as:

- available
- downloading
- missing
- not_in_radarr
- unknown

The frontend may map those internal states into the visible statuses required by the product.

---

# 4. Radarr Source of Truth Requirement

Radarr must be treated as the authoritative source for the following movie attributes:

- movie existence in Radarr
- monitored state
- file presence
- download / queue state
- Radarr identifiers

The application database may cache or store these values, but cached values must be updated from Radarr during synchronization and must not permanently override Radarr truth.

If Radarr and local state disagree, the reconciled state must be based on Radarr.

---

## 4.1 Deletion Detection

The system must check whether the movie still exists in Radarr.

If the movie has been deleted from Radarr:

- the application must detect that during sync
- the movie’s local state must be updated accordingly
- the frontend must no longer incorrectly show stale availability/downloading state
- the movie should be marked in a way that clearly indicates it is no longer present in Radarr

This must work for both:

- single movie sync
- sync all

---

## 4.2 Monitored State Persistence

When a monitored toggle is changed from the app:

1. the frontend sends the change request to the backend
2. the backend updates the monitored value in Radarr
3. the backend retrieves the updated movie record from Radarr
4. the backend updates the local database using the Radarr-confirmed value
5. the frontend refreshes using the confirmed state

The monitored toggle must not revert incorrectly after the update.

This means:

- local optimistic state must not overwrite confirmed Radarr state later
- stale database values must not overwrite newer Radarr values
- background sync must not reapply old monitored values
- the app must always display the current monitored value from the most recent reconciliation

---

# 5. Movie Status Reconciliation

Movie status must be derived from Radarr data through a clear ruleset.

Possible backend state fields may include:

- radarr_id
- tmdb_id
- monitored
- has_file
- movie_file_id
- in_radarr
- is_downloading
- queue_id
- last_radarr_sync_at
- radarr_sync_error

Status derivation should follow rules such as:

- **available**  
  movie exists in Radarr and a movie file exists

- **downloading**  
  movie exists in Radarr, no completed file exists, and the movie is currently in an active download / queue state

- **movie missing**  
  movie exists in Radarr but no movie file exists and it is not actively downloading

- **not in Radarr**  
  movie no longer exists in Radarr

- **unknown**  
  sync failed or data is incomplete

These rules must be implemented in a transparent and testable way.

---

## 5.1 False State Prevention

The system must explicitly prevent stale or misleading states.

That means:

- do not continue showing a movie as available after it has been deleted from Radarr
- do not continue showing downloading if queue state no longer supports that
- do not continue showing old monitored state after a toggle has changed
- do not rely only on local cached values when a sync is requested

If synchronization fails, the UI should show that sync failed rather than silently continuing to show incorrect confirmed state as if it were fresh.

---

# 6. Database

Database interaction is handled by:

backend/services/database.py  
backend/services/models.py  

Responsibilities include:

- storing job records
- storing configuration data
- storing synchronization state
- storing movie records
- storing Radarr sync results
- storing last known monitored state
- storing last sync timestamps
- storing reconciliation metadata if needed

Database access must be centralized in the services layer.

Routers must never access the database directly.

The database must not be treated as the ultimate source of truth for Radarr-managed state.

---

# 7. Job System

Jobs represent background operations.

Examples include:

- synchronization tasks
- scheduled processes
- webhook-triggered actions
- media search operations
- media validation operations
- download preparation or execution
- Radarr reconciliation operations

Job flow involves:

routers/jobs.py  
services/orchestrator.py  
services/sync.py  

The orchestrator controls job lifecycle.

If sync-all is implemented as a background job, it must still produce status updates that the frontend can reflect clearly.

---

# 8. Webhooks

Webhook endpoints allow external services to trigger workflows.

Webhook behavior:

1. receive request
2. validate payload
3. call appropriate service logic
4. log activity

Webhook routes exist in:

routers/webhook.py

If Radarr-related webhooks already exist or are later added, they may be used to improve freshness, but manual sync must still exist and work independently.

---

# 9. Configuration

Configuration is managed through:

services/config.py  
.env  
docker-compose.yml  

Configuration may include:

- database connection
- API settings
- job parameters
- runtime environment configuration
- Radarr API connection details
- sync behavior configuration
- queue polling configuration
- reconciliation timeouts
- logging configuration

Secrets must never be stored in the repository.

.env.example should provide sample configuration.

---

# 10. Docker Deployment

The project runs using Docker.

Deployment files:

docker-compose.yml  
Dockerfile  

Requirements:

- containers must build reproducibly
- environment variables must load correctly
- services must start reliably

The new Radarr sync behavior must work correctly within the Docker deployment environment.

---

# 11. Functional Requirements

The system must support:

1. job creation
2. job monitoring
3. webhook triggered workflows
4. background synchronization
5. configuration management
6. API communication with the frontend
7. accurate media search and matching
8. validated download flows
9. per-movie Radarr sync
10. sync all movies
11. correct status reconciliation
12. Radarr deletion detection
13. monitored toggle persistence
14. correct available / movie missing / downloading status refresh

---

# 12. Non-Functional Requirements

## Reliability

The system should run continuously without crashing.

All errors must be logged clearly.

Synchronization and reconciliation logic must behave predictably and safely.

## Maintainability

The system must follow a modular structure.

Core logic belongs in services/.

Routers remain thin.

State derivation and Radarr synchronization should be centralized and testable.

## Scalability

The system should support:

- multiple concurrent jobs
- frequent API requests
- bursts of webhook events
- repeated sync operations
- sync-all behavior over larger movie collections

## Accuracy

Displayed movie state must accurately reflect current Radarr truth.

The system must minimize stale or reverted states.

## Usability

The frontend must make it clear:

- which movies are in sync
- which movies need attention
- which statuses changed after sync
- whether a sync action succeeded or failed

---

# 13. Deliverables

The completed stage must include:

1. backend support for single-movie sync
2. backend support for sync all
3. correct Radarr deletion detection
4. correct movie status reconciliation
5. frontend Sync button on each movie card
6. frontend Sync All button
7. correct monitored toggle persistence
8. clear logging and error handling for sync operations
9. reliable Docker-compatible implementation
10. explainable and testable reconciliation behavior

---

# 14. Definition of Done

This stage is complete when:

1. the system checks whether a movie has been deleted from Radarr
2. deleting a movie from Radarr causes the app status to update correctly after sync
3. each movie card has a working Sync button
4. the UI has a working Sync All button
5. sync updates available, movie missing, and downloading states correctly
6. monitored toggles no longer revert incorrectly
7. the backend uses Radarr-confirmed state during reconciliation
8. stale local state no longer overrides newer Radarr state
9. logs clearly show sync actions, reconciliation decisions, and errors
10. the implementation is modular, explainable, and testable

---

# Implementation History

The agent must read this section before starting any work to understand what was previously implemented.

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
- Added proper year extraction using regex from card text
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
- Added implementation log to `instructions.md` with all previous changes documented
- Verified `docker-compose.yml` in repo is a clean template (no secrets)
- Pushed all accumulated changes to GitHub; GHCR build triggered automatically via GitHub Actions

**Files changed:**
- `instructions.md`

---

## 2026-03-07 — Search Fix + Frontend Revamp

**Backend:**
- Removed `-40` year mismatch penalty in `einthusan.py` — was falsely rejecting valid movies (e.g. Guppy 2015 Malayalam)
- Year mismatch no longer penalises; only correct year receives +15 bonus
- Added 6 additional fallback card selectors for Einthusan layout variations
- Added DEBUG-level logging for all candidate cards and match scores

**Frontend:**
- `ui.jsx`: Added `movie_missing` → 'File Missing' badge; removed emojis from all badge labels; fixed null safety on `ProgressBar`
- `Dashboard.jsx`: Trigger button in header; language badge on active downloads; accent colour for active count; `movie_missing` coloured red in activity log
- `Jobs.jsx`: Path column shows filename only; `movie_missing` jobs can be retried
- `Settings.jsx`: Removed emojis from all section titles
- `index.css`: Added purple token for `movie_missing` badge; stat card lifts on hover with green top border; removed duplicate `btn-danger` rule

**Files changed:**
- `backend/services/einthusan.py`
- `frontend/src/components/ui.jsx`
- `frontend/src/pages/Dashboard.jsx`
- `frontend/src/pages/Jobs.jsx`
- `frontend/src/pages/Settings.jsx`
- `frontend/src/index.css`
- `instructions.md`

---

## 2026-03-07 — Guppy Not Found Root Cause Fix

**Root cause diagnosed:**
- Einthusan's `<a class="title">` anchor contains the movie title in an `<h3>` AND a badge (e.g. 'Must Watch') in a sibling `<span>`
- Calling `anchor.get_text()` concatenates both into "GuppyMust Watch"
- `fuzz.token_set_ratio('guppy', 'guppymust watch')` ≈ 67 → fails the 85 threshold → movie rejected
- This affected any movie with a 'Must Watch', 'Dubbed', 'Recommended', or similar badge

**Fix applied to `einthusan.py`:**
- Changed selector to `a.title[href*='/movie/watch/']` — the canonical Einthusan anchor
- Title is now extracted from `anchor.find('h3').get_text()` instead of `anchor.get_text()`
- Fallback strips known badge strings (Must Watch, Recommended, Dubbed, Subtitle, New, Premium) before matching
- Added `_BADGE_STRINGS` constant for maintainability
- `token_set_ratio('guppy', 'guppy')` = 100 → well above 85 threshold
- Year matching unchanged: bonus-only, walks up DOM to parent li for year extraction

**Files changed:**
- `backend/services/einthusan.py`

---

## 2026-03-12 — Documentation Restructured

**Changes made:**
- Removed implementation history from `instructions.md` — it now contains only operating rules
- Moved full implementation history to `project_specs.md` (this section)
- Updated Section 9 of `instructions.md` to reference `project_specs.md` for history

**Files changed:**
- `instructions.md`
- `project_specs.md`

---

## [2026-05-02] Fix Edge Cases for Search & Downloading

**Changes made:**
- **Search Accuracy:** Modified `backend/services/einthusan.py` to add strict penalty for standalone number mismatches. This prevents false positive matches like querying "Aadu" and downloading the sequel "Aadu 2".
- **Release Date Fallback:** Modified `backend/orchestrator.py` to allow the search to proceed if the digital release date is unknown (`None`), preventing movies like "Bokshi" from being skipped unnecessarily.
- **Retry Logic (Refind):** Modified `backend/routers/jobs.py` to reset the job status to `PENDING` when the user clicks Retry. This resolves the bug where pressing the button on a `DONE` or `FAILED` job did nothing because the orchestrator guard immediately rejected it.

**Files changed:**
- `backend/services/einthusan.py`
- `backend/orchestrator.py`
- `backend/routers/jobs.py`

---

## [2026-05-02] Fix Stale Errors & Unmonitored Sync

**Changes made:**
- **Clear Error on Success:** Modified `backend/orchestrator.py` to clear `error_msg` when a job finishes successfully. Previously, an old error (like "Release date not yet passed") would persist even after the movie was successfully downloaded on a later sync.
- **Sync Unmonitored Jobs:** Modified `backend/sync.py` so the background sync scheduler checks Radarr for *all* unmonitored jobs, not just `DONE` jobs. This ensures movies marked as `MOVIE_MISSING` or `SKIPPED` are updated to `DONE` if the user downloaded them manually via another indexer.

**Files changed:**
- `backend/orchestrator.py`
- `backend/sync.py`

---

## [2026-05-08] Two-Way Monitored Sync and Radarr Import

**Changes made:**
- **Two-Way Sync for Monitored Status:**
  - Radarr to App: Modified `backend/sync.py` to compare and fetch the Radarr `monitored` status for both monitored and unmonitored local jobs during the standard background sync loop.
  - App to Radarr: Updated `backend/routers/jobs.py` (`PUT /jobs/{job_id}/monitor`) to instantly push local UI monitored toggles directly to Radarr.
- **Import Regional Movies Feature:**
  - Added `POST /jobs/import-radarr` endpoint in `backend/routers/jobs.py` that fetches all movies from Radarr, checks if their `originalLanguage` matches configured Einthusan languages, and populates them into the database.
  - Added an "Import Regional Movies" UI button inside the `Settings.jsx` Radarr configuration section to trigger this API endpoint.

**Files changed:**
- `backend/services/radarr.py`
- `backend/routers/jobs.py`
- `backend/sync.py`
- `frontend/src/api.js`
- `frontend/src/pages/Settings.jsx`

---

## [2026-05-08] Import Radarr Bugfixes

**Changes made:**
- **Missing Movies Status Fix:** Modified `backend/routers/jobs.py` so that movies imported from Radarr without files are given the `MOVIE_MISSING` status instead of `PENDING`. This fixes the issue where missing or unreleased movies incorrectly displayed "Downloading on Radarr". Since they are monitored, the background sync will accurately check their status, and trigger the Einthusan fallback search if they are not actively downloading.
- **Import Posters Fix:** Updated the import logic to parse and save the TMDB `poster_path` from the Radarr `images` array (by parsing `remoteUrl`) so that newly imported movies display their posters correctly.

**Files changed:**
- `backend/routers/jobs.py`

---

## [2026-05-08] Auto-Import Regional Movies in Sync & Import Bugfixes

**Changes made:**
- **Auto-Import in Sync Loop:** Added a mechanism to `backend/sync.py` that automatically queries Radarr for all movies on every sync interval. It filters for the configured regional languages and imports any new movies directly into the database. If they don't have files and Radarr isn't actively downloading them, the Einthusan fallback search will automatically trigger.
- **Import Bugfix (Early Exit):** Discovered and removed an old code snippet in `backend/routers/jobs.py` that caused the manual import endpoint to prematurely exit when it encountered existing database entries, which was entirely bypassing the newly added "healing" logic for posters and `MOVIE_MISSING` statuses. The manual import now properly heals and updates existing database records.

**Files changed:**
- `backend/routers/jobs.py`
- `backend/sync.py`

---

## [2026-05-08] Movies UI Action Buttons

**Changes made:**
- **Trigger Missing Button:** Added a `POST /jobs/trigger-missing` endpoint and corresponding UI button to trigger the orchestrator search pipeline specifically for all movies with the `MOVIE_MISSING` status.
- **Trigger Monitored Button:** Renamed and refactored the old "Trigger All" endpoint to `POST /jobs/trigger-monitored` and updated the UI button to "Trigger Monitored", explicitly targeting jobs where `monitored == True`.

**Files changed:**
- `backend/routers/jobs.py`
- `frontend/src/api.js`
- `frontend/src/pages/Movies.jsx`

---

## [2026-05-08] Fix Database Connection Exhaustion

**Changes made:**
- **Database Engine Config:** Replaced the default SQLAlchemy `SingletonThreadPool` (which has a limit of 5 connections) with `NullPool` for SQLite. Since SQLite handles concurrent tasks by waiting on file locks, using a connection pool is unnecessary and was causing `QueuePool limit of size 5 overflow 10 reached` timeout errors when triggering dozens of concurrent downloads using the new "Trigger Monitored" or "Trigger Missing" buttons. Added a 30-second timeout and disabled thread checking to allow high concurrency without crashing the app.

**Files changed:**
- `backend/database.py`

---

## [2026-05-08] Fix TMDB Rate Limiting and Duplicate Failed Jobs

**Changes made:**
- **TMDB API Backoff:** Added an exponential backoff and retry mechanism (`_fetch_with_retry`) in `backend/services/tmdb.py` to properly handle `429 Too Many Requests` responses from the TMDB API. This prevents lookups from immediately failing when triggering large batches of downloads concurrently.
- **Duplicate Job Fix:** Modified the orchestrator (`backend/orchestrator.py`) so that if a TMDB lookup *does* fail, it first checks if the job already exists in the database and updates its status to `FAILED`. Previously, it was blindly creating a duplicate "TMDB:xxxxxx" fallback job every time the lookup failed.

**Files changed:**
- `backend/orchestrator.py`
- `backend/services/tmdb.py`

