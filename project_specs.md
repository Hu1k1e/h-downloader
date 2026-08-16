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
- the movieâ€™s local state must be updated accordingly
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

## 2026-02-22 â€” Deployment Simplification

**Changes made:**
- Removed `env_file: .env` from `docker-compose.yml` â€” replaced with inline `environment:` block to fix Portainer compatibility
- Removed external `media-network` requirement from `docker-compose.yml` â€” Docker will use default network automatically
- Updated `README.md` Quick Start section to embed the docker-compose template and `.env` block directly so users can deploy without cloning the repo
- Removed GHCR authentication requirement from README (repo and package are now public)

**Files changed:**
- `docker-compose.yml`
- `README.md`

---

## 2026-02-22 â€” MOVIE_MISSING Status and UI Polish

**Changes made:**
- Added `MOVIE_MISSING` status to `JobStatus` enum in `backend/models.py`
- Modified `sync.py` to detect when a `DONE` job's file is deleted from disk â†’ marks as `MOVIE_MISSING`, unmonitored
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

## 2026-02-26 â€” Einthusan Search Accuracy Improvement

**Changes made:**
- Replaced `fuzz.partial_ratio` with `fuzz.token_set_ratio` for title matching in `einthusan.py`
- Raised the minimum match score threshold from 55 to 85
- Added proper year extraction using regex from card text
- Year matches within Â±1 year receive a +15 score bonus; wrong years receive a -40 penalty
- Used `isinstance(year, int)` to safely handle `Optional[int]` year parameter

**Files changed:**
- `backend/services/einthusan.py`

---

## 2026-02-26 â€” Radarr RescanMovie Trigger

**Changes made:**
- Replaced `DownloadedMoviesScan` command with `RescanMovie` command in `radarr.py`
- `RescanMovie` uses the Radarr movie ID directly, scanning the movie's specific folder
- Updated `orchestrator.py` to fetch the Radarr movie ID after download and call `trigger_rescan`
- Root cause: `DownloadedMoviesScan` is for staging directories; files placed directly in Radarr's media folder were being ignored by it

**Files changed:**
- `backend/services/radarr.py`
- `backend/orchestrator.py`

---

## 2026-02-26 â€” Sync Grace Period + Jobs Path Column

**Changes made:**
- Added a 2-hour grace period in `sync.py` before marking a `DONE` job as `MOVIE_MISSING`
  - Root cause: large files can take time for Radarr to import; sync was flagging them as missing during that window
- Added `Path` column to the Jobs table in `Jobs.jsx` showing the file destination path
  - Column truncates with ellipsis; full path visible on hover via `title` attribute

**Files changed:**
- `backend/sync.py`
- `frontend/src/pages/Jobs.jsx`

---

## 2026-03-07 â€” Instructions Update

**Changes made:**
- Added Section 9 (Push to GitHub Rules) to `instructions.md`
- Added implementation log to `instructions.md` with all previous changes documented
- Verified `docker-compose.yml` in repo is a clean template (no secrets)
- Pushed all accumulated changes to GitHub; GHCR build triggered automatically via GitHub Actions

**Files changed:**
- `instructions.md`

---

## 2026-03-07 â€” Search Fix + Frontend Revamp

**Backend:**
- Removed `-40` year mismatch penalty in `einthusan.py` â€” was falsely rejecting valid movies (e.g. Guppy 2015 Malayalam)
- Year mismatch no longer penalises; only correct year receives +15 bonus
- Added 6 additional fallback card selectors for Einthusan layout variations
- Added DEBUG-level logging for all candidate cards and match scores

**Frontend:**
- `ui.jsx`: Added `movie_missing` â†’ 'File Missing' badge; removed emojis from all badge labels; fixed null safety on `ProgressBar`
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

## 2026-03-07 â€” Guppy Not Found Root Cause Fix

**Root cause diagnosed:**
- Einthusan's `<a class="title">` anchor contains the movie title in an `<h3>` AND a badge (e.g. 'Must Watch') in a sibling `<span>`
- Calling `anchor.get_text()` concatenates both into "GuppyMust Watch"
- `fuzz.token_set_ratio('guppy', 'guppymust watch')` â‰ˆ 67 â†’ fails the 85 threshold â†’ movie rejected
- This affected any movie with a 'Must Watch', 'Dubbed', 'Recommended', or similar badge

**Fix applied to `einthusan.py`:**
- Changed selector to `a.title[href*='/movie/watch/']` â€” the canonical Einthusan anchor
- Title is now extracted from `anchor.find('h3').get_text()` instead of `anchor.get_text()`
- Fallback strips known badge strings (Must Watch, Recommended, Dubbed, Subtitle, New, Premium) before matching
- Added `_BADGE_STRINGS` constant for maintainability
- `token_set_ratio('guppy', 'guppy')` = 100 â†’ well above 85 threshold
- Year matching unchanged: bonus-only, walks up DOM to parent li for year extraction

**Files changed:**
- `backend/services/einthusan.py`

---

## 2026-03-12 â€” Documentation Restructured

**Changes made:**
- Removed implementation history from `instructions.md` â€” it now contains only operating rules
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

---

## [2026-05-08] Fix MP4 Extraction JSON Parsing Error

**Changes made:**
- **Decrypted JSON Safety:** Added type checking to the decrypted `EJLinks` JSON response in `backend/services/einthusan.py`. Sometimes the Einthusan API returns a top-level string (or double-encoded JSON) instead of a dictionary, causing the app to crash with an unhandled `'str' object has no attribute 'get'` error when trying to extract the MP4 link. The function now correctly checks the type and parses it properly, or raises a descriptive exception containing the actual Einthusan API error message (e.g. if the IP was blocked).

**Files changed:**
- `backend/services/einthusan.py`


---

## [2026-05-17] Tag Einthusan Downloads as 720p for Radarr Upgrade Compatibility

**Problem:**
Files downloaded from Einthusan were saved without a quality tag in the filename (e.g. `Guppy (2015).mp4`).
When Radarr rescanned the file, it had no quality information to parse, so it treated the file as `Unknown` quality.
This prevented Radarr from upgrading the file when a proper higher-quality release became available on an indexer.

**Fix:**
Modified `get_movie_file_path()` in `backend/services/downloader.py` to append `- 720p` to every filename.
Example: `Guppy (2015) - 720p.mp4`

Radarr's filename parser recognises the `720p` token when it performs a `RescanMovie` after download.
It records the file as 720p quality in its database.
If the configured quality profile has upgrading enabled (e.g. 720p -> 1080p), Radarr will replace this file
when it later grabs a 1080p release from a proper indexer.

**Why 720p specifically:**
Einthusan streams are typically 720p resolution web streams. Tagging them as 720p is accurate.
It ensures Radarr does not keep the Einthusan copy permanently when a proper Blu-ray or 1080p WEB release becomes available.

**Files changed:**
- `backend/services/downloader.py`

---

## [2026-06-01] Fix Language Filtering and Job Cleanup

**Problem:**
The database contained legacy Hollywood movies from a reverted update, and the app was displaying them. Radarr import and sync processes were not actively removing jobs that no longer matched the configured languages in settings.

**Changes made:**
- **UI Filtering:** Updated `GET /api/jobs` in `backend/routers/jobs.py` to strictly filter returned jobs by the languages currently ticked in settings (unless specifically querying a single language). This immediately hides any irrelevant legacy movies from the UI.
- **Active Cleanup on Import:** Modified the `POST /jobs/import-radarr` endpoint to proactively delete any existing jobs from the database whose language does not match the configured languages.
- **Active Cleanup on Sync:** Modified both `sync_radarr_status` and `sync_jellyseerr_requests` in `backend/sync.py` to identify and delete any jobs from the database that no longer match the configured languages.

**Files changed:**
- `backend/routers/jobs.py`
- `backend/sync.py`

---

## [2026-06-02] Fix CPU Utilization and N+1 API Spam

**Problem:**
The background sync loop (sync_jellyseerr_requests) was executing an N+1 API call pattern. For every single monitored and unmonitored job in the database, it was calling is_movie_in_radarr and get_movie_queue_status. Each of these functions made an HTTP GET request to Radarr that fetched the *entire* movie library or queue. This resulted in hundreds of heavy HTTP requests every 30 seconds, maxing out CPU utilization to ~70% and causing extreme UI latency. 
Additionally, the previous language cleanup loop was missing a session.commit(), which meant legacy jobs were deleted from memory but never permanently removed from the SQLite database.

**Changes made:**
- **N+1 Optimization:** Completely rewrote the `sync_jellyseerr_requests` loop. It now fetches the Radarr movie list and Radarr queue exactly ONCE at the start of the loop and converts them into constant-time dictionaries (`radarr_by_tmdb` and `queue_by_movie_id`).
- **Eliminated HTTP Spam:** Replaced all iterative `is_movie_in_radarr` and `get_movie_queue_status` calls with instant dictionary lookups.
- **Fixed DB Cleanup:** Added the missing `session.commit()` inside the auto-cleanup block so that Hollywood movies are permanently purged from the database.
- **Refactored Radarr Client:** Added `get_full_queue` to `backend/services/radarr.py` to support bulk queue fetching.

**Files changed:**
- `backend/sync.py`
- `backend/services/radarr.py`

---

## [2026-06-02] Fix Pagination Limits for Large Collections

- Year matching unchanged: bonus-only, walks up DOM to parent li for year extraction

**Files changed:**
- `backend/services/einthusan.py`

---

## 2026-03-12 â€” Documentation Restructured

**Changes made:**
- Removed implementation history from `instructions.md` â€” it now contains only operating rules
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

---

## [2026-05-08] Fix MP4 Extraction JSON Parsing Error

**Changes made:**
- **Decrypted JSON Safety:** Added type checking to the decrypted `EJLinks` JSON response in `backend/services/einthusan.py`. Sometimes the Einthusan API returns a top-level string (or double-encoded JSON) instead of a dictionary, causing the app to crash with an unhandled `'str' object has no attribute 'get'` error when trying to extract the MP4 link. The function now correctly checks the type and parses it properly, or raises a descriptive exception containing the actual Einthusan API error message (e.g. if the IP was blocked).

**Files changed:**
- `backend/services/einthusan.py`


---

## [2026-05-17] Tag Einthusan Downloads as 720p for Radarr Upgrade Compatibility

**Problem:**
Files downloaded from Einthusan were saved without a quality tag in the filename (e.g. `Guppy (2015).mp4`).
When Radarr rescanned the file, it had no quality information to parse, so it treated the file as `Unknown` quality.
This prevented Radarr from upgrading the file when a proper higher-quality release became available on an indexer.

**Fix:**
Modified `get_movie_file_path()` in `backend/services/downloader.py` to append `- 720p` to every filename.
Example: `Guppy (2015) - 720p.mp4`

Radarr's filename parser recognises the `720p` token when it performs a `RescanMovie` after download.
It records the file as 720p quality in its database.
If the configured quality profile has upgrading enabled (e.g. 720p -> 1080p), Radarr will replace this file
when it later grabs a 1080p release from a proper indexer.

**Why 720p specifically:**
Einthusan streams are typically 720p resolution web streams. Tagging them as 720p is accurate.
It ensures Radarr does not keep the Einthusan copy permanently when a proper Blu-ray or 1080p WEB release becomes available.

**Files changed:**
- `backend/services/downloader.py`

---

## [2026-06-01] Fix Language Filtering and Job Cleanup

**Problem:**
The database contained legacy Hollywood movies from a reverted update, and the app was displaying them. Radarr import and sync processes were not actively removing jobs that no longer matched the configured languages in settings.

**Changes made:**
- **UI Filtering:** Updated `GET /api/jobs` in `backend/routers/jobs.py` to strictly filter returned jobs by the languages currently ticked in settings (unless specifically querying a single language). This immediately hides any irrelevant legacy movies from the UI.
- **Active Cleanup on Import:** Modified the `POST /jobs/import-radarr` endpoint to proactively delete any existing jobs from the database whose language does not match the configured languages.
- **Active Cleanup on Sync:** Modified both `sync_radarr_status` and `sync_jellyseerr_requests` in `backend/sync.py` to identify and delete any jobs from the database that no longer match the configured languages.

**Files changed:**
- `backend/routers/jobs.py`
- `backend/sync.py`

---

## [2026-06-02] Fix CPU Utilization and N+1 API Spam

**Problem:**
The background sync loop (sync_jellyseerr_requests) was executing an N+1 API call pattern. For every single monitored and unmonitored job in the database, it was calling is_movie_in_radarr and get_movie_queue_status. Each of these functions made an HTTP GET request to Radarr that fetched the *entire* movie library or queue. This resulted in hundreds of heavy HTTP requests every 30 seconds, maxing out CPU utilization to ~70% and causing extreme UI latency. 
Additionally, the previous language cleanup loop was missing a session.commit(), which meant legacy jobs were deleted from memory but never permanently removed from the SQLite database.

**Changes made:**
- **N+1 Optimization:** Completely rewrote the `sync_jellyseerr_requests` loop. It now fetches the Radarr movie list and Radarr queue exactly ONCE at the start of the loop and converts them into constant-time dictionaries (`radarr_by_tmdb` and `queue_by_movie_id`).
- **Eliminated HTTP Spam:** Replaced all iterative `is_movie_in_radarr` and `get_movie_queue_status` calls with instant dictionary lookups.
- **Fixed DB Cleanup:** Added the missing `session.commit()` inside the auto-cleanup block so that Hollywood movies are permanently purged from the database.
- **Refactored Radarr Client:** Added `get_full_queue` to `backend/services/radarr.py` to support bulk queue fetching.

**Files changed:**
- `backend/sync.py`
- `backend/services/radarr.py`

---

## [2026-06-02] Fix Pagination Limits for Large Collections

**Problem:**
The API default `limit` for fetching movies was 100, which caused the frontend to silently truncate the list to 100 movies. Jellyseerr also had a `take: 50` limit when fetching approved requests.

**Changes made:**
- Increased API limits for `GET /api/jobs` to 10000.
- Increased Jellyseerr approved request fetch `take` parameter to 10000.
- Added `pageSize=10000` to Radarr `/queue` API calls to ensure large queues are not truncated.

---

## [2026-06-03] Delayed Missing Searches and Configurable Background Sync

**Problem:**
The app would either immediately query qBittorrent and execute searches, leading to double-searches before Radarr had a chance to import and stall them. It also lacked a way to cleanly space out background searches for movies that were stuck in the `MOVIE_MISSING` status without tying it to the frequent Jellyseerr sync loop.

**Changes made:**
- **Delayed Search Execution:** Implemented a `delayed_search()` async function in `backend/sync.py`. When a new missing movie is synced from Radarr or Jellyseerr, it is delayed by 2 minutes. The system then queries Radarr directlyâ€”if Radarr is actively downloading it (e.g. from a different list sync), the fallback Einthusan/1TamilMV search is skipped entirely.
- **Configurable Background Loop:** Added a separate `sync_missing_movies()` async loop specifically for retrying `MOVIE_MISSING` jobs. Configured a brand new `missing_search_interval_hours` and `missing_search_batch_size` parameter in `backend/models.py`. Exposed these to the user in the `Settings` UI page, parsing them accurately in the frontend.
- **Generalize Torrent Checks:** Removed hardcoded `"1tamilmv"` string checks across the app where it attempted to monitor torrent hashes. The system now evaluates progress for ANY download source that populates `job.torrent_hash`, providing future-proof compatibility with apps like `cleanuparr`.

---

## [2026-06-04] Fix Radarr Queue Conflict & Status Desync

**Problem:**
The app showed conflicting statuses: it downloaded via Einthusan but simultaneously flagged the UI with a "Not found or failed" error, and it incorrectly searched for movies that Radarr was already actively downloading. This was caused by `webhook.py` triggering searches immediately (bypassing the 2m delay), the Radarr queue check reading only the *first* (often stalled) torrent out of multiple grabs, and the Einthusan step forgetting to clear stale error messages.

**Changes made:**
- **Webhook Delay Integration:** Modified `backend/routers/webhook.py` to stop firing `process_request` immediately. It now correctly creates the job as `MOVIE_MISSING` and triggers `delayed_search`, giving Radarr its full 2 minutes to grab torrents from its own RSS or lists.
- **Queue Active Item Preference:** Updated `backend/services/radarr.py`'s `get_movie_queue_status` to scan all queue records for a movie instead of just returning the first one. If Radarr grabbed 6 torrents and the first one stalled, it will now correctly find the active one and realize Radarr is handling it.
- **Stale Error Cleanup:** Updated `backend/orchestrator.py` to explicitly clear `error_msg=None` when transitioning a job to `JobStatus.DOWNLOADING` via Einthusan, resolving the contradictory UI state.



---

## [2026-06-04] System Logs, Active Downloads Validation, and Torrent File Filtering

**Problem:**
The app lacked detailed logs for searches and background tasks, making it difficult to monitor. The 'Active Downloads' UI was falling out of sync with qBittorrent, showing an active count but an empty list because the default 50-limit fetch missed older downloading jobs. Furthermore, qBittorrent was downloading unnecessary non-movie files (e.g. .exe, .txt) from 1TamilMV torrents.

**Changes made:**
- **System Logs:** Created a `LogEntry` database model and a dedicated `Logs` UI page. Actions such as auto-searches, manual searches, filtering, and import events are now explicitly logged and viewable in the UI, complete with filtering and bulk-deletion options.
- **Active Downloads Fix:** Replaced generic DB status checks with a new `GET /api/jobs/active` endpoint. This endpoint actively queries qBittorrent's real-time state, stripping out jobs that are paused or errored, ensuring the UI list strictly reflects live active downloads regardless of their age.
- **Torrent File Filtering:** Added `filter_torrent_files` to `backend/services/qbittorrent.py`. When a torrent fetches metadata, the system now automatically scans the files, identifies the largest video file (`.mp4`, `.mkv`, etc.), and disables downloading (sets priority to 0) for all other junk files.


---

## 2026-06-04 — Backend Refactoring, System Logs & Frontend Redesign

**Backend:**
- Implemented robust ilter_torrent_files to explicitly check for video extensions and enforce size limits (min_file_size_mb, max_file_size_mb).
- Added uto_delete_failed_torrents_hours configuration.
- Improved Active Job tracking (/api/jobs/active) by querying qBittorrent for live download status and tracking active direct HTTP streams in memory.
- Added syncio.Lock() per TMDB ID to prevent concurrent duplicate processing.
- Created /api/logs router for fetching and managing system logs.

**Frontend:**
- Created Logs.jsx for viewing, searching, and deleting system logs.
- Redesigned index.css to use a premium dark mode with glassmorphism effects (ackdrop-filter: blur(16px)).
- Updated Settings.jsx to configure the new size limits and auto-delete settings.
- Fixed a JSX syntax error in Logs.jsx to resolve Docker uildx issues.



---

## 2026-06-04 — Settings API Fix & Automation Toggles

**Backend:**
- Fixed a bug in outers/settings.py where new fields were missing from the AppSettingsRead schema, causing the /api/settings endpoint to crash (500 error) during validation.
- Added enable_jellyseerr_auto_request and enable_radarr_auto_search boolean columns to the SQLite ppsettings table via auto-migration in database.py.
- Updated ackend/sync.py to respect the new automation toggles before fetching from Jellyseerr or importing from Radarr.

**Frontend:**
- Added a new 'Automation' section to Settings.jsx with checkboxes to enable/disable Jellyseerr and Radarr automatic background processes.



## 2026-06-04 - Fix Auto Search, Title Regex, and Remove Blacklist

**Backend:**
- Gate background sync searches behind enable_radarr_auto_search.
- Remove blacklist logic entirely from orchestrator and sync.
- Set JobStatus.SEARCHING immediately to fix UI latency on manual trigger.
- Use exact regex word matching for movie titles in 1TamilMV.


- Fixed qBittorrent 409 Conflict error failing searches by correctly tracking already-added torrents.
- Fixed UI displaying 'Downloading on Radarr' for movies that were just 'Pending' in the local queue.


- Replaced periodic background sync with a real-time event-driven architecture using Radarr Webhooks.
- Replaced global sync interval settings with a configurable search_delay_seconds setting for fallback searches.

---

## [2026-06-29] Manual Provider Links, URL Import, and Short-Title Search Fix

**Problem:**
1. The UI provided no way to manually search active providers (Einthusan, 1TamilMV) for a specific movie.
2. The movie `Mrs` (TMDB year 2023) failed to be found on Einthusan despite being present, because Einthusan lists it as 2025 (a 2-year gap exceeded the ±1 year tolerance).
3. When automated search failed, there was no way to paste a provider URL to manually trigger the download pipeline.

**Changes made:**
- **Einthusan Search Fallback:** Refactored `search()` in `backend/services/einthusan.py` into a wrapper that calls `_search_with_query()`. If the initial title-only query returns no match, it retries with `{title} {year}` and adjacent years. This helps short titles (e.g. `Mrs`) and year-discrepancy cases.
- **Year Tolerance Widened:** Changed the Einthusan year bonus match from ±1 to ±2 years to handle Einthusan/TMDB date discrepancies.
- **Manual URL Import Endpoint:** Added `POST /api/jobs/{job_id}/import-url` in `backend/routers/jobs.py`. Accepts an Einthusan watch URL or 1TamilMV thread URL, auto-detects the provider, extracts the download (MP4 or magnet), and starts the job.
- **Manual Search Links:** Updated `MovieModal` in `frontend/src/pages/Movies.jsx` to display clickable search links for each active provider — one Einthusan link per configured language, plus a 1TamilMV search link. Links open in new tabs.
- **Import URL UI:** Added an `Import from URL` input field in the movie modal. Users can paste a provider URL and click Import to start the download.
- **Frontend API:** Added `importUrl()` method to `frontend/src/api.js`.

**Files changed:**
- `backend/services/einthusan.py`
- `backend/routers/jobs.py`
- `frontend/src/api.js`
- `frontend/src/pages/Movies.jsx`
- `project_specs.md`

---

## [2026-07-14] Discovery Loop Fixes: NOT_FOUND Retry + Release Date Bypass

**Problem:**
A movie ('Mollywood Times') was added to Radarr on June 12 but the app never searched for it. Radarr independently grabbed it 32 days later. Root cause analysis revealed:
1. Movies that failed source search were marked `NOT_FOUND` — a permanent dead end never retried by the discovery loop.
2. Movies without a TMDB digital release date were perpetually `SKIPPED` by the pipeline, even when available on sources (common for regional Indian cinema where digital dates are rarely listed).
3. `delayed_search` passed `None` as language instead of using the resolved language from the webhook.
4. No log entries were created when movies were SKIPPED, making debugging impossible.

**Changes made:**
- **NOT_FOUND Retry:** Added `NOT_FOUND` to the discovery loop query in `backend/sync.py`. Movies that weren't found on Einthusan/1TamilMV will now be retried every `missing_search_interval_hours` (default 24h).
- **Release Date Bypass:** Added `skip_release_check` parameter to `process_request` and `_run_pipeline` in `backend/orchestrator.py`. The discovery loop now passes `skip_release_check=True` for `SKIPPED` and `NOT_FOUND` jobs, allowing them to proceed to source search even if TMDB lacks a digital release date.
- **Language Passthrough:** Fixed `backend/routers/webhook.py` to pass `job.language` instead of `None` to `delayed_search`, avoiding a redundant TMDB API call.
- **SKIPPED Logging:** Added `log_action` call in `backend/orchestrator.py` when a movie is SKIPPED due to release date gating.

**Files changed:**
- `backend/sync.py`
- `backend/orchestrator.py`
- `backend/routers/webhook.py`
- `project_specs.md`


---

## [2026-07-20] Auto-Download Workflow Fixes & Sync Loopholes Patched

**Problem:**
Several movies (e.g. Thira, Naradan, Vodka Diaries) failed to trigger auto-downloads despite Radarr grabs failing. Radarr would indefinitely cycle through grabs, or the download would sit in a Warning/Error state without our platform falling back to custom sources. Furthermore, the discovery_tracker_loop was silently crashing due to a missing import, and two major sync loopholes allowed movies to be permanently ignored if they were added while the app was offline or deleted from Radarr after completing.

**Changes made:**
- **Error State Detection:** Modified active_job_tracker_loop in backend/sync.py to trigger an immediate fallback search if all Radarr queue items for a movie enter a warning or error state.
- **Dual Download Prevention:** Added a check in orchestrator.py (_run_pipeline) to defer to Radarr if Radarr actively has a healthy (non-error) download, preventing both systems from downloading the same movie simultaneously.
- **Discovery Loop Fixes:** Added missing datetime import to backend/sync.py to prevent silent crashes, and added JobStatus.FAILED to the discovery loop query so failed jobs get retried.
- **Sync Loopholes Patched:** Modified radarr_state_sync_loop in backend/sync.py to actively cross-reference Radarrs library. It now creates a MOVIE_MISSING job for any monitored Radarr movie missing a file that isnt in our DB, and it reverts DONE jobs back to MOVIE_MISSING if their file gets deleted from Radarr.
- **Model and Config Consistency:** Added the missing enable_radarr_auto_search field to the AppSettings SQLModel schemas in backend/models.py and exposed it via the settings API in backend/routers/settings.py.
- **Variable Scope Crash Fix:** Fixed an undefined mapped_lang variable scope crash in the MovieAdded webhook handler (backend/routers/webhook.py).

**Files changed:**
- backend/sync.py
- backend/orchestrator.py
- backend/models.py
- backend/routers/webhook.py
- backend/routers/settings.py



---

## [2026-07-20] Auto-Retrieve Missing Posters Fix

**Problem:**
Movies automatically added by Radarr webhooks or state sync showed up in the UI without movie posters or release years. The system only fetched the poster path and year if the user manually clicked search or if the backend orchestration pipeline was fully triggered. If Radarr grabbed the movie natively, it never entered the orchestration pipeline, leaving the UI permanently broken with a placeholder image.

**Changes made:**
- **Webhook Extraction:** Updated backend/routers/webhook.py to immediately extract and save the \poster_path\ and \year\ to the DownloadJob when processing the MovieAdded webhook.
- **Background Metadata Fetcher:** Created an \_fetch_and_update_metadata(job_id)\ background helper in backend/sync.py to silently fetch missing TMDB metadata.
- **Sync Loop Backfill:** Hooked the metadata fetcher into adarr_state_sync_loop\ so any \MOVIE_MISSING\ jobs created from missed webhooks immediately fetch their posters.
- **Active Download Backfill:** Hooked the metadata fetcher into \ ctive_job_tracker_loop\ so any natively downloading Radarr jobs that were previously missing posters get backfilled dynamically.

**Files changed:**
- backend/routers/webhook.py
- backend/sync.py
- project_specs.md


---

## [2026-08-11] New Release Grace Period — Replace Priority Queue with Deferral Window

**Problem:**
The `run_discovery_batch()` function had a priority queue that front-loaded jobs with a `release_date` within the last 2 days. This caused H-Downloader to rush to grab whatever torrent was available first on custom sources (e.g., CAM/HDTS rips on 1TamilMV), before Radarr had a chance to find a quality release through its indexers. This undermined Radarr's quality profile and upgrade logic.

**Changes made:**
- **Grace Period Deferral:** Replaced the priority queue in `run_discovery_batch()` with a new release grace period. Jobs with a `release_date` within the configured `new_release_grace_hours` (default 48h) are now EXCLUDED from the discovery loop, giving Radarr/Sonarr time to find quality releases first.
- **New Setting:** Added `new_release_grace_hours` (default 48) to `AppSettings` model, DB migration, and API.
- **Frontend:** Added a "New Release Grace" input field to the Automation section in Settings.jsx with an explanation.
- **Bug Fix:** Removed a duplicate `missing_search_batch_size` handler in `routers/settings.py`.

**Files changed:**
- backend/models.py
- backend/database.py
- backend/sync.py
- backend/routers/settings.py
- frontend/src/pages/Settings.jsx
- project_specs.md
- instructions.md

---

# System Architecture Reference

This section documents the complete system architecture including all background loops, download sources, and integration points.

---

## Background Loop Architecture

The application runs 4 concurrent background loops launched at startup in `backend/main.py`:

### 1. `active_job_tracker_loop()` (sync.py)
- **Interval:** Every 5 seconds
- **Purpose:** Rapidly tracks active downloads in qBittorrent AND Radarr/Sonarr native queues
- **Responsibilities:**
  - Updates progress_pct, downloaded_bytes, total_bytes, eta_seconds for downloading jobs
  - Detects Radarr native downloads completing (marks DONE) or failing (triggers fallback search)
  - Detects Sonarr native downloads completing or failing
  - Tracks qBittorrent torrents: progress, completion, import into Radarr/Sonarr
  - Re-syncs stalled Radarr native downloads into active job tracking
  - Backfills missing TMDB metadata (poster, year) for jobs that lack it

### 2. `discovery_tracker_loop()` (sync.py)
- **Interval:** Configurable via `missing_search_interval_hours` (default 24h)
- **Purpose:** Periodically retries searching for MOVIE_MISSING, SKIPPED, NOT_FOUND, and FAILED jobs
- **Calls:** `run_discovery_batch(batch_size)` which triggers `process_request()` for eligible jobs
- **Grace Period:** Jobs with a release_date within `new_release_grace_hours` are deferred to let Radarr/Sonarr grab quality releases first

### 3. `radarr_state_sync_loop()` (sync.py)
- **Interval:** Every 60 seconds
- **Purpose:** Full state reconciliation with Radarr
- **Responsibilities:**
  - Creates MOVIE_MISSING jobs for monitored Radarr movies not in DB
  - Marks jobs NOT_IN_RADARR if movie deleted from Radarr
  - Syncs monitored state from Radarr
  - Updates DONE status when Radarr has file
  - Reverts DONE to MOVIE_MISSING if file deleted in Radarr
  - Backfills TMDB metadata for newly created jobs

### 4. `sonarr_state_sync_loop()` (sync.py)
- **Interval:** Every 60 seconds
- **Purpose:** Full state reconciliation with Sonarr for TV shows
- **Responsibilities:**
  - Creates MOVIE_MISSING jobs for monitored, un-downloaded episodes
  - Tracks air dates from Sonarr episode data
  - Syncs monitored state
  - Updates DONE status when Sonarr has episode file

---

## Download Source Priority System

The system supports configurable download source priority for both movies and TV shows:

- **Movies:** `movie_download_sources_priority` (default: `einthusan,1tamilmv`)
- **TV Shows:** `tv_download_sources_priority` (default: `1tamilmv,bollyzone`)

The orchestrator tries each source in priority order. If one fails, it falls back to the next.

### Download Sources

| Source | Type | Method | Module |
|--------|------|--------|--------|
| Einthusan | Movies | Direct MP4/M3U8 download | `services/einthusan.py` |
| 1TamilMV | Movies + TV | Magnet links → qBittorrent | `services/tamilmv.py` |
| BollyZone | TV | Magnet links → qBittorrent | `services/bollyzone.py` |

### Quality Profile Integration
- `radarr.get_quality_profile_resolution()` extracts the resolution from Radarr's quality profile name (1080p, 720p, 2160p)
- This resolution is passed to `tamilmv.search_movie()` to filter torrents by quality

---

## qBittorrent Integration

Module: `services/qbittorrent.py`

- **Torrent Management:** Adds magnet links, monitors download progress, handles completion
- **File Priority:** When a torrent contains multiple files, sets priority=0 for non-target files
- **Category Routing:** Uses `qbittorrent_category_movies` and `qbittorrent_category_series` to route downloads to correct Radarr/Sonarr import directories
- **Size Filtering:** Validates files against `min_file_size_mb` / `max_file_size_mb`
- **Stall Detection:** Failed torrents auto-deleted after `auto_delete_failed_torrents_hours`

---

## Media Type Support

The system supports both movies and TV shows:

| Field | Movies | TV Shows |
|-------|--------|----------|
| ID | `tmdb_id` | `tvdb_id` |
| Tracking | Per movie | Per episode (`season_number`, `episode_number`) |
| *arr | Radarr | Sonarr |
| Release Date | TMDB digital/physical/theatrical | Sonarr `airDateUtc` |
| Sources | Einthusan, 1TamilMV | 1TamilMV, BollyZone |

---

## Webhook Events

### Radarr Webhooks (`POST /webhook/radarr`)
- `MovieAdded` → Creates job, triggers delayed search
- `MovieDeleted` → Marks NOT_IN_RADARR
- `Download` → Marks DONE
- `MovieFileDeleted` → Marks MOVIE_MISSING, triggers fallback
- `Grab` → Marks DOWNLOADING (native Radarr download)
- `DownloadFailed` / `ManualInteractionRequired` → Immediate fallback search

### Sonarr Webhooks (`POST /webhook/sonarr`)
- All events logged; actual job management delegated to `sonarr_state_sync_loop`

### Jellyseerr Webhooks (`POST /webhook/jellyseerr`)
- Request approved → Creates job, triggers delayed search

---

## Delayed Search Flow

When a movie is added via webhook, the system uses `delayed_search()` to give Radarr/Sonarr a head start:

1. Wait `search_delay_seconds` (default 120s), polling every 10s
2. During wait, check if Radarr has started a native download
4. If delay expires with no Radarr activity → trigger `process_request()` for custom source search

---

## [2026-08-14] Add FMovies and Korean Language Support

**Changes made:**
- **Korean Language Support:** Added `korean` (and TMDB language code `ko`) to `config.LANGUAGE_SLUG_MAP` and `config.TMDB_LANG_TO_EINTHUSAN`. Added `korean` to frontend `ALL_LANGS` in `Settings.jsx`.
- **FMovies Source Integration:** Created `backend/services/fmovies.py` to search FMovies/clones using TMDB ID and LLM title variants, and extract m3u8 streams by resolving iframe embeds.
- **Orchestrator Integration:** Updated `backend/orchestrator.py` to handle the `fmovies` source for both Movies and TV Shows. Uses the existing `download_m3u8` from `downloader.py`.
- **Settings Configuration:** Added `fmovies_base_url` to `backend/models.py` `AppSettings`, auto-migrated via `backend/database.py`, and exposed via `backend/routers/settings.py`. Added configuration UI in `Settings.jsx`.
- **URL Import and Force Search:** Updated `backend/routers/jobs.py` to parse FMovies watch URLs in the `import-url` flow. Updated frontend `Movies.jsx` and `Series.jsx` with FMovies search links and Force Search buttons.
- **Rules Documentation:** Added rule to `instructions.md` ensuring `instructions.md` and `project_specs.md` are updated with implementation changes.

**Files changed:**
- `backend/config.py`
- `backend/services/fmovies.py` (NEW)
- `backend/orchestrator.py`
- `backend/models.py`
- `backend/routers/settings.py`
- `backend/database.py`
- `backend/routers/jobs.py`
- `frontend/src/pages/Settings.jsx`
- `frontend/src/pages/Movies.jsx`
- `frontend/src/pages/Series.jsx`
- `instructions.md`
- `project_specs.md`

---

## [2026-08-14] FMovies Native PyNaCl API Extraction

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
- `project_specs.md`

---

## 2026-08-15 — Fix Radarr API Delay Causing False Fallback Triggers

**Problem diagnosed:**
- When Radarr/Sonarr grabs a download, it sometimes takes a few seconds to appear in its API queue.
- The `active_job_tracker_loop` observed the missing queue item and immediately triggered the fallback pipeline for custom sources (logging it as missing).
- The pipeline then queried the Radarr queue a few seconds later, found the newly grabbed torrent was present and healthy, and aborted the fallback to respect Radarr's download.
- This caused a 11-second race condition loop resulting in continuous "Re-synced stalled Radarr native download" log spam whenever Radarr silently replaced a stalled download.

**Fix implemented:**
- Added a 60-second grace period in `active_job_tracker_loop` for both Radarr and Sonarr missing queue checks.
- If `job.updated_at` is within the last 60 seconds, the loop will log an info message and wait for the queue to populate instead of triggering an immediate fallback.

**Files changed:**
- `backend/sync.py`
- `project_specs.md`
