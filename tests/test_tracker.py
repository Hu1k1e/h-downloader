"""Tracker behaviour: qBittorrent outages, torrent failures, completion, import timeouts, startup recovery."""
import asyncio
from datetime import datetime, timedelta

import pytest
from sqlmodel import Session

from backend import sync
from backend.models import DownloadJob, JobStatus
from backend.services import qbittorrent, radarr
from backend.services.qbittorrent import QbittorrentError, NO_METADATA

NOW = datetime.utcnow()


@pytest.fixture()
def env(db, monkeypatch):
    """A Session, settings and a fake Radarr context for _track_torrent / _track_importing."""
    from backend.database import engine, get_settings
    state = {"movies": [], "queue": [], "rescans": [], "deleted": []}

    async def movies(settings, max_age=0):
        return state["movies"]

    async def queue(settings, max_age=0):
        return state["queue"]

    async def rescan(movie_id, settings):
        state["rescans"].append(movie_id)

    monkeypatch.setattr(radarr, "get_all_movies", movies)
    monkeypatch.setattr(radarr, "get_full_queue", queue)
    monkeypatch.setattr(radarr, "trigger_rescan", rescan)
    monkeypatch.setattr(qbittorrent, "delete_torrent", lambda h, s: state["deleted"].append(h) or True)
    monkeypatch.setattr(qbittorrent, "filter_torrent_files", lambda h, s, enforce_size=True: (True, None))
    sync._filtered_torrents.clear()
    sync._importing_since.clear()
    sync._last_rescan.clear()

    session = Session(engine)
    settings = get_settings(session)
    state["session"], state["settings"] = session, settings
    yield state
    session.close()


def make_job(env, **kw):
    kw.setdefault("tmdb_id", 10)
    kw.setdefault("title", "Movie")
    kw.setdefault("status", JobStatus.DOWNLOADING)
    kw.setdefault("source_indexer", "1tamilmv")
    kw.setdefault("torrent_hash", "h1")
    kw.setdefault("updated_at", NOW - timedelta(minutes=30))
    job = DownloadJob(**kw)
    env["session"].add(job)
    env["session"].commit()
    env["session"].refresh(job)
    return job


def torrent(**kw):
    base = {"hash": "h1", "state": "downloading", "progress": 0.5, "downloaded": 50, "size": 100, "eta": 120}
    base.update(kw)
    return base


def run(coro):
    return asyncio.run(coro)


def track(env, job, ctx=None):
    ctx = ctx or sync._ArrContext(env["settings"])
    return run(sync._track_torrent(env["session"], job, ctx, env["settings"], NOW))


def test_qbittorrent_outage_is_not_treated_as_removed(env, monkeypatch):
    def boom(h, s):
        raise QbittorrentError("down")
    monkeypatch.setattr(qbittorrent, "get_torrent_info", boom)
    job = make_job(env)
    assert track(env, job) is None
    assert job.status == JobStatus.DOWNLOADING and job.torrent_hash == "h1"


def test_progress_eta_and_bytes_are_recorded(env, monkeypatch):
    monkeypatch.setattr(qbittorrent, "get_torrent_info", lambda h, s: torrent())
    job = make_job(env)
    track(env, job)
    assert (job.progress_pct, job.eta_seconds, job.total_bytes, job.downloaded_bytes) == (50, 120, 100, 50)


def test_just_added_torrent_gets_a_grace_period(env, monkeypatch):
    monkeypatch.setattr(qbittorrent, "get_torrent_info", lambda h, s: None)
    job = make_job(env, updated_at=NOW - timedelta(seconds=10))
    assert track(env, job) is None and job.status == JobStatus.DOWNLOADING


def test_missing_torrent_falls_back_from_its_source(env, monkeypatch):
    monkeypatch.setattr(qbittorrent, "get_torrent_info", lambda h, s: None)
    job = make_job(env)
    assert track(env, job) == "1tamilmv"
    assert job.status == JobStatus.FAILED and job.torrent_hash is None


def test_missing_torrent_with_healthy_radarr_grab_is_handed_over(env, monkeypatch):
    monkeypatch.setattr(qbittorrent, "get_torrent_info", lambda h, s: None)
    env["movies"] = [{"id": 7, "tmdbId": 10, "hasFile": False, "monitored": True}]
    env["queue"] = [{"movieId": 7, "status": "downloading", "trackedDownloadStatus": "ok"}]
    job = make_job(env)
    assert track(env, job) is None
    assert job.status == JobStatus.MOVIE_MISSING and job.torrent_hash is None


def test_error_state_deletes_torrent_and_falls_back(env, monkeypatch):
    monkeypatch.setattr(qbittorrent, "get_torrent_info", lambda h, s: torrent(state="error"))
    job = make_job(env)
    assert track(env, job) == "1tamilmv"
    assert job.status == JobStatus.FAILED
    import time; time.sleep(0.2)  # delete runs in an executor
    assert env["deleted"] == ["h1"]


def test_rejected_torrent_is_deleted(env, monkeypatch):
    monkeypatch.setattr(qbittorrent, "get_torrent_info", lambda h, s: torrent())
    monkeypatch.setattr(qbittorrent, "filter_torrent_files", lambda h, s, enforce_size=True: (False, "Main video file is too small"))
    job = make_job(env)
    assert track(env, job) == "1tamilmv"
    assert "too small" in job.error_msg


def test_files_not_known_yet_is_retried_not_rejected(env, monkeypatch):
    monkeypatch.setattr(qbittorrent, "get_torrent_info", lambda h, s: torrent(state="metaDL", progress=0))
    monkeypatch.setattr(qbittorrent, "filter_torrent_files", lambda h, s, enforce_size=True: (False, NO_METADATA))
    job = make_job(env, updated_at=NOW - timedelta(minutes=1))
    assert track(env, job) is None and job.status == JobStatus.DOWNLOADING and job.id not in sync._filtered_torrents


def test_size_limits_only_enforced_for_movies(env, monkeypatch):
    seen = []
    monkeypatch.setattr(qbittorrent, "get_torrent_info", lambda h, s: torrent())
    monkeypatch.setattr(qbittorrent, "filter_torrent_files", lambda h, s, enforce_size=True: seen.append(enforce_size) or (True, None))
    track(env, make_job(env, tmdb_id=1))
    sync._filtered_torrents.clear()
    track(env, make_job(env, tmdb_id=0, media_type="tv", tvdb_id=5, season_number=1, episode_number=1, torrent_hash="h2"))
    assert seen == [True, False]


def test_stalled_torrent_is_removed_after_configured_hours(env, monkeypatch):
    env["settings"].auto_delete_failed_torrents_hours = 24
    monkeypatch.setattr(qbittorrent, "get_torrent_info", lambda h, s: torrent(state="stalledDL"))
    assert track(env, make_job(env, updated_at=NOW - timedelta(hours=2))) is None
    job = make_job(env, tmdb_id=11, torrent_hash="h3", updated_at=NOW - timedelta(hours=30))
    assert track(env, job) == "1tamilmv" and "stalled" in job.error_msg
    env["settings"].auto_delete_failed_torrents_hours = 0
    job = make_job(env, tmdb_id=12, torrent_hash="h4", updated_at=NOW - timedelta(hours=30))
    assert track(env, job) is None  # 0 disables


def test_completed_torrent_moves_to_importing_and_rescans_with_radarr_id(env, monkeypatch):
    monkeypatch.setattr(qbittorrent, "get_torrent_info", lambda h, s: torrent(state="uploading", progress=1.0, downloaded=100))
    env["movies"] = [{"id": 7, "tmdbId": 10, "hasFile": False, "monitored": True}]
    job = make_job(env)
    track(env, job)
    assert job.status == JobStatus.IMPORTING and env["rescans"] == [7]  # the Radarr id, not the TMDB id


def test_importing_resolves_to_done_when_radarr_has_the_file(env):
    env["movies"] = [{"id": 7, "tmdbId": 10, "hasFile": True, "monitored": True, "movieFile": {"path": "/m/x.mkv"}}]
    job = make_job(env, status=JobStatus.IMPORTING, progress_pct=100)
    run(sync._track_importing(env["session"], job, sync._ArrContext(env["settings"]), env["settings"], NOW, NOW))
    assert job.status == JobStatus.DONE and job.file_path == "/m/x.mkv"


def test_importing_is_rescanned_periodically_then_times_out(env):
    env["movies"] = [{"id": 7, "tmdbId": 10, "hasFile": False, "monitored": True}]
    job = make_job(env, status=JobStatus.IMPORTING, progress_pct=100)
    ctx = sync._ArrContext(env["settings"])
    run(sync._track_importing(env["session"], job, ctx, env["settings"], NOW, NOW))
    assert job.status == JobStatus.IMPORTING and env["rescans"] == [7]
    run(sync._track_importing(env["session"], job, sync._ArrContext(env["settings"]), env["settings"], NOW + timedelta(minutes=1), NOW))
    assert env["rescans"] == [7]  # not again within 5 minutes
    run(sync._track_importing(env["session"], job, sync._ArrContext(env["settings"]), env["settings"], NOW + timedelta(hours=3), NOW))
    assert job.status == JobStatus.FAILED and "2 hours" in job.error_msg


def test_startup_recovery_resets_orphans_but_keeps_torrents_and_native(db):
    from backend.database import engine
    with Session(engine) as s:
        ids = {}
        for name, kw in {
            "searching": dict(status=JobStatus.SEARCHING),
            "direct": dict(status=JobStatus.DOWNLOADING, source_indexer="einthusan"),
            "torrent": dict(status=JobStatus.DOWNLOADING, source_indexer="1tamilmv", torrent_hash="h"),
            "native": dict(status=JobStatus.DOWNLOADING, source_indexer="radarr"),
            "done": dict(status=JobStatus.DONE),
        }.items():
            j = DownloadJob(title=name, tmdb_id=hash(name) % 1000, **kw)
            s.add(j)
            s.commit()
            ids[name] = j.id
    out = sync.recover_orphaned_jobs()
    assert out["searching"] == 1 and out["interrupted"] == 1
    with Session(engine) as s:
        st = {n: s.get(DownloadJob, i).status for n, i in ids.items()}
    assert st == {"searching": JobStatus.MOVIE_MISSING, "direct": JobStatus.FAILED, "torrent": JobStatus.DOWNLOADING,
                  "native": JobStatus.DOWNLOADING, "done": JobStatus.DONE}
