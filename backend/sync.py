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
    """Wait for configured delay, looping every 10s to check if Radarr grabbed it natively."""
    with Session(engine) as session:
        settings = get_settings(session)
        delay = settings.search_delay_seconds if override_delay is None else override_delay
        
    waited = 0
    poll_interval = 10
    
    while waited <= delay:
        with Session(engine) as session:
            settings = get_settings(session)
            job = session.exec(select(DownloadJob).where(DownloadJob.tmdb_id == tmdb_id)).first()
            if not job or job.status != JobStatus.MOVIE_MISSING:
                return  # Already processing or deleted
            
            try:
                radarr_movie = await radarr.is_movie_in_radarr(tmdb_id, settings)
                if radarr_movie and "id" in radarr_movie:
                    queue_item = await radarr.get_movie_queue_status(radarr_movie["id"], settings)
                    
                    active = False
                    if queue_item:
                        tracked = queue_item.get("trackedDownloadStatus", "").lower()
                        status = queue_item.get("status", "").lower()
                        if tracked not in ("warning", "error") and status != "completed":
                            active = True
                            
                    if active:
                        logger.info(f"Delayed search check: Radarr actively downloading '{job.title}' natively.")
                        job.status = JobStatus.DOWNLOADING
                        job.source_indexer = "radarr"
                        sizeleft = queue_item.get("sizeleft", 0)
                        size = queue_item.get("size", 1)
                        if size > 0:
                            job.progress_pct = int(max(0, 100 * (1 - sizeleft/size)))
                        session.add(job)
                        session.commit()
                        return
            except Exception as e:
                logger.warning(f"Error checking Radarr queue in delayed search: {e}")
                
        if waited >= delay:
            break
            
        await asyncio.sleep(min(poll_interval, delay - waited + 1))
        waited += poll_interval
        
    logger.info(f"Delayed search check: No active Radarr download for tmdb_id={tmdb_id} after {delay}s. Triggering Auto-Download.")
    asyncio.create_task(process_request(tmdb_id, language, auto_download=True))

async def active_job_tracker_loop():
    """
    Rapidly tracks active downloads in qBittorrent AND Radarr native queue, updating progress.
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
                    # 1. Handle Radarr native downloads
                    if job.status == JobStatus.DOWNLOADING and job.source_indexer == "radarr":
                        try:
                            radarr_movie = await radarr.is_movie_in_radarr(job.tmdb_id, settings)
                            if not radarr_movie or "id" not in radarr_movie:
                                logger.warning(f"Radarr native download '{job.title}' missing from Radarr library. Triggering fallback.")
                                job.status = JobStatus.MOVIE_MISSING
                                session.add(job)
                                session.commit()
                                asyncio.create_task(process_request(job.tmdb_id, job.language, auto_download=True))
                                continue
                                
                            queue_item = await radarr.get_movie_queue_status(radarr_movie["id"], settings)
                            if queue_item:
                                status = queue_item.get("status", "").lower()
                                tracked = queue_item.get("trackedDownloadStatus", "").lower()
                                
                                if status == "completed":
                                    job.status = JobStatus.DONE
                                    job.progress_pct = 100
                                    # Try getting path
                                    if radarr_movie.get("hasFile"):
                                        job.file_path = radarr_movie.get("movieFile", {}).get("path")
                                    session.add(job)
                                else:
                                    sizeleft = queue_item.get("sizeleft", 0)
                                    size = queue_item.get("size", 0)
                                    pct = int(max(0, 100 * (1 - sizeleft/size))) if size > 0 else 0
                                    
                                    job.downloaded_bytes = max(0, size - sizeleft)
                                    job.total_bytes = size
                                    
                                    timeleft_str = queue_item.get("timeleft", "")
                                    eta_secs = 0
                                    if timeleft_str:
                                        try:
                                            parts = timeleft_str.split(':')
                                            if len(parts) == 3:
                                                h_str, m_str, s_str = parts
                                                days = 0
                                                if '.' in h_str:
                                                    d_h = h_str.split('.')
                                                    days = int(d_h[0])
                                                    h_str = d_h[1]
                                                eta_secs = int(days * 86400 + int(h_str) * 3600 + int(m_str) * 60 + float(s_str))
                                        except Exception:
                                            pass
                                            
                                    if eta_secs > 0:
                                        job.eta_seconds = eta_secs
                                    
                                    # If it's stalled, pct stays whatever it is, and it stays DOWNLOADING
                                    if pct != job.progress_pct or job.total_bytes != size or job.eta_seconds != eta_secs:
                                        job.progress_pct = pct
                                        session.add(job)
                            else:
                                # Not in queue. Did it finish successfully or fail/get removed?
                                if radarr_movie.get("hasFile"):
                                    job.status = JobStatus.DONE
                                    job.progress_pct = 100
                                    job.file_path = radarr_movie.get("movieFile", {}).get("path")
                                    session.add(job)
                                else:
                                    logger.warning(f"Radarr native download removed without file for '{job.title}'. Triggering fallback.")
                                    job.status = JobStatus.MOVIE_MISSING
                                    session.add(job)
                                    session.commit()
                                    asyncio.create_task(process_request(job.tmdb_id, job.language, auto_download=True))
                        except Exception as e:
                            logger.error(f"Error checking Radarr native queue for {job.title}: {e}")
                            
                    # 2. Handle qBittorrent downloads
                    elif job.status == JobStatus.DOWNLOADING and job.torrent_hash:
                        t_info = await asyncio.to_thread(qbittorrent.get_torrent_info, job.torrent_hash, settings)
                        if not t_info:
                            logger.warning(f"Torrent {job.torrent_hash} missing from qBittorrent. Checking for native alternatives...")
                            
                            try:
                                queue = await radarr.get_full_queue(settings)
                                all_radarr_movies = await radarr.get_all_movies(settings)
                                movie_id_to_tmdb = {m.get("id"): m.get("tmdbId") for m in all_radarr_movies if m.get("id")}
                                
                                has_native = False
                                for q in (queue or []):
                                    rad_tmdb_id = movie_id_to_tmdb.get(q.get("movieId"))
                                    if rad_tmdb_id == job.tmdb_id:
                                        has_native = True
                                        break
                                        
                                if has_native:
                                    logger.info(f"Found native Radarr alternative for '{job.title}'. Native sync will catch it.")
                                    job.status = JobStatus.PENDING
                                    job.source_indexer = None
                                    job.torrent_hash = None
                                    job.progress_pct = 0
                                    session.add(job)
                                    session.commit()
                                    continue
                            except Exception as e:
                                logger.error(f"Failed to check Radarr queue for alternatives: {e}")
                                
                            logger.info(f"No native alternative. Falling back from '{job.source_indexer}' for '{job.title}'.")
                            fallback_source = job.source_indexer
                            job.status = JobStatus.FAILED
                            job.error_msg = f"Torrent removed unexpectedly. Falling back from {fallback_source}"
                            job.torrent_hash = None
                            job.progress_pct = 0
                            session.add(job)
                            session.commit()
                            
                            from backend.orchestrator import process_request
                            asyncio.create_task(process_request(job.tmdb_id, job.language, auto_download=True, fallback_from=fallback_source))
                            continue
                        
                        state = t_info.get("state", "").lower()
                        progress = t_info.get("progress", 0.0)
                        pct = int(progress * 100)
                        
                        eta_secs = t_info.get("eta", 0)
                        if eta_secs > 0 and eta_secs < 8640000:
                            job.eta_seconds = eta_secs
                        else:
                            job.eta_seconds = None
                            
                        # Also update bytes
                        job.total_bytes = t_info.get("size", 0)
                        job.downloaded_bytes = t_info.get("downloaded", 0)
                        
                        if pct != job.progress_pct or job.eta_seconds != eta_secs:
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
                
                # 3. NATIVE QUEUE SYNC: Check Radarr queue for un-tracked native downloads
                try:
                    queue = await radarr.get_full_queue(settings)
                    if queue:
                        # Map radarr internal IDs to tmdb IDs
                        all_radarr_movies = await radarr.get_all_movies(settings)
                        movie_id_to_tmdb = {m.get("id"): m.get("tmdbId") for m in all_radarr_movies if m.get("id")}
                        
                        # Grab all jobs not already downloading/importing/searching
                        inactive_jobs = session.exec(
                            select(DownloadJob).where(
                                DownloadJob.status.notin_([JobStatus.DOWNLOADING, JobStatus.IMPORTING, JobStatus.SEARCHING])
                            )
                        ).all()
                        
                        job_by_tmdb = {j.tmdb_id: j for j in inactive_jobs if j.tmdb_id}
                        
                        for q in queue:
                            radarr_movie_id = q.get("movieId")
                            tmdb_id = movie_id_to_tmdb.get(radarr_movie_id)
                            if tmdb_id and tmdb_id in job_by_tmdb:
                                j = job_by_tmdb[tmdb_id]
                                status = q.get("status", "").lower()
                                
                                if status != "completed":
                                    logger.info(f"Discovered un-tracked Radarr native download for '{j.title}'. Bringing into Active Downloads.")
                                    j.status = JobStatus.DOWNLOADING
                                    j.source_indexer = "radarr"
                                    
                                    sizeleft = q.get("sizeleft", 0)
                                    size = q.get("size", 0)
                                    j.progress_pct = int(max(0, 100 * (1 - sizeleft/size))) if size > 0 else 0
                                    j.total_bytes = size
                                    j.downloaded_bytes = max(0, size - sizeleft)
                                    
                                    timeleft_str = q.get("timeleft", "")
                                    eta_secs = 0
                                    if timeleft_str:
                                        try:
                                            parts = timeleft_str.split(':')
                                            if len(parts) == 3:
                                                h_str, m_str, s_str = parts
                                                days = 0
                                                if '.' in h_str:
                                                    d_h = h_str.split('.')
                                                    days = int(d_h[0])
                                                    h_str = d_h[1]
                                                eta_secs = int(days * 86400 + int(h_str) * 3600 + int(m_str) * 60 + float(s_str))
                                        except Exception:
                                            pass
                                            
                                    if eta_secs > 0:
                                        j.eta_seconds = eta_secs
                                    
                                    from backend.db_logger import log_action
                                    log_action("System", f"Re-synced stalled Radarr native download into Active Jobs: '{j.title}'", tmdb_id=j.tmdb_id, job_id=j.id)
                                    session.add(j)
                        session.commit()
                except Exception as e:
                    logger.error(f"Error checking full Radarr queue: {e}")
                
        except Exception as e:
            logger.error(f"Error in active_job_tracker_loop: {e}")
            
        await asyncio.sleep(5)

async def run_discovery_batch(batch_size: int) -> int:
    """Runs a single batch of discovery searches and returns the number of movies triggered."""
    from backend.orchestrator import process_request
    from backend.db_logger import log_action
    
    with Session(engine) as session:
        jobs = session.exec(
            select(DownloadJob)
            .where(DownloadJob.status.in_([JobStatus.MOVIE_MISSING, JobStatus.SKIPPED]))
            .order_by(DownloadJob.updated_at.asc())
            .limit(batch_size)
        ).all()
        
        if jobs:
            log_action("Discovery", f"Triggering discovery search for {len(jobs)} movies")
            for job in jobs:
                # Update the updated_at timestamp immediately so it goes to the back of the queue
                job.updated_at = datetime.utcnow()
                session.add(job)
                
                # Fully automate the discovery background loop
                asyncio.create_task(process_request(job.tmdb_id, job.language, auto_download=True))
                
            session.commit()
            
        return len(jobs)

async def discovery_tracker_loop():
    """
    Periodically retries searching for MOVIE_MISSING and SKIPPED jobs.
    """
    logger.info("Starting discovery tracker loop...")
    while True:
        try:
            with Session(engine) as session:
                settings = get_settings(session)
                interval = settings.missing_search_interval_hours
                batch_size = settings.missing_search_batch_size

            if interval > 0:
                await run_discovery_batch(batch_size)

            sleep_time = (interval * 3600) if interval > 0 else 86400
            await asyncio.sleep(sleep_time)
            
        except Exception as e:
            logger.error(f"Error in discovery_tracker_loop: {e}")
            await asyncio.sleep(3600)

async def radarr_state_sync_loop():
    """
    Periodically syncs full state with Radarr. Removes unmonitored/deleted, 
    updates paths and done states. Runs frequently to keep UI real-time.
    """
    logger.info("Starting full radarr state sync loop...")
    while True:
        try:
            with Session(engine) as session:
                settings = get_settings(session)
                all_radarr_movies = await radarr.get_all_movies(settings)
                radarr_map = {m["tmdbId"]: m for m in all_radarr_movies if "tmdbId" in m}
                
                all_jobs = session.exec(select(DownloadJob)).all()
                deleted_count = 0
                completed_count = 0
                
                for job in all_jobs:
                    if job.status in (JobStatus.SEARCHING, JobStatus.IMPORTING) or (job.status == JobStatus.DOWNLOADING and job.source_indexer != "radarr"):
                        continue
                        
                    radarr_movie = radarr_map.get(job.tmdb_id)
                    
                    if not radarr_movie:
                        if job.status != JobStatus.NOT_IN_RADARR:
                            job.status = JobStatus.NOT_IN_RADARR
                            job.monitored = False
                            session.add(job)
                            deleted_count += 1
                        continue
                        
                    # Sync monitored state
                    monitored_in_radarr = radarr_movie.get("monitored", False)
                    if job.monitored != monitored_in_radarr:
                        job.monitored = monitored_in_radarr
                        session.add(job)
                        
                    if radarr_movie.get("hasFile"):
                        path = radarr_movie.get("movieFile", {}).get("path")
                        if job.status != JobStatus.DONE or job.file_path != path:
                            job.status = JobStatus.DONE
                            job.progress_pct = 100
                            job.file_path = path
                            session.add(job)
                            completed_count += 1
                        
                session.commit()
                # Don't log every 10 seconds unless there's a change to avoid log spam
                if deleted_count > 0 or completed_count > 0:
                    logger.info(f"Radarr state sync: Marked {deleted_count} as NOT_IN_RADARR, marked {completed_count} as DONE/Updated.")
                    
        except Exception as e:
            logger.error(f"Error in radarr_state_sync_loop: {e}")
            
        await asyncio.sleep(60)
