import asyncio
import logging
from typing import Optional
from sqlmodel import Session, select
from backend.database import engine, get_settings
from backend.models import DownloadJob, JobStatus
from backend.services import radarr, qbittorrent
from backend.orchestrator import process_request

logger = logging.getLogger(__name__)

async def delayed_search(tmdb_id: int, language: Optional[str] = None, override_delay: Optional[int] = None):
    """Wait for configured delay, check if Radarr is actively downloading, if not, trigger process_request."""
    with Session(engine) as session:
        settings = get_settings(session)
        delay = settings.search_delay_seconds if override_delay is None else override_delay
        
    if delay > 0:
        logger.info(f"delayed_search: waiting {delay} seconds before checking Radarr for tmdb_id={tmdb_id}")
        await asyncio.sleep(delay)
        
    with Session(engine) as session:
        settings = get_settings(session)
        job = session.exec(select(DownloadJob).where(DownloadJob.tmdb_id == tmdb_id)).first()
        if not job or job.status != JobStatus.MOVIE_MISSING:
            return  # Already processing or deleted
        
        try:
            radarr_movie = await radarr.is_movie_in_radarr(tmdb_id, settings)
            if radarr_movie and "id" in radarr_movie:
                queue_item = await radarr.get_movie_queue_status(radarr_movie["id"], settings)
                
                # Check if it's healthy and downloading
                active = False
                if queue_item:
                    tracked = queue_item.get("trackedDownloadStatus", "").lower()
                    status = queue_item.get("status", "").lower()
                    if tracked not in ("warning", "error") and status != "completed":
                        active = True

                if active:
                    logger.info(f"Delayed search check: Radarr actively downloading '{job.title}', skipping search.")
                    return
        except Exception as e:
            logger.warning(f"Error checking Radarr queue in delayed search: {e}")
            
        logger.info(f"Delayed search check: No active Radarr download for '{job.title}'. Triggering fallback.")
        asyncio.create_task(process_request(tmdb_id, language))

async def active_job_tracker_loop():
    """
    Rapidly tracks active downloads in qBittorrent and updates progress.
    """
    logger.info("Starting active job tracker loop...")
    while True:
        try:
            with Session(engine) as session:
                settings = get_settings(session)
                active_jobs = session.exec(
                    select(DownloadJob).where(
                        DownloadJob.status.in_([JobStatus.DOWNLOADING, JobStatus.SEARCHING, JobStatus.IMPORTING])
                    )
                ).all()

                for job in active_jobs:
                    if job.status == JobStatus.DOWNLOADING and job.torrent_hash:
                        t_info = await asyncio.to_thread(qbittorrent.get_torrent_info, job.torrent_hash, settings)
                        if not t_info:
                            logger.warning(f"Torrent {job.torrent_hash} missing from qBittorrent. Marking as failed.")
                            job.status = JobStatus.FAILED
                            job.error_msg = "Torrent removed from qBittorrent unexpectedly"
                            job.progress_pct = 0
                            session.add(job)
                            continue
                        
                        state = t_info.get("state", "").lower()
                        progress = t_info.get("progress", 0.0)
                        pct = int(progress * 100)
                        
                        # Just update UI progress
                        if pct != job.progress_pct:
                            job.progress_pct = pct
                            session.add(job)

                        if pct == 100 and state not in ("error", "missingfiles"):
                            logger.info(f"Torrent for '{job.title}' completed in qBittorrent. Triggering Radarr rescan.")
                            job.status = JobStatus.IMPORTING
                            session.add(job)
                            session.commit()
                            try:
                                await radarr.trigger_rescan(job.tmdb_id, settings)
                            except Exception as e:
                                logger.error(f"Failed to trigger Radarr rescan for {job.tmdb_id}: {e}")
                            continue

                        if state in ("error", "missingfiles"):
                            logger.error(f"Torrent {job.torrent_hash} for '{job.title}' entered error state: {state}")
                            job.status = JobStatus.FAILED
                            job.error_msg = f"qBittorrent error state: {state}"
                            job.progress_pct = 0
                            session.add(job)
                            # Cleanup
                            await asyncio.to_thread(qbittorrent.delete_torrent, job.torrent_hash, settings)
                        elif state in ("stalleddl", "stalledup", "pauseddl") and pct == 100:
                            # It's actually done but stalled/paused at 100%
                            pass

                session.commit()
                
        except Exception as e:
            logger.error(f"Error in active_job_tracker_loop: {e}")
            
        await asyncio.sleep(5)

async def missing_movie_tracker_loop():
    """
    Periodically retries searching for MOVIE_MISSING jobs if enable_radarr_auto_search is on.
    """
    logger.info("Starting missing movie tracker loop...")
    while True:
        try:
            with Session(engine) as session:
                settings = get_settings(session)
                interval = settings.missing_search_interval_hours
                batch_size = settings.missing_search_batch_size
                enabled = settings.enable_radarr_auto_search

            if enabled and interval > 0:
                with Session(engine) as session:
                    jobs = session.exec(
                        select(DownloadJob)
                        .where(DownloadJob.status == JobStatus.MOVIE_MISSING)
                        .limit(batch_size)
                    ).all()
                    
                    if jobs:
                        from backend.db_logger import log_action
                        log_action("Auto-Search", f"Triggering missing search for {len(jobs)} movies")
                        for job in jobs:
                            if job.status not in (JobStatus.DOWNLOADING, JobStatus.SEARCHING, JobStatus.IMPORTING):
                                asyncio.create_task(process_request(job.tmdb_id, job.language))

            # Sleep for the configured interval (or default 24h if missing)
            sleep_time = (interval * 3600) if interval > 0 else 86400
            await asyncio.sleep(sleep_time)
            
        except Exception as e:
            logger.error(f"Error in missing_movie_tracker_loop: {e}")
            await asyncio.sleep(3600)  # Retry in an hour on critical failure
