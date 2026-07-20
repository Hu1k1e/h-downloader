"""
Webhook router — receives Jellyseerr notification events.
"""
import hashlib
import hmac
import json
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request, Depends
from pydantic import BaseModel
from sqlmodel import Session, select

from backend import config
from backend.database import get_session, get_settings
from backend.models import AppSettings, DownloadJob, JobStatus
from backend.orchestrator import process_request
from backend.sync import delayed_search
from backend.db_logger import log_action
from backend.services.tmdb import get_movie_details

router = APIRouter(prefix="/webhook", tags=["webhook"])


class JellyseerrPayload(BaseModel):
    notification_type: Optional[str] = None
    media_type: Optional[str] = None
    tmdbId: Optional[str] = None
    title: Optional[str] = None

class RadarrMoviePayload(BaseModel):
    tmdbId: Optional[int] = None
    title: Optional[str] = None

class RadarrPayload(BaseModel):
    eventType: Optional[str] = None
    movie: Optional[RadarrMoviePayload] = None


@router.post("/jellyseerr")
async def jellyseerr_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_hub_signature: Optional[str] = Header(default=None),
    session: Session = Depends(get_session),
):
    """
    Receives Jellyseerr webhook events (media_pending, media_approved, etc.)
    and kicks off the download pipeline for movies.
    """
    settings = get_settings(session)
    raw_body = await request.body()

    # ── Optional HMAC verification ────────────────────────────────────────
    if settings.webhook_secret:
        if not x_hub_signature:
            raise HTTPException(status_code=401, detail="Missing signature")
        expected = "sha256=" + hmac.new(
            settings.webhook_secret.encode(), raw_body, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected, x_hub_signature):
            raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        payload_data = json.loads(raw_body)
        payload = JellyseerrPayload(**payload_data)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    # Only handle movie requests
    if payload.media_type and payload.media_type.lower() != "movie":
        return {"status": "skipped", "reason": "not a movie"}

    # Only act on pending/approved events
    allowed_types = {"media_pending", "media_approved", "media-pending", "media-approved"}
    if payload.notification_type and payload.notification_type.lower() not in allowed_types:
        return {"status": "skipped", "reason": f"unhandled notification_type: {payload.notification_type}"}

    if not payload.tmdbId:
        raise HTTPException(status_code=400, detail="tmdbId missing from payload")

    tmdb_id = int(payload.tmdbId)

    job = session.exec(select(DownloadJob).where(DownloadJob.tmdb_id == tmdb_id)).first()
    if not job:
        job = DownloadJob(
            tmdb_id=tmdb_id,
            title=payload.title or f"TMDB:{tmdb_id}",
            status=JobStatus.MOVIE_MISSING
        )
        session.add(job)
        session.commit()

    # Fire and forget — trigger delayed search to allow Radarr to grab torrents first
    log_action("Webhook", f"Jellyseerr request approved for '{payload.title}'", tmdb_id=tmdb_id)
    background_tasks.add_task(delayed_search, tmdb_id, None)

    return {"status": "accepted", "tmdb_id": tmdb_id, "title": payload.title}

@router.post("/radarr")
async def radarr_webhook(
    payload: RadarrPayload,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
):
    """
    Receives Radarr webhook events (MovieAdded, MovieDeleted, Download, MovieFileDeleted)
    and manages the local jobs in real-time.
    """
    settings = get_settings(session)
    event_type = payload.eventType
    if not event_type or not payload.movie or not payload.movie.tmdbId:
        return {"status": "skipped", "reason": "missing required fields"}

    tmdb_id = payload.movie.tmdbId
    title = payload.movie.title or f"TMDB:{tmdb_id}"
    
    job = session.exec(select(DownloadJob).where(DownloadJob.tmdb_id == tmdb_id)).first()

    if event_type == "MovieAdded":
        if not job:
            mapped_lang = None
            poster_path = None
            year = None
            if settings.tmdb_api_key:
                try:
                    details = await get_movie_details(tmdb_id, settings)
                    tmdb_lang_code = details.get("original_language", "").lower()
                    mapped_lang = config.TMDB_LANG_TO_EINTHUSAN.get(tmdb_lang_code, tmdb_lang_code)
                    poster_path = details.get("poster_path")
                    year = details.get("year")
                    allowed_langs = [l.strip().lower() for l in settings.einthusan_languages_str.split(",") if l.strip()]
                    if mapped_lang not in allowed_langs:
                        log_action("Webhook", f"Skipped movie '{title}' (Language '{mapped_lang}' not in configured languages)", tmdb_id=tmdb_id)
                        return {"status": "skipped", "reason": "language_not_allowed", "language": mapped_lang}
                except Exception as e:
                    import logging
                    logging.getLogger(__name__).warning(f"Failed to fetch TMDB details for {tmdb_id}: {e}")

            job = DownloadJob(
                tmdb_id=tmdb_id, title=title, status=JobStatus.MOVIE_MISSING, 
                language=mapped_lang, poster_path=poster_path, year=year
            )
            session.add(job)
            session.commit()
            session.refresh(job)
        
        log_action("Webhook", f"Movie '{title}' added to Radarr", tmdb_id=tmdb_id, job_id=job.id if job else None)
        if job.status == JobStatus.MOVIE_MISSING:
            background_tasks.add_task(delayed_search, tmdb_id, job.language)
            
    elif event_type == "MovieDeleted":
        if job:
            log_action("Webhook", f"Movie '{title}' deleted from Radarr", tmdb_id=tmdb_id, job_id=job.id)
            job.status = JobStatus.NOT_IN_RADARR
            job.monitored = False
            session.add(job)
            session.commit()
            
    elif event_type == "Download":
        # Radarr successfully downloaded a file
        if not job:
            job = DownloadJob(tmdb_id=tmdb_id, title=title)
            session.add(job)
        job.status = JobStatus.DONE
        job.monitored = False
        job.progress_pct = 100
        job.error_msg = None
        log_action("Webhook", f"Radarr finished downloading '{title}'", tmdb_id=tmdb_id, job_id=job.id)
        session.commit()
        
    elif event_type == "MovieFileDeleted":
        if not job:
            job = DownloadJob(tmdb_id=tmdb_id, title=title)
            session.add(job)
        job.status = JobStatus.MOVIE_MISSING
        job.monitored = True
        log_action("Webhook", f"Movie file deleted for '{title}' in Radarr", tmdb_id=tmdb_id, job_id=job.id)
        session.commit()
        if settings.enable_radarr_auto_search:
            background_tasks.add_task(delayed_search, tmdb_id, job.language)

    elif event_type == "Grab":
        # Radarr grabbed a download — track it as a native Radarr download
        # so the active_job_tracker_loop monitors it and triggers fallback if it disappears
        if not job:
            job = DownloadJob(tmdb_id=tmdb_id, title=title)
            session.add(job)
        if job.status not in (JobStatus.DOWNLOADING, JobStatus.DONE, JobStatus.IMPORTING):
            job.status = JobStatus.DOWNLOADING
            job.source_indexer = "radarr"
            job.error_msg = None
            job.progress_pct = 0
        log_action("Webhook", f"Radarr grabbed download for '{title}'", tmdb_id=tmdb_id, job_id=job.id)
        session.commit()

    elif event_type in ("DownloadFailed", "ManualInteractionRequired"):
        # Radarr download failed or was removed (e.g. stalled deletion)
        # Trigger immediate fallback search
        if job and job.status in (JobStatus.DOWNLOADING, JobStatus.MOVIE_MISSING, JobStatus.PENDING):
            job.status = JobStatus.MOVIE_MISSING
            job.source_indexer = None
            job.torrent_hash = None
            job.progress_pct = 0
            job.error_msg = None
            log_action("Webhook", f"Radarr download failed/removed for '{title}'. Triggering fallback search.", tmdb_id=tmdb_id, job_id=job.id)
            session.commit()
            # Immediate fallback — override delay to 0
            background_tasks.add_task(delayed_search, tmdb_id, None, override_delay=0)

    return {"status": "accepted", "event": event_type, "tmdb_id": tmdb_id}
