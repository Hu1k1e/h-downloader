import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from backend import config
from backend.models import DownloadJob, JobStatus


@pytest.fixture()
def client(db):
    from backend.main import app
    with TestClient(app) as c:
        yield c


def add_job(**kw):
    from backend.database import engine
    kw.setdefault("title", "Movie")
    kw.setdefault("tmdb_id", 10)
    kw.setdefault("language", "malayalam")
    with Session(engine) as s:
        j = DownloadJob(**kw)
        s.add(j)
        s.commit()
        s.refresh(j)
        return j.id


def get_job(job_id):
    from backend.database import engine
    with Session(engine) as s:
        return s.get(DownloadJob, job_id)


def set_radarr_key():
    from backend.database import engine, get_settings
    with Session(engine) as s:
        st = get_settings(s)
        st.radarr_api_key = "k"
        s.add(st)
        s.commit()


def test_health_and_unknown_api_is_404_not_html(client):
    assert client.get("/health").json()["status"] == "ok"
    r = client.get("/api/does-not-exist")
    assert r.status_code == 404 and "html" not in r.headers.get("content-type", "")


def test_api_token_is_opt_in(client, monkeypatch):
    assert client.get("/api/jobs").status_code == 200
    monkeypatch.setattr(config, "API_AUTH_TOKEN", "s3cret")
    assert client.get("/api/jobs").status_code == 401
    assert client.get("/api/jobs", headers={"X-API-Key": "nope"}).status_code == 401
    assert client.get("/api/jobs", headers={"X-API-Key": "s3cret"}).status_code == 200
    assert client.get("/api/jobs", headers={"Authorization": "Bearer s3cret"}).status_code == 200
    assert client.get("/health").status_code == 200  # never protected


def test_jellyseerr_webhook_without_media_type_does_not_crash(client):
    r = client.post("/webhook/jellyseerr", json={"notification_type": "MEDIA_APPROVED", "tmdbId": "1"})
    assert r.status_code == 200 and r.json()["status"] == "skipped"
    r = client.post("/webhook/jellyseerr", json={"media_type": "movie", "notification_type": "MEDIA_APPROVED"})
    assert r.status_code == 400


def test_jellyseerr_movie_creates_job(client, monkeypatch):
    import backend.routers.webhook as wh
    calls = []

    async def fake_delayed(*a, **k):  # the real one waits search_delay_seconds
        calls.append(a)

    monkeypatch.setattr(wh, "delayed_search", fake_delayed)
    r = client.post("/webhook/jellyseerr", json={"media_type": "movie", "notification_type": "MEDIA_APPROVED", "tmdbId": "77", "title": "Hi"})
    assert r.status_code == 200 and r.json()["status"] == "accepted" and calls == [(77, None)]
    from backend.database import engine
    with Session(engine) as s:
        assert s.exec(select(DownloadJob).where(DownloadJob.tmdb_id == 77)).first().status == JobStatus.MOVIE_MISSING


def test_radarr_webhook_token_is_opt_in_and_events_work(client, monkeypatch):
    body = {"eventType": "Download", "movie": {"tmdbId": 5, "title": "X"}}
    assert client.post("/webhook/radarr", json=body).status_code == 200
    monkeypatch.setattr(config, "WEBHOOK_TOKEN", "tok")
    assert client.post("/webhook/radarr", json=body).status_code == 401
    assert client.post("/webhook/radarr?token=tok", json=body).status_code == 200
    assert client.post("/webhook/radarr", json=body, headers={"X-Webhook-Token": "tok"}).status_code == 200
    jid = add_job(tmdb_id=6, status=JobStatus.DONE, monitored=True, has_file=True)
    client.post("/webhook/radarr?token=tok", json={"eventType": "MovieDeleted", "movie": {"tmdbId": 6, "title": "Y"}})
    j = get_job(jid)
    assert j.status == JobStatus.NOT_IN_RADARR and j.in_arr is False


def test_download_webhook_does_not_unmonitor(client):
    jid = add_job(tmdb_id=8, status=JobStatus.MOVIE_MISSING, monitored=True)
    client.post("/webhook/radarr", json={"eventType": "Download", "movie": {"tmdbId": 8, "title": "Z"}})
    j = get_job(jid)
    assert j.status == JobStatus.DONE and j.monitored is True


def test_logs_csv_export_works_and_neutralises_formulas(client):
    from backend.db_logger import log_action
    log_action("Test", '=HYPERLINK("x")', job_id=1)
    r = client.get("/api/logs/csv")
    assert r.status_code == 200
    assert "'=HYPERLINK" in r.text and "Job ID" in r.text


def test_stats_counts_by_status(client):
    add_job(tmdb_id=1, status=JobStatus.DONE)
    add_job(tmdb_id=2, status=JobStatus.FAILED)
    add_job(tmdb_id=3, status=JobStatus.FAILED)
    s = client.get("/api/stats").json()
    assert (s["total"], s["completed"], s["failed"]) == (3, 1, 2)


def test_monitor_toggle_stores_radarr_confirmed_value(client, monkeypatch):
    from backend.services import radarr
    jid = add_job(tmdb_id=20, monitored=False, status=JobStatus.MOVIE_MISSING)

    async def in_radarr(tmdb_id, settings):
        return {"id": 99, "tmdbId": tmdb_id}

    async def update(movie_id, monitored, settings):
        assert movie_id == 99
        return False  # Radarr keeps False: UI must reflect that, not what was requested

    monkeypatch.setattr(radarr, "is_movie_in_radarr", in_radarr)
    monkeypatch.setattr(radarr, "update_movie_monitored", update)
    r = client.put(f"/api/jobs/{jid}/monitor", json={"monitored": True})
    assert r.status_code == 200 and r.json()["monitored"] is False
    assert get_job(jid).monitored is False


def test_monitor_toggle_for_movie_missing_in_radarr_is_an_error(client, monkeypatch):
    from backend.services import radarr
    jid = add_job(tmdb_id=21, monitored=False)

    async def none(*a, **k):
        return None

    monkeypatch.setattr(radarr, "is_movie_in_radarr", none)
    assert client.put(f"/api/jobs/{jid}/monitor", json={"monitored": True}).status_code == 404
    assert get_job(jid).monitored is False


def test_sync_all_and_single_reflect_radarr(client, monkeypatch):
    from backend.services import radarr
    from backend import sync
    done = add_job(tmdb_id=30, status=JobStatus.MOVIE_MISSING, monitored=False)
    gone = add_job(tmdb_id=31, status=JobStatus.DONE, has_file=True)
    dl = add_job(tmdb_id=32, status=JobStatus.MOVIE_MISSING)

    movies = [
        {"id": 1, "tmdbId": 30, "hasFile": True, "monitored": True, "movieFile": {"path": "/m/30.mkv"}},
        {"id": 3, "tmdbId": 32, "hasFile": False, "monitored": True},
    ]
    queue = [{"movieId": 3, "status": "downloading", "trackedDownloadStatus": "ok", "size": 100, "sizeleft": 50, "timeleft": "00:01:00"}]

    async def snapshot(settings):
        return movies, queue

    async def one(tmdb_id, settings):
        return next((m for m in movies if m["tmdbId"] == tmdb_id), None)

    async def q(settings, max_age=0):
        return queue

    monkeypatch.setattr(sync, "fetch_radarr_snapshot", snapshot)
    monkeypatch.setattr(radarr, "is_movie_in_radarr", one)
    monkeypatch.setattr(radarr, "get_full_queue", q)
    set_radarr_key()

    res = client.post("/api/jobs/sync-all").json()
    assert res["status"] == "success" and res["updated"] == 3 and res["deleted"] == 1
    assert {c["to"] for c in res["changes"]} == {"done", "not_in_radarr", "downloading"}
    a, b, c = get_job(done), get_job(gone), get_job(dl)
    assert (a.status, a.monitored, a.file_path) == (JobStatus.DONE, True, "/m/30.mkv")
    assert b.status == JobStatus.NOT_IN_RADARR and b.in_arr is False
    assert c.status == JobStatus.DOWNLOADING and c.progress_pct == 50 and c.last_synced_at is not None

    r = client.post(f"/api/jobs/{gone}/sync").json()
    assert r["state"] == "not_in_radarr" and r["changed"] is False


def test_sync_reports_failure_instead_of_silent_success(client, monkeypatch):
    from backend import sync
    jid = add_job(tmdb_id=40, status=JobStatus.DONE)
    set_radarr_key()

    async def boom(settings):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(sync, "fetch_radarr_snapshot", boom)
    r = client.post("/api/jobs/sync-all")
    assert r.status_code == 502 and "connection refused" in r.json()["detail"]
    assert "unreachable" in get_job(jid).sync_error
    assert client.get("/api/sync/status").json()["radarr"]["ok"] is False


def test_import_url_host_parsing():
    from backend.routers.jobs import _classify_url
    assert _classify_url("https://einthusan.tv/movie/watch/AbC/?lang=tamil") == "einthusan"
    assert _classify_url("https://www.1tamilmv.fi/index.php?/forums/topic/1-x") == "1tamilmv"
    assert _classify_url("https://www.f-movies.org/movie/x") == "fmovies"
    assert _classify_url("https://evil.example/einthusan.tv/movie/watch/x") is None
    assert _classify_url("https://evil.example/?u=1tamilmv.fi/") is None
    assert _classify_url("ftp://einthusan.tv/movie/watch/x") is None
    assert _classify_url("not a url") is None


def test_cancel_removes_torrent(client, monkeypatch):
    from backend.services import qbittorrent
    removed = []
    monkeypatch.setattr(qbittorrent, "delete_torrent", lambda h, s: removed.append(h) or True)
    jid = add_job(tmdb_id=50, status=JobStatus.DOWNLOADING, torrent_hash="abc", source_indexer="1tamilmv")
    assert client.post(f"/api/jobs/{jid}/cancel", json={}).status_code == 200
    j = get_job(jid)
    assert removed == ["abc"] and j.torrent_hash is None and j.status == JobStatus.MOVIE_MISSING


def test_trigger_monitored_skips_done_and_busy(client, monkeypatch):
    import backend.routers.jobs as jobs_router
    seen = []

    async def fake_many(ids, **kw):
        seen.extend(ids)

    monkeypatch.setattr(jobs_router, "process_many", fake_many)
    a = add_job(tmdb_id=60, status=JobStatus.MOVIE_MISSING, monitored=True)
    add_job(tmdb_id=61, status=JobStatus.DONE, monitored=True)
    add_job(tmdb_id=62, status=JobStatus.DOWNLOADING, monitored=True)
    add_job(tmdb_id=63, status=JobStatus.MOVIE_MISSING, monitored=False)
    r = client.post("/api/jobs/trigger-monitored")
    assert r.json()["triggered"] == 1 and seen == [a]
