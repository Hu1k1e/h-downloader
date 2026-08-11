"""
Jobs API router — CRUD for download jobs and manual trigger.
"""
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from backend.database import get_session, get_settings
from backend.models import DownloadJob, DownloadJobRead, JobStatus, AppSettings
from backend.orchestrator import process_request
from backend.services import radarr as radarr_svc
from backend.services import tmdb as tmdb_svc
from backend import config
from backend.services import qbittorrent
from backend.services import sonarr as sonarr_svc
from backend.sync import delayed_search
from backend.db_logger import log_action

router = APIRouter(prefix="/api", tags=["jobs"])

# ── Jobs list & detail ───────────────────────────────────────────────────────

@router.get("/jobs", response_model=List[DownloadJobRead])
def list_jobs(
    status: Optional[str] = None,
    language: Optional[str] = None,
    media_type: Optional[str] = None,
    limit: int = 10000,
    offset: int = 0,
    session: Session = Depends(get_session),
):
    settings = get_settings(session)
    configured_langs = [l.strip().lower() for l in settings.einthusan_languages_str.split(",") if l.strip().lower() in config.LANGUAGE_SLUG_MAP]

    query = select(DownloadJob).order_by(DownloadJob.created_at.desc())
    if status:
        query = query.where(DownloadJob.status == status)
    if language:
        query = query.where(DownloadJob.language == language)
    elif configured_langs and media_type != "tv":
        # Only show languages that have been ticked in settings (for movies)
        query = query.where(DownloadJob.language.in_(configured_langs))
        
    if media_type:
        query = query.where(DownloadJob.media_type == media_type)
        
    query = query.offset(offset).limit(limit)
    return session.exec(query).all()


@router.get("/jobs/active", response_model=List[DownloadJobRead])
def get_active_jobs(session: Session = Depends(get_session)):
    """
    Returns jobs that are actively downloading or searching right now.
    For qBittorrent jobs, validates they are actually in an active state.
    For Einthusan jobs, validates they are actively streaming.
    """
    settings = get_settings(session)
    jobs = session.exec(select(DownloadJob).where(DownloadJob.status.in_([JobStatus.DOWNLOADING, JobStatus.SEARCHING, JobStatus.CHECKING_RADARR, JobStatus.IMPORTING]))).all()
    
    active_jobs = []
    from backend.services.downloader import is_direct_download_active
    
    for job in jobs:
        if job.status == JobStatus.DOWNLOADING:
            if job.torrent_hash:
                t_info = qbittorrent.get_torrent_info(job.torrent_hash, settings)
                if not t_info:
                    continue # Not in qbittorrent anymore
                state = t_info.get("state", "").lower()
                if "pause" in state or "error" in state or "up" in state or state == "uploading":
                    continue # paused, errored, or seeding
                active_jobs.append(job)
            elif job.source_indexer == "einthusan":
                if is_direct_download_active(job.id):
                    active_jobs.append(job)
            else:
                active_jobs.append(job)
        else:
            # direct downloads or searching
            active_jobs.append(job)
            
    return active_jobs


@router.get("/jobs/{job_id}", response_model=DownloadJobRead)
def get_job(job_id: int, session: Session = Depends(get_session)):
    job = session.get(DownloadJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.delete("/jobs/{job_id}")
def delete_job(job_id: int, session: Session = Depends(get_session)):
    job = session.get(DownloadJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    session.delete(job)
    session.commit()
    return {"status": "deleted"}


class MonitorUpdate(BaseModel):
    monitored: bool

@router.put("/jobs/{job_id}/monitor")
async def update_monitor_status(job_id: int, update: MonitorUpdate, session: Session = Depends(get_session)):
    job = session.get(DownloadJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
        
    settings = get_settings(session)
    
    try:
        # Push update to Radarr
        radarr_movie = await radarr_svc.is_movie_in_radarr(job.tmdb_id, settings)
        if radarr_movie:
            await radarr_svc.update_movie_monitored(radarr_movie["id"], update.monitored, settings)
    except Exception as e:
        # Log the error but still update local state if preferred, or fail.
        # It's better to fail if Radarr is authoritative.
        import logging
        logging.getLogger(__name__).error(f"Failed to update monitored status in Radarr: {e}")
        raise HTTPException(status_code=502, detail="Failed to update Radarr")
        
    job.monitored = update.monitored
    session.add(job)
    session.commit()
    session.refresh(job)
    return {"status": "updated", "monitored": job.monitored}

@router.post("/jobs/{job_id}/download")
async def trigger_discovered_download(job_id: int, session: Session = Depends(get_session)):
    job = session.get(DownloadJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != JobStatus.DISCOVERED:
        raise HTTPException(status_code=400, detail=f"Job is in state {job.status}, not DISCOVERED")
        
    settings = get_settings(session)
    job.status = JobStatus.DOWNLOADING
    job.error_msg = None
    
    # Check if it was discovered via magnet (1tamilmv) or direct URL (einthusan)
    if job.discovered_magnet:
        import asyncio
        torrent_hash = await asyncio.to_thread(qbittorrent.add_magnet_to_qbittorrent, job.discovered_magnet, settings)
        if torrent_hash:
            job.source_indexer = job.discovered_source
            job.torrent_hash = torrent_hash
            session.add(job)
            session.commit()
            
            from backend.db_logger import log_action
            log_action("search_success", f"Successfully started discovered magnet via {job.source_indexer}", tmdb_id=job.tmdb_id, job_id=job.id)
            return {"status": "started", "hash": torrent_hash}
        else:
            job.status = JobStatus.FAILED
            job.error_msg = "Failed to add magnet to qBittorrent"
            session.add(job)
            session.commit()
            raise HTTPException(status_code=500, detail="Failed to add to qBittorrent")
            
    elif job.direct_url:
        # Einthusan direct download
        job.source_indexer = job.discovered_source
        
        # We need the file_path
        from backend.services.downloader import get_movie_file_path, download_movie
        import asyncio
        from backend.services import radarr
        
        folder_path = await radarr.get_movie_folder(job.tmdb_id, job.title, job.year or 0, settings)
        file_path = get_movie_file_path(folder_path, job.title, job.year)
        job.file_path = file_path
        session.add(job)
        session.commit()
        
        # Fire async task
        async def run_einthusan_dl(jid, direct_url, fp):
            with Session(engine) as sess:
                dl_success = await download_movie(jid, direct_url, fp, sess)
                if dl_success:
                    sess_job = sess.get(DownloadJob, jid)
                    if sess_job:
                        movie_data = await radarr.is_movie_in_radarr(sess_job.tmdb_id, settings)
                        if movie_data and "id" in movie_data:
                            await radarr.trigger_rescan(movie_data["id"], settings)
                        sess_job.status = JobStatus.DONE
                        sess_job.progress_pct = 100
                        sess_job.monitored = False
                        sess.add(sess_job)
                        sess.commit()
                        
        asyncio.create_task(run_einthusan_dl(job.id, job.direct_url, file_path))
        return {"status": "started", "type": "einthusan"}
        
    else:
        raise HTTPException(status_code=400, detail="Discovered job missing both magnet and direct_url")


class ImportUrlRequest(BaseModel):
    url: str

@router.post("/jobs/{job_id}/import-url")
async def import_url_for_job(job_id: int, req: ImportUrlRequest, session: Session = Depends(get_session)):
    """
    Accept a provider URL (Einthusan watch page or 1TamilMV thread) and start the
    download pipeline for an existing job.
    """
    import re
    import asyncio
    from backend.services import einthusan
    from backend.services import tamilmv
    from backend.services.downloader import get_movie_file_path, download_movie
    from backend.database import engine

    job = session.get(DownloadJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    settings = get_settings(session)
    url = req.url.strip()

    if not url:
        raise HTTPException(status_code=400, detail="URL is required")

    # ── Detect provider from URL ──────────────────────────────────────────
    is_einthusan = bool(re.search(r'einthusan\.tv/movie/watch/', url, re.IGNORECASE))
    is_tamilmv = bool(re.search(r'1tamilmv\.\w+/', url, re.IGNORECASE))

    if not is_einthusan and not is_tamilmv:
        raise HTTPException(
            status_code=400,
            detail="URL not recognised. Must be an Einthusan watch page or 1TamilMV thread URL."
        )

    if is_einthusan:
        # Extract MP4 from Einthusan watch page
        try:
            direct_url = await einthusan.extract_mp4_url(url)
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Failed to extract video from Einthusan: {e}")

        if not direct_url:
            raise HTTPException(status_code=404, detail="Could not extract video URL from this Einthusan page.")

        # Get file path from Radarr
        folder_path = await radarr_svc.get_movie_folder(job.tmdb_id, job.title, job.year or 0, settings)
        file_path = get_movie_file_path(folder_path, job.title, job.year)

        job.status = JobStatus.DOWNLOADING
        job.error_msg = None
        job.source_indexer = "einthusan"
        job.einthusan_url = url
        job.direct_url = direct_url
        job.file_path = file_path
        session.add(job)
        session.commit()

        log_action("Manual", f"Manual URL import: starting Einthusan download for '{job.title}'", tmdb_id=job.tmdb_id, job_id=job.id)

        # Fire async download task
        async def _run_dl(jid, dl_url, fp):
            with Session(engine) as sess:
                dl_success = await download_movie(jid, dl_url, fp, sess)
                if dl_success:
                    sess_job = sess.get(DownloadJob, jid)
                    if sess_job:
                        movie_data = await radarr_svc.is_movie_in_radarr(sess_job.tmdb_id, settings)
                        if movie_data and "id" in movie_data:
                            await radarr_svc.trigger_rescan(movie_data["id"], settings)
                        sess_job.status = JobStatus.DONE
                        sess_job.progress_pct = 100
                        sess_job.monitored = False
                        sess_job.error_msg = None
                        sess.add(sess_job)
                        sess.commit()

        asyncio.create_task(_run_dl(job.id, direct_url, file_path))
        return {"status": "started", "type": "einthusan", "url": url}

    elif is_tamilmv:
        # Extract magnet from 1TamilMV thread
        try:
            magnet = await tamilmv.extract_magnet(url)
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Failed to extract magnet from 1TamilMV: {e}")

        if not magnet:
            raise HTTPException(status_code=404, detail="No magnet link found on this 1TamilMV page.")

        torrent_hash = await asyncio.to_thread(qbittorrent.add_magnet_to_qbittorrent, magnet, settings)
        if not torrent_hash:
            raise HTTPException(status_code=500, detail="Failed to add magnet to qBittorrent")

        job.status = JobStatus.DOWNLOADING
        job.error_msg = None
        job.source_indexer = "1tamilmv"
        job.torrent_hash = torrent_hash
        session.add(job)
        session.commit()

        log_action("Manual", f"Manual URL import: added 1TamilMV magnet for '{job.title}'. Hash: {torrent_hash}", tmdb_id=job.tmdb_id, job_id=job.id)
        return {"status": "started", "type": "1tamilmv", "hash": torrent_hash}


# ── Stats ────────────────────────────────────────────────────────────────────

@router.get("/stats")
def get_stats(session: Session = Depends(get_session)):
    jobs = session.exec(select(DownloadJob)).all()
    active_jobs = get_active_jobs(session)
    return {
        "total": len(jobs),
        "active": len(active_jobs),
        "completed": sum(1 for j in jobs if j.status == JobStatus.DONE),
        "failed": sum(1 for j in jobs if j.status == JobStatus.FAILED),
        "not_found": sum(1 for j in jobs if j.status == JobStatus.NOT_FOUND),
        "skipped": sum(1 for j in jobs if j.status == JobStatus.SKIPPED),
    }


# ── Manual trigger ───────────────────────────────────────────────────────────


class TriggerRequest(BaseModel):
    media_type: str = "movie"
    tmdb_id: Optional[int] = None
    tvdb_id: Optional[int] = None
    season_number: Optional[int] = None
    episode_number: Optional[int] = None
    title: Optional[str] = None
    language: Optional[str] = None
    indexer: Optional[str] = None



@router.post("/jobs/trigger")
async def trigger_download(req: TriggerRequest, background_tasks: BackgroundTasks, session: Session = Depends(get_session)):
    settings = get_settings(session)
    
    if req.media_type == "tv":
        if not req.tvdb_id and not req.title:
            raise HTTPException(status_code=400, detail="Provide tvdb_id or title for TV Show")
        if req.season_number is None:
            raise HTTPException(status_code=400, detail="Season number is required for TV Shows")
            
        tvdb_id = req.tvdb_id
        if not tvdb_id:
            try:
                import httpx
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.get(
                        f"{settings.sonarr_url}/api/v3/series/lookup",
                        params={"term": req.title},
                        headers={"X-Api-Key": settings.sonarr_api_key}
                    )
                    resp.raise_for_status()
                    results = resp.json()
                    if not results:
                        raise HTTPException(status_code=404, detail=f"No Sonarr results for '{req.title}'")
                    tvdb_id = results[0]["tvdbId"]
            except Exception as e:
                raise HTTPException(status_code=502, detail=f"Sonarr search failed: {e}")
                
        try:
            series = await sonarr_svc.ensure_series_added(tvdb_id, req.title or "Unknown", settings)
            episodes = await sonarr_svc.get_episodes(series["id"], settings)
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Failed to setup series in Sonarr: {e}")
            
        episodes_to_dl = []
        if req.episode_number is not None:
            ep = next((e for e in episodes if e.get("seasonNumber") == req.season_number and e.get("episodeNumber") == req.episode_number), None)
            if ep: episodes_to_dl.append(ep)
        else:
            episodes_to_dl = [e for e in episodes if e.get("seasonNumber") == req.season_number]
            
        if not episodes_to_dl:
            raise HTTPException(status_code=404, detail="No episodes found for specified season/episode")
            
        triggered = 0
        for ep in episodes_to_dl:
            s_num = ep.get("seasonNumber")
            e_num = ep.get("episodeNumber")
            
            job = session.exec(select(DownloadJob).where(
                DownloadJob.media_type == "tv",
                DownloadJob.tvdb_id == tvdb_id,
                DownloadJob.season_number == s_num,
                DownloadJob.episode_number == e_num
            )).first()
            
            if not job:
                title = f"{series.get('title', 'Unknown')} S{s_num:02d}E{e_num:02d}"
                job = DownloadJob(
                    media_type="tv", tmdb_id=0, tvdb_id=tvdb_id, season_number=s_num, episode_number=e_num,
                    title=title, status=JobStatus.MOVIE_MISSING, monitored=True
                )
                session.add(job)
                session.commit()
                session.refresh(job)
                
            background_tasks.add_task(process_request, job.id, auto_download=True, indexer=req.indexer)
            triggered += 1
            
        log_action("Manual", f"Triggered {triggered} TV episodes for tvdb_id={tvdb_id} season={req.season_number}", tvdb_id=tvdb_id)
        return {"status": "accepted", "tvdb_id": tvdb_id, "triggered": triggered}

    # Movie logic
    if not req.tmdb_id and not req.title:
        raise HTTPException(status_code=400, detail="Provide tmdb_id or title")

    tmdb_id = req.tmdb_id

    if not tmdb_id and req.title:
        if not settings.tmdb_api_key:
            raise HTTPException(status_code=400, detail="TMDB API key is not configured. Please go to Settings and save your TMDB API key first.")
        import httpx
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{config.TMDB_BASE_URL}/search/movie",
                    params={"api_key": settings.tmdb_api_key, "query": req.title},
                )
                resp.raise_for_status()
                results = resp.json().get("results", [])
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                raise HTTPException(status_code=400, detail="TMDB API key is invalid. Please update it in Settings.")
            raise HTTPException(status_code=502, detail=f"TMDB search failed: {e}")
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"TMDB search failed: {e}")
        if not results:
            raise HTTPException(status_code=404, detail=f"No TMDB results for '{req.title}'")
        tmdb_id = results[0]["id"]

    job = session.exec(select(DownloadJob).where(DownloadJob.tmdb_id == tmdb_id, DownloadJob.media_type == "movie")).first()
    if not job:
        job = DownloadJob(media_type="movie", tmdb_id=tmdb_id, title=req.title or f"TMDB:{tmdb_id}", status=JobStatus.MOVIE_MISSING, language=req.language)
        session.add(job)
        session.commit()
        session.refresh(job)

    log_action("Manual", f"Manual search triggered for tmdb_id={tmdb_id} (language={req.language}, indexer={req.indexer})", tmdb_id=tmdb_id, job_id=job.id)
    background_tasks.add_task(process_request, job.id, auto_download=True, indexer=req.indexer)
    return {"status": "accepted", "tmdb_id": tmdb_id, "job_id": job.id}

@router.post("/jobs/trigger-monitored")
async def trigger_all_monitored(background_tasks: BackgroundTasks, session: Session = Depends(get_session)):
    """Manually trigger orchestrator for all monitored movies."""
    jobs = session.exec(select(DownloadJob).where(DownloadJob.monitored == True)).all()
    triggered = 0
    for job in jobs:
        # Avoid re-triggering jobs that are already actively processing
        if job.status not in (JobStatus.DOWNLOADING, JobStatus.SEARCHING, JobStatus.IMPORTING):
             background_tasks.add_task(process_request, job.id)
             triggered += 1
    
    log_action("Manual", f"Bulk trigger: {triggered} monitored jobs queued for search")
    return {"status": "accepted", "triggered": triggered}

@router.post("/jobs/trigger-missing")
async def trigger_missing(background_tasks: BackgroundTasks, session: Session = Depends(get_session)):
    """Manually trigger orchestrator for all MOVIE_MISSING movies."""
    jobs = session.exec(select(DownloadJob).where(DownloadJob.status == JobStatus.MOVIE_MISSING)).all()
    triggered = 0
    for job in jobs:
        if job.status not in (JobStatus.DOWNLOADING, JobStatus.SEARCHING, JobStatus.IMPORTING):
             background_tasks.add_task(process_request, job.id)
             triggered += 1
    
    log_action("Manual", f"Bulk trigger: {triggered} missing jobs queued for search")
    return {"status": "accepted", "triggered": triggered}

@router.post("/jobs/{job_id}/retry")
async def retry_job(job_id: int, background_tasks: BackgroundTasks, session: Session = Depends(get_session)):
    job = session.get(DownloadJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
        
    job.status = JobStatus.PENDING
    job.progress_pct = 0
    job.error_msg = None
    job.blacklisted_urls = None
    session.add(job)
    session.commit()
    
    log_action("Manual", f"Retrying job for '{job.title}'", tmdb_id=job.tmdb_id, job_id=job.id)
    background_tasks.add_task(process_request, job.id)
    return {"status": "retrying", "tmdb_id": job.tmdb_id}


@router.post("/jobs/{job_id}/sync")
async def sync_single_job(job_id: int, session: Session = Depends(get_session)):
    """Manually reconcile a single job's state with Radarr."""
    job = session.get(DownloadJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
        
    settings = get_settings(session)
    try:
        radarr_movie = await radarr_svc.is_movie_in_radarr(job.tmdb_id, settings)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to reach Radarr: {e}")
        
    if not radarr_movie:
        job.status = JobStatus.NOT_IN_RADARR
        job.monitored = False
        log_action("Manual", f"Sync: '{job.title}' marked as NOT_IN_RADARR", tmdb_id=job.tmdb_id, job_id=job.id)
    else:
        job.monitored = radarr_movie.get("monitored", False)
        if radarr_movie.get("hasFile"):
            job.status = JobStatus.DONE
            job.progress_pct = 100
            job.file_path = radarr_movie.get("movieFile", {}).get("path")
        elif job.status in (JobStatus.DONE, JobStatus.NOT_IN_RADARR, JobStatus.NOT_FOUND):
            # It's back in Radarr or file is missing
            job.status = JobStatus.MOVIE_MISSING
            job.progress_pct = 0
            job.file_path = None
        log_action("Manual", f"Sync: '{job.title}' state updated from Radarr", tmdb_id=job.tmdb_id, job_id=job.id)
        
    session.add(job)
    session.commit()
    return {"status": "synced", "job_id": job.id, "state": job.status}

@router.post("/jobs/sync-all")
async def sync_all_jobs(background_tasks: BackgroundTasks, session: Session = Depends(get_session)):
    """Manually trigger a full Radarr state reconciliation for all jobs."""
    settings = get_settings(session)
    try:
        all_radarr_movies = await radarr_svc.get_all_movies(settings)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch movies from Radarr: {e}")
        
    radarr_map = {m["tmdbId"]: m for m in all_radarr_movies if "tmdbId" in m}
    all_jobs = session.exec(select(DownloadJob).where(DownloadJob.media_type == "movie")).all()
    
    updated_count = 0
    deleted_count = 0
    
    for job in all_jobs:
        if job.status == JobStatus.IMPORTING or (job.status == JobStatus.DOWNLOADING and job.source_indexer != "radarr"):
            continue
        if job.status == JobStatus.SEARCHING:
            # If it's been searching for less than 15 minutes, assume it's still running
            from datetime import datetime, timezone
            if (datetime.utcnow() - job.updated_at).total_seconds() < 900:
                continue
            
        radarr_movie = radarr_map.get(job.tmdb_id)
        changed = False
        
        if not radarr_movie:
            if job.status != JobStatus.NOT_IN_RADARR:
                job.status = JobStatus.NOT_IN_RADARR
                job.monitored = False
                changed = True
                deleted_count += 1
        else:
            monitored = radarr_movie.get("monitored", False)
            if job.monitored != monitored:
                job.monitored = monitored
                changed = True
                
            if radarr_movie.get("hasFile"):
                path = radarr_movie.get("movieFile", {}).get("path")
                if job.status != JobStatus.DONE or job.file_path != path:
                    job.status = JobStatus.DONE
                    job.progress_pct = 100
                    job.file_path = path
                    changed = True
            elif job.status in (JobStatus.DONE, JobStatus.NOT_IN_RADARR, JobStatus.NOT_FOUND, JobStatus.SEARCHING):
                job.status = JobStatus.MOVIE_MISSING
                job.progress_pct = 0
                job.file_path = None
                changed = True
                
        if changed:
            session.add(job)
            updated_count += 1
            
    if updated_count > 0:
        session.commit()
        log_action("Manual", f"Sync All: {updated_count} jobs updated from Radarr (including {deleted_count} deleted).")
        
    return {"status": "success", "updated": updated_count}

@router.post("/jobs/import-radarr")
async def trigger_import_radarr(background_tasks: BackgroundTasks, session: Session = Depends(get_session)):
    """Import all movies from Radarr that match configured regional languages."""
    settings = get_settings(session)
    if not settings.radarr_api_key:
        raise HTTPException(status_code=400, detail="Radarr API key is not configured.")

    try:
        movies = await radarr_svc.get_all_movies(settings)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch movies from Radarr: {e}")

    # Parse configured languages (e.g. "malayalam,tamil")
    configured_langs = [l.strip().lower() for l in settings.einthusan_languages_str.split(",") if l.strip().lower() in config.LANGUAGE_SLUG_MAP]
    if not configured_langs:
        raise HTTPException(status_code=400, detail="No Einthusan languages configured in settings.")

    imported_count = 0
    deleted_count = 0
    to_trigger = []
    
    # First, remove non-relevant imports that are already in the DB
    existing_jobs = session.exec(select(DownloadJob)).all()
    for job in existing_jobs:
        if job.language and job.language.lower() not in configured_langs:
            session.delete(job)
            deleted_count += 1
            
    for movie in movies:
        # Radarr language comes as {"id": 4, "name": "Malayalam"}
        lang_obj = movie.get("originalLanguage")
        if not lang_obj:
            continue
        
        lang_name = lang_obj.get("name", "").lower()
        if lang_name in configured_langs:
            tmdb_id = movie.get("tmdbId")
            if not tmdb_id:
                continue

            # Proceed with import or heal

            # Add it to jobs
            poster_path = None
            for img in movie.get("images", []):
                if img.get("coverType") == "poster":
                    remote_url = img.get("remoteUrl", "")
                    if remote_url and "tmdb.org" in remote_url:
                        poster_path = "/" + remote_url.split("/")[-1]
                    break

            # Check if job already exists
            existing_job = session.exec(select(DownloadJob).where(DownloadJob.tmdb_id == tmdb_id)).first()
            if existing_job:
                # Heal previously imported jobs missing poster or stuck in PENDING
                updated = False
                if not existing_job.poster_path and poster_path:
                    existing_job.poster_path = poster_path
                    updated = True
                if not existing_job.language or existing_job.language != lang_name:
                    existing_job.language = lang_name
                    updated = True
                if existing_job.status == JobStatus.PENDING and not movie.get("hasFile"):
                    existing_job.status = JobStatus.MOVIE_MISSING
                    updated = True
                if updated:
                    session.add(existing_job)
                    imported_count += 1
                    if existing_job.status == JobStatus.MOVIE_MISSING:
                        to_trigger.append(tmdb_id)
                continue

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
            imported_count += 1
            if new_job.status == JobStatus.MOVIE_MISSING:
                to_trigger.append(tmdb_id)

    if imported_count > 0 or deleted_count > 0:
        session.commit()
        from backend.db_logger import log_action
        log_action("Import", f"Manual Radarr import completed. Imported {imported_count}, Deleted {deleted_count}.")
        
    for tid in to_trigger:
        background_tasks.add_task(delayed_search, tid, None, 0)
        
    return {"status": "success", "imported": imported_count, "deleted": deleted_count}


@router.post("/jobs/import-sonarr")
async def trigger_import_sonarr(background_tasks: BackgroundTasks, session: Session = Depends(get_session)):
    """Import all series from Sonarr to ensure they are tracked as jobs."""
    settings = get_settings(session)
    if not settings.sonarr_api_key:
        raise HTTPException(status_code=400, detail="Sonarr API key is not configured.")

    try:
        series_list = await sonarr_svc.get_all_series(settings)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch series from Sonarr: {e}")

    imported_count = 0
    to_trigger = []

    for series in series_list:
        tvdb_id = series.get("tvdbId")
        if not tvdb_id:
            continue
            
        series_id = series.get("id")
        title = series.get("title", "Unknown")

        try:
            episodes = await sonarr_svc.get_episodes(series_id, settings)
        except Exception:
            continue

        poster_path = None
        for img in series.get("images", []):
            if img.get("coverType") == "poster":
                poster_path = img.get("remoteUrl", "")
                break

        for ep in episodes:
            s_num = ep.get("seasonNumber")
            e_num = ep.get("episodeNumber")
            has_file = ep.get("hasFile", False)
            monitored = ep.get("monitored", False)

            if not monitored and not has_file:
                continue

            existing_job = session.exec(select(DownloadJob).where(
                DownloadJob.media_type == "tv",
                DownloadJob.tvdb_id == tvdb_id,
                DownloadJob.season_number == s_num,
                DownloadJob.episode_number == e_num
            )).first()

            if existing_job:
                updated = False
                if existing_job.status in (JobStatus.PENDING, JobStatus.NOT_IN_RADARR, JobStatus.NOT_FOUND) and not has_file:
                    existing_job.status = JobStatus.MOVIE_MISSING
                    updated = True
                if poster_path and not existing_job.poster_path:
                    existing_job.poster_path = poster_path
                    updated = True
                if updated:
                    session.add(existing_job)
                    imported_count += 1
                continue

            ep_title = f"{title} S{s_num:02d}E{e_num:02d}"
            new_job = DownloadJob(
                media_type="tv",
                tmdb_id=0,
                tvdb_id=tvdb_id,
                season_number=s_num,
                episode_number=e_num,
                title=ep_title,
                monitored=monitored,
                status=JobStatus.DONE if has_file else JobStatus.MOVIE_MISSING,
                poster_path=poster_path
            )
            session.add(new_job)
            imported_count += 1
            if new_job.status == JobStatus.MOVIE_MISSING:
                to_trigger.append(new_job)

    if imported_count > 0:
        session.commit()
        from backend.db_logger import log_action
        log_action("Import", f"Manual Sonarr import completed. Imported/updated {imported_count} episodes.")

    for job in to_trigger:
        # Trigger background search for missing episodes
        background_tasks.add_task(process_request, job.id, auto_download=True)

    return {"status": "success", "imported": imported_count}


@router.post("/jobs/sync-all-sonarr")
async def sync_all_sonarr(background_tasks: BackgroundTasks, session: Session = Depends(get_session)):
    """Manually trigger a full Sonarr state reconciliation for TV jobs."""
    settings = get_settings(session)
    if not settings.sonarr_api_key:
        raise HTTPException(status_code=400, detail="Sonarr API key is not configured.")

    try:
        all_sonarr_series = await sonarr_svc.get_all_series(settings)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch series from Sonarr: {e}")

    sonarr_map = {s["tvdbId"]: s for s in all_sonarr_series if "tvdbId" in s}
    sonarr_map_by_title = {s.get("title", "").lower(): s for s in all_sonarr_series}
    all_jobs = session.exec(select(DownloadJob).where(DownloadJob.media_type == "tv")).all()

    updated_count = 0
    deleted_count = 0

    # Fetch episodes for series that have jobs
    series_episodes = {}
    for job in all_jobs:
        if job.status == JobStatus.IMPORTING or (job.status == JobStatus.DOWNLOADING and job.source_indexer != "sonarr"):
            continue
        if job.status == JobStatus.SEARCHING:
            from datetime import datetime, timezone
            if (datetime.utcnow() - job.updated_at).total_seconds() < 900:
                continue

        series = sonarr_map.get(job.tvdb_id) if job.tvdb_id else None
        if not series and job.title:
            series_title = job.title.split(" S")[0].lower()
            series = sonarr_map_by_title.get(series_title)

        changed = False

        if not series:
            if job.status != JobStatus.NOT_IN_RADARR:  # Reuse NOT_IN_RADARR state for Sonarr
                job.status = JobStatus.NOT_IN_RADARR
                job.monitored = False
                changed = True
                deleted_count += 1
        else:
            series_id = series.get("id")
            if series_id not in series_episodes:
                try:
                    episodes = await sonarr_svc.get_episodes(series_id, settings)
                    series_episodes[series_id] = {(e.get("seasonNumber"), e.get("episodeNumber")): e for e in episodes}
                except Exception:
                    continue

            ep = series_episodes[series_id].get((job.season_number, job.episode_number))
            if not ep:
                if job.status != JobStatus.NOT_IN_RADARR:
                    job.status = JobStatus.NOT_IN_RADARR
                    job.monitored = False
                    changed = True
                    deleted_count += 1
            else:
                monitored = ep.get("monitored", False)
                if job.monitored != monitored:
                    job.monitored = monitored
                    changed = True

                if ep.get("hasFile"):
                    if job.status != JobStatus.DONE:
                        job.status = JobStatus.DONE
                        job.progress_pct = 100
                        changed = True
                elif job.status in (JobStatus.DONE, JobStatus.NOT_IN_RADARR, JobStatus.NOT_FOUND, JobStatus.SEARCHING):
                    job.status = JobStatus.MOVIE_MISSING
                    job.progress_pct = 0
                    job.file_path = None
                    changed = True

        if changed:
            session.add(job)
            updated_count += 1

    if updated_count > 0:
        session.commit()
        from backend.db_logger import log_action
        log_action("Manual", f"Sync All Sonarr: {updated_count} episodes updated (including {deleted_count} deleted).")

    return {"status": "success", "updated": updated_count}


@router.post("/jobs/discovery")
async def trigger_discovery(session: Session = Depends(get_session)):
    """Manually trigger a background discovery batch."""
    settings = get_settings(session)
    from backend.sync import run_discovery_batch
    triggered = await run_discovery_batch(settings.missing_search_batch_size)
    return {"status": "success", "triggered": triggered}


# ── Connection tests ─────────────────────────────────────────────────────────


@router.get("/test/sonarr")
async def test_sonarr(session: Session = Depends(get_session)):
    settings = get_settings(session)
    try:
        result = await sonarr_svc.test_connection(settings)
        return {"status": "ok", "version": result.get("version")}
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))

@router.get("/test/radarr")
async def test_radarr(session: Session = Depends(get_session)):
    settings = get_settings(session)
    try:
        result = await radarr_svc.test_connection(settings)
        return {"status": "ok", "version": result.get("version")}
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/test/tmdb")
async def test_tmdb(session: Session = Depends(get_session)):
    settings = get_settings(session)
    try:
        await tmdb_svc.test_connection(settings)
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))
