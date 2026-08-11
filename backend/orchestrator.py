import asyncio
import logging
from datetime import datetime
from typing import Optional

from sqlmodel import Session, select

logger = logging.getLogger(__name__)

from backend import config
from backend.database import engine, get_settings
from backend.models import DownloadJob, JobStatus, AppSettings, LogLevel
from backend.services import einthusan, radarr, tmdb, tamilmv, qbittorrent, sonarr, bollyzone
from backend.services.downloader import download_movie, download_m3u8, get_movie_file_path
from backend.db_logger import log_action

_job_locks = {}

def _update_job(session: Session, job: DownloadJob, **kwargs):
    for k, v in kwargs.items():
        setattr(job, k, v)
    job.updated_at = datetime.utcnow()
    session.add(job)
    session.commit()
    session.refresh(job)


async def process_request(job_id: int, auto_download: bool = True, indexer: Optional[str] = None, fallback_from: Optional[str] = None, skip_release_check: bool = False) -> int:
    """
    Main entry point. Runs the full pipeline for a specific job.
    Returns the job_id.
    """
    if job_id not in _job_locks:
        _job_locks[job_id] = asyncio.Lock()
        
    async with _job_locks[job_id]:
        with Session(engine) as session:
            job = session.get(DownloadJob, job_id)
            if not job:
                return job_id
                
            if job.status not in (JobStatus.DOWNLOADING, JobStatus.DONE, JobStatus.IMPORTING):
                job.status = JobStatus.SEARCHING
                session.add(job)
                session.commit()
                session.refresh(job)
                
            log_action("Orchestrator", f"Pipeline started for '{job.title}' (job_id={job_id}, indexer={indexer or 'all'}, fallback_from={fallback_from})", tmdb_id=job.tmdb_id, tvdb_id=job.tvdb_id, job_id=job_id)

        # Run the async pipeline in a background task
        asyncio.create_task(
            _run_pipeline(job_id, auto_download, indexer, fallback_from, skip_release_check)
        )
        return job_id


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
        if job.status in (JobStatus.DOWNLOADING, JobStatus.DONE, JobStatus.IMPORTING):
            logger.info(f"Job '{job.title}' is already in status '{job.status}' — skipping re-trigger.")
            return

        if job.media_type == "movie":
            await _run_movie_pipeline(session, job, settings, auto_download, indexer, fallback_from, skip_release_check)
        elif job.media_type == "tv":
            await _run_tv_pipeline(session, job, settings, auto_download, indexer, fallback_from, skip_release_check)


async def _run_movie_pipeline(session: Session, job: DownloadJob, settings: AppSettings, auto_download: bool, indexer: Optional[str], fallback_from: Optional[str], skip_release_check: bool):
    tmdb_id = job.tmdb_id
    title = job.title
    year = job.year
    job_id = job.id

    try:
        available = await radarr.is_movie_available(tmdb_id, settings)
    except Exception as e:
        _update_job(session, job, status=JobStatus.FAILED, error_msg=f"Radarr check failed: {e}")
        return

    if available and not indexer:
        logger.info(f"Radarr already has '{title}' — marking DONE, unmonitoring.")
        _update_job(session, job, status=JobStatus.DONE, monitored=False, progress_pct=100, error_msg=None)
        return

    if not indexer:
        try:
            radarr_movie_data = await radarr.is_movie_in_radarr(tmdb_id, settings)
            if radarr_movie_data and "id" in radarr_movie_data:
                queue_item = await radarr.get_movie_queue_status(radarr_movie_data["id"], settings)
                if queue_item:
                    tracked = queue_item.get("trackedDownloadStatus", "").lower()
                    q_status = queue_item.get("status", "").lower()
                    if tracked not in ("warning", "error") and q_status != "completed":
                        _update_job(session, job, status=JobStatus.DOWNLOADING, source_indexer="radarr", error_msg=None)
                        return
        except Exception as e:
            logger.warning(f"Failed to check Radarr queue for active downloads: {e}")

    try:
        passed, release_msg = await tmdb.has_digital_release_passed(tmdb_id, settings)
    except Exception as e:
        _update_job(session, job, status=JobStatus.FAILED, error_msg=f"TMDB date check failed: {e}")
        return

    if not passed and not indexer and not skip_release_check:
        log_action(action="search_skipped", message=f"'{title}' skipped: {release_msg}", tmdb_id=tmdb_id, job_id=job_id)
        _update_job(session, job, status=JobStatus.SKIPPED, error_msg=release_msg)
        return

    langs_to_try = []
    einthusan_languages = [l.strip() for l in settings.einthusan_languages_str.split(",") if l.strip()]
    if job.language and job.language in config.LANGUAGE_SLUG_MAP:
        langs_to_try = [job.language]
    else:
        # Wait, the job.language was set on webhook. If not set, maybe it's missing.
        # Fallback to fetching it
        try:
            movie = await tmdb.get_movie_details(tmdb_id, settings)
            original_lang_code = movie.get("original_language", "")
            mapped = config.TMDB_LANG_TO_EINTHUSAN.get(original_lang_code)
            if mapped and mapped in einthusan_languages:
                langs_to_try = [mapped]
        except:
            pass
            
    if not langs_to_try:
        _update_job(session, job, status=JobStatus.SKIPPED, error_msg=f"Language not in configured languages")
        return

    try:
        await radarr.ensure_movie_added(tmdb_id, title, year or 0, settings)
    except Exception as e:
        _update_job(session, job, status=JobStatus.FAILED, error_msg=f"Radarr add failed: {e}")
        return
        
    radarr_resolution = None
    try:
        radarr_resolution = await radarr.get_quality_profile_resolution(settings.radarr_quality_profile_id, settings)
    except Exception:
        pass

    _update_job(session, job, status=JobStatus.SEARCHING)
    sources = [s.strip() for s in settings.movie_download_sources_priority.split(",") if s.strip()]
    if not sources: sources = ["einthusan", "1tamilmv"]
        
    if indexer:
        sources = [indexer]
    elif fallback_from:
        try:
            sources = sources[sources.index(fallback_from)+1:]
        except ValueError:
            pass
            
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
                except: continue

            if watch_url:
                _update_job(session, job, einthusan_url=watch_url, language=found_lang)
                try:
                    direct_url = await einthusan.extract_mp4_url(watch_url)
                    if direct_url:
                        if auto_download:
                            _update_job(session, job, direct_url=direct_url)
                            folder_path = await radarr.get_movie_folder(tmdb_id, title, year or 0, settings)
                            file_path = get_movie_file_path(folder_path, title, year)
                            
                            _update_job(session, job, file_path=file_path, status=JobStatus.DOWNLOADING, source_indexer="einthusan", error_msg=None)
                            dl_success = await download_movie(job_id, direct_url, file_path, session)
                            if dl_success:
                                success_source = "einthusan"
                                movie_data = await radarr.is_movie_in_radarr(tmdb_id, settings)
                                if movie_data and "id" in movie_data:
                                    await radarr.trigger_rescan(movie_data["id"], settings)
                                _update_job(session, job, status=JobStatus.DONE, progress_pct=100, monitored=False, file_path=file_path, error_msg=None)
                                break
                        else:
                            success_source = "einthusan"
                            _update_job(session, job, status=JobStatus.DISCOVERED, error_msg=None, discovered_source="einthusan", discovered_url=watch_url, direct_url=direct_url)
                            break
                except Exception as e:
                    logger.error(f"Einthusan download failed: {e}")

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
            _update_job(session, job, status=JobStatus.DONE, monitored=False, progress_pct=100, error_msg=None)
            return

        if not indexer:
            queue_item = await sonarr.get_episode_queue_status(ep["id"], settings)
            if queue_item:
                tracked = queue_item.get("trackedDownloadStatus", "").lower()
                q_status = queue_item.get("status", "").lower()
                if tracked not in ("warning", "error") and q_status != "completed":
                    _update_job(session, job, status=JobStatus.DOWNLOADING, source_indexer="sonarr", error_msg=None)
                    return
    except Exception as e:
        _update_job(session, job, status=JobStatus.FAILED, error_msg=f"Sonarr check failed: {e}")
        return

    _update_job(session, job, status=JobStatus.SEARCHING)
    sources = [s.strip() for s in settings.tv_download_sources_priority.split(",") if s.strip()]
    if not sources: sources = ["1tamilmv", "bollyzone"]
        
    if indexer:
        sources = [indexer]
    elif fallback_from:
        try:
            sources = sources[sources.index(fallback_from)+1:]
        except ValueError:
            pass
            
    if not sources:
        _update_job(session, job, status=JobStatus.NOT_FOUND, error_msg="Exhausted all download sources.")
        return
        
    sonarr_resolution = None
    try:
        sonarr_resolution = await sonarr.get_quality_profile_resolution(settings.sonarr_quality_profile_id, settings)
    except:
        pass

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
                # We need the air_date of the episode. We can get it from TMDB if tmdb_id exists, or from Sonarr episode data directly!
                air_date = ep.get("airDate") # YYYY-MM-DD
                
                episode_url = await bollyzone.search_series(series.get("title", ""), air_date, job.season_number, job.episode_number)
                if episode_url:
                    if auto_download:
                        extracted = await bollyzone.extract_url(episode_url)
                        if extracted:
                            m3u8_url, referer, u_a = extracted
                            folder_path = await sonarr.get_series_folder(tvdb_id, series.get("title", ""), settings)
                            # Format for sonarr: Show Name - S01E01 - 720p.mp4
                            safe_title = "".join(c for c in series.get("title", "") if c.isalnum() or c in " -_.").strip()
                            file_path = f"{folder_path}/{safe_title} - S{job.season_number:02d}E{job.episode_number:02d} - {sonarr_resolution or '720p'}.mp4"
                            
                            _update_job(session, job, status=JobStatus.DOWNLOADING, source_indexer="bollyzone", error_msg=None, discovered_url=episode_url)
                            dl_success = await download_m3u8(job_id, m3u8_url, referer, file_path, session)
                            if dl_success:
                                success_source = "bollyzone"
                                await sonarr.trigger_rescan(series_id, settings)
                                _update_job(session, job, status=JobStatus.DONE, progress_pct=100, monitored=False, file_path=file_path, error_msg=None)
                                break
                    else:
                        success_source = "bollyzone"
                        _update_job(session, job, status=JobStatus.DISCOVERED, error_msg=None, discovered_source="bollyzone", discovered_url=episode_url)
                        break
            except Exception as e:
                logger.error(f"Bollyzone search failed: {e}")

    if not success_source:
        msg = f"'{title}' not found on all configured sources ({', '.join(sources)})"
        _update_job(session, job, status=JobStatus.NOT_FOUND, error_msg=msg)
