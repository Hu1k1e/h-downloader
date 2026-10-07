"""
Webhook router — receives Jellyseerr, Radarr and Sonarr events.
"""
import hashlib
import hmac
import json
import logging
from typing import Optional, Tuple

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request, Depends
from pydantic import BaseModel
from sqlmodel import Session, select

from backend import config
from backend.database import get_session, get_settings
from backend.models import AppSettings, DownloadJob, JobStatus
from backend.sync import delayed_search
from backend.db_logger import log_action
from backend.services.tmdb import get_movie_details

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhook", tags=["webhook"])


def require_webhook_token(request: Request, x_webhook_token: Optional[str] = Header(default=None)):
    """Opt-in shared-secret check for the Radarr/Sonarr webhooks (set WEBHOOK_TOKEN).

    Radarr/Sonarr can't sign requests, so configure the webhook URL as
    `.../webhook/radarr?token=<WEBHOOK_TOKEN>` (or add the X-Webhook-Token header)."""
    expected = config.WEBHOOK_TOKEN
    if not expected:
        return
    supplied = x_webhook_token or request.query_params.get("token") or ""
    if not hmac.compare_digest(supplied.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="Invalid webhook token")


class JellyseerrPayload(BaseModel):
    notification_type: Optional[str] = None
    media_type: Optional[str] = None
    tmdbId: Optional[str] = None
    tvdbId: Optional[str] = None
    title: Optional[str] = None

class RadarrMoviePayload(BaseModel):
    tmdbId: Optional[int] = None
    title: Optional[str] = None

class RadarrPayload(BaseModel):
    eventType: Optional[str] = None
    movie: Optional[RadarrMoviePayload] = None

class SonarrSeriesPayload(BaseModel):
    tvdbId: Optional[int] = None
    title: Optional[str] = None

class SonarrEpisodePayload(BaseModel):
    id: Optional[int] = None
    title: Optional[str] = None
    seasonNumber: Optional[int] = None
    episodeNumber: Optional[int] = None

class SonarrPayload(BaseModel):
    eventType: Optional[str] = None
    series: Optional[SonarrSeriesPayload] = None
    episodes: Optional[list[SonarrEpisodePayload]] = None


async def _movie_meta(tmdb_id: int, title: str, settings: AppSettings) -> Tuple[Optional[str], Optional[str], Optional[int], bool]:
    """Look the movie up on TMDB. Returns (language, poster_path, year, allowed).
    `allowed` is False only when TMDB positively says the language isn't configured."""
    if not settings.tmdb_api_key:
        return None, None, None, True
    try:
        details = await get_movie_details(tmdb_id, settings)
    except Exception as e:
        logger.warning(f"Failed to fetch TMDB details for {tmdb_id}: {e}")
        return None, None, None, True
    code = (details.get("original_language") or "").lower()
    lang = config.TMDB_LANG_TO_EINTHUSAN.get(code, code)
    allowed_langs = [l.strip().lower() for l in settings.einthusan_languages_str.split(",") if l.strip()]
    return lang, details.get("poster_path"), details.get("year"), lang in allowed_langs


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

    media_type = (payload.media_type or "").lower()
    if media_type not in ("movie", "tv"):
        return {"status": "skipped", "reason": f"unsupported media_type: {payload.media_type}"}

    # Only act on pending/approved events
    allowed_types = {"media_pending", "media_approved", "media-pending", "media-approved"}
    if payload.notification_type and payload.notification_type.lower() not in allowed_types:
        return {"status": "skipped", "reason": f"unhandled notification_type: {payload.notification_type}"}

    if not payload.tmdbId:
        raise HTTPException(status_code=400, detail="tmdbId missing from payload")

    try:
        tmdb_id = int(payload.tmdbId)
    except ValueError:
        raise HTTPException(status_code=400, detail="tmdbId must be a number")

    if media_type == "movie":
        job = session.exec(select(DownloadJob).where(DownloadJob.tmdb_id == tmdb_id, DownloadJob.media_type == "movie")).first()
        if not job:
            title = payload.title or f"TMDB:{tmdb_id}"
            lang, poster, year, allowed = await _movie_meta(tmdb_id, title, settings)
            if not allowed:
                log_action("Webhook", f"Skipped Jellyseerr movie '{title}' (language '{lang}' not in configured languages)", tmdb_id=tmdb_id)
                return {"status": "skipped", "reason": "language_not_allowed", "language": lang}
            job = DownloadJob(
                media_type="movie", tmdb_id=tmdb_id, title=title, status=JobStatus.MOVIE_MISSING,
                language=lang, poster_path=poster, year=year,
            )
            session.add(job)
            session.commit()

        log_action("Webhook", f"Jellyseerr request approved for movie '{payload.title}'", tmdb_id=tmdb_id)
        if settings.enable_jellyseerr_auto_request:
            # Give Radarr a head start to grab it itself before we search custom sources
            background_tasks.add_task(delayed_search, tmdb_id, None)
        else:
            logger.info("Jellyseerr auto-request is disabled — job created but no search started.")
    else:
        tvdb_id = int(payload.tvdbId) if payload.tvdbId and payload.tvdbId.isdigit() else None
        log_action("Webhook", f"Jellyseerr request approved for TV show '{payload.title}'", tmdb_id=tmdb_id, tvdb_id=tvdb_id)
        # Episode jobs are created by the Sonarr state sync loop once Sonarr knows the series.

    return {"status": "accepted", "tmdb_id": tmdb_id, "media_type": payload.media_type, "title": payload.title}


@router.post("/radarr", dependencies=[Depends(require_webhook_token)])
async def radarr_webhook(
    payload: RadarrPayload,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
):
    """
    Receives Radarr webhook events (MovieAdded, MovieDeleted, Download, MovieFileDeleted, Grab,
    DownloadFailed) and updates the local jobs in real time. The 60s Radarr sync loop is the
    safety net for anything missed here.
    """
    settings = get_settings(session)
    event_type = payload.eventType
    if not event_type or not payload.movie or not payload.movie.tmdbId:
        return {"status": "skipped", "reason": "missing required fields"}

    tmdb_id = payload.movie.tmdbId
    title = payload.movie.title or f"TMDB:{tmdb_id}"

    job = session.exec(select(DownloadJob).where(DownloadJob.tmdb_id == tmdb_id, DownloadJob.media_type == "movie")).first()

    if event_type == "MovieAdded":
        if not job:
            lang, poster, year, allowed = await _movie_meta(tmdb_id, title, settings)
            if not allowed:
                log_action("Webhook", f"Skipped movie '{title}' (Language '{lang}' not in configured languages)", tmdb_id=tmdb_id)
                return {"status": "skipped", "reason": "language_not_allowed", "language": lang}

            job = DownloadJob(
                media_type="movie",
                tmdb_id=tmdb_id, title=title, status=JobStatus.MOVIE_MISSING,
                language=lang, poster_path=poster, year=year
            )
            session.add(job)
            session.commit()
            session.refresh(job)

        log_action("Webhook", f"Movie '{title}' added to Radarr", tmdb_id=tmdb_id, job_id=job.id)
        if job.status == JobStatus.MOVIE_MISSING and settings.enable_radarr_auto_search:
            background_tasks.add_task(delayed_search, tmdb_id, job.language)

    elif event_type == "MovieDeleted":
        if job:
            log_action("Webhook", f"Movie '{title}' deleted from Radarr", tmdb_id=tmdb_id, job_id=job.id)
            job.status = JobStatus.NOT_IN_RADARR
            job.in_arr = False
            job.has_file = False
            job.monitored = False
            session.add(job)
            session.commit()

    elif event_type == "Download":
        # Radarr successfully imported a file. (monitored is left alone: Radarr is the source of truth.)
        if not job:
            job = DownloadJob(media_type="movie", tmdb_id=tmdb_id, title=title)
            session.add(job)
        job.status = JobStatus.DONE
        job.has_file = True
        job.in_arr = True
        job.progress_pct = 100
        job.error_msg = None
        session.commit()
        session.refresh(job)
        log_action("Webhook", f"Radarr finished downloading '{title}'", tmdb_id=tmdb_id, job_id=job.id)

    elif event_type == "MovieFileDeleted":
        if not job:
            job = DownloadJob(media_type="movie", tmdb_id=tmdb_id, title=title)
            session.add(job)
        job.status = JobStatus.MOVIE_MISSING
        job.has_file = False
        job.progress_pct = 0
        job.file_path = None
        session.commit()
        session.refresh(job)
        log_action("Webhook", f"Movie file deleted for '{title}' in Radarr", tmdb_id=tmdb_id, job_id=job.id)
        if settings.enable_radarr_auto_search:
            background_tasks.add_task(delayed_search, tmdb_id, job.language)

    elif event_type == "Grab":
        # Radarr grabbed a download — track it as a native Radarr download so the tracker
        # monitors it and triggers fallback if it disappears.
        if not job:
            job = DownloadJob(media_type="movie", tmdb_id=tmdb_id, title=title)
            session.add(job)
        if job.status not in (JobStatus.DOWNLOADING, JobStatus.DONE, JobStatus.IMPORTING):
            job.status = JobStatus.DOWNLOADING
            job.source_indexer = "radarr"
            job.error_msg = None
            job.progress_pct = 0
        session.commit()
        session.refresh(job)
        log_action("Webhook", f"Radarr grabbed download for '{title}'", tmdb_id=tmdb_id, job_id=job.id)

    elif event_type in ("DownloadFailed", "ManualInteractionRequired"):
        # Radarr download failed or was removed (e.g. stalled deletion) — search our own sources now.
        if job and job.status in (JobStatus.DOWNLOADING, JobStatus.MOVIE_MISSING, JobStatus.PENDING):
            job.status = JobStatus.MOVIE_MISSING
            job.source_indexer = None
            job.torrent_hash = None
            job.progress_pct = 0
            job.error_msg = None
            session.commit()
            log_action("Webhook", f"Radarr download failed/removed for '{title}'. Triggering fallback search.", tmdb_id=tmdb_id, job_id=job.id)
            if settings.enable_radarr_auto_search:
                background_tasks.add_task(delayed_search, tmdb_id, None, override_delay=0)

    return {"status": "accepted", "event": event_type, "tmdb_id": tmdb_id}


@router.post("/sonarr", dependencies=[Depends(require_webhook_token)])
async def sonarr_webhook(
    payload: SonarrPayload,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
):
    """
    Receives Sonarr webhook events. Episode jobs are created and updated by the
    Sonarr state sync loop (avoids races with Sonarr's own initial scan); here we only log.
    """
    event_type = payload.eventType
    if not event_type or not payload.series or not payload.series.tvdbId:
        return {"status": "skipped", "reason": "missing required fields"}

    tvdb_id = payload.series.tvdbId
    series_title = payload.series.title or f"TVDB:{tvdb_id}"

    log_action("Webhook", f"Sonarr event '{event_type}' received for '{series_title}'", tvdb_id=tvdb_id)

    return {"status": "accepted", "event": event_type, "tvdb_id": tvdb_id}
