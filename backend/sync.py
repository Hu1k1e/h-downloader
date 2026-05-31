import asyncio
import logging
from typing import List, Optional, Dict, Any

import httpx
from sqlmodel import Session, select

from backend import config
from backend.database import engine, get_settings
from backend.models import DownloadJob, JobStatus, AppSettings
from backend.orchestrator import process_request
from backend.services import radarr, sonarr, tmdb

logger = logging.getLogger(__name__)


async def fetch_approved_requests(settings: AppSettings) -> List[dict]:
    """Fetch approved movie and tv requests from Jellyseerr API."""
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


async def _is_sonarr_actively_downloading(series_id: int, season: int, episode: int, settings: AppSettings) -> bool:
    try:
        queue_item = await sonarr.get_episode_queue_status(series_id, season, episode, settings)
        if not queue_item:
            return False
        status = queue_item.get("status", "").lower()
        tracked = queue_item.get("trackedDownloadStatus", "").lower()
        return status in ("downloading", "delay", "queued") and tracked not in ("warning", "error")
    except Exception as e:
        logger.warning(f"Could not check Sonarr download status for series {series_id}: {e}")
        return False


async def sync_media_status(session, settings):
    """Sync all local jobs against Radarr/Sonarr in one API call."""
    updated = deleted = unchanged = 0

    if settings.radarr_api_key:
        try:
            all_radarr = await radarr.get_all_movies(settings)
            radarr_by_tmdb = {m["tmdbId"]: m for m in all_radarr if m.get("tmdbId")}
            
            jobs = session.exec(select(DownloadJob).where(DownloadJob.media_type == "movie")).all()
            for job in jobs:
                rm = radarr_by_tmdb.get(job.tmdb_id)
                if rm is None:
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
                        job.status = JobStatus.DONE
                        job.progress_pct = 100
                        job.error_msg = None
                        changed = True
                else:
                    if job.status in (JobStatus.DOWNLOADING, JobStatus.SEARCHING, JobStatus.IMPORTING, JobStatus.CHECKING_RADARR):
                        unchanged += 1
                        continue
                    if job.status == JobStatus.DONE:
                        job.status = JobStatus.MOVIE_MISSING
                        job.error_msg = "File missing from folder"
                        job.monitored = rm_monitored
                        changed = True
                if changed:
                    session.add(job)
                    updated += 1
                else:
                    unchanged += 1
        except Exception as e:
            logger.error(f"sync_media_status: Radarr fetch failed: {e}")

    if settings.sonarr_api_key:
        try:
            all_sonarr = await sonarr.get_all_series(settings)
            sonarr_by_tmdb = {s["tmdbId"]: s for s in all_sonarr if s.get("tmdbId")}
            
            series_jobs = session.exec(select(DownloadJob).where(DownloadJob.media_type == "series")).all()
            from collections import defaultdict
            jobs_by_tmdb = defaultdict(list)
            for j in series_jobs:
                jobs_by_tmdb[j.tmdb_id].append(j)

            for tmdb_id, j_list in jobs_by_tmdb.items():
                sm = sonarr_by_tmdb.get(tmdb_id)
                if sm is None:
                    for job in j_list:
                        session.delete(job)
                        deleted += 1
                    continue
                
                episodes = await sonarr.get_episodes_for_series(sm["id"], settings)
                ep_map = {(ep["seasonNumber"], ep["episodeNumber"]): ep for ep in episodes}
                
                sm_monitored = sm.get("monitored", False)

                for job in j_list:
                    ep = ep_map.get((job.season_number, job.episode_number))
                    if ep is None:
                        session.delete(job)
                        deleted += 1
                        continue
                        
                    has_file = ep.get("hasFile", False)
                    # Sonarr episodes have their own monitored flag, plus the series monitored flag
                    ep_monitored = sm_monitored and ep.get("monitored", False)
                    
                    changed = False
                    if job.monitored != ep_monitored:
                        job.monitored = ep_monitored
                        changed = True
                        
                    if has_file:
                        if job.status != JobStatus.DONE:
                            job.status = JobStatus.DONE
                            job.progress_pct = 100
                            job.error_msg = None
                            changed = True
                    else:
                        if job.status in (JobStatus.DOWNLOADING, JobStatus.SEARCHING, JobStatus.IMPORTING, JobStatus.CHECKING_RADARR):
                            unchanged += 1
                            continue
                        if job.status == JobStatus.DONE:
                            job.status = JobStatus.MOVIE_MISSING
                            job.error_msg = "File missing from folder"
                            job.monitored = ep_monitored
                            changed = True
                    if changed:
                        session.add(job)
                        updated += 1
                    else:
                        unchanged += 1
        except Exception as e:
            logger.error(f"sync_media_status: Sonarr fetch failed: {e}")

    session.commit()
    return {"updated": updated, "deleted": deleted, "unchanged": unchanged}



async def sync_jellyseerr_requests():
    """Main sync loop."""
    logger.info("Starting Sync Loop...")
    
    with Session(engine) as session:
        settings = get_settings(session)
        einthusan_languages = _get_einthusan_languages(settings)
        
        # ── Step 1: New approved requests ────────────────────────────────────
        requests = await fetch_approved_requests(settings)
        for req in requests:
            media = req.get("media", {})
            tmdb_id = media.get("tmdbId")
            if not tmdb_id:
                continue

            media_type = req.get("type", "movie")
            
            if media_type == "movie":
                existing = session.exec(select(DownloadJob).where(DownloadJob.tmdb_id == tmdb_id)).first()
                if existing: continue

                try:
                    movie_info = await tmdb.get_movie_details(tmdb_id, settings)
                except Exception:
                    continue

                original_lang_code = movie_info.get("original_language", "")
                
                # If hollywood is configured, we can download english movies too.
                is_supported = _is_supported_language(original_lang_code, einthusan_languages)
                if not is_supported and "hollywood" not in einthusan_languages:
                    continue

                logger.info(f"Adding new approved movie: TMDB {tmdb_id}")
                job = DownloadJob(
                    tmdb_id=tmdb_id,
                    title=movie_info["title"],
                    year=movie_info.get("year"),
                    media_type="movie",
                    language=config.TMDB_LANG_TO_EINTHUSAN.get(original_lang_code, "hollywood"),
                    status=JobStatus.PENDING,
                    monitored=True,
                    poster_path=movie_info.get("poster_path"),
                )
                session.add(job)
                session.commit()
            
            elif media_type == "tv":
                try:
                    series_info = await tmdb.get_series_details(tmdb_id, settings)
                except Exception:
                    continue
                
                original_lang_code = series_info.get("original_language", "")
                is_supported = _is_supported_language(original_lang_code, einthusan_languages)
                if not is_supported and "hollywood" not in einthusan_languages:
                    continue
                    
                # Iterate over requested seasons/episodes
                # Jellyseerr puts tv requests in `seasons` array
                for req_season in req.get("seasons", []):
                    season_num = req_season.get("seasonNumber")
                    # If episodes are not specified, it means all episodes, which is too complex for our orchestrator right now.
                    # Usually jellyseerr gives specific episodes if we query correctly, but for this sync, we just queue a job to check.
                    # We will skip full seasons for now and only process webhook-triggered episodes.
                    pass

        # ── Step 2 & 3: Monitored & Unmonitored jobs ─────────────────────────
        all_jobs = session.exec(select(DownloadJob)).all()

        for job in all_jobs:
            try:
                if job.media_type == "movie":
                    radarr_movie = await radarr.is_movie_in_radarr(job.tmdb_id, settings)
                    if radarr_movie is None:
                        session.delete(job)
                        session.commit()
                        continue

                    rm_monitored = radarr_movie.get("monitored", False)
                    if job.monitored != rm_monitored:
                        job.monitored = rm_monitored
                        session.add(job)
                        session.commit()

                    if radarr_movie.get("hasFile", False):
                        if job.status != JobStatus.DONE:
                            job.status = JobStatus.DONE
                            job.progress_pct = 100
                            session.add(job)
                            session.commit()
                        continue

                    if job.monitored:
                        if await _is_radarr_actively_downloading(job.tmdb_id, settings):
                            continue
                        
                        queue_item = await radarr.get_movie_queue_status(radarr_movie.get("id"), settings)
                        if queue_item:
                            tracked = queue_item.get("trackedDownloadStatus", "").lower()
                            if tracked in ("warning", "error"):
                                asyncio.create_task(process_request(job.tmdb_id, job.language, "movie"))
                        else:
                            asyncio.create_task(process_request(job.tmdb_id, job.language, "movie"))
                
                elif job.media_type == "series":
                    series = await sonarr.is_series_in_sonarr(job.tmdb_id, settings)
                    if series is None:
                        session.delete(job)
                        session.commit()
                        continue
                        
                    has_file = await sonarr.is_episode_available(series["id"], job.season_number, job.episode_number, settings)
                    if has_file:
                        if job.status != JobStatus.DONE:
                            job.status = JobStatus.DONE
                            job.progress_pct = 100
                            session.add(job)
                            session.commit()
                        continue
                        
                    if job.monitored:
                        if await _is_sonarr_actively_downloading(series["id"], job.season_number, job.episode_number, settings):
                            continue
                            
                        queue_item = await sonarr.get_episode_queue_status(series["id"], job.season_number, job.episode_number, settings)
                        if queue_item:
                            tracked = queue_item.get("trackedDownloadStatus", "").lower()
                            if tracked in ("warning", "error"):
                                asyncio.create_task(process_request(job.tmdb_id, job.language, "series", job.season_number, job.episode_number))
                        else:
                            asyncio.create_task(process_request(job.tmdb_id, job.language, "series", job.season_number, job.episode_number))

            except Exception as e:
                logger.error(f"Error syncing job '{job.title}': {e}")
