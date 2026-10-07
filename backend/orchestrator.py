import asyncio
import logging
from datetime import datetime, timezone
from typing import Iterable, Optional

from sqlmodel import Session

logger = logging.getLogger(__name__)

from backend import config
from backend.database import engine, get_settings
from backend.models import DownloadJob, JobStatus, AppSettings
from backend.services import einthusan, radarr, tmdb, tamilmv, qbittorrent, sonarr, bollyzone, fmovies
from backend.services.downloader import (
    download_movie, download_m3u8, get_movie_file_path, get_episode_file_path,
)
from backend.db_logger import log_action

# Job ids whose pipeline is currently running. Prevents two pipelines (e.g. a webhook delay
# expiring while a manual trigger is in flight) from searching/downloading the same job.
_running_pipelines: set = set()

_PIPELINE_ACTIVE_STATUSES = (JobStatus.DOWNLOADING, JobStatus.DONE, JobStatus.IMPORTING)


def is_pipeline_running(job_id: int) -> bool:
    return job_id in _running_pipelines


def _update_job(session: Session, job: DownloadJob, **kwargs):
    for k, v in kwargs.items():
        setattr(job, k, v)
    job.updated_at = datetime.utcnow()
    session.add(job)
    session.commit()
    session.refresh(job)


async def process_request(job_id: int, auto_download: bool = True, indexer: Optional[str] = None, fallback_from: Optional[str] = None, skip_release_check: bool = False) -> int:
    """
    Main entry point. Runs the full pipeline for a specific job in the background.
    Returns the job_id immediately. A job that already has a pipeline running is ignored.
    """
    if job_id in _running_pipelines:
        logger.info(f"Pipeline for job {job_id} is already running — ignoring duplicate request.")
        return job_id

    with Session(engine) as session:
        job = session.get(DownloadJob, job_id)
        if not job:
            return job_id

        if job.status not in _PIPELINE_ACTIVE_STATUSES:
            job.status = JobStatus.SEARCHING
            session.add(job)
            session.commit()
            session.refresh(job)

        log_action("Orchestrator", f"Pipeline started for '{job.title}' (job_id={job_id}, indexer={indexer or 'all'}, fallback_from={fallback_from})", tmdb_id=job.tmdb_id, tvdb_id=job.tvdb_id, job_id=job_id)

    _running_pipelines.add(job_id)
    asyncio.create_task(
        _run_pipeline_guarded(job_id, auto_download, indexer, fallback_from, skip_release_check)
    )
    return job_id


async def process_many(job_ids: Iterable[int], delay: float = 1.0, **kwargs) -> None:
    """Start pipelines for many jobs, staggered so a bulk action doesn't hit Radarr,
    TMDB and the sources with dozens of simultaneous requests."""
    for i, job_id in enumerate(job_ids):
        if i:
            await asyncio.sleep(delay)
        try:
            await process_request(job_id, **kwargs)
        except Exception as e:
            logger.error(f"Failed to start pipeline for job {job_id}: {e}")


async def _run_pipeline_guarded(job_id, auto_download, indexer, fallback_from, skip_release_check):
    """Run the pipeline; an unexpected crash must never leave the job stuck in 'searching'."""
    try:
        await _run_pipeline(job_id, auto_download, indexer, fallback_from, skip_release_check)
    except Exception as e:
        logger.exception(f"Pipeline crashed for job {job_id}: {e}")
        try:
            with Session(engine) as session:
                job = session.get(DownloadJob, job_id)
                if job and job.status in (JobStatus.SEARCHING, JobStatus.PENDING):
                    _update_job(session, job, status=JobStatus.FAILED, error_msg=f"Pipeline error: {e}")
            log_action("Orchestrator", f"Pipeline crashed for job {job_id}: {e}", job_id=job_id)
        except Exception as inner:
            logger.error(f"Could not record pipeline crash for job {job_id}: {inner}")
    finally:
        _running_pipelines.discard(job_id)


async def _run_pipeline(
    job_id: int,
    auto_download: bool = True,
    indexer: Optional[str] = None,
    fallback_from: Optional[str] = None,
    skip_release_check: bool = False,
):
    with Session(engine) as session:
        job = session.get(DownloadJob, job_id)
        if not job: return
        settings = get_settings(session)

        # ── Guard: skip if already downloading or done ────────────────────────
        if job.status in _PIPELINE_ACTIVE_STATUSES:
            logger.info(f"Job '{job.title}' is already in status '{job.status}' — skipping re-trigger.")
            return

        if job.media_type == "movie":
            await _run_movie_pipeline(session, job, settings, auto_download, indexer, fallback_from, skip_release_check)
        elif job.media_type == "tv":
            await _run_tv_pipeline(session, job, settings, auto_download, indexer, fallback_from, skip_release_check)


def _ordered_sources(configured: str, default: list, indexer: Optional[str], fallback_from: Optional[str]) -> list:
    sources = [s.strip() for s in (configured or "").split(",") if s.strip()] or list(default)
    if indexer:
        return [indexer]
    if fallback_from:
        try:
            return sources[sources.index(fallback_from) + 1:]
        except ValueError:
            pass
    return sources


async def _rescan_movie(movie_id: Optional[int], settings: AppSettings, title: str):
    """Ask Radarr to rescan. A rescan failure must not turn a finished download into a failure."""
    if not movie_id:
        return
    try:
        await radarr.trigger_rescan(movie_id, settings)
    except Exception as e:
        logger.warning(f"Radarr rescan failed for '{title}' (the file is on disk; Radarr will pick it up on its next scan): {e}")


async def _run_movie_pipeline(session: Session, job: DownloadJob, settings: AppSettings, auto_download: bool, indexer: Optional[str], fallback_from: Optional[str], skip_release_check: bool):
    tmdb_id = job.tmdb_id
    title = job.title
    year = job.year
    job_id = job.id

    # One Radarr library fetch for the whole pipeline.
    try:
        arr_movie = await radarr.is_movie_in_radarr(tmdb_id, settings)
    except Exception as e:
        _update_job(session, job, status=JobStatus.FAILED, error_msg=f"Radarr check failed: {e}")
        return

    if arr_movie and arr_movie.get("hasFile") and not indexer:
        logger.info(f"Radarr already has '{title}' — marking DONE.")
        _update_job(session, job, status=JobStatus.DONE, progress_pct=100, error_msg=None, has_file=True, in_arr=True)
        return

    if arr_movie and "id" in arr_movie and not indexer:
        try:
            queue_item = await radarr.get_movie_queue_status(arr_movie["id"], settings)
            if queue_item:
                tracked = (queue_item.get("trackedDownloadStatus") or "").lower()
                q_status = (queue_item.get("status") or "").lower()
                if tracked not in ("warning", "error") and q_status != "completed":
                    _update_job(session, job, status=JobStatus.DOWNLOADING, source_indexer="radarr", error_msg=None)
                    return
        except Exception as e:
            logger.warning(f"Failed to check Radarr queue for active downloads: {e}")

    release_gate = not indexer and not skip_release_check
    try:
        digital_date, physical_date, theatrical_date = await tmdb.get_digital_release_date(tmdb_id, settings)

        # Determine the best release date to store
        best_date = digital_date or physical_date or theatrical_date
        if best_date:
            new_release = datetime(best_date.year, best_date.month, best_date.day)
            if job.release_date != new_release:
                _update_job(session, job, release_date=new_release)

        passed, release_msg = tmdb.evaluate_release(
            digital_date, physical_date, theatrical_date, settings.digital_release_fallback_days
        )
    except Exception as e:
        if release_gate:
            _update_job(session, job, status=JobStatus.FAILED, error_msg=f"TMDB date check failed: {e}")
            return
        logger.warning(f"TMDB date lookup failed for '{title}' (continuing, release check not required): {e}")
        passed, release_msg = True, None

    if not passed and release_gate:
        log_action(action="search_skipped", message=f"'{title}' skipped: {release_msg}", tmdb_id=tmdb_id, job_id=job_id)
        _update_job(session, job, status=JobStatus.SKIPPED, error_msg=release_msg)
        return

    langs_to_try = []
    einthusan_languages = [l.strip() for l in settings.einthusan_languages_str.split(",") if l.strip()]
    if job.language and job.language in config.LANGUAGE_SLUG_MAP:
        langs_to_try = [job.language]
    else:
        # job.language is normally set on creation; otherwise resolve it from TMDB.
        try:
            movie = await tmdb.get_movie_details(tmdb_id, settings)
            original_lang_code = movie.get("original_language", "")
            mapped = config.TMDB_LANG_TO_EINTHUSAN.get(original_lang_code)
            if mapped and mapped in einthusan_languages:
                langs_to_try = [mapped]
        except Exception as e:
            logger.warning(f"Could not resolve language for '{title}' from TMDB: {e}")

    if not langs_to_try:
        _update_job(session, job, status=JobStatus.SKIPPED, error_msg="Language not in configured languages")
        return

    try:
        arr_movie = await radarr.ensure_movie_added(tmdb_id, title, year or 0, settings, existing=arr_movie)
    except Exception as e:
        _update_job(session, job, status=JobStatus.FAILED, error_msg=f"Radarr add failed: {e}")
        return
    arr_movie_id = arr_movie.get("id") if arr_movie else None

    radarr_resolution = await radarr.get_quality_profile_resolution(settings.radarr_quality_profile_id, settings)

    _update_job(session, job, status=JobStatus.SEARCHING)
    sources = _ordered_sources(settings.movie_download_sources_priority, ["einthusan", "1tamilmv", "fmovies"], indexer, fallback_from)

    if not sources:
        _update_job(session, job, status=JobStatus.NOT_FOUND, error_msg="Exhausted all download sources.")
        return

    success_source = None
    for source in sources:
        if source == "1tamilmv":
            try:
                domain = await tamilmv.get_current_domain()
                thread_url = await tamilmv.search_movie(title, year or 0, domain, langs_to_try, radarr_resolution)
                if thread_url:
                    magnet = await tamilmv.extract_magnet(thread_url)
                    if magnet:
                        if auto_download:
                            torrent_hash = await asyncio.to_thread(qbittorrent.add_magnet_to_qbittorrent, magnet, settings)
                            if torrent_hash:
                                success_source = "1tamilmv"
                                _update_job(session, job, status=JobStatus.DOWNLOADING, error_msg=None, source_indexer="1tamilmv", torrent_hash=torrent_hash)
                                log_action(action="search_success", message=f"Added '{title}' magnet via 1TamilMV.", tmdb_id=tmdb_id, job_id=job.id)
                                break
                        else:
                            success_source = "1tamilmv"
                            _update_job(session, job, status=JobStatus.DISCOVERED, error_msg=None, discovered_source="1tamilmv", discovered_url=thread_url, discovered_magnet=magnet)
                            break
            except Exception as e:
                logger.error(f"1TamilMV search failed: {e}")

        elif source == "einthusan":
            watch_url = None
            found_lang = None
            for lang in langs_to_try:
                try:
                    url = await einthusan.search(title, year, lang)
                    if url:
                        watch_url = url
                        found_lang = lang
                        break
                except Exception as e:
                    logger.error(f"Einthusan search failed for '{title}' (lang={lang}): {e}")
                    continue

            if watch_url:
                _update_job(session, job, einthusan_url=watch_url, language=found_lang)
            else:
                log_action("search_failed", f"Einthusan search returned no match for '{title}' (langs={langs_to_try})", tmdb_id=tmdb_id, job_id=job_id)

            if watch_url:
                try:
                    direct_url = await einthusan.extract_mp4_url(watch_url)
                    if direct_url:
                        if auto_download:
                            _update_job(session, job, direct_url=direct_url)
                            folder_path = await radarr.get_movie_folder(tmdb_id, title, year or 0, settings, movie=arr_movie)
                            file_path = get_movie_file_path(folder_path, title, year, radarr_resolution or "720p")

                            _update_job(session, job, file_path=file_path, status=JobStatus.DOWNLOADING, source_indexer="einthusan", error_msg=None)
                            dl_success = await download_movie(job_id, direct_url, file_path, session)
                            if dl_success:
                                success_source = "einthusan"
                                await _rescan_movie(arr_movie_id, settings, title)
                                _update_job(session, job, status=JobStatus.DONE, progress_pct=100, file_path=file_path, error_msg=None)
                                break
                        else:
                            success_source = "einthusan"
                            _update_job(session, job, status=JobStatus.DISCOVERED, error_msg=None, discovered_source="einthusan", discovered_url=watch_url, direct_url=direct_url)
                            break
                except Exception as e:
                    logger.error(f"Einthusan download failed: {e}")

        elif source == "fmovies":
            try:
                watch_url = await fmovies.search_movie(tmdb_id, title, year, settings)
                if watch_url:
                    if auto_download:
                        extracted = await fmovies.extract_stream_url(watch_url, settings, radarr_resolution)
                        if extracted:
                            m3u8_url, referer, u_a = extracted
                            folder_path = await radarr.get_movie_folder(tmdb_id, title, year or 0, settings, movie=arr_movie)
                            file_path = get_movie_file_path(folder_path, title, year, radarr_resolution or "720p")

                            _update_job(session, job, status=JobStatus.DOWNLOADING, source_indexer="fmovies", error_msg=None)
                            dl_success = await download_m3u8(job_id, m3u8_url, referer, file_path, session)
                            if dl_success:
                                success_source = "fmovies"
                                await _rescan_movie(arr_movie_id, settings, title)
                                _update_job(session, job, status=JobStatus.DONE, progress_pct=100, file_path=file_path, error_msg=None)
                                break
                    else:
                        success_source = "fmovies"
                        _update_job(session, job, status=JobStatus.DISCOVERED, error_msg=None, discovered_source="fmovies", discovered_url=watch_url)
                        break
            except Exception as e:
                logger.error(f"FMovies search/download failed: {e}")

    if not success_source:
        msg = f"'{title}' not found on all configured sources ({', '.join(sources)})"
        _update_job(session, job, status=JobStatus.NOT_FOUND, error_msg=msg)


async def _run_tv_pipeline(session: Session, job: DownloadJob, settings: AppSettings, auto_download: bool, indexer: Optional[str], fallback_from: Optional[str], skip_release_check: bool):
    tvdb_id = job.tvdb_id
    title = job.title
    job_id = job.id

    try:
        series = await sonarr.ensure_series_added(tvdb_id, job.title, settings)
        series_id = series["id"]

        ep = await sonarr.get_episode(series_id, job.season_number, job.episode_number, settings)
        if not ep:
            _update_job(session, job, status=JobStatus.FAILED, error_msg="Episode not found in Sonarr")
            return

        if ep.get("hasFile") and not indexer:
            _update_job(session, job, status=JobStatus.DONE, progress_pct=100, error_msg=None, has_file=True, in_arr=True)
            return

        if not indexer:
            queue_item = await sonarr.get_episode_queue_status(ep["id"], settings)
            if queue_item:
                tracked = (queue_item.get("trackedDownloadStatus") or "").lower()
                q_status = (queue_item.get("status") or "").lower()
                if tracked not in ("warning", "error") and q_status != "completed":
                    _update_job(session, job, status=JobStatus.DOWNLOADING, source_indexer="sonarr", error_msg=None)
                    return
    except Exception as e:
        _update_job(session, job, status=JobStatus.FAILED, error_msg=f"Sonarr check failed: {e}")
        return

    # Release Check for TV Shows
    air_date_utc = ep.get("airDateUtc")
    if air_date_utc:
        try:
            air_dt = datetime.fromisoformat(air_date_utc.replace("Z", "+00:00"))

            # Update the release date
            new_release = air_dt.replace(tzinfo=None)
            if job.release_date != new_release:
                _update_job(session, job, release_date=new_release)

            if datetime.now(timezone.utc) < air_dt and not indexer and not skip_release_check:
                msg = f"Episode has not aired yet (airs {air_dt.strftime('%Y-%m-%d %H:%M UTC')})"
                log_action(action="search_skipped", message=f"'{title}' skipped: {msg}", tvdb_id=tvdb_id, job_id=job_id)
                _update_job(session, job, status=JobStatus.SKIPPED, error_msg=msg)
                return
        except Exception as e:
            logger.warning(f"Failed to parse airDateUtc '{air_date_utc}': {e}")

    _update_job(session, job, status=JobStatus.SEARCHING)
    sources = _ordered_sources(settings.tv_download_sources_priority, ["1tamilmv", "bollyzone", "fmovies"], indexer, fallback_from)

    if not sources:
        _update_job(session, job, status=JobStatus.NOT_FOUND, error_msg="Exhausted all download sources.")
        return

    sonarr_resolution = await sonarr.get_quality_profile_resolution(settings.sonarr_quality_profile_id, settings)
    series_title = series.get("title", "")
    # vidlink (FMovies) is keyed by TMDB id; Sonarr reports it on the series.
    series_tmdb_id = series.get("tmdbId")

    success_source = None
    for source in sources:
        if source == "1tamilmv":
            try:
                domain = await tamilmv.get_current_domain()
                thread_url = await tamilmv.search_movie(job.title, 0, domain, ["tamil", "malayalam", "telugu"], sonarr_resolution)
                if thread_url:
                    magnet = await tamilmv.extract_magnet(thread_url)
                    if magnet:
                        if auto_download:
                            torrent_hash = await asyncio.to_thread(qbittorrent.add_magnet_to_qbittorrent, magnet, settings, is_tv=True)
                            if torrent_hash:
                                success_source = "1tamilmv"
                                _update_job(session, job, status=JobStatus.DOWNLOADING, error_msg=None, source_indexer="1tamilmv", torrent_hash=torrent_hash)
                                break
                        else:
                            success_source = "1tamilmv"
                            _update_job(session, job, status=JobStatus.DISCOVERED, error_msg=None, discovered_source="1tamilmv", discovered_url=thread_url, discovered_magnet=magnet)
                            break
            except Exception as e:
                logger.error(f"1TamilMV TV search failed: {e}")

        elif source == "bollyzone":
            try:
                # Air date comes from the Sonarr episode, falling back to the stored release date.
                air_date = ep.get("airDate")  # YYYY-MM-DD
                if not air_date and job.release_date:
                    air_date = job.release_date.strftime("%Y-%m-%d")

                episode_url = await bollyzone.search_series(series_title, air_date, job.season_number, job.episode_number)
                if episode_url:
                    if auto_download:
                        extracted = await bollyzone.extract_url(episode_url)
                        if extracted:
                            m3u8_url, referer, u_a = extracted
                            folder_path = await sonarr.get_series_folder(tvdb_id, series_title, settings)
                            file_path = get_episode_file_path(folder_path, series_title, job.season_number, job.episode_number, sonarr_resolution or "720p")

                            _update_job(session, job, status=JobStatus.DOWNLOADING, source_indexer="bollyzone", error_msg=None, discovered_url=episode_url)
                            dl_success = await download_m3u8(job_id, m3u8_url, referer, file_path, session)
                            if dl_success:
                                success_source = "bollyzone"
                                await _rescan_series(series_id, settings, title)
                                _update_job(session, job, status=JobStatus.DONE, progress_pct=100, file_path=file_path, error_msg=None)
                                break
                    else:
                        success_source = "bollyzone"
                        _update_job(session, job, status=JobStatus.DISCOVERED, error_msg=None, discovered_source="bollyzone", discovered_url=episode_url)
                        break
            except Exception as e:
                logger.error(f"Bollyzone search failed: {e}")

        elif source == "fmovies":
            try:
                if not series_tmdb_id:
                    logger.info(f"FMovies skipped for '{title}': Sonarr has no TMDB id for the series.")
                    continue
                watch_url = await fmovies.search_tv(series_tmdb_id, series_title, job.season_number, job.episode_number, settings)
                if watch_url:
                    if auto_download:
                        extracted = await fmovies.extract_stream_url(watch_url, settings, sonarr_resolution)
                        if extracted:
                            m3u8_url, referer, u_a = extracted
                            folder_path = await sonarr.get_series_folder(tvdb_id, series_title, settings)
                            file_path = get_episode_file_path(folder_path, series_title, job.season_number, job.episode_number, sonarr_resolution or "720p")

                            _update_job(session, job, status=JobStatus.DOWNLOADING, source_indexer="fmovies", error_msg=None, discovered_url=watch_url)
                            dl_success = await download_m3u8(job_id, m3u8_url, referer, file_path, session)
                            if dl_success:
                                success_source = "fmovies"
                                await _rescan_series(series_id, settings, title)
                                _update_job(session, job, status=JobStatus.DONE, progress_pct=100, file_path=file_path, error_msg=None)
                                break
                    else:
                        success_source = "fmovies"
                        _update_job(session, job, status=JobStatus.DISCOVERED, error_msg=None, discovered_source="fmovies", discovered_url=watch_url)
                        break
            except Exception as e:
                logger.error(f"FMovies TV search/download failed: {e}")

    if not success_source:
        msg = f"'{title}' not found on all configured sources ({', '.join(sources)})"
        _update_job(session, job, status=JobStatus.NOT_FOUND, error_msg=msg)


async def _rescan_series(series_id: Optional[int], settings: AppSettings, title: str):
    if not series_id:
        return
    try:
        await sonarr.trigger_rescan(series_id, settings)
    except Exception as e:
        logger.warning(f"Sonarr rescan failed for '{title}' (the file is on disk; Sonarr will pick it up on its next scan): {e}")


# ── Manual / discovered downloads (used by the jobs router) ───────────────────

async def run_movie_file_download(job_id: int, direct_url: str, file_path: str, settings: AppSettings):
    """Background task: download an MP4, then tell Radarr and mark the job DONE."""
    with Session(engine) as sess:
        if not await download_movie(job_id, direct_url, file_path, sess):
            return
        job = sess.get(DownloadJob, job_id)
        if not job:
            return
        movie = await radarr.is_movie_in_radarr(job.tmdb_id, settings)
        await _rescan_movie(movie.get("id") if movie else None, settings, job.title)
        _update_job(sess, job, status=JobStatus.DONE, progress_pct=100, error_msg=None)


async def run_stream_download(job_id: int, m3u8_url: str, referer: str, file_path: str, settings: AppSettings):
    """Background task: download an HLS stream, then tell Radarr/Sonarr and mark the job DONE."""
    with Session(engine) as sess:
        if not await download_m3u8(job_id, m3u8_url, referer, file_path, sess):
            return
        job = sess.get(DownloadJob, job_id)
        if not job:
            return
        if job.media_type == "tv":
            series = await sonarr.is_series_in_sonarr(job.tvdb_id, settings)
            await _rescan_series(series.get("id") if series else None, settings, job.title)
        else:
            movie = await radarr.is_movie_in_radarr(job.tmdb_id, settings)
            await _rescan_movie(movie.get("id") if movie else None, settings, job.title)
        _update_job(sess, job, status=JobStatus.DONE, progress_pct=100, error_msg=None)
