"""
Background synchronisation with Radarr / Sonarr / qBittorrent.

* active_job_tracker_loop  (5s)  progress + completion of downloads we or the *arr own
* radarr_state_sync_loop   (60s) full Radarr -> local reconciliation
* sonarr_state_sync_loop   (60s) full Sonarr -> local reconciliation
* discovery_tracker_loop   (h)   periodically retries missing/failed jobs

All state decisions are made by `services.reconcile.reconcile_job`; this module only
fetches data, applies the result, commits and triggers fallback searches.
"""
import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import update
from sqlmodel import Session, select

from backend import config
from backend.database import engine, get_settings
from backend.db_logger import log_action
from backend.models import AppSettings, DownloadJob, JobStatus
from backend.orchestrator import process_request, process_many, is_pipeline_running
from backend.services import radarr, qbittorrent, sonarr
from backend.services.qbittorrent import QbittorrentError, NO_METADATA
from backend.services.reconcile import (
    ReconcileResult, queue_health, reconcile_job,
)
from backend.services.downloader import is_direct_download_active

logger = logging.getLogger(__name__)

DIRECT_SOURCES = ("einthusan", "fmovies", "bollyzone")

# ── Sync health (exposed to the UI) ───────────────────────────────────────────

sync_status: Dict[str, Dict[str, Any]] = {
    "radarr": {"ok": None, "last_success": None, "error": None},
    "sonarr": {"ok": None, "last_success": None, "error": None},
}


def _record_sync(kind: str, error: Optional[str] = None) -> None:
    st = sync_status[kind]
    if error is None:
        st.update(ok=True, last_success=datetime.utcnow().isoformat() + "Z", error=None)
    else:
        st.update(ok=False, error=error)


def get_sync_status() -> Dict[str, Dict[str, Any]]:
    return sync_status


class SyncError(Exception):
    """A manual sync could not complete (e.g. Radarr unreachable). Carries an HTTP status."""

    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


# ── Small helpers ─────────────────────────────────────────────────────────────

def auto_search_enabled(settings: AppSettings, media_type: str) -> bool:
    return bool(settings.enable_sonarr_auto_search if media_type == "tv" else settings.enable_radarr_auto_search)


def configured_languages(settings: AppSettings) -> List[str]:
    return [l.strip().lower() for l in settings.einthusan_languages_str.split(",")
            if l.strip().lower() in config.LANGUAGE_SLUG_MAP]


def _poster_from_images(images) -> Optional[str]:
    for img in images or []:
        if img.get("coverType") == "poster":
            remote = img.get("remoteUrl", "")
            if remote and "tmdb.org" in remote:
                return "/" + remote.split("/")[-1]
            break
    return None


def _movie_language(movie: Dict[str, Any]) -> str:
    return ((movie.get("originalLanguage") or {}).get("name") or "").lower()


def _parse_air_date(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def mark_synced(session: Session, job_ids: List[int], now: datetime) -> None:
    """Stamp last_synced_at / clear sync_error WITHOUT touching updated_at (which the grace
    periods and discovery ordering rely on)."""
    ids = [i for i in job_ids if i is not None]
    for i in range(0, len(ids), 500):
        session.execute(
            update(DownloadJob)
            .where(DownloadJob.id.in_(ids[i:i + 500]))
            .values(last_synced_at=now, sync_error=None, updated_at=DownloadJob.updated_at)
        )
    session.commit()


def mark_sync_error(media_type: str, message: str) -> None:
    """Flag every job of this media type as 'last sync failed' (idempotent, no updated_at bump)."""
    try:
        with Session(engine) as session:
            session.execute(
                update(DownloadJob)
                .where(DownloadJob.media_type == media_type)
                .where((DownloadJob.sync_error == None) | (DownloadJob.sync_error != message))  # noqa: E711
                .values(sync_error=message[:300], updated_at=DownloadJob.updated_at)
            )
            session.commit()
    except Exception as e:
        logger.error(f"Could not record sync error: {e}")


def _trigger_fallbacks(job_ids: List[int], media_type: str, settings: AppSettings) -> None:
    if not job_ids:
        return
    if not auto_search_enabled(settings, media_type):
        logger.info(f"Auto-search disabled — not searching custom sources for {len(job_ids)} job(s).")
        return
    asyncio.create_task(process_many(job_ids, auto_download=True))


async def _fetch_and_update_metadata(job_id: int):
    """Background task to fetch missing TMDB metadata (poster/year/lang) for a movie job."""
    from backend.services.tmdb import get_movie_details

    with Session(engine) as session:
        job = session.get(DownloadJob, job_id)
        if not job or job.media_type != "movie" or (job.poster_path and job.language and job.year):
            return
        settings = get_settings(session)
        if not settings.tmdb_api_key:
            return

        try:
            details = await get_movie_details(job.tmdb_id, settings)
            job.poster_path = job.poster_path or details.get("poster_path")
            job.year = job.year or details.get("year")

            if not job.language:
                tmdb_lang_code = details.get("original_language", "").lower()
                job.language = config.TMDB_LANG_TO_EINTHUSAN.get(tmdb_lang_code, tmdb_lang_code)

            session.add(job)
            session.commit()
        except Exception as e:
            logger.warning(f"Failed to fetch metadata for job {job_id}: {e}")


# ── Delayed search (webhook flow) ─────────────────────────────────────────────

async def delayed_search(tmdb_id: int, language: Optional[str] = None, override_delay: Optional[int] = None, force: bool = False):
    """Give Radarr `search_delay_seconds` to grab the movie itself; if it doesn't, search our sources.
    `force` bypasses the 'auto search' toggle (used for explicit user actions)."""
    with Session(engine) as session:
        settings = get_settings(session)
        delay = settings.search_delay_seconds if override_delay is None else override_delay

    waited = 0
    while True:
        with Session(engine) as session:
            settings = get_settings(session)
            job = session.exec(select(DownloadJob).where(
                DownloadJob.tmdb_id == tmdb_id, DownloadJob.media_type == "movie")).first()
            if not job or job.status != JobStatus.MOVIE_MISSING:
                return  # Already processing or deleted

            try:
                snapshot_at = datetime.utcnow()
                movies = await radarr.get_all_movies(settings, max_age=5)
                queue = await radarr.get_full_queue(settings, max_age=5)
                movie = next((m for m in movies if m.get("tmdbId") == tmdb_id), None)
                q = radarr.pick_queue_record(queue, "movieId", movie.get("id")) if movie else None
                if queue_health(q) == "healthy":
                    logger.info(f"Delayed search check: Radarr actively downloading '{job.title}' natively.")
                    reconcile_job(job, movie, q, source="radarr", snapshot_at=snapshot_at)
                    session.add(job)
                    session.commit()
                    return
            except Exception as e:
                logger.warning(f"Error checking Radarr queue in delayed search: {e}")

        if waited >= delay:
            break
        step = min(10, delay - waited)
        await asyncio.sleep(step)
        waited += step

    with Session(engine) as session:
        settings = get_settings(session)
        job = session.exec(select(DownloadJob).where(
            DownloadJob.tmdb_id == tmdb_id, DownloadJob.media_type == "movie")).first()
        if not job or job.status != JobStatus.MOVIE_MISSING:
            return
        if not force and not settings.enable_radarr_auto_search:
            logger.info(f"Auto-search disabled — not searching for '{job.title}'.")
            return
        job_id = job.id
    logger.info(f"Delayed search: no active Radarr download for tmdb_id={tmdb_id} after {delay}s. Triggering auto-download.")
    await process_request(job_id, auto_download=True)


# ── Snapshots + applying reconciliation ───────────────────────────────────────

@dataclass
class SyncStats:
    total: int = 0
    updated: int = 0
    deleted: int = 0
    created: int = 0
    changes: List[Dict[str, Any]] = field(default_factory=list)
    fallback_ids: List[int] = field(default_factory=list)
    new_job_ids: List[int] = field(default_factory=list)

    def note(self, job: DownloadJob, res: ReconcileResult) -> None:
        if res.changed:
            self.updated += 1
        if res.status_changed:
            if res.new_status == JobStatus.NOT_IN_RADARR:
                self.deleted += 1
            if len(self.changes) < 100:
                self.changes.append({
                    "id": job.id, "title": job.title,
                    "from": res.old_status.value if res.old_status else None,
                    "to": res.new_status.value if res.new_status else None,
                })
        if res.fallback:
            self.fallback_ids.append(job.id)

    def as_dict(self) -> Dict[str, Any]:
        return {"total": self.total, "updated": self.updated, "deleted": self.deleted,
                "created": self.created, "changes": self.changes}


async def fetch_radarr_snapshot(settings: AppSettings) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    movies = await radarr.get_all_movies(settings)
    queue = await radarr.get_full_queue(settings)
    return movies, queue


def apply_radarr_state(session: Session, movies, queue, settings: AppSettings, now: datetime,
                       snapshot_at: datetime, create_missing: bool = True,
                       jobs: Optional[List[DownloadJob]] = None) -> SyncStats:
    """Reconcile local movie jobs with a Radarr snapshot. Commits."""
    stats = SyncStats()
    by_tmdb = {m["tmdbId"]: m for m in movies if m.get("tmdbId")}
    all_jobs = jobs if jobs is not None else list(session.exec(
        select(DownloadJob).where(DownloadJob.media_type == "movie")).all())

    if create_missing and jobs is None:
        langs = configured_languages(settings)
        known = {j.tmdb_id for j in all_jobs if j.tmdb_id}
        for tmdb_id, movie in by_tmdb.items():
            # Catches movies added while we were offline / missed webhooks (regional, monitored, no file).
            if tmdb_id in known or not movie.get("monitored") or movie.get("hasFile"):
                continue
            lang = _movie_language(movie)
            if lang not in langs:
                continue
            new_job = DownloadJob(
                media_type="movie", tmdb_id=tmdb_id, title=movie.get("title", f"TMDB:{tmdb_id}"),
                year=movie.get("year"), language=lang, monitored=True,
                status=JobStatus.MOVIE_MISSING, poster_path=_poster_from_images(movie.get("images")),
                arr_id=movie.get("id"),
            )
            session.add(new_job)
            session.commit()
            session.refresh(new_job)
            all_jobs.append(new_job)
            stats.created += 1
            stats.new_job_ids.append(new_job.id)

    touched = []
    for job in all_jobs:
        if not job.tmdb_id:
            continue
        stats.total += 1
        movie = by_tmdb.get(job.tmdb_id)
        q = radarr.pick_queue_record(queue, "movieId", movie.get("id")) if movie else None
        res = reconcile_job(job, movie, q, source="radarr", now=now, snapshot_at=snapshot_at, skip_queue_grace=True)
        stats.note(job, res)
        if res.changed:
            session.add(job)
        touched.append(job.id)
    session.commit()
    mark_synced(session, touched, now)
    return stats


@dataclass
class SonarrSnapshot:
    series: List[Dict[str, Any]]
    queue: List[Dict[str, Any]]
    episodes: Dict[int, Dict[Tuple[int, int], Dict[str, Any]]]   # series_id -> {(season, ep): episode}
    failed_series: set = field(default_factory=set)               # series whose episodes could not be fetched


async def fetch_sonarr_snapshot(settings: AppSettings) -> SonarrSnapshot:
    series_list = await sonarr.get_all_series(settings)
    queue = await sonarr.get_full_queue(settings)
    snap = SonarrSnapshot(series_list, queue, {})
    sem = asyncio.Semaphore(5)

    async def one(series):
        sid = series.get("id")
        async with sem:
            try:
                eps = await sonarr.get_episodes(sid, settings)
                snap.episodes[sid] = {(e.get("seasonNumber"), e.get("episodeNumber")): e for e in eps}
            except Exception as e:
                logger.error(f"Failed to fetch episodes for series {series.get('tvdbId')}: {e}")
                snap.failed_series.add(sid)

    await asyncio.gather(*(one(s) for s in series_list if s.get("id")))
    return snap


def apply_sonarr_state(session: Session, snap: SonarrSnapshot, now: datetime, snapshot_at: datetime,
                       create_missing: bool = True, create_all: bool = False) -> SyncStats:
    """Reconcile local TV jobs with a Sonarr snapshot. Commits.
    `create_all` also creates jobs for episodes that already have a file (manual sync/import)."""
    stats = SyncStats()
    series_by_tvdb = {s["tvdbId"]: s for s in snap.series if s.get("tvdbId")}
    all_jobs = list(session.exec(select(DownloadJob).where(DownloadJob.media_type == "tv")).all())
    job_map = {(j.tvdb_id, j.season_number, j.episode_number): j for j in all_jobs if j.tvdb_id}

    if create_missing:
        for tvdb_id, series in series_by_tvdb.items():
            eps = snap.episodes.get(series.get("id"), {})
            poster = None
            for img in series.get("images", []):
                if img.get("coverType") == "poster":
                    poster = img.get("remoteUrl") or None
                    break
            for (s_num, e_num), ep in eps.items():
                if s_num is None or e_num is None:
                    continue
                has_file, monitored = bool(ep.get("hasFile")), bool(ep.get("monitored"))
                if (tvdb_id, s_num, e_num) in job_map:
                    continue
                if not (monitored and not has_file) and not (create_all and (monitored or has_file)):
                    continue
                job = DownloadJob(
                    media_type="tv", tmdb_id=0, tvdb_id=tvdb_id, season_number=s_num, episode_number=e_num,
                    title=f"{series.get('title', 'Unknown')} S{s_num:02d}E{e_num:02d}",
                    status=JobStatus.DONE if has_file else JobStatus.MOVIE_MISSING,
                    progress_pct=100 if has_file else 0, monitored=monitored, poster_path=poster,
                    release_date=_parse_air_date(ep.get("airDateUtc")), arr_id=ep.get("id"), has_file=has_file,
                )
                session.add(job)
                job_map[(tvdb_id, s_num, e_num)] = job
                all_jobs.append(job)
                stats.created += 1
        session.commit()

    touched = []
    for job in all_jobs:
        if not job.tvdb_id:
            continue
        series = series_by_tvdb.get(job.tvdb_id)
        if series is not None and series.get("id") in snap.failed_series:
            continue  # episode list unavailable: leave the job alone rather than guessing
        stats.total += 1
        ep = None
        if series is not None:
            ep = snap.episodes.get(series.get("id"), {}).get((job.season_number, job.episode_number))
        q = radarr.pick_queue_record(snap.queue, "episodeId", ep.get("id")) if ep else None
        res = reconcile_job(job, ep, q, source="sonarr", now=now, snapshot_at=snapshot_at, skip_queue_grace=True)
        if ep:
            air = _parse_air_date(ep.get("airDateUtc"))
            if air and job.release_date != air:
                job.release_date = air
                res.changed = True
        stats.note(job, res)
        if res.changed:
            session.add(job)
        touched.append(job.id)
    session.commit()
    mark_synced(session, touched, now)
    return stats


# ── Manual sync (called by the jobs router) ───────────────────────────────────

async def sync_all_movies() -> Dict[str, Any]:
    """Full Radarr reconciliation, awaited by the caller so the UI sees the result immediately."""
    with Session(engine) as session:
        settings = get_settings(session)
    if not settings.radarr_api_key:
        raise SyncError(400, "Radarr API key is not configured.")
    snapshot_at = datetime.utcnow()
    try:
        movies, queue = await fetch_radarr_snapshot(settings)
    except Exception as e:
        _record_sync("radarr", str(e))
        mark_sync_error("movie", f"Radarr unreachable: {e}")
        raise SyncError(502, f"Failed to fetch movies from Radarr: {e}")
    _record_sync("radarr")
    with Session(engine) as session:
        stats = apply_radarr_state(session, movies, queue, settings, datetime.utcnow(), snapshot_at)
    _trigger_fallbacks(stats.fallback_ids, "movie", settings)
    for jid in stats.new_job_ids:
        asyncio.create_task(_fetch_and_update_metadata(jid))
    if stats.updated or stats.created:
        log_action("Manual", f"Sync All: {stats.updated} jobs updated ({stats.deleted} no longer in Radarr), {stats.created} created.")
    return {"status": "success", **stats.as_dict()}


async def sync_all_sonarr() -> Dict[str, Any]:
    with Session(engine) as session:
        settings = get_settings(session)
    if not settings.sonarr_api_key:
        raise SyncError(400, "Sonarr API key is not configured.")
    snapshot_at = datetime.utcnow()
    try:
        snap = await fetch_sonarr_snapshot(settings)
    except Exception as e:
        _record_sync("sonarr", str(e))
        mark_sync_error("tv", f"Sonarr unreachable: {e}")
        raise SyncError(502, f"Failed to fetch series from Sonarr: {e}")
    _record_sync("sonarr")
    with Session(engine) as session:
        stats = apply_sonarr_state(session, snap, datetime.utcnow(), snapshot_at, create_all=True)
    _trigger_fallbacks(stats.fallback_ids, "tv", settings)
    if stats.updated or stats.created:
        log_action("Manual", f"Sync All Sonarr: {stats.updated} updated ({stats.deleted} no longer in Sonarr), {stats.created} newly imported.")
    return {"status": "success", **stats.as_dict(), "imported": stats.created}


async def sync_single_job(job_id: int) -> Dict[str, Any]:
    """Reconcile one job against live Radarr/Sonarr data."""
    with Session(engine) as session:
        job = session.get(DownloadJob, job_id)
        if not job:
            raise SyncError(404, "Job not found")
        settings = get_settings(session)
        media_type = job.media_type
        tmdb_id, tvdb_id, season, episode = job.tmdb_id, job.tvdb_id, job.season_number, job.episode_number

    snapshot_at = datetime.utcnow()
    try:
        if media_type == "tv":
            series = await sonarr.is_series_in_sonarr(tvdb_id, settings)
            ep = None
            if series:
                ep = await sonarr.get_episode(series["id"], season, episode, settings)
            queue = await sonarr.get_full_queue(settings)
            item, source, qkey = ep, "sonarr", "episodeId"
        else:
            movie = await radarr.is_movie_in_radarr(tmdb_id, settings)
            queue = await radarr.get_full_queue(settings)
            item, source, qkey = movie, "radarr", "movieId"
    except Exception as e:
        kind = "sonarr" if media_type == "tv" else "radarr"
        with Session(engine) as session:
            j = session.get(DownloadJob, job_id)
            if j:
                session.execute(update(DownloadJob).where(DownloadJob.id == job_id).values(
                    sync_error=f"{kind.title()} unreachable: {e}"[:300], updated_at=DownloadJob.updated_at))
                session.commit()
        raise SyncError(502, f"Failed to reach {kind.title()}: {e}")

    now = datetime.utcnow()
    with Session(engine) as session:
        job = session.get(DownloadJob, job_id)
        if not job:
            raise SyncError(404, "Job not found")
        q = radarr.pick_queue_record(queue, qkey, item.get("id")) if item else None
        res = reconcile_job(job, item, q, source=source, now=now, snapshot_at=snapshot_at, skip_queue_grace=True)
        if res.changed:
            session.add(job)
        session.commit()
        mark_synced(session, [job.id], now)
        session.refresh(job)
        log_action("Manual", f"Sync: '{job.title}' -> {job.status.value}" + (" (changed)" if res.changed else ""),
                   tmdb_id=job.tmdb_id, tvdb_id=job.tvdb_id, job_id=job.id)
        out = {"status": "synced", "job_id": job.id, "state": job.status.value, "changed": res.changed,
               "previous": res.old_status.value if res.old_status else None,
               "in_arr": job.in_arr, "monitored": job.monitored}
        fallback = [job.id] if res.fallback else []
    _trigger_fallbacks(fallback, media_type, settings)
    return out


async def import_radarr_movies() -> Dict[str, Any]:
    """Import every Radarr movie in a configured regional language (and heal existing ones)."""
    with Session(engine) as session:
        settings = get_settings(session)
    if not settings.radarr_api_key:
        raise SyncError(400, "Radarr API key is not configured.")
    try:
        movies = await radarr.get_all_movies(settings)
    except Exception as e:
        raise SyncError(502, f"Failed to fetch movies from Radarr: {e}")

    langs = configured_languages(settings)
    if not langs:
        raise SyncError(400, "No Einthusan languages configured in settings.")

    imported = deleted = 0
    to_trigger: List[int] = []
    with Session(engine) as session:
        # Remove jobs for languages that are no longer configured
        for job in session.exec(select(DownloadJob).where(DownloadJob.media_type == "movie")).all():
            if job.language and job.language.lower() not in langs:
                session.delete(job)
                deleted += 1
        session.commit()

        for movie in movies:
            lang = _movie_language(movie)
            tmdb_id = movie.get("tmdbId")
            if not tmdb_id or lang not in langs:
                continue
            poster_path = _poster_from_images(movie.get("images"))
            existing = session.exec(select(DownloadJob).where(
                DownloadJob.tmdb_id == tmdb_id, DownloadJob.media_type == "movie")).first()
            if existing:
                updated = False
                if not existing.poster_path and poster_path:
                    existing.poster_path = poster_path
                    updated = True
                if existing.language != lang:
                    existing.language = lang
                    updated = True
                if existing.status == JobStatus.PENDING and not movie.get("hasFile"):
                    existing.status = JobStatus.MOVIE_MISSING
                    updated = True
                if updated:
                    session.add(existing)
                    session.commit()
                    imported += 1
                    if existing.status == JobStatus.MOVIE_MISSING and existing.monitored:
                        to_trigger.append(existing.id)
                continue

            new_job = DownloadJob(
                media_type="movie", tmdb_id=tmdb_id, title=movie.get("title", "Unknown"), year=movie.get("year"),
                language=lang, monitored=bool(movie.get("monitored", True)),
                status=JobStatus.DONE if movie.get("hasFile") else JobStatus.MOVIE_MISSING,
                progress_pct=100 if movie.get("hasFile") else 0, poster_path=poster_path,
                arr_id=movie.get("id"), has_file=bool(movie.get("hasFile")),
            )
            session.add(new_job)
            session.commit()
            session.refresh(new_job)
            imported += 1
            if new_job.status == JobStatus.MOVIE_MISSING and new_job.monitored:
                to_trigger.append(new_job.id)

    if imported or deleted:
        log_action("Import", f"Manual Radarr import completed. Imported {imported}, Deleted {deleted}.")
    if to_trigger and settings.enable_radarr_auto_search:
        asyncio.create_task(process_many(to_trigger, auto_download=True))
    return {"status": "success", "imported": imported, "deleted": deleted}


async def import_sonarr_series() -> Dict[str, Any]:
    """Import every monitored/downloaded episode from Sonarr as a tracked job."""
    with Session(engine) as session:
        settings = get_settings(session)
    if not settings.sonarr_api_key:
        raise SyncError(400, "Sonarr API key is not configured.")
    snapshot_at = datetime.utcnow()
    try:
        snap = await fetch_sonarr_snapshot(settings)
    except Exception as e:
        raise SyncError(502, f"Failed to fetch series from Sonarr: {e}")

    with Session(engine) as session:
        before = {j.id for j in session.exec(select(DownloadJob).where(DownloadJob.media_type == "tv")).all()}
        stats = apply_sonarr_state(session, snap, datetime.utcnow(), snapshot_at, create_all=True)
        new_missing = [j.id for j in session.exec(select(DownloadJob).where(
            DownloadJob.media_type == "tv", DownloadJob.status == JobStatus.MOVIE_MISSING,
            DownloadJob.monitored == True)).all() if j.id not in before]  # noqa: E712
    if stats.created or stats.updated:
        log_action("Import", f"Manual Sonarr import completed. Imported/updated {stats.created + stats.updated} episodes.")
    if new_missing and settings.enable_sonarr_auto_search:
        asyncio.create_task(process_many(new_missing, auto_download=True))
    return {"status": "success", "imported": stats.created + stats.updated}


# ── Active job tracker ────────────────────────────────────────────────────────

_importing_since: Dict[int, datetime] = {}
_last_rescan: Dict[int, datetime] = {}
_filtered_torrents: set = set()
IMPORT_RESCAN_EVERY = timedelta(minutes=5)
IMPORT_TIMEOUT = timedelta(hours=2)
ORPHAN_GRACE = timedelta(minutes=2)
TORRENT_MISSING_GRACE = timedelta(seconds=60)
_ACTIVE_STATUSES = [JobStatus.DOWNLOADING, JobStatus.SEARCHING, JobStatus.IMPORTING]


class _ArrContext:
    """Lazily fetches Radarr/Sonarr data at most once per tracker cycle."""

    def __init__(self, settings: AppSettings):
        self.settings = settings
        self._movies: Optional[Dict[int, Dict[str, Any]]] = None
        self._movies_fresh = False
        self._rqueue: Optional[List[Dict[str, Any]]] = None
        self._series: Optional[Dict[int, Dict[str, Any]]] = None
        self._squeue: Optional[List[Dict[str, Any]]] = None
        self._eps: Dict[int, Dict[Tuple[int, int], Dict[str, Any]]] = {}

    async def movies(self, fresh: bool = False) -> Dict[int, Dict[str, Any]]:
        # The library list changes rarely, so a 30s-old copy is fine for progress tracking. Anything
        # that concludes "it vanished / has no file" must use fresh data to avoid false fallbacks.
        if self._movies is None or (fresh and not self._movies_fresh):
            data = await radarr.get_all_movies(self.settings, max_age=0 if fresh else 30)
            self._movies = {m["tmdbId"]: m for m in data if m.get("tmdbId")}
            self._movies_fresh = fresh or self._movies_fresh
        return self._movies

    async def radarr_queue(self, fresh: bool = False) -> List[Dict[str, Any]]:
        if self._rqueue is None or fresh:
            self._rqueue = await radarr.get_full_queue(self.settings)
        return self._rqueue

    async def series(self) -> Dict[int, Dict[str, Any]]:
        if self._series is None:
            self._series = {s["tvdbId"]: s for s in await sonarr.get_all_series(self.settings) if s.get("tvdbId")}
        return self._series

    async def sonarr_queue(self, fresh: bool = False) -> List[Dict[str, Any]]:
        if self._squeue is None or fresh:
            self._squeue = await sonarr.get_full_queue(self.settings)
        return self._squeue

    async def episodes(self, series_id: int) -> Dict[Tuple[int, int], Dict[str, Any]]:
        if series_id not in self._eps:
            eps = await sonarr.get_episodes(series_id, self.settings)
            self._eps[series_id] = {(e.get("seasonNumber"), e.get("episodeNumber")): e for e in eps}
        return self._eps[series_id]

    async def lookup(self, job: DownloadJob, fresh: bool = False):
        """(item, queue_record, source) for a job from Radarr/Sonarr."""
        if job.media_type == "tv":
            series = (await self.series()).get(job.tvdb_id)
            ep = (await self.episodes(series["id"])).get((job.season_number, job.episode_number)) if series else None
            q = radarr.pick_queue_record(await self.sonarr_queue(fresh=fresh), "episodeId", ep.get("id")) if ep else None
            return ep, q, "sonarr"
        movie = (await self.movies(fresh=fresh)).get(job.tmdb_id)
        q = radarr.pick_queue_record(await self.radarr_queue(fresh=fresh), "movieId", movie.get("id")) if movie else None
        return movie, q, "radarr"


def _fail_job(job: DownloadJob, message: str) -> None:
    job.status = JobStatus.FAILED
    job.error_msg = message
    job.torrent_hash = None
    job.progress_pct = 0
    job.eta_seconds = None


async def _track_native(session: Session, job: DownloadJob, ctx: _ArrContext, now: datetime, snapshot_at: datetime) -> ReconcileResult:
    """Radarr/Sonarr-owned download: mirror queue progress; detect completion, failure and deletion."""
    item, q, source = await ctx.lookup(job)
    # If queue item disappeared, do a fresh re-check to confirm it's truly gone.
    # If still gone after the fresh check, skip the QUEUE_GRACE: we know this was a real
    # download that was removed (not a new grab that hasn't appeared yet).
    skip_grace = False
    if q is None:
        item, q, source = await ctx.lookup(job, fresh=True)
        if q is None:
            skip_grace = True  # confirmed gone on fresh data
    res = reconcile_job(job, item, q, source=source, now=now, snapshot_at=snapshot_at, skip_queue_grace=skip_grace)
    if res.fallback:
        log_action("System", f"Radarr/Sonarr download for '{job.title}' failed or vanished ({'; '.join(res.notes)}). Triggering fallback search.",
                   tmdb_id=job.tmdb_id, tvdb_id=job.tvdb_id, job_id=job.id)
    return res


async def _track_importing(session: Session, job: DownloadJob, ctx: _ArrContext, settings: AppSettings,
                           now: datetime, snapshot_at: datetime) -> ReconcileResult:
    item, q, source = await ctx.lookup(job)
    res = reconcile_job(job, item, q, source=source, now=now, snapshot_at=snapshot_at)
    if job.status != JobStatus.IMPORTING:
        _importing_since.pop(job.id, None)
        _last_rescan.pop(job.id, None)
        return res

    since = _importing_since.setdefault(job.id, now)
    # Torrents we added are imported by Radarr/Sonarr's completed-download handling; nudge them with
    # a rescan now and then in case that missed it.
    if job.source_indexer not in ("radarr", "sonarr") and item is not None:
        last = _last_rescan.get(job.id)
        if last is None or now - last >= IMPORT_RESCAN_EVERY:
            _last_rescan[job.id] = now
            try:
                if job.media_type == "tv":
                    series = (await ctx.series()).get(job.tvdb_id)
                    if series:
                        await sonarr.trigger_rescan(series["id"], settings)
                elif item.get("id"):
                    await radarr.trigger_rescan(item["id"], settings)
            except Exception as e:
                logger.warning(f"Rescan for importing job '{job.title}' failed: {e}")

    if now - since > IMPORT_TIMEOUT:
        _fail_job(job, "Import was not detected by Radarr/Sonarr within 2 hours")
        res.changed = res.status_changed = True
        _importing_since.pop(job.id, None)
        _last_rescan.pop(job.id, None)
    return res


async def _track_torrent(session: Session, job: DownloadJob, ctx: _ArrContext, settings: AppSettings,
                         now: datetime) -> Optional[str]:
    """Track one qBittorrent download. Returns the source name to fall back from, if the torrent died."""
    age = (now - job.updated_at) if job.updated_at else timedelta(days=1)
    try:
        t_info = await asyncio.to_thread(qbittorrent.get_torrent_info, job.torrent_hash, settings)
    except QbittorrentError as e:
        logger.warning(f"qBittorrent unreachable, skipping torrent check for '{job.title}': {e}")
        return None  # an outage is not a removed torrent

    source = job.source_indexer

    def die(message: str, delete: bool) -> str:
        if delete:
            asyncio.get_running_loop().run_in_executor(None, qbittorrent.delete_torrent, job.torrent_hash, settings)
        _filtered_torrents.discard(job.id)
        _fail_job(job, message)
        return source

    if not t_info:
        if age < TORRENT_MISSING_GRACE:
            return None  # qBittorrent may not list a just-added magnet yet
        # Maybe Radarr/Sonarr grabbed it natively in the meantime.
        try:
            item, q, _ = await ctx.lookup(job, fresh=True)
        except Exception as e:
            logger.error(f"Failed to check Radarr/Sonarr queue for alternatives: {e}")
            item, q = None, None
        if queue_health(q) == "healthy":
            logger.info(f"Found native alternative for '{job.title}'. Handing over to Radarr/Sonarr.")
            job.status = JobStatus.MOVIE_MISSING
            job.source_indexer = None
            job.torrent_hash = None
            job.progress_pct = 0
            _filtered_torrents.discard(job.id)
            return None
        logger.info(f"No native alternative. Falling back from '{source}' for '{job.title}'.")
        return die(f"Torrent removed unexpectedly. Falling back from {source}", delete=False)

    state = (t_info.get("state") or "").lower()
    pct = int((t_info.get("progress") or 0) * 100)

    if state in ("error", "missingfiles"):
        logger.error(f"Torrent {job.torrent_hash} for '{job.title}' entered error state: {state}")
        return die(f"qBittorrent error state: {state}", delete=True)

    # Once the file list is known: keep only the video, reject torrents that are the wrong size.
    if job.id not in _filtered_torrents:
        ok, err = await asyncio.to_thread(
            qbittorrent.filter_torrent_files, job.torrent_hash, settings, job.media_type == "movie")
        if ok:
            _filtered_torrents.add(job.id)
        elif err != NO_METADATA:
            logger.warning(f"Rejecting torrent for '{job.title}': {err}")
            log_action("System", f"Rejected torrent for '{job.title}': {err}", tmdb_id=job.tmdb_id, tvdb_id=job.tvdb_id, job_id=job.id)
            return die(f"Torrent rejected: {err}", delete=True)

    eta = t_info.get("eta", 0) or 0
    job.eta_seconds = eta if 0 < eta < 8640000 else None
    job.total_bytes = t_info.get("size", 0) or 0
    job.downloaded_bytes = t_info.get("downloaded", 0) or 0
    job.progress_pct = pct

    hours = settings.auto_delete_failed_torrents_hours
    if hours and hours > 0 and pct < 100 and state in ("stalleddl", "metadl", "forcedmetadl") and age > timedelta(hours=hours):
        logger.warning(f"Torrent for '{job.title}' stalled for over {hours}h. Removing it.")
        return die(f"Torrent stalled for over {hours} hours", delete=True)

    if pct >= 100:
        logger.info(f"Torrent for '{job.title}' completed in qBittorrent. Waiting for Radarr/Sonarr import.")
        job.status = JobStatus.IMPORTING
        job.eta_seconds = None
        _importing_since[job.id] = now
        _filtered_torrents.discard(job.id)
        try:
            item, _, _ = await ctx.lookup(job)
            if job.media_type == "tv":
                series = (await ctx.series()).get(job.tvdb_id)
                if series:
                    await sonarr.trigger_rescan(series["id"], settings)
            elif item and item.get("id"):
                await radarr.trigger_rescan(item["id"], settings)
            _last_rescan[job.id] = now
        except Exception as e:
            logger.error(f"Failed to trigger rescan for '{job.title}': {e}")
    return None


async def _tracker_cycle(cycle: int) -> None:
    fallbacks: Dict[str, List[Tuple[int, Optional[str]]]] = {"movie": [], "tv": []}
    # Loaded in its own session: the working session below commits often, which would expire it.
    with Session(engine) as settings_session:
        settings = get_settings(settings_session)
    with Session(engine) as session:
        ctx = _ArrContext(settings)
        now = datetime.utcnow()
        snapshot_at = now
        active_jobs = session.exec(select(DownloadJob).where(DownloadJob.status.in_(_ACTIVE_STATUSES))).all()

        for job in active_jobs:
            try:
                fallback_from: Optional[str] = None
                fallback = False

                if job.status == JobStatus.SEARCHING:
                    age = now - (job.updated_at or now)
                    if not is_pipeline_running(job.id) and age > ORPHAN_GRACE:
                        job.status = JobStatus.MOVIE_MISSING
                        job.error_msg = "Search was interrupted"
                        session.add(job)
                        session.commit()
                    continue

                if job.status == JobStatus.IMPORTING:
                    res = await _track_importing(session, job, ctx, settings, now, snapshot_at)
                    fallback = res.fallback
                elif job.source_indexer in ("radarr", "sonarr"):
                    res = await _track_native(session, job, ctx, now, snapshot_at)
                    fallback = res.fallback
                elif job.torrent_hash:
                    fallback_from = await _track_torrent(session, job, ctx, settings, now)
                elif job.source_indexer in DIRECT_SOURCES:
                    age = now - (job.updated_at or now)
                    if not is_direct_download_active(job.id) and age > ORPHAN_GRACE:
                        _fail_job(job, "Download was interrupted")

                session.add(job)
                session.commit()
                if fallback:
                    fallbacks[job.media_type].append((job.id, None))
                if fallback_from:
                    fallbacks[job.media_type].append((job.id, fallback_from))
            except Exception as e:
                session.rollback()
                logger.error(f"Error tracking job {job.id} ('{job.title}'): {e}")

        # Pick up Radarr grabs we don't know about yet (webhook missed / grabbed manually). Every ~30s.
        if cycle % 6 == 0 and settings.radarr_api_key:
            try:
                queue = await ctx.radarr_queue()
                if queue:
                    movies = await ctx.movies()
                    by_id = {m["id"]: m for m in movies.values() if m.get("id") is not None}
                    candidates = {j.tmdb_id: j for j in session.exec(select(DownloadJob).where(
                        DownloadJob.media_type == "movie",
                        DownloadJob.status.notin_([JobStatus.DOWNLOADING, JobStatus.IMPORTING, JobStatus.SEARCHING, JobStatus.DONE]),
                    )).all() if j.tmdb_id}
                    for rec in queue:
                        movie = by_id.get(rec.get("movieId"))
                        job = candidates.get(movie.get("tmdbId")) if movie else None
                        if not job:
                            continue
                        res = reconcile_job(job, movie, radarr.pick_queue_record(queue, "movieId", movie["id"]),
                                            source="radarr", now=now, snapshot_at=snapshot_at)
                        if res.changed:
                            if res.new_status == JobStatus.DOWNLOADING:
                                log_action("System", f"Discovered Radarr native download for '{job.title}'. Tracking it.",
                                           tmdb_id=job.tmdb_id, job_id=job.id)
                                if not job.poster_path:
                                    asyncio.create_task(_fetch_and_update_metadata(job.id))
                            session.add(job)
                    session.commit()
            except Exception as e:
                session.rollback()
                logger.error(f"Error checking full Radarr queue: {e}")

    for media_type, items in fallbacks.items():
        for source in {src for _, src in items}:
            ids = [jid for jid, src in items if src == source]
            if source is None:
                _trigger_fallbacks(ids, media_type, settings)
            elif auto_search_enabled(settings, media_type):
                for jid in ids:
                    asyncio.create_task(process_request(jid, auto_download=True, fallback_from=source))


async def active_job_tracker_loop():
    """Tracks active downloads in qBittorrent AND the Radarr/Sonarr queues every 5 seconds."""
    logger.info("Starting active job tracker loop...")
    cycle = 0
    while True:
        try:
            await _tracker_cycle(cycle)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"Error in active_job_tracker_loop: {e}")
        cycle += 1
        await asyncio.sleep(5)


# ── Discovery ─────────────────────────────────────────────────────────────────

async def run_discovery_batch(batch_size: int, force: bool = False) -> int:
    """Start a batch of discovery searches and return how many jobs were triggered.

    Only monitored jobs are searched. New Release Grace Period: jobs whose release_date is within
    `new_release_grace_hours` are skipped so Radarr/Sonarr get first chance at a quality release.
    Unless `force`, the per-library auto-search toggles are respected."""
    with Session(engine) as session:
        settings = get_settings(session)
        now = datetime.utcnow()

        allowed = [mt for mt in ("movie", "tv") if force or auto_search_enabled(settings, mt)]
        if not allowed:
            return 0

        grace_hours = settings.new_release_grace_hours
        grace_cutoff = now - timedelta(hours=grace_hours) if grace_hours > 0 else None

        query = select(DownloadJob).where(
            DownloadJob.status.in_([JobStatus.MOVIE_MISSING, JobStatus.SKIPPED, JobStatus.NOT_FOUND, JobStatus.FAILED]),
            DownloadJob.monitored == True,  # noqa: E712
            DownloadJob.media_type.in_(allowed),
        )
        if grace_cutoff:
            query = query.where((DownloadJob.release_date == None) | (DownloadJob.release_date <= grace_cutoff))  # noqa: E711
        jobs = list(session.exec(query.order_by(DownloadJob.updated_at.asc()).limit(batch_size)).all())

        strict_ids, relaxed_ids = [], []
        for job in jobs:
            job.updated_at = now  # goes to the back of the queue
            session.add(job)
            # SKIPPED (release date not passed) and NOT_FOUND (source search failed) bypass the digital
            # release gate: regional titles often lack a TMDB digital date but exist on the sources.
            (relaxed_ids if job.status in (JobStatus.SKIPPED, JobStatus.NOT_FOUND) else strict_ids).append(job.id)
        session.commit()

    if jobs:
        log_action("Discovery", f"Triggering discovery search for {len(jobs)} jobs (grace period: {grace_hours}h)")
        if strict_ids:
            asyncio.create_task(process_many(strict_ids, auto_download=True))
        if relaxed_ids:
            asyncio.create_task(process_many(relaxed_ids, auto_download=True, skip_release_check=True))
    return len(jobs)


async def discovery_tracker_loop():
    """Periodically retries searching for missing / failed jobs."""
    logger.info("Starting discovery tracker loop...")
    while True:
        try:
            with Session(engine) as session:
                settings = get_settings(session)
                interval = settings.missing_search_interval_hours
                batch_size = settings.missing_search_batch_size

            if interval > 0:
                await run_discovery_batch(batch_size)

            await asyncio.sleep((interval * 3600) if interval > 0 else 86400)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"Error in discovery_tracker_loop: {e}")
            await asyncio.sleep(3600)


# ── State sync loops ──────────────────────────────────────────────────────────

async def radarr_state_sync_once() -> Optional[SyncStats]:
    with Session(engine) as session:
        settings = get_settings(session)
    if not settings.radarr_api_key:
        return None
    snapshot_at = datetime.utcnow()
    try:
        movies, queue = await fetch_radarr_snapshot(settings)
    except Exception as e:
        _record_sync("radarr", str(e))
        mark_sync_error("movie", f"Radarr unreachable: {e}")
        raise
    _record_sync("radarr")
    with Session(engine) as session:
        stats = apply_radarr_state(session, movies, queue, settings, datetime.utcnow(), snapshot_at)
    for jid in stats.new_job_ids:
        asyncio.create_task(_fetch_and_update_metadata(jid))
    _trigger_fallbacks(stats.fallback_ids, "movie", settings)
    if stats.created or stats.deleted or any(c["to"] in ("done", "movie_missing") for c in stats.changes):
        logger.info(f"Radarr state sync: {stats.created} added, {stats.deleted} removed, {stats.updated} updated.")
    return stats


async def radarr_state_sync_loop():
    """Every 60s: full reconciliation of local movie jobs with Radarr (Radarr is the source of truth)."""
    logger.info("Starting full radarr state sync loop...")
    while True:
        try:
            await radarr_state_sync_once()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"Error in radarr_state_sync_loop: {e}")
        await asyncio.sleep(60)


async def sonarr_state_sync_once() -> Optional[SyncStats]:
    with Session(engine) as session:
        settings = get_settings(session)
    if not settings.sonarr_api_key:
        return None
    snapshot_at = datetime.utcnow()
    try:
        snap = await fetch_sonarr_snapshot(settings)
    except Exception as e:
        _record_sync("sonarr", str(e))
        mark_sync_error("tv", f"Sonarr unreachable: {e}")
        raise
    _record_sync("sonarr")
    with Session(engine) as session:
        stats = apply_sonarr_state(session, snap, datetime.utcnow(), snapshot_at)
    _trigger_fallbacks(stats.fallback_ids, "tv", settings)
    if stats.created or stats.deleted:
        logger.info(f"Sonarr state sync: {stats.created} episodes added, {stats.deleted} removed, {stats.updated} updated.")
    return stats


async def sonarr_state_sync_loop():
    """Every 60s: full reconciliation of local TV jobs with Sonarr."""
    logger.info("Starting full sonarr state sync loop...")
    while True:
        try:
            await sonarr_state_sync_once()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"Error in sonarr_state_sync_loop: {e}")
        await asyncio.sleep(60)


# ── Startup recovery ──────────────────────────────────────────────────────────

def recover_orphaned_jobs() -> Dict[str, int]:
    """Run once at startup. Nothing is running yet, so any job still 'searching' or downloading
    through one of our own direct downloads was interrupted by the restart."""
    searching = interrupted = parts = 0
    with Session(engine) as session:
        for job in session.exec(select(DownloadJob).where(DownloadJob.status == JobStatus.SEARCHING)).all():
            job.status = JobStatus.MOVIE_MISSING
            job.error_msg = "Search was interrupted by a restart"
            session.add(job)
            searching += 1
        for job in session.exec(select(DownloadJob).where(DownloadJob.status == JobStatus.DOWNLOADING)).all():
            if job.torrent_hash or job.source_indexer in ("radarr", "sonarr", None):
                continue
            job.status = JobStatus.FAILED
            job.error_msg = "Download was interrupted by a restart"
            job.progress_pct = 0
            session.add(job)
            interrupted += 1
            if job.file_path and os.path.exists(job.file_path + ".part"):
                try:
                    os.remove(job.file_path + ".part")
                    parts += 1
                except OSError as e:
                    logger.warning(f"Could not remove partial file {job.file_path}.part: {e}")
        session.commit()
    if searching or interrupted:
        logger.info(f"Startup recovery: reset {searching} searching and {interrupted} interrupted jobs ({parts} partial files removed).")
    return {"searching": searching, "interrupted": interrupted, "partial_files": parts}
