import asyncio
import logging
from typing import List, Optional, Dict, Any

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
    return [l.strip().lower() for l in settings.einthusan_languages_str.split(",") if l.strip()]


def _is_supported_language(original_lang_code: str, einthusan_languages: List[str]) -> bool:
    mapped = config.TMDB_LANG_TO_EINTHUSAN.get(original_lang_code)
    return mapped is not None and mapped in einthusan_languages


def _is_queue_item_active(queue_item: Optional[dict]) -> bool:
    """Return True if Radarr has a healthy (non-stalled) queue entry."""
    if not queue_item:
        return False
    status = queue_item.get("status", "").lower()
    tracked = queue_item.get("trackedDownloadStatus", "").lower()
    return status in ("downloading", "delay", "queued") and tracked not in ("warning", "error")


async def sync_radarr_status(session, settings):
    """Sync all local jobs against Radarr in one API call."""
    if not settings.radarr_api_key:
        logger.warning("sync_radarr_status: Radarr API key not configured.")
        return {"updated": 0, "deleted": 0, "unchanged": 0}
    try:
        all_radarr = await radarr.get_all_movies(settings)
    except Exception as e:
        logger.error(f"sync_radarr_status: Radarr fetch failed: {e}")
        raise
    radarr_by_tmdb = {m["tmdbId"]: m for m in all_radarr if m.get("tmdbId")}
    logger.info(f"sync_radarr_status: {len(radarr_by_tmdb)} Radarr movies, reconciling...")
    configured_langs = _get_einthusan_languages(settings)
    jobs = session.exec(select(DownloadJob)).all()
    updated = deleted = unchanged = 0
    for job in jobs:
        # Delete if language is no longer relevant
        if job.language and configured_langs and job.language.lower() not in configured_langs:
            logger.info(f"sync_radarr_status: {job.title!r} language '{job.language}' not in configured languages, deleting job.")
            session.delete(job)
            deleted += 1
            continue
            
        rm = radarr_by_tmdb.get(job.tmdb_id)
        if rm is None:
            logger.info(f"sync_radarr_status: {job.title!r} removed from Radarr, deleting job.")
            session.delete(job)
            deleted += 1
            continue
        has_file = rm.get("hasFile", False)
        rm_monitored = rm.get("monitored", False)
        changed = False
        if job.monitored != rm_monitored:
            job.monitored = rm_monitored
            changed = True
        if has_file:
            if job.status != JobStatus.DONE:
                logger.info(f"sync_radarr_status: {job.title!r} has file -> DONE")
                job.status = JobStatus.DONE
                job.progress_pct = 100
                job.error_msg = None
                changed = True
        else:
            if job.status in (JobStatus.DOWNLOADING, JobStatus.SEARCHING,
                               JobStatus.IMPORTING, JobStatus.CHECKING_RADARR):
                unchanged += 1
                continue
            if job.status == JobStatus.DONE:
                logger.info(f"sync_radarr_status: {job.title!r} DONE but no file -> MOVIE_MISSING")
                job.status = JobStatus.MOVIE_MISSING
                job.error_msg = "File missing from Radarr folder"
                job.monitored = rm_monitored
                changed = True
        if changed:
            session.add(job)
            updated += 1
        else:
            unchanged += 1
    session.commit()
    logger.info(f"sync_radarr_status: updated={updated} deleted={deleted} unchanged={unchanged}")
    return {"updated": updated, "deleted": deleted, "unchanged": unchanged}


async def sync_jellyseerr_requests():
    """
    Main sync loop — runs on a configurable schedule.
    Optimized to eliminate N+1 API calls to Radarr.
    """
    logger.info("Starting Sync Loop...")
    
    with Session(engine) as session:
        settings = get_settings(session)
        einthusan_languages = _get_einthusan_languages(settings)
        
        # ── Pre-fetch all Radarr data ONCE ──────────────────────────────────
        try:
            logger.info("Fetching all movies and queue from Radarr for sync...")
            radarr_movies = await radarr.get_all_movies(settings)
            radarr_queue = await radarr.get_full_queue(settings)
        except Exception as e:
            logger.error(f"Failed to fetch Radarr state for sync: {e}")
            return
            
        radarr_by_tmdb = {m["tmdbId"]: m for m in radarr_movies if m.get("tmdbId")}
        queue_by_movie_id = {q.get("movieId"): q for q in radarr_queue if q.get("movieId")}
        
        # ── Step 0: Clean up non-relevant languages immediately ──────────────
        if einthusan_languages:
            all_jobs = session.exec(select(DownloadJob)).all()
            deleted_any = False
            for job in all_jobs:
                if job.language and job.language.lower() not in einthusan_languages:
                    logger.info(f"Auto-import cleanup: '{job.title}' language not relevant, deleting.")
                    session.delete(job)
                    deleted_any = True
            if deleted_any:
                session.commit()

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

        # ── Step 1.5: Import regional movies from Radarr ──────────────────────
        if einthusan_languages:
            for movie in radarr_movies:
                lang_obj = movie.get("originalLanguage")
                if not lang_obj:
                    continue
                
                lang_name = lang_obj.get("name", "").lower()
                if lang_name in einthusan_languages:
                    tmdb_id = movie.get("tmdbId")
                    if not tmdb_id:
                        continue

                    # Extract poster
                    poster_path = None
                    for img in movie.get("images", []):
                        if img.get("coverType") == "poster":
                            remote_url = img.get("remoteUrl", "")
                            if remote_url and "tmdb.org" in remote_url:
                                poster_path = "/" + remote_url.split("/")[-1]
                            break

                    existing_job = session.exec(select(DownloadJob).where(DownloadJob.tmdb_id == tmdb_id)).first()
                    if existing_job:
                        # Heal existing jobs missing poster or stuck in PENDING
                        updated = False
                        if not existing_job.poster_path and poster_path:
                            existing_job.poster_path = poster_path
                            updated = True
                        if existing_job.status == JobStatus.PENDING and not movie.get("hasFile"):
                            existing_job.status = JobStatus.MOVIE_MISSING
                            updated = True
                        if updated:
                            session.add(existing_job)
                            session.commit()
                        continue

                    logger.info(f"Auto-importing regional movie from Radarr: '{movie.get('title')}' (TMDB {tmdb_id})")
                    new_job = DownloadJob(
                        tmdb_id=tmdb_id,
                        title=movie.get("title", "Unknown"),
                        year=movie.get("year"),
                        language=lang_name,
                        monitored=movie.get("monitored", True),
                        status=JobStatus.DONE if movie.get("hasFile") else JobStatus.MOVIE_MISSING,
                        poster_path=poster_path
                    )
                    session.add(new_job)
                    session.commit()

        # ── Step 2: Monitored jobs ────────────────────────────────────────────
        monitored_jobs = session.exec(
            select(DownloadJob).where(DownloadJob.monitored == True)
        ).all()

        for job in monitored_jobs:
            logger.info(f"Checking monitored: '{job.title}' (TMDB {job.tmdb_id}, status={job.status})")
            try:
                radarr_movie = radarr_by_tmdb.get(job.tmdb_id)

                if radarr_movie is None:
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
                    logger.info(f"'{job.title}' has file in Radarr → DONE")
                    job.monitored = False
                    job.status = JobStatus.DONE
                    job.progress_pct = 100
                    job.error_msg = None
                    session.add(job)
                    session.commit()
                    continue

                # No file. Is it actively downloading?
                queue_item = queue_by_movie_id.get(radarr_movie.get("id"))
                if _is_queue_item_active(queue_item):
                    logger.info(f"Radarr is actively downloading '{job.title}' — skip Einthusan.")
                    continue

                # Radarr entry exists but no file and not downloading.
                if queue_item:
                    tracked = queue_item.get("trackedDownloadStatus", "").lower()
                    if tracked in ("warning", "error"):
                        logger.info(
                            f"Radarr queue for '{job.title}' stalled (tracked={tracked}). "
                            "Triggering Einthusan."
                        )
                        asyncio.create_task(process_request(job.tmdb_id, job.language))
                    else:
                        logger.info(f"Radarr queue for '{job.title}' exists but inactive. Waiting.")
                else:
                    # Nothing in queue — trigger Einthusan fallback
                    logger.info(f"'{job.title}' in Radarr but no file/queue. Triggering Einthusan.")
                    asyncio.create_task(process_request(job.tmdb_id, job.language))

            except Exception as e:
                logger.error(f"Error monitoring '{job.title}' (TMDB {job.tmdb_id}): {e}")

        # ── Step 3: Unmonitored jobs ─────────────────────────────────────────
        unmonitored_jobs = session.exec(
            select(DownloadJob).where(DownloadJob.monitored == False)
        ).all()
        
        for job in unmonitored_jobs:
            try:
                radarr_movie = radarr_by_tmdb.get(job.tmdb_id)

                if radarr_movie is None:
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

                if job.status == JobStatus.DONE:
                    import datetime
                    if job.updated_at and (datetime.datetime.utcnow() - job.updated_at).total_seconds() < 7200:
                        logger.info(f"DONE job '{job.title}' has no file yet, but is within 2-hour grace period. Waiting.")
                        continue

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
