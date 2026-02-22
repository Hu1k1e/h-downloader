"""
Orchestrator — the main flow controller.

Called by:
- The webhook router when Jellyseerr fires a media request event
- The jobs router when a user manually triggers a download

Flow:
1. Check if Radarr already has the file → skip if yes
2. Check if digital release date has passed → skip if no
3. For each configured language, search Einthusan
4. If found: extract MP4, download, trigger Radarr import
5. Update job status throughout
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
from backend.services import einthusan, radarr, tmdb
from backend.services.downloader import download_movie, get_movie_file_path


def _update_job(session: Session, job: DownloadJob, **kwargs):
    for k, v in kwargs.items():
        setattr(job, k, v)
    job.updated_at = datetime.utcnow()
    session.add(job)
    session.commit()
    session.refresh(job)


async def process_request(tmdb_id: int, requested_language: Optional[str] = None) -> int:
    """
    Main entry point. Creates a DownloadJob and runs the full pipeline.
    Returns the job_id.
    """
    with Session(engine) as session:
        settings = get_settings(session)
        
        # Get movie metadata from TMDB
        try:
            movie = await tmdb.get_movie_details(tmdb_id, settings)
        except Exception as e:
            # Create a minimal failed job
            job = DownloadJob(
                tmdb_id=tmdb_id,
                title=f"TMDB:{tmdb_id}",
                status=JobStatus.FAILED,
                monitored=False,
                error_msg=f"TMDB lookup failed: {e}",
            )
            session.add(job)
            session.commit()
            session.refresh(job)
            return job.id

        title = movie["title"]
        year = movie["year"]
        original_lang_code = movie.get("original_language", "")
        poster_path = movie.get("poster_path")

        # Create job record or update existing
        job = session.exec(select(DownloadJob).where(DownloadJob.tmdb_id == tmdb_id)).first()
        if not job:
            job = DownloadJob(
                tmdb_id=tmdb_id,
                title=title,
                year=year,
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
        _run_pipeline(job_id, tmdb_id, title, year, original_lang_code, requested_language)
    )
    return job_id


async def _run_pipeline(
    job_id: int,
    tmdb_id: int,
    title: str,
    year: Optional[int],
    original_lang_code: str,
    requested_language: Optional[str],
):
    with Session(engine) as session:
        job = session.get(DownloadJob, job_id)
        settings = get_settings(session)

        # ── Guard: skip if already downloading or done ────────────────────────
        if job and job.status in (JobStatus.DOWNLOADING, JobStatus.DONE, JobStatus.IMPORTING):
            logger.info(f"Job '{job.title}' is already in status '{job.status}' — skipping re-trigger.")
            return

        # ── Step 1: Check Radarr ─────────────────────────────────────────────
        try:
            available = await radarr.is_movie_available(tmdb_id, settings)
        except Exception as e:
            _update_job(session, job, status=JobStatus.FAILED, error_msg=f"Radarr check failed: {e}")
            return

        if available:
            logger.info(f"Radarr already has '{title}' — marking DONE, unmonitoring.")
            _update_job(session, job, status=JobStatus.DONE, monitored=False, progress_pct=100, error_msg=None)
            return

        # ── Step 2: Check digital release date ──────────────────────────────
        try:
            passed, release_date = await tmdb.has_digital_release_passed(tmdb_id, settings)
        except Exception as e:
            _update_job(session, job, status=JobStatus.FAILED, error_msg=f"TMDB date check failed: {e}")
            return

        if not passed:
            msg = f"Digital release date not yet passed (estimated: {release_date})" if release_date else "No release date info"
            _update_job(session, job, status=JobStatus.SKIPPED, error_msg=msg)
            return

        # ── Step 3: Determine which languages to search ──────────────────────
        # Priority: explicitly requested language > TMDB original language > skip
        langs_to_try = []
        einthusan_languages = [l.strip() for l in settings.einthusan_languages_str.split(",") if l.strip()]
        
        if requested_language and requested_language in config.LANGUAGE_SLUG_MAP:
            # Manual override — trust the caller
            langs_to_try = [requested_language]
        else:
            # Map TMDB language code to Einthusan slug
            mapped = config.TMDB_LANG_TO_EINTHUSAN.get(original_lang_code)
            if mapped and mapped in einthusan_languages:
                # Movie is in a supported regional language — search that language first
                langs_to_try = [mapped]
            else:
                # Movie's original language (e.g. English) is NOT in configured languages.
                # Do NOT search Einthusan for it — mark as skipped.
                logger.info(
                    f"Skipping '{title}' — original language '{original_lang_code}' "
                    f"is not in configured Einthusan languages: {einthusan_languages}"
                )
                _update_job(session, job, status=JobStatus.SKIPPED,
                            error_msg=f"Language '{original_lang_code}' not in configured languages")
                return

        # ── Step 4: Search Einthusan ─────────────────────────────────────────
        _update_job(session, job, status=JobStatus.SEARCHING)
        watch_url: Optional[str] = None
        found_lang: Optional[str] = None

        for lang in langs_to_try:
            try:
                url = await einthusan.search(title, year, lang)
                if url:
                    watch_url = url
                    found_lang = lang
                    break
            except Exception:
                continue

        if not watch_url:
            _update_job(session, job, status=JobStatus.NOT_FOUND,
                        error_msg=f"Not found on Einthusan (searched: {', '.join(langs_to_try)})")
            return

        _update_job(session, job, einthusan_url=watch_url, language=found_lang)

        # ── Step 5: Extract direct MP4 URL ──────────────────────────────────
        try:
            direct_url = await einthusan.extract_mp4_url(watch_url)
        except Exception as e:
            _update_job(session, job, status=JobStatus.FAILED, error_msg=f"MP4 extraction failed: {e}")
            return

        if not direct_url:
            _update_job(session, job, status=JobStatus.FAILED, error_msg="Could not extract MP4 URL from Einthusan")
            return

        _update_job(session, job, direct_url=direct_url)

        # ── Step 6: Ensure movie exists in Radarr ────────────────────────────
        try:
            await radarr.ensure_movie_added(tmdb_id, title, year or 0, settings)
        except Exception as e:
            _update_job(session, job, status=JobStatus.FAILED, error_msg=f"Radarr add failed: {e}")
            return

        # ── Step 7: Download ─────────────────────────────────────────────────
        try:
            folder_path = await radarr.get_movie_folder(tmdb_id, title, year or 0, settings)
            file_path = get_movie_file_path(folder_path, title, year)
        except Exception as e:
            _update_job(session, job, status=JobStatus.FAILED, error_msg=f"Failed to get movie folder: {e}")
            return
            
        _update_job(session, job, file_path=file_path, status=JobStatus.DOWNLOADING)

        success = await download_movie(job_id, direct_url, file_path, session)
        if not success:
            return  # download_movie already updated the job status

        # ── Step 8: Trigger Radarr import ────────────────────────────────────
        try:
            folder = str(file_path).rsplit("/", 1)[0] if "/" in file_path else file_path.rsplit("\\", 1)[0]
            await radarr.trigger_import(folder, settings)
        except Exception as e:
            _update_job(session, job, status=JobStatus.FAILED, error_msg=f"Radarr import failed: {e}")
            return

        _update_job(session, job, status=JobStatus.DONE, progress_pct=100,
                    monitored=False, file_path=file_path)
