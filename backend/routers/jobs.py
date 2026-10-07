"""
Jobs API router — CRUD for download jobs, manual triggers and sync controls.

Business logic (reconciliation, imports, downloads) lives in backend/sync.py,
backend/orchestrator.py and backend/services/*; this module validates input,
calls them and shapes the response.
"""
import asyncio
import logging
from typing import List, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlmodel import Session, select

from backend.database import get_session, get_settings
from backend.models import DownloadJob, DownloadJobRead, JobStatus
from backend.orchestrator import (
    process_request, process_many, run_movie_file_download, run_stream_download,
)
from backend.services import radarr as radarr_svc
from backend.services import tmdb as tmdb_svc
from backend import config
from backend.services import qbittorrent
from backend.services.qbittorrent import QbittorrentError
from backend.services import sonarr as sonarr_svc
from backend import sync as sync_svc
from backend.services.downloader import (
    cancel_download, get_movie_file_path, get_episode_file_path, is_direct_download_active,
)
from backend.db_logger import log_action

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["jobs"])

_BUSY = (JobStatus.DOWNLOADING, JobStatus.SEARCHING, JobStatus.IMPORTING)


def _raise_sync(e: sync_svc.SyncError):
    raise HTTPException(status_code=e.status_code, detail=e.message)


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
    configured_langs = sync_svc.configured_languages(settings)

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
    For direct (Einthusan/stream) jobs, validates they are actively streaming.
    """
    settings = get_settings(session)
    jobs = session.exec(select(DownloadJob).where(DownloadJob.status.in_(
        [JobStatus.DOWNLOADING, JobStatus.SEARCHING, JobStatus.CHECKING_RADARR, JobStatus.IMPORTING]))).all()

    # One qBittorrent request for all torrents instead of one login per job.
    hashes = [j.torrent_hash for j in jobs if j.status == JobStatus.DOWNLOADING and j.torrent_hash]
    torrents = None
    if hashes:
        try:
            torrents = qbittorrent.get_torrents_info(hashes, settings)
        except QbittorrentError as e:
            logger.warning(f"qBittorrent unreachable while listing active jobs: {e}")

    active_jobs = []
    for job in jobs:
        if job.status == JobStatus.DOWNLOADING:
            if job.torrent_hash:
                if torrents is None:
                    active_jobs.append(job)  # qBittorrent unreachable: don't hide a possibly-running download
                    continue
                t_info = torrents.get(job.torrent_hash.lower())
                if not t_info:
                    continue  # Not in qbittorrent anymore
                state = t_info.get("state", "").lower()
                if "pause" in state or "error" in state or "up" in state or state == "uploading":
                    continue  # paused, errored, or seeding
                active_jobs.append(job)
            elif job.source_indexer in sync_svc.DIRECT_SOURCES:
                if is_direct_download_active(job.id):
                    active_jobs.append(job)
            else:
                active_jobs.append(job)
        else:
            active_jobs.append(job)

    return active_jobs


@router.get("/jobs/{job_id}", response_model=DownloadJobRead)
def get_job(job_id: int, session: Session = Depends(get_session)):
    job = session.get(DownloadJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


async def _drop_torrent(job: DownloadJob, settings) -> None:
    """Remove the job's torrent (if any) so a cancelled/cleared download doesn't keep running."""
    if job.torrent_hash:
        await asyncio.to_thread(qbittorrent.delete_torrent, job.torrent_hash, settings)
        job.torrent_hash = None


@router.delete("/jobs/{job_id}")
async def delete_job(job_id: int, session: Session = Depends(get_session)):
    """Cancel any download, delete the media file from Radarr/Sonarr and reset the job to 'missing'."""
    job = session.get(DownloadJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    cancel_download(job_id)

    settings = get_settings(session)
    await _drop_torrent(job, settings)
    if job.media_type == "tv" and job.tvdb_id:
        try:
            series = await sonarr_svc.is_series_in_sonarr(job.tvdb_id, settings)
            if series:
                ep = await sonarr_svc.get_episode(series["id"], job.season_number, job.episode_number, settings)
                if ep and ep.get("episodeFileId"):
                    await sonarr_svc.delete_episode_file(ep["episodeFileId"], settings)
        except Exception as e:
            logger.error(f"Failed to delete episode from Sonarr: {e}")
    elif job.media_type == "movie" and job.tmdb_id:
        try:
            movie = await radarr_svc.is_movie_in_radarr(job.tmdb_id, settings)
            if movie and movie.get("movieFile") and movie["movieFile"].get("id"):
                await radarr_svc.delete_movie_file(movie["movieFile"]["id"], settings)
        except Exception as e:
            logger.error(f"Failed to delete movie from Radarr: {e}")

    job.status = JobStatus.MOVIE_MISSING
    job.progress_pct = 0
    job.downloaded_bytes = 0
    job.total_bytes = 0
    job.error_msg = None
    job.file_path = None
    job.has_file = False
    job.source_indexer = None
    session.add(job)
    session.commit()
    return {"status": "cleared"}


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: int, session: Session = Depends(get_session)):
    job = session.get(DownloadJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    cancel_download(job_id)
    await _drop_torrent(job, get_settings(session))

    job.status = JobStatus.MOVIE_MISSING
    job.source_indexer = None
    job.progress_pct = 0
    job.downloaded_bytes = 0
    job.total_bytes = 0
    job.error_msg = "Cancelled by user"
    session.add(job)
    session.commit()
    return {"status": "cancelled"}


class MonitorUpdate(BaseModel):
    monitored: bool


@router.put("/jobs/{job_id}/monitor")
async def update_monitor_status(job_id: int, update: MonitorUpdate, session: Session = Depends(get_session)):
    """Toggle monitored in Radarr/Sonarr and store the value *they* confirm (they are the source of truth)."""
    job = session.get(DownloadJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    settings = get_settings(session)
    try:
        if job.media_type == "tv":
            series = await sonarr_svc.is_series_in_sonarr(job.tvdb_id, settings)
            ep = await sonarr_svc.get_episode(series["id"], job.season_number, job.episode_number, settings) if series else None
            if not ep:
                raise HTTPException(status_code=404, detail="This episode no longer exists in Sonarr. Run a sync.")
            confirmed = await sonarr_svc.update_episode_monitored(ep["id"], update.monitored, settings)
        else:
            movie = await radarr_svc.is_movie_in_radarr(job.tmdb_id, settings)
            if not movie:
                raise HTTPException(status_code=404, detail="This movie no longer exists in Radarr. Run a sync.")
            confirmed = await radarr_svc.update_movie_monitored(movie["id"], update.monitored, settings)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update monitored status in Radarr/Sonarr: {e}")
        raise HTTPException(status_code=502, detail=f"Failed to update Radarr/Sonarr: {e}")

    job.monitored = confirmed
    job.in_arr = True
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

    # Discovered via magnet (1TamilMV)
    if job.discovered_magnet:
        torrent_hash = await asyncio.to_thread(
            qbittorrent.add_magnet_to_qbittorrent, job.discovered_magnet, settings, job.media_type == "tv")
        if not torrent_hash:
            job.status = JobStatus.FAILED
            job.error_msg = "Failed to add magnet to qBittorrent"
            session.add(job)
            session.commit()
            raise HTTPException(status_code=500, detail="Failed to add to qBittorrent")
        job.status = JobStatus.DOWNLOADING
        job.error_msg = None
        job.source_indexer = job.discovered_source
        job.torrent_hash = torrent_hash
        session.add(job)
        session.commit()
        log_action("search_success", f"Successfully started discovered magnet via {job.source_indexer}", tmdb_id=job.tmdb_id, job_id=job.id)
        return {"status": "started", "hash": torrent_hash}

    # Discovered via direct URL (Einthusan)
    if job.direct_url and job.media_type == "movie":
        folder_path = await radarr_svc.get_movie_folder(job.tmdb_id, job.title, job.year or 0, settings)
        file_path = get_movie_file_path(folder_path, job.title, job.year)
        job.status = JobStatus.DOWNLOADING
        job.error_msg = None
        job.source_indexer = job.discovered_source or "einthusan"
        job.file_path = file_path
        session.add(job)
        session.commit()
        asyncio.create_task(run_movie_file_download(job.id, job.direct_url, file_path, settings))
        return {"status": "started", "type": "einthusan"}

    raise HTTPException(status_code=400, detail="Discovered job has no magnet or direct URL to download")


class ImportUrlRequest(BaseModel):
    url: str


def _classify_url(url: str) -> Optional[str]:
    """Identify the provider from the URL's *host* (not a substring anywhere in the URL)."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return None
    host = parsed.hostname.lower()
    if (host == "einthusan.tv" or host.endswith(".einthusan.tv")) and "/movie/watch/" in parsed.path:
        return "einthusan"
    labels = host.split(".")
    if any(l == "1tamilmv" for l in labels):
        return "1tamilmv"
    if any(l == "f-movies" for l in labels):
        return "fmovies"
    return None


@router.post("/jobs/{job_id}/import-url")
async def import_url_for_job(job_id: int, req: ImportUrlRequest, session: Session = Depends(get_session)):
    """
    Accept a provider URL (Einthusan watch page, 1TamilMV thread or FMovies page) and start the
    download pipeline for an existing job.
    """
    from backend.services import einthusan, tamilmv, fmovies

    job = session.get(DownloadJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    settings = get_settings(session)
    url = req.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL is required")

    provider = _classify_url(url)
    if not provider:
        raise HTTPException(status_code=400, detail="URL not recognised. Must be an Einthusan, 1TamilMV, or FMovies URL.")

    if provider == "einthusan":
        if job.media_type != "movie":
            raise HTTPException(status_code=400, detail="Einthusan URLs can only be imported for movies.")
        try:
            direct_url = await einthusan.extract_mp4_url(url)
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Failed to extract video from Einthusan: {e}")
        if not direct_url:
            raise HTTPException(status_code=404, detail="Could not extract video URL from this Einthusan page.")

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
        asyncio.create_task(run_movie_file_download(job.id, direct_url, file_path, settings))
        return {"status": "started", "type": "einthusan", "url": url}

    if provider == "1tamilmv":
        try:
            magnet = await tamilmv.extract_magnet(url)
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Failed to extract magnet from 1TamilMV: {e}")
        if not magnet:
            raise HTTPException(status_code=404, detail="No magnet link found on this 1TamilMV page.")

        torrent_hash = await asyncio.to_thread(
            qbittorrent.add_magnet_to_qbittorrent, magnet, settings, job.media_type == "tv")
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

    # FMovies: the stream is looked up by TMDB id (vidlink), so the pasted URL only confirms the provider.
    if job.media_type == "tv":
        series = await sonarr_svc.ensure_series_added(job.tvdb_id, job.title, settings)
        if not series.get("tmdbId"):
            raise HTTPException(status_code=404, detail="Sonarr has no TMDB id for this series, so FMovies can't be used.")
        watch_ref = f"{series['tmdbId']}/{job.season_number}/{job.episode_number}"
    else:
        watch_ref = str(job.tmdb_id)

    extracted = await fmovies.extract_stream_url(watch_ref, settings)
    if not extracted:
        raise HTTPException(status_code=404, detail="Could not extract m3u8 stream from FMovies.")
    m3u8_url, referer, _user_agent = extracted

    if job.media_type == "tv":
        folder_path = series.get("path") or await sonarr_svc.get_series_folder(job.tvdb_id, series.get("title", ""), settings)
        file_path = get_episode_file_path(folder_path, series.get("title", job.title), job.season_number, job.episode_number)
    else:
        folder_path = await radarr_svc.get_movie_folder(job.tmdb_id, job.title, job.year or 0, settings)
        file_path = get_movie_file_path(folder_path, job.title, job.year)

    job.status = JobStatus.DOWNLOADING
    job.error_msg = None
    job.source_indexer = "fmovies"
    job.file_path = file_path
    session.add(job)
    session.commit()

    log_action("Manual", f"Manual URL import: starting FMovies download for '{job.title}'", tmdb_id=job.tmdb_id, job_id=job.id)
    asyncio.create_task(run_stream_download(job.id, m3u8_url, referer, file_path, settings))
    return {"status": "started", "type": "fmovies", "url": url}


# ── Stats ────────────────────────────────────────────────────────────────────

@router.get("/stats")
def get_stats(session: Session = Depends(get_session)):
    rows = session.exec(select(DownloadJob.status, func.count()).group_by(DownloadJob.status)).all()
    counts = {(s.value if hasattr(s, "value") else s): n for s, n in rows}
    return {
        "total": sum(counts.values()),
        "active": len(get_active_jobs(session)),
        "completed": counts.get("done", 0),
        "failed": counts.get("failed", 0),
        "not_found": counts.get("not_found", 0),
        "skipped": counts.get("skipped", 0),
    }


@router.get("/sync/status")
def get_sync_status():
    """Health of the background Radarr/Sonarr syncs (so the UI can warn when data may be stale)."""
    return sync_svc.get_sync_status()


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
            import httpx
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.get(
                        f"{settings.sonarr_url.rstrip('/')}/api/v3/series/lookup",
                        params={"term": req.title},
                        headers={"X-Api-Key": settings.sonarr_api_key}
                    )
                    resp.raise_for_status()
                    results = resp.json()
            except Exception as e:
                raise HTTPException(status_code=502, detail=f"Sonarr search failed: {e}")
            if not results:
                raise HTTPException(status_code=404, detail=f"No Sonarr results for '{req.title}'")
            tvdb_id = results[0]["tvdbId"]

        try:
            series = await sonarr_svc.ensure_series_added(tvdb_id, req.title or "Unknown", settings)
            episodes = await sonarr_svc.get_episodes(series["id"], settings)
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Failed to setup series in Sonarr: {e}")

        episodes_to_dl = []
        if req.episode_number is not None:
            ep = next((e for e in episodes if e.get("seasonNumber") == req.season_number and e.get("episodeNumber") == req.episode_number), None)
            if ep:
                episodes_to_dl.append(ep)
        else:
            episodes_to_dl = [e for e in episodes if e.get("seasonNumber") == req.season_number]

        if not episodes_to_dl:
            raise HTTPException(status_code=404, detail="No episodes found for specified season/episode")

        job_ids = []
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
                    title=title, status=JobStatus.MOVIE_MISSING, monitored=bool(ep.get("monitored", True)),
                    arr_id=ep.get("id"),
                )
                session.add(job)
                session.commit()
                session.refresh(job)
            job_ids.append(job.id)

        background_tasks.add_task(process_many, job_ids, auto_download=True, indexer=req.indexer)
        log_action("Manual", f"Triggered {len(job_ids)} TV episodes for tvdb_id={tvdb_id} season={req.season_number}", tvdb_id=tvdb_id)
        return {"status": "accepted", "tvdb_id": tvdb_id, "triggered": len(job_ids)}

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
async def trigger_all_monitored(background_tasks: BackgroundTasks, media_type: str = "movie", session: Session = Depends(get_session)):
    """Search for every monitored job that still needs a file (movies by default, `?media_type=tv` for episodes)."""
    jobs = session.exec(select(DownloadJob).where(
        DownloadJob.monitored == True,  # noqa: E712
        DownloadJob.media_type == media_type,
        DownloadJob.status.notin_(list(_BUSY) + [JobStatus.DONE, JobStatus.NOT_IN_RADARR]),
    )).all()
    ids = [j.id for j in jobs]
    background_tasks.add_task(process_many, ids)
    log_action("Manual", f"Bulk trigger: {len(ids)} monitored {media_type} jobs queued for search")
    return {"status": "accepted", "triggered": len(ids)}


@router.post("/jobs/trigger-missing")
async def trigger_missing(background_tasks: BackgroundTasks, media_type: str = "movie", session: Session = Depends(get_session)):
    """Search for every job in the 'missing' state."""
    jobs = session.exec(select(DownloadJob).where(
        DownloadJob.status == JobStatus.MOVIE_MISSING, DownloadJob.media_type == media_type)).all()
    ids = [j.id for j in jobs]
    background_tasks.add_task(process_many, ids)
    log_action("Manual", f"Bulk trigger: {len(ids)} missing {media_type} jobs queued for search")
    return {"status": "accepted", "triggered": len(ids)}


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

    log_action("Manual", f"Retrying job for '{job.title}'", tmdb_id=job.tmdb_id, tvdb_id=job.tvdb_id, job_id=job.id)
    background_tasks.add_task(process_request, job.id)
    return {"status": "retrying", "tmdb_id": job.tmdb_id}


# ── Sync & import (logic lives in backend/sync.py) ───────────────────────────

@router.post("/jobs/{job_id}/sync")
async def sync_single_job(job_id: int):
    """Reconcile a single job with live Radarr/Sonarr data."""
    try:
        return await sync_svc.sync_single_job(job_id)
    except sync_svc.SyncError as e:
        _raise_sync(e)


@router.post("/jobs/sync-all")
async def sync_all_jobs():
    """Reconcile all movie jobs with Radarr (awaited, so the response reflects the new state)."""
    try:
        return await sync_svc.sync_all_movies()
    except sync_svc.SyncError as e:
        _raise_sync(e)


@router.post("/jobs/sync-all-sonarr")
async def sync_all_sonarr():
    """Reconcile all TV jobs with Sonarr."""
    try:
        return await sync_svc.sync_all_sonarr()
    except sync_svc.SyncError as e:
        _raise_sync(e)


@router.post("/jobs/import-radarr")
async def trigger_import_radarr():
    """Import all movies from Radarr that match configured regional languages."""
    try:
        return await sync_svc.import_radarr_movies()
    except sync_svc.SyncError as e:
        _raise_sync(e)


@router.post("/jobs/import-sonarr")
async def trigger_import_sonarr():
    """Import all series from Sonarr to ensure they are tracked as jobs."""
    try:
        return await sync_svc.import_sonarr_series()
    except sync_svc.SyncError as e:
        _raise_sync(e)


@router.post("/jobs/discovery")
async def trigger_discovery(session: Session = Depends(get_session)):
    """Manually trigger a background discovery batch (ignores the auto-search toggles)."""
    settings = get_settings(session)
    triggered = await sync_svc.run_discovery_batch(settings.missing_search_batch_size, force=True)
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
