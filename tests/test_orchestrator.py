"""Pipeline behaviour with every external service faked."""
import asyncio
import functools
import http.server
import os
import threading
from datetime import date

import pytest
from sqlmodel import Session

from backend import orchestrator
from backend.models import DownloadJob, JobStatus
from backend.services import einthusan, fmovies, qbittorrent, radarr, sonarr, tamilmv, tmdb, bollyzone


@pytest.fixture()
def media(tmp_path):
    (tmp_path / "www").mkdir()
    (tmp_path / "www" / "m.mp4").write_bytes(os.urandom(200_000))
    httpd = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(tmp_path / "www")))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}/m.mp4", tmp_path
    httpd.shutdown()


def add_job(db, **kw):
    kw.setdefault("title", "Guppy")
    kw.setdefault("tmdb_id", 55)
    kw.setdefault("year", 2016)
    kw.setdefault("language", "malayalam")
    kw.setdefault("status", JobStatus.MOVIE_MISSING)
    with Session(db) as s:
        j = DownloadJob(**kw)
        s.add(j)
        s.commit()
        s.refresh(j)
        return j.id


def state(db, job_id):
    with Session(db) as s:
        return s.get(DownloadJob, job_id)


async def run_pipeline(job_id, **kw):
    await orchestrator.process_request(job_id, **kw)
    for _ in range(300):
        if not orchestrator.is_pipeline_running(job_id):
            return
        await asyncio.sleep(0.05)
    raise AssertionError("pipeline did not finish")


@pytest.fixture()
def movie_env(db, media, monkeypatch):
    url, tmp = media
    calls = {"rescan": []}
    folder = str(tmp / "movies" / "Guppy (2016)")

    async def in_radarr(tmdb_id, settings):
        return {"id": 5, "tmdbId": tmdb_id, "path": folder, "hasFile": False}

    async def no_queue(movie_id, settings):
        return None

    async def dates(tmdb_id, settings):
        return date(2020, 1, 1), None, None

    async def search(title, year, lang):
        return "https://einthusan.tv/movie/watch/abc/?lang=malayalam"

    async def mp4(watch_url):
        return url

    async def ensure(tmdb_id, title, year, settings, existing=None):
        return existing or {"id": 5, "path": folder}

    async def resolution(pid, settings):
        return "1080p"

    async def rescan(movie_id, settings):
        calls["rescan"].append(movie_id)
        raise RuntimeError("radarr is down")  # must NOT undo a finished download

    monkeypatch.setattr(radarr, "is_movie_in_radarr", in_radarr)
    monkeypatch.setattr(radarr, "get_movie_queue_status", no_queue)
    monkeypatch.setattr(radarr, "ensure_movie_added", ensure)
    monkeypatch.setattr(radarr, "get_quality_profile_resolution", resolution)
    monkeypatch.setattr(radarr, "trigger_rescan", rescan)
    monkeypatch.setattr(tmdb, "get_digital_release_date", dates)
    monkeypatch.setattr(einthusan, "search", search)
    monkeypatch.setattr(einthusan, "extract_mp4_url", mp4)
    return calls, folder


def test_einthusan_pipeline_completes_even_if_radarr_rescan_fails(db, movie_env):
    calls, folder = movie_env
    job_id = add_job(db)
    asyncio.run(run_pipeline(job_id))
    job = state(db, job_id)
    assert job.status == JobStatus.DONE and job.progress_pct == 100 and job.error_msg is None
    assert job.file_path.endswith("Guppy (2016) - 1080p.mp4") and os.path.getsize(job.file_path) == 200_000
    assert calls["rescan"] == [5]
    assert job.monitored is True  # Radarr stays the owner of the monitored flag


def test_duplicate_requests_run_one_pipeline(db, movie_env, monkeypatch):
    searches = []
    orig = einthusan.search

    async def counting(title, year, lang):
        searches.append(1)
        await asyncio.sleep(0.2)
        return await orig(title, year, lang)

    monkeypatch.setattr(einthusan, "search", counting)
    job_id = add_job(db)

    async def go():
        await orchestrator.process_request(job_id)
        await orchestrator.process_request(job_id)  # ignored: already running
        for _ in range(300):
            if not orchestrator.is_pipeline_running(job_id):
                break
            await asyncio.sleep(0.05)

    asyncio.run(go())
    assert len(searches) == 1 and state(db, job_id).status == JobStatus.DONE


def test_unexpected_crash_never_leaves_the_job_searching(db, movie_env, monkeypatch):
    def boom(*a, **k):
        raise ValueError("kaboom")

    monkeypatch.setattr(tmdb, "evaluate_release", boom)
    job_id = add_job(db)
    asyncio.run(run_pipeline(job_id))
    job = state(db, job_id)
    assert job.status == JobStatus.FAILED and "kaboom" in job.error_msg
    assert not orchestrator.is_pipeline_running(job_id)


def test_release_gate_skips_unreleased_but_manual_indexer_ignores_it(db, movie_env, monkeypatch):
    async def future(tmdb_id, settings):
        return date(2999, 1, 1), None, None

    monkeypatch.setattr(tmdb, "get_digital_release_date", future)
    job_id = add_job(db)
    asyncio.run(run_pipeline(job_id))
    assert state(db, job_id).status == JobStatus.SKIPPED
    job_id2 = add_job(db, tmdb_id=56)
    asyncio.run(run_pipeline(job_id2, indexer="einthusan"))
    assert state(db, job_id2).status == JobStatus.DONE


def test_manual_search_works_when_tmdb_is_down(db, movie_env, monkeypatch):
    async def down(tmdb_id, settings):
        raise RuntimeError("tmdb down")

    monkeypatch.setattr(tmdb, "get_digital_release_date", down)
    job_id = add_job(db)
    asyncio.run(run_pipeline(job_id))
    assert state(db, job_id).status == JobStatus.FAILED  # automatic search needs the release check
    job_id2 = add_job(db, tmdb_id=57)
    asyncio.run(run_pipeline(job_id2, indexer="einthusan"))
    assert state(db, job_id2).status == JobStatus.DONE


def test_radarr_already_has_file_marks_done_without_searching(db, movie_env, monkeypatch):
    async def has_file(tmdb_id, settings):
        return {"id": 5, "tmdbId": tmdb_id, "hasFile": True}

    monkeypatch.setattr(radarr, "is_movie_in_radarr", has_file)
    job_id = add_job(db)
    asyncio.run(run_pipeline(job_id))
    job = state(db, job_id)
    assert job.status == JobStatus.DONE and job.has_file is True


def test_nothing_found_ends_not_found(db, movie_env, monkeypatch):
    async def none(title, year, lang):
        return None

    monkeypatch.setattr(einthusan, "search", none)
    monkeypatch.setattr(tamilmv, "get_current_domain", lambda: asyncio.sleep(0, "https://x"))
    monkeypatch.setattr(tamilmv, "search_movie", lambda *a, **k: asyncio.sleep(0, None))

    async def nostream(*a, **k):
        return None

    monkeypatch.setattr(fmovies, "search_movie", nostream)
    job_id = add_job(db)
    asyncio.run(run_pipeline(job_id))
    assert state(db, job_id).status == JobStatus.NOT_FOUND


# ── TV ────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def tv_env(db, monkeypatch):
    seen = {}
    series = {"id": 3, "title": "Cool Show", "tmdbId": 9001, "tvdbId": 77, "path": "/tv/Cool Show"}

    async def ensure(tvdb_id, title, settings):
        return series

    async def get_ep(series_id, s, e, settings):
        return {"id": 11, "hasFile": False, "airDateUtc": "2020-01-01T00:00:00Z", "airDate": "2020-01-01"}

    async def no_queue(ep_id, settings):
        return None

    async def res(pid, settings):
        return None

    monkeypatch.setattr(sonarr, "ensure_series_added", ensure)
    monkeypatch.setattr(sonarr, "get_episode", get_ep)
    monkeypatch.setattr(sonarr, "get_episode_queue_status", no_queue)
    monkeypatch.setattr(sonarr, "get_quality_profile_resolution", res)
    return seen


def add_tv_job(db):
    return add_job(db, title="Cool Show S01E02", tmdb_id=0, tvdb_id=77, season_number=1, episode_number=2, media_type="tv", language=None)


def test_tv_torrents_use_the_series_category(db, tv_env, monkeypatch):
    seen = tv_env

    async def domain():
        return "https://x"

    async def search(*a, **k):
        return "https://x/topic"

    async def magnet(url):
        return "magnet:?xt=urn:btih:abc"

    def add(magnet_link, settings, is_tv=False):
        seen["is_tv"] = is_tv
        return "abc"

    monkeypatch.setattr(tamilmv, "get_current_domain", domain)
    monkeypatch.setattr(tamilmv, "search_movie", search)
    monkeypatch.setattr(tamilmv, "extract_magnet", magnet)
    monkeypatch.setattr(qbittorrent, "add_magnet_to_qbittorrent", add)
    job_id = add_tv_job(db)
    asyncio.run(run_pipeline(job_id, indexer="1tamilmv"))
    job = state(db, job_id)
    assert seen["is_tv"] is True and job.status == JobStatus.DOWNLOADING and job.torrent_hash == "abc"


def test_tv_fmovies_is_keyed_by_the_series_tmdb_id_not_tvdb(db, tv_env, monkeypatch, tmp_path):
    seen = tv_env

    async def search_tv(tmdb_id, title, season, episode, settings):
        seen["tmdb_id"] = tmdb_id
        return f"{tmdb_id}/{season}/{episode}"

    async def extract(ref, settings, res=None):
        return "http://stream/x.m3u8", "http://ref/", "UA"

    async def folder(tvdb_id, title, settings):
        return str(tmp_path / "tv" / "Cool Show")

    async def fake_dl(job_id, url, referer, dest, session):
        seen["dest"] = dest
        return True

    async def rescan(series_id, settings):
        seen["rescan"] = series_id

    monkeypatch.setattr(fmovies, "search_tv", search_tv)
    monkeypatch.setattr(fmovies, "extract_stream_url", extract)
    monkeypatch.setattr(sonarr, "get_series_folder", folder)
    monkeypatch.setattr(sonarr, "trigger_rescan", rescan)
    monkeypatch.setattr(orchestrator, "download_m3u8", fake_dl)
    job_id = add_tv_job(db)
    asyncio.run(run_pipeline(job_id, indexer="fmovies"))
    job = state(db, job_id)
    assert seen["tmdb_id"] == 9001  # not the TVDB id 77
    assert seen["dest"].endswith("Cool Show - S01E02 - 720p.mp4") and seen["rescan"] == 3
    assert job.status == JobStatus.DONE
