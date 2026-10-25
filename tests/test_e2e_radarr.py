"""End-to-end against a fake Radarr HTTP server: exercises the real radarr client, sync and tracker."""
import asyncio
import socket
import threading
import time
from datetime import datetime, timedelta

import pytest
import uvicorn
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlmodel import Session

from backend.models import DownloadJob, JobStatus


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture()
def radarr_server():
    state = {
        "movies": {
            1: {"id": 1, "tmdbId": 101, "title": "Has File", "year": 2020, "monitored": True, "hasFile": True,
                "movieFile": {"id": 900, "path": "/movies/hasfile.mkv"}, "originalLanguage": {"name": "Malayalam"}, "images": []},
            2: {"id": 2, "tmdbId": 102, "title": "Grabbing", "year": 2021, "monitored": True, "hasFile": False,
                "originalLanguage": {"name": "Malayalam"}, "images": []},
            3: {"id": 3, "tmdbId": 103, "title": "Wanted New", "year": 2022, "monitored": True, "hasFile": False,
                "originalLanguage": {"name": "Tamil"},
                "images": [{"coverType": "poster", "remoteUrl": "https://image.tmdb.org/t/p/original/abc.jpg"}]},
            4: {"id": 4, "tmdbId": 104, "title": "English Movie", "year": 2022, "monitored": True, "hasFile": False,
                "originalLanguage": {"name": "English"}, "images": []},
        },
        "queue": [{"movieId": 2, "status": "downloading", "trackedDownloadStatus": "ok", "size": 1000, "sizeleft": 400, "timeleft": "00:05:00"}],
        "commands": [],
        "calls": [],
    }
    app = FastAPI()

    @app.middleware("http")
    async def record(request: Request, call_next):
        state["calls"].append((request.method, request.url.path))
        assert request.headers.get("x-api-key") == "radarr-key"
        return await call_next(request)

    @app.get("/api/v3/movie")
    def movies():
        return list(state["movies"].values())

    @app.get("/api/v3/movie/{mid}")
    def movie(mid: int):
        return state["movies"][mid]

    @app.put("/api/v3/movie/{mid}")
    async def put_movie(mid: int, request: Request):
        state["movies"][mid] = await request.json()
        return state["movies"][mid]

    @app.get("/api/v3/queue")
    def queue():
        return {"records": state["queue"]}

    @app.post("/api/v3/command")
    async def command(request: Request):
        state["commands"].append(await request.json())
        return {"id": 1}

    @app.get("/api/v3/qualityprofile")
    def profiles():
        return [{"id": 1, "name": "HD-1080p"}]

    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    state["url"] = f"http://127.0.0.1:{port}"
    yield state
    server.should_exit = True


@pytest.fixture()
def client(db, radarr_server):
    from backend.database import engine, get_settings
    from backend.main import app
    with Session(engine) as s:
        st = get_settings(s)
        st.radarr_url, st.radarr_api_key = radarr_server["url"], "radarr-key"
        st.einthusan_languages_str = "malayalam,tamil"
        s.add(st)
        s.commit()
    with TestClient(app) as c:
        yield c


def jobs_by_tmdb():
    from backend.database import engine
    from sqlmodel import select
    with Session(engine) as s:
        return {j.tmdb_id: j for j in s.exec(select(DownloadJob)).all()}


def test_sync_all_end_to_end(client, radarr_server):
    from backend.database import engine
    with Session(engine) as s:
        for tmdb, status in ((101, JobStatus.MOVIE_MISSING), (102, JobStatus.MOVIE_MISSING), (999, JobStatus.DONE)):
            s.add(DownloadJob(tmdb_id=tmdb, title=f"J{tmdb}", status=status, language="malayalam"))
        s.commit()

    res = client.post("/api/jobs/sync-all").json()
    assert res["status"] == "success"
    jobs = jobs_by_tmdb()
    assert jobs[101].status == JobStatus.DONE and jobs[101].file_path == "/movies/hasfile.mkv" and jobs[101].has_file
    assert jobs[102].status == JobStatus.DOWNLOADING and jobs[102].source_indexer == "radarr" and jobs[102].progress_pct == 60
    assert jobs[999].status == JobStatus.NOT_IN_RADARR and jobs[999].in_arr is False
    # a regional monitored movie we didn't know about is picked up; the English one is not
    assert jobs[103].status == JobStatus.MOVIE_MISSING and jobs[103].language == "tamil" and jobs[103].poster_path == "/abc.jpg"
    assert 104 not in jobs
    assert all(j.last_synced_at is not None for j in jobs.values())


def test_monitor_toggle_round_trips_through_radarr(client, radarr_server):
    from backend.database import engine
    with Session(engine) as s:
        j = DownloadJob(tmdb_id=102, title="Grabbing", status=JobStatus.MOVIE_MISSING, monitored=True, language="malayalam")
        s.add(j)
        s.commit()
        jid = j.id
    r = client.put(f"/api/jobs/{jid}/monitor", json={"monitored": False})
    assert r.status_code == 200 and r.json()["monitored"] is False
    assert radarr_server["movies"][2]["monitored"] is False  # actually changed in Radarr
    # background sync must not flip it back: Radarr now says False
    client.post("/api/jobs/sync-all")
    assert jobs_by_tmdb()[102].monitored is False


def test_tracker_follows_a_native_download_to_completion_without_false_fallback(client, radarr_server, monkeypatch):
    from backend import sync
    fallbacks = []
    monkeypatch.setattr(sync, "_trigger_fallbacks", lambda ids, mt, st: fallbacks.extend(ids))
    from backend.database import engine
    with Session(engine) as s:
        j = DownloadJob(tmdb_id=102, title="Grabbing", status=JobStatus.DOWNLOADING, source_indexer="radarr", language="malayalam")
        s.add(j)
        s.commit()
        jid = j.id

    asyncio.run(sync._tracker_cycle(1))
    with Session(engine) as s:
        j = s.get(DownloadJob, jid)
        assert j.status == JobStatus.DOWNLOADING and j.progress_pct == 60 and j.eta_seconds == 300

    # Download finishes: queue empties and the file appears in Radarr in the same instant.
    radarr_server["queue"].clear()
    radarr_server["movies"][2].update(hasFile=True, movieFile={"id": 5, "path": "/movies/grabbing.mkv"})
    asyncio.run(sync._tracker_cycle(2))
    with Session(engine) as s:
        j = s.get(DownloadJob, jid)
        assert j.status == JobStatus.DONE and j.file_path == "/movies/grabbing.mkv"
    assert fallbacks == []


def test_tracker_triggers_fallback_when_native_download_disappears(client, radarr_server, monkeypatch):
    from backend import sync
    fallbacks = []
    monkeypatch.setattr(sync, "_trigger_fallbacks", lambda ids, mt, st: fallbacks.extend(ids))
    from backend.database import engine
    with Session(engine) as s:
        j = DownloadJob(tmdb_id=102, title="Grabbing", status=JobStatus.DOWNLOADING, source_indexer="radarr",
                        language="malayalam", updated_at=datetime.utcnow() - timedelta(minutes=10))
        s.add(j)
        s.commit()
        jid = j.id
    radarr_server["queue"].clear()  # grab vanished, still no file
    asyncio.run(sync._tracker_cycle(1))
    with Session(engine) as s:
        assert s.get(DownloadJob, jid).status == JobStatus.MOVIE_MISSING
    assert set(fallbacks) == {jid}  # the 60s sync loop may detect it too; process_request dedupes


def test_fresh_grab_survives_tracker_and_state_sync_before_it_reaches_the_queue(client, radarr_server, monkeypatch):
    """Regression (Dude/Tharangam): Grab webhook, then the tracker / 60s sync ran before Radarr
    listed the download and declared it 'vanished' 3s after the grab."""
    from backend import sync
    from backend.database import engine
    fallbacks = []
    monkeypatch.setattr(sync, "_trigger_fallbacks", lambda ids, mt, st: fallbacks.extend(ids))
    radarr_server["queue"].clear()  # grabbed, but not in the queue API yet
    with Session(engine) as s:
        j = DownloadJob(tmdb_id=102, title="Grabbing", status=JobStatus.DOWNLOADING, source_indexer="radarr",
                        language="malayalam", updated_at=datetime.utcnow())
        s.add(j)
        s.commit()
        jid = j.id

    asyncio.run(sync._tracker_cycle(1))
    asyncio.run(sync.radarr_state_sync_once())
    with Session(engine) as s:
        assert s.get(DownloadJob, jid).status == JobStatus.DOWNLOADING
    assert fallbacks == []


def test_disabled_auto_search_is_logged_not_silent(client):
    from backend import sync
    from backend.database import engine, get_settings
    from backend.models import LogEntry, LogLevel
    from sqlmodel import select
    with Session(engine) as s:
        st = get_settings(s)
        st.enable_radarr_auto_search = False
        s.add(st)
        s.commit()
        s.refresh(st)
        sync._trigger_fallbacks([7], "movie", st)
        logs = s.exec(select(LogEntry).where(LogEntry.level == LogLevel.WARNING)).all()
    assert any("auto-search is disabled" in l.message for l in logs)


def test_tracker_discovers_untracked_grab(client, radarr_server):
    from backend import sync
    from backend.database import engine
    with Session(engine) as s:
        j = DownloadJob(tmdb_id=102, title="Grabbing", status=JobStatus.MOVIE_MISSING, language="malayalam")
        s.add(j)
        s.commit()
        jid = j.id
    asyncio.run(sync._tracker_cycle(0))  # cycle % 6 == 0 -> queue discovery runs
    with Session(engine) as s:
        j = s.get(DownloadJob, jid)
        assert j.status == JobStatus.DOWNLOADING and j.source_indexer == "radarr"


def test_quality_profile_resolution_and_queue_picker(radarr_server):
    from backend.services import radarr
    from backend.models import AppSettings
    st = AppSettings(radarr_url=radarr_server["url"], radarr_api_key="radarr-key")
    assert asyncio.run(radarr.get_quality_profile_resolution(1, st)) == "1080p"
    assert radarr.resolution_from_profile_name("Any") is None  # was returned verbatim and ended up in filenames
    recs = [{"movieId": 1, "trackedDownloadStatus": "warning", "n": 1}, {"movieId": 1, "trackedDownloadStatus": "ok", "n": 2}]
    assert radarr.pick_queue_record(recs, "movieId", 1)["n"] == 2
    assert radarr.pick_queue_record(recs[:1], "movieId", 1)["n"] == 1
    assert radarr.pick_queue_record(recs, "movieId", 9) is None


def test_sync_single_movie_removes_download_when_deleted_from_radarr(client, radarr_server):
    """When a download is deleted in Radarr, syncing the movie immediately resets it to missing."""
    from backend.database import engine

    radarr_server["queue"].clear()  # No active download in Radarr
    radarr_server["movies"][2].update(hasFile=False, movieFile=None)
    with Session(engine) as s:
        j = DownloadJob(tmdb_id=102, title="Grabbing", status=JobStatus.DOWNLOADING,
                        source_indexer="radarr", progress_pct=40, downloaded_bytes=400,
                        language="malayalam", updated_at=datetime.utcnow())
        s.add(j)
        s.commit()
        jid = j.id

    r = client.post(f"/api/jobs/{jid}/sync")
    assert r.status_code == 200
    res = r.json()
    assert res["state"] in ("movie_missing", "searching")
    with Session(engine) as s:
        updated = s.get(DownloadJob, jid)
        assert updated.status in (JobStatus.MOVIE_MISSING, JobStatus.SEARCHING)
        assert updated.source_indexer is None or updated.status == JobStatus.SEARCHING
        assert updated.progress_pct == 0


def test_manual_trigger_proceeds_while_radarr_downloading(client, radarr_server, monkeypatch):
    """When a movie is currently downloading via Radarr, clicking trigger searches custom sources."""
    from backend.database import engine
    from backend import orchestrator
    searched = []

    async def fake_run_pipeline(*args, **kwargs):
        searched.append(args)

    monkeypatch.setattr(orchestrator, "_run_pipeline", fake_run_pipeline)
    radarr_server["movies"][2] = {"id": 2, "tmdbId": 102, "title": "Grabbing", "hasFile": False, "monitored": True}

    with Session(engine) as s:
        j = DownloadJob(tmdb_id=102, title="ActiveRadarr", status=JobStatus.DOWNLOADING,
                        source_indexer="radarr", progress_pct=30, language="malayalam")
        s.add(j)
        s.commit()
        jid = j.id

    r = client.post("/api/jobs/trigger", json={"tmdb_id": 102, "language": "malayalam"})
    assert r.status_code == 200
    with Session(engine) as s:
        updated = s.get(DownloadJob, jid)
        assert updated.status == JobStatus.SEARCHING

