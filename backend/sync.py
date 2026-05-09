import asyncio
import logging
from typing import List, Optional

import httpx
from sqlmodel import Session, select

from backend import config
from backend.database import engine, get_settings
from backend.models import DownloadJob, JobStatus, AppSettings
from backend.orchestrator import process_request
from backend.services import radarr, tmdb

logger = logging.getLogger(__name__)


async def fetch_approved_requests(settings: AppSettings) -> List[dict]:
    """Fetch approved movie requests from Jellyseerr API."""
    if not settings.jellyseerr_api_key:
        logger.warning("JELLYSEERR_API_KEY is missing. Skipping sync.")
        return []

    url = f"{settings.jellyseerr_url}/api/v1/request"
    headers = {
        "X-Api-Key": settings.jellyseerr_api_key,
        "Accept": "application/json"
    }
    
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, headers=headers, params={"filter": "approved", "take": 50})
            resp.raise_for_status()
            data = resp.json()
            return data.get("results", [])
    except Exception as e:
        logger.error(f"Failed to fetch from Jellyseerr API: {e}")
        return []


def _get_einthusan_languages(settings: AppSettings) -> List[str]:
    return [l.strip() for l in settings.einthusan_languages_str.split(",") if l.strip()]


def _is_supported_language(original_lang_code: str, einthusan_languages: List[str]) -> bool:
    mapped = config.TMDB_LANG_TO_EINTHUSAN.get(original_lang_code)
    return mapped is not None and mapped in einthusan_languages


async def _is_radarr_actively_downloading(tmdb_id: int, settings: AppSettings) -> bool:
    """Return True if Radarr has a healthy (non-stalled) queue entry for this movie."""
    try:
        movie = await radarr.is_movie_in_radarr(tmdb_id, settings)
        if not movie:
            return False
        queue_item = await radarr.get_movie_queue_status(movie.get("id"), settings)
        if not queue_item:
            return False
        status = queue_item.get("status", "").lower()
        tracked = queue_item.get("trackedDownloadStatus", "").lower()
        return status in ("downloading", "delay", "queued") and tracked not in ("warning", "error")
    except Exception as e:
        logger.warning(f"Could not check Radarr download status for TMDB {tmdb_id}: {e}")
        return False


async def sync_jellyseerr_requests():
    """
    Main sync loop — runs on a configurable schedule.

    Step 1 — New requests:
      · Fetch approved requests from Jellyseerr.
      · If we don't already track the movie, look it up in TMDB and create a job.
      · Skip languages not in configured Einthusan languages.

    Step 2 — Monitored jobs:
      · If Radarr has the file → DONE, unmonitor.
      · If movie entry is in Radarr but hasFile=False → MOVIE_MISSING, re-monitor so
        the user can trigger a re-download.
      · If movie no longer in Radarr at all → DELETE the job (it can be re-added from
        Jellyseerr cleanly next poll).
      · If Radarr is actively downloading → skip (don't duplicate via Einthusan).
      · Otherwise → trigger Einthusan fallback.

    Step 3 — DONE unmonitored jobs:
      · If still in Radarr and has the file → leave alone (happy path).
      · If in Radarr but hasFile=False (deleted from disk) → set MOVIE_MISSING,
        re-monitor so user can trigger a fresh download.
      · If completely removed from Radarr → DELETE the job so re-adding from
        Jellyseerr works cleanly.
    """
    logger.info("Starting Sync Loop...")
    
    with Session(engine) as session:
        settings = get_settings(session)
        einthusan_languages = _get_einthusan_languages(settings)
        
        # ── Step 1: New approved requests ────────────────────────────────────
        requests = await fetch_approved_requests(settings)
        for req in requests:
            if req.get("type") != "movie":
                continue
            media = req.get("media", {})
            tmdb_id = media.get("tmdbId")
            if not tmdb_id:
                continue

            existing = session.exec(
                select(DownloadJob).where(DownloadJob.tmdb_id == tmdb_id)
            ).first()
            if existing:
                continue

            try:
                movie_info = await tmdb.get_movie_details(tmdb_id, settings)
            except Exception as e:
                logger.warning(f"TMDB lookup failed for {tmdb_id}: {e}. Skipping.")
                continue

            title = movie_info["title"]
            year = movie_info.get("year")
            original_lang_code = movie_info.get("original_language", "")
            poster_path = movie_info.get("poster_path")

            if not _is_supported_language(original_lang_code, einthusan_languages):
                logger.info(
                    f"Skipping '{title}' (TMDB {tmdb_id}) — language '{original_lang_code}' "
                    f"not in configured languages: {einthusan_languages}"
                )
                continue

            logger.info(f"Adding new approved movie: '{title}' ({year}) TMDB {tmdb_id}")
            job = DownloadJob(
                tmdb_id=tmdb_id,
                title=title,
                year=year,
                language=config.TMDB_LANG_TO_EINTHUSAN.get(original_lang_code),
                status=JobStatus.PENDING,
                monitored=True,
                poster_path=poster_path,
            )
            session.add(job)
            session.commit()

        # ── Step 2: Monitored jobs ────────────────────────────────────────────
        monitored_jobs = session.exec(
            select(DownloadJob).where(DownloadJob.monitored == True)
        ).all()

        for job in monitored_jobs:
            logger.info(f"Checking monitored: '{job.title}' (TMDB {job.tmdb_id}, status={job.status})")
            try:
                radarr_movie = await radarr.is_movie_in_radarr(job.tmdb_id, settings)

                if radarr_movie is None:
                    # Movie removed from Radarr entirely → delete job so Jellyseerr
                    # can re-add it cleanly on the next sync if re-requested.
                    logger.info(
                        f"'{job.title}' removed from Radarr. Deleting H-Downloader job."
                    )
                    session.delete(job)
                    session.commit()
                    continue

                radarr_monitored = radarr_movie.get("monitored", False)
                if job.monitored != radarr_monitored:
                    logger.info(f"Syncing monitored state from Radarr for '{job.title}': {radarr_monitored}")
                    job.monitored = radarr_monitored
                    session.add(job)
                    session.commit()

                has_file = radarr_movie.get("hasFile", False)

                if has_file:
                    # ✅ Radarr has the file → mark DONE
                    logger.info(f"'{job.title}' has file in Radarr → DONE")
                    job.monitored = False
                    job.status = JobStatus.DONE
                    job.progress_pct = 100
                    job.error_msg = None
                    session.add(job)
                    session.commit()
                    continue

                # No file. Is it actively downloading?
                if await _is_radarr_actively_downloading(job.tmdb_id, settings):
                    logger.info(f"Radarr is actively downloading '{job.title}' — skip Einthusan.")
                    continue

                # Radarr entry exists but no file and not downloading.
                # Is there a stalled queue item?
                queue_item = await radarr.get_movie_queue_status(radarr_movie.get("id"), settings)
                if queue_item:
                    status_str = queue_item.get("status", "").lower()
                    tracked = queue_item.get("trackedDownloadStatus", "").lower()
                    if tracked in ("warning", "error"):
                        logger.info(
                            f"Radarr queue for '{job.title}' stalled (tracked={tracked}). "
                            "Triggering Einthusan."
                        )
                        asyncio.create_task(process_request(job.tmdb_id, job.language))
                    else:
                        logger.info(f"Radarr queue for '{job.title}': status={status_str}. Waiting.")
                else:
                    # Nothing in queue — trigger Einthusan fallback
                    logger.info(f"'{job.title}' in Radarr but no file/queue. Triggering Einthusan.")
                    asyncio.create_task(process_request(job.tmdb_id, job.language))

            except Exception as e:
                logger.error(f"Error monitoring '{job.title}' (TMDB {job.tmdb_id}): {e}")

        # ── Step 3: Unmonitored jobs ─────────────────────────────────────────
        # Check all unmonitored jobs to see if the user resolved them externally
        # (e.g. manually downloaded a missing movie).
        unmonitored_jobs = session.exec(
            select(DownloadJob).where(DownloadJob.monitored == False)
        ).all()
        for job in unmonitored_jobs:
            try:
                radarr_movie = await radarr.is_movie_in_radarr(job.tmdb_id, settings)

                if radarr_movie is None:
                    # Removed from Radarr entirely → delete so Jellyseerr can re-add cleanly
                    logger.info(
                        f"Unmonitored job '{job.title}' no longer in Radarr. Deleting."
                    )
                    session.delete(job)
                    session.commit()
                    continue

                radarr_monitored = radarr_movie.get("monitored", False)
                if job.monitored != radarr_monitored:
                    logger.info(f"Syncing monitored state from Radarr for '{job.title}': {radarr_monitored}")
                    job.monitored = radarr_monitored
                    session.add(job)
                    session.commit()

                if radarr_movie.get("hasFile", False):
                    if job.status != JobStatus.DONE:
                        logger.info(f"Unmonitored job '{job.title}' now has file in Radarr → DONE")
                        job.status = JobStatus.DONE
                        job.progress_pct = 100
                        job.error_msg = None
                        session.add(job)
                        session.commit()
                    continue

                # If no file in Radarr, and the app thought it was DONE...
                if job.status == JobStatus.DONE:
                    # Give Radarr a 2-hour grace period to import the file before 
                    # flagging it as missing. Sometimes large files take a while to 
                    # move across network drives after the download finishes.
                    import datetime
                    if job.updated_at and (datetime.datetime.utcnow() - job.updated_at).total_seconds() < 7200:
                        logger.info(f"DONE job '{job.title}' has no file yet, but is within 2-hour grace period. Waiting.")
                        continue

                    # Movie entry exists but file deleted from disk → MOVIE_MISSING
                    # Mirror Radarr's monitored state — if the movie is monitored in Radarr,
                    # keep it monitored here; if not, keep it unmonitored.
                    radarr_monitored = radarr_movie.get("monitored", False)
                    logger.info(
                        f"DONE job '{job.title}' file deleted from Radarr folder → MOVIE_MISSING "
                        f"(radarr monitored={radarr_monitored})"
                    )
                    job.status = JobStatus.MOVIE_MISSING
                    job.monitored = radarr_monitored
                    job.error_msg = "File missing from Radarr folder"
                    session.add(job)
                    session.commit()

            except Exception as e:
                logger.error(f"Error checking unmonitored job '{job.title}': {e}")
