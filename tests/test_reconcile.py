from datetime import datetime, timedelta

from backend.models import DownloadJob, JobStatus
from backend.services.reconcile import (
    derive_status, parse_eta, queue_health, queue_progress, reconcile_job,
)

NOW = datetime(2026, 1, 1, 12, 0, 0)


def job(status=JobStatus.MOVIE_MISSING, **kw):
    kw.setdefault("updated_at", NOW - timedelta(hours=1))
    return DownloadJob(id=1, tmdb_id=10, title="T", status=status, **kw)


def movie(**kw):
    base = {"id": 5, "tmdbId": 10, "monitored": True, "hasFile": False}
    base.update(kw)
    return base


def q(status="downloading", tracked="ok", size=1000, left=250, timeleft="00:10:00"):
    return {"movieId": 5, "status": status, "trackedDownloadStatus": tracked, "size": size, "sizeleft": left, "timeleft": timeleft}


def run(j, item, queue=None, **kw):
    return reconcile_job(j, item, queue, source="radarr", now=NOW, **kw)


def test_deleted_from_radarr():
    j = job(JobStatus.DONE, monitored=True, has_file=True)
    r = run(j, None)
    assert j.status == JobStatus.NOT_IN_RADARR and j.monitored is False and j.in_arr is False and not j.has_file
    assert r.status_changed
    assert not run(j, None).changed  # idempotent


def test_file_means_done():
    j = job()
    run(j, movie(hasFile=True, movieFile={"path": "/m/a.mkv"}))
    assert (j.status, j.progress_pct, j.file_path, j.has_file) == (JobStatus.DONE, 100, "/m/a.mkv", True)


def test_not_in_radarr_comes_back_missing():
    j = job(JobStatus.NOT_IN_RADARR, in_arr=False)
    run(j, movie())
    assert j.status == JobStatus.MOVIE_MISSING and j.in_arr is True


def test_healthy_queue_is_downloading_with_progress():
    j = job()
    run(j, movie(), q())
    assert j.status == JobStatus.DOWNLOADING and j.source_indexer == "radarr"
    assert j.progress_pct == 75 and j.total_bytes == 1000 and j.eta_seconds == 600


def test_completed_queue_without_file_is_importing_not_done():
    j = job(JobStatus.DOWNLOADING, source_indexer="radarr")
    run(j, movie(), q(status="completed", left=0))
    assert j.status == JobStatus.IMPORTING


def test_native_download_failed_requests_fallback():
    j = job(JobStatus.DOWNLOADING, source_indexer="radarr")
    r = run(j, movie(), q(tracked="error"))
    assert j.status == JobStatus.MOVIE_MISSING and r.fallback and j.source_indexer is None


def test_failed_queue_for_idle_job_does_not_loop_fallbacks():
    j = job(JobStatus.NOT_FOUND)
    r = run(j, movie(), q(tracked="warning"))
    assert j.status == JobStatus.NOT_FOUND and not r.fallback


def test_native_download_vanished_waits_for_queue_grace_then_falls_back():
    j = job(JobStatus.DOWNLOADING, source_indexer="radarr", updated_at=NOW - timedelta(seconds=20))
    r = run(j, movie(), None)
    assert j.status == JobStatus.DOWNLOADING and not r.fallback
    j.updated_at = NOW - timedelta(minutes=5)
    r = run(j, movie(), None)
    assert j.status == JobStatus.MOVIE_MISSING and r.fallback


def test_native_download_vanished_with_skip_queue_grace():
    # Manual sync / confirmed gone: does not wait for queue grace
    j = job(JobStatus.DOWNLOADING, source_indexer="radarr", updated_at=NOW - timedelta(seconds=5))
    r = reconcile_job(j, movie(), None, source="radarr", now=NOW, skip_queue_grace=True)
    assert j.status == JobStatus.MOVIE_MISSING and r.fallback and j.source_indexer is None


def test_native_download_with_progress_vanished_does_not_wait_for_grace():
    # If the download was already in progress (progress > 0), queue had already populated.
    # It must immediately become missing when removed, not wait 60s.
    j = job(JobStatus.DOWNLOADING, source_indexer="radarr", progress_pct=50, downloaded_bytes=500, updated_at=NOW - timedelta(seconds=5))
    r = run(j, movie(), None)
    assert j.status == JobStatus.MOVIE_MISSING and r.fallback and j.progress_pct == 0 and j.source_indexer is None


def test_movie_deleted_from_radarr_clears_download_fields():
    j = job(JobStatus.DOWNLOADING, source_indexer="radarr", progress_pct=60, downloaded_bytes=600, total_bytes=1000)
    r = run(j, None)
    assert j.status == JobStatus.NOT_IN_RADARR and j.source_indexer is None and j.progress_pct == 0
    assert j.in_arr is False and j.monitored is False and j.downloaded_bytes == 0


def test_done_but_file_gone():
    j = job(JobStatus.DONE, file_path="/x", updated_at=NOW - timedelta(hours=1))
    run(j, movie())
    assert j.status == JobStatus.MOVIE_MISSING and j.file_path is None
    # ...but not inside the rescan grace window right after our own download finished
    j = job(JobStatus.DONE, updated_at=NOW - timedelta(minutes=1))
    run(j, movie())
    assert j.status == JobStatus.DONE


def test_own_downloads_are_left_alone():
    j = job(JobStatus.DOWNLOADING, source_indexer="einthusan")
    run(j, movie(), None)
    assert j.status == JobStatus.DOWNLOADING
    j = job(JobStatus.SEARCHING, updated_at=NOW - timedelta(minutes=1))
    run(j, movie())
    assert j.status == JobStatus.SEARCHING


def test_orphaned_search_is_released():
    j = job(JobStatus.SEARCHING, updated_at=NOW - timedelta(hours=1))
    run(j, movie())
    assert j.status == JobStatus.MOVIE_MISSING


def test_monitored_follows_radarr_but_not_a_newer_local_change():
    j = job(monitored=False)
    run(j, movie(monitored=True))
    assert j.monitored is True
    # user toggled locally after the Radarr snapshot was taken -> stale snapshot must not revert it
    j = job(monitored=False, updated_at=NOW)
    run(j, movie(monitored=True), snapshot_at=NOW - timedelta(seconds=5))
    assert j.monitored is False


def test_helpers():
    assert parse_eta("00:01:30") == 90 and parse_eta("1.02:00:00") == 93600 and parse_eta("") == 0 and parse_eta("bad") == 0
    assert queue_health(None) is None and queue_health(q(tracked="Warning")) == "failed" and queue_health(q(status="completed")) == "completed"
    assert queue_progress(q())["pct"] == 75 and queue_progress({"size": 0})["pct"] == 0
    assert derive_status(None) == "not_in_arr"
    assert derive_status(movie(hasFile=True)) == "available"
    assert derive_status(movie(), q()) == "downloading"
    assert derive_status(movie()) == "missing"
