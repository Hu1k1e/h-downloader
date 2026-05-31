"""
Orchestrator — the main flow controller.
"""
import asyncio
import logging
from datetime import datetime
from typing import Optional

from sqlmodel import Session, select

logger = logging.getLogger(__name__)

from backend import config
from backend.database import engine, get_settings
from backend.models import DownloadJob, JobStatus, AppSettings
from backend.services import einthusan, radarr, sonarr, tmdb, onetwothreemovies
from backend.services.downloader import download_movie, get_movie_file_path


def _update_job(session: Session, job: DownloadJob, **kwargs):
    for k, v in kwargs.items():
        setattr(job, k, v)
    job.updated_at = datetime.utcnow()
    session.add(job)
    session.commit()
    session.refresh(job)


async def process_request(
    tmdb_id: int, 
    requested_language: Optional[str] = None,
    media_type: str = "movie",
    season_number: Optional[int] = None,
    episode_number: Optional[int] = None
) -> int:
    """
    Main entry point. Creates a DownloadJob and runs the full pipeline.
    Returns the job_id.
    """
    with Session(engine) as session:
        settings = get_settings(session)
        
        # Get metadata from TMDB
        try:
            if media_type == "series":
                media = await tmdb.get_series_details(tmdb_id, settings)
                title = media["title"]
                year = media["year"]
                if season_number and episode_number:
                    job_title = f"{title} S{season_number:02d}E{episode_number:02d}"
                else:
                    job_title = title
            else:
                media = await tmdb.get_movie_details(tmdb_id, settings)
                title = media["title"]
                year = media["year"]
                job_title = title
        except Exception as e:
            # Create a failed job to record the error
            job = session.exec(select(DownloadJob).where(DownloadJob.tmdb_id == tmdb_id)).first()
            if not job:
                job = DownloadJob(
                    tmdb_id=tmdb_id,
                    title=f"TMDB:{tmdb_id}",
                    media_type=media_type,
                    season_number=season_number,
                    episode_number=episode_number,
                    status=JobStatus.FAILED,
                    monitored=False,
                    error_msg=f"TMDB lookup failed: {e}",
                )
            else:
                job.status = JobStatus.FAILED
                job.error_msg = f"TMDB lookup failed: {e}"
            session.add(job)
            session.commit()
            return job.id
            
        original_lang_code = media.get("original_language", "")
        poster_path = media.get("poster_path")

        # Create job record or update existing
        query = select(DownloadJob).where(DownloadJob.tmdb_id == tmdb_id)
        if media_type == "series":
            query = query.where(DownloadJob.season_number == season_number).where(DownloadJob.episode_number == episode_number)
            
        job = session.exec(query).first()
        
        if not job:
            job = DownloadJob(
                tmdb_id=tmdb_id,
                title=job_title,
                year=year,
                media_type=media_type,
                season_number=season_number,
                episode_number=episode_number,
                status=JobStatus.CHECKING_RADARR,
                poster_path=poster_path,
            )
            session.add(job)
            session.commit()
            session.refresh(job)
        elif poster_path and not job.poster_path:
            # Back-fill poster for existing jobs that don't have one
            job.poster_path = poster_path
            session.add(job)
            session.commit()
            session.refresh(job)
            
        job_id = job.id

    # Run the async pipeline in a background task
    asyncio.create_task(
        _run_pipeline(
            job_id, tmdb_id, title, year, original_lang_code, requested_language,
            media_type, season_number, episode_number
        )
    )
    return job_id


async def _run_pipeline(
    job_id: int,
    tmdb_id: int,
    title: str,
    year: Optional[int],
    original_lang_code: str,
    requested_language: Optional[str],
    media_type: str,
    season_number: Optional[int],
    episode_number: Optional[int]
):
    with Session(engine) as session:
        job = session.get(DownloadJob, job_id)
        settings = get_settings(session)

        # ── Guard: skip if already downloading or done ────────────────────────
        if job and job.status in (JobStatus.DOWNLOADING, JobStatus.DONE, JobStatus.IMPORTING):
            logger.info(f"Job '{job.title}' is already in status '{job.status}' — skipping re-trigger.")
            return

        # ── Step 1: Check Radarr/Sonarr ──────────────────────────────────────
        try:
            if media_type == "series":
                series_dict = await sonarr.is_series_in_sonarr(tmdb_id, settings)
                available = False
                if series_dict and "id" in series_dict:
                    available = await sonarr.is_episode_available(series_dict["id"], season_number, episode_number, settings)
            else:
                available = await radarr.is_movie_available(tmdb_id, settings)
        except Exception as e:
            _update_job(session, job, status=JobStatus.FAILED, error_msg=f"Media server check failed: {e}")
            return

        if available:
            logger.info(f"Media server already has '{job.title}' — marking DONE, unmonitoring.")
            _update_job(session, job, status=JobStatus.DONE, monitored=False, progress_pct=100, error_msg=None)
            return

        # ── Step 2: Check digital release date (Movies only) ────────────────
        if media_type == "movie":
            try:
                passed, release_date = await tmdb.has_digital_release_passed(tmdb_id, settings)
            except Exception as e:
                _update_job(session, job, status=JobStatus.FAILED, error_msg=f"TMDB date check failed: {e}")
                return

            if not passed and release_date is not None:
                msg = f"Digital release date not yet passed (estimated: {release_date})"
                _update_job(session, job, status=JobStatus.SKIPPED, error_msg=msg)
                return

        # ── Step 3: Determine which languages to search ──────────────────────
        langs_to_try = []
        einthusan_languages = [l.strip() for l in settings.einthusan_languages_str.split(",") if l.strip()]
        
        if requested_language and requested_language in config.LANGUAGE_SLUG_MAP:
            langs_to_try = [requested_language]
        else:
            mapped = config.TMDB_LANG_TO_EINTHUSAN.get(original_lang_code)
            if mapped and mapped in einthusan_languages:
                langs_to_try = [mapped]
            else:
                _update_job(session, job, status=JobStatus.SKIPPED,
                            error_msg=f"Language '{original_lang_code}' not in configured languages")
                return

        # ── Step 4: Search Einthusan or 123movies ────────────────────────────
        _update_job(session, job, status=JobStatus.SEARCHING)
        watch_url: Optional[str] = None
        found_lang: Optional[str] = None
        
        is_hollywood = ("hollywood" in langs_to_try)

        if media_type == "movie" and not is_hollywood:
            for lang in langs_to_try:
                if lang == "hollywood": continue
                try:
                    url = await einthusan.search(title, year, lang)
                    if url:
                        watch_url = url
                        found_lang = lang
                        break
                except Exception:
                    continue

        # Fallback to 123movies if Einthusan fails, OR if it's a series, OR if language is hollywood
        if not watch_url and (is_hollywood or media_type == "series" or not watch_url):
            try:
                url = await onetwothreemovies.search_media(title, year, media_type == "series", season_number, episode_number)
                if url:
                    watch_url = url
                    found_lang = "hollywood" if is_hollywood else langs_to_try[0]
            except Exception as e:
                logger.error(f"123movies fallback failed: {e}")

        if not watch_url:
            _update_job(session, job, status=JobStatus.NOT_FOUND,
                        error_msg=f"Not found on any configured indexers (searched: {', '.join(langs_to_try)})")
            return

        _update_job(session, job, einthusan_url=watch_url, language=found_lang)

        # ── Step 5: Extract direct MP4 URL ──────────────────────────────────
        try:
            if "einthusan" in watch_url:
                direct_url = await einthusan.extract_mp4_url(watch_url)
            else:
                direct_url = await onetwothreemovies.extract_mp4_url(watch_url, media_type == "series", season_number, episode_number)
        except Exception as e:
            _update_job(session, job, status=JobStatus.FAILED, error_msg=f"MP4 extraction failed: {e}")
            return

        if not direct_url:
            _update_job(session, job, status=JobStatus.FAILED, error_msg="Could not extract MP4 URL from source")
            return

        _update_job(session, job, direct_url=direct_url)

        # ── Step 6: Ensure media exists in Radarr/Sonarr ────────────────────
        try:
            if media_type == "series":
                await sonarr.ensure_series_added(tmdb_id, title, year or 0, settings)
            else:
                await radarr.ensure_movie_added(tmdb_id, title, year or 0, settings)
        except Exception as e:
            _update_job(session, job, status=JobStatus.FAILED, error_msg=f"Media server add failed: {e}")
            return

        # ── Step 7: Download ─────────────────────────────────────────────────
        try:
            if media_type == "series":
                folder_path = await sonarr.get_series_folder(tmdb_id, title, year or 0, settings)
                file_name = f"{title} S{season_number:02d}E{episode_number:02d}.mp4"
                file_path = f"{folder_path}/{file_name}"
            else:
                folder_path = await radarr.get_movie_folder(tmdb_id, title, year or 0, settings)
                file_path = get_movie_file_path(folder_path, title, year)
        except Exception as e:
            _update_job(session, job, status=JobStatus.FAILED, error_msg=f"Failed to get media folder: {e}")
            return
            
        _update_job(session, job, file_path=file_path, status=JobStatus.DOWNLOADING)

        success = await download_movie(job_id, direct_url, file_path, session)
        if not success:
            return  # download_movie already updated the job status

        # ── Step 8: Trigger Radarr/Sonarr import ────────────────────────────
        try:
            if media_type == "series":
                series_data = await sonarr.is_series_in_sonarr(tmdb_id, settings)
                if series_data and "id" in series_data:
                    await sonarr.trigger_rescan(series_data["id"], settings)
            else:
                movie_data = await radarr.is_movie_in_radarr(tmdb_id, settings)
                if movie_data and "id" in movie_data:
                    await radarr.trigger_rescan(movie_data["id"], settings)
        except Exception as e:
            _update_job(session, job, status=JobStatus.FAILED, error_msg=f"Media server rescan failed: {e}")
            return

        _update_job(session, job, status=JobStatus.DONE, progress_pct=100,
                    monitored=False, file_path=file_path, error_msg=None)
