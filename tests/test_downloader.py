"""Downloader against a real local HTTP server and real ffmpeg."""
import asyncio
import functools
import http.server
import os
import shutil
import subprocess
import threading

import pytest
from sqlmodel import Session

from backend.models import DownloadJob, JobStatus
from backend.services import downloader


class _Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.startswith("/truncated"):
            # Promise 1000 bytes, deliver 400, then hang up.
            self.send_response(200)
            self.send_header("Content-Length", "1000")
            self.end_headers()
            self.wfile.write(b"x" * 400)
            self.wfile.flush()
            self.close_connection = True
            return
        return super().do_GET()


@pytest.fixture()
def server(tmp_path):
    handler = functools.partial(_Handler, directory=str(tmp_path / "www"))
    (tmp_path / "www").mkdir()
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", tmp_path / "www"
    httpd.shutdown()


def make_job(db):
    with Session(db) as s:
        j = DownloadJob(title="Dl", tmdb_id=1, status=JobStatus.DOWNLOADING)
        s.add(j)
        s.commit()
        s.refresh(j)
        return j.id


def job_state(db, job_id):
    with Session(db) as s:
        j = s.get(DownloadJob, job_id)
        return j.status, j.progress_pct, j.error_msg


def test_filename_helpers():
    assert downloader.get_movie_file_path("/m/Film (2020)", "Film: The/End", 2020, "1080p").endswith("Film The End (2020) - 1080p.mp4") or \
        downloader.get_movie_file_path("/m/Film (2020)", "Film: The/End", 2020, "1080p").endswith("Film TheEnd (2020) - 1080p.mp4")
    assert downloader.get_episode_file_path("/tv/Show/", "Show: Name!", 1, 2, "720p") == "/tv/Show/Show Name - S01E02 - 720p.mp4"


def test_direct_download_writes_part_then_renames(db, server, tmp_path):
    url, www = server
    payload = os.urandom(3 * 1024 * 1024 + 123)
    (www / "movie.mp4").write_bytes(payload)
    job_id = make_job(db)
    dest = str(tmp_path / "out" / "Movie (2020) - 720p.mp4")
    with Session(db) as s:
        ok = asyncio.run(downloader.download_movie(job_id, f"{url}/movie.mp4", dest, s))
    assert ok and open(dest, "rb").read() == payload
    assert not os.path.exists(dest + ".part")
    assert job_state(db, job_id)[:2] == (JobStatus.DOWNLOADING, 100)  # caller marks DONE after the rescan


def test_truncated_download_is_a_failure_and_leaves_no_file(db, server, tmp_path):
    url, _ = server
    job_id = make_job(db)
    dest = str(tmp_path / "out" / "x.mp4")
    with Session(db) as s:
        ok = asyncio.run(downloader.download_movie(job_id, f"{url}/truncated", dest, s))
    assert not ok
    assert not os.path.exists(dest) and not os.path.exists(dest + ".part")
    assert job_state(db, job_id)[0] == JobStatus.FAILED


def test_not_enough_disk_space_is_detected(monkeypatch):
    class U:
        free = 10
    monkeypatch.setattr(shutil, "disk_usage", lambda d: U)
    with pytest.raises(Exception, match="disk space"):
        downloader._check_disk_space("/", 10 ** 9)
    downloader._check_disk_space("/", 0)  # unknown size: no check


def test_cancel_does_not_overwrite_the_cancelled_state_with_failed(db, server, tmp_path):
    url, www = server
    (www / "big.bin").write_bytes(os.urandom(2 * 1024 * 1024))
    job_id = make_job(db)
    dest = str(tmp_path / "out" / "c.mp4")

    async def scenario():
        with Session(db) as s:
            task = asyncio.create_task(downloader.download_movie(job_id, f"{url}/big.bin", dest, s))
            await asyncio.sleep(0)  # let it register as active
            downloader.cancel_download(job_id)
            return await task

    assert asyncio.run(scenario()) is False
    assert not os.path.exists(dest) and not os.path.exists(dest + ".part")
    assert job_state(db, job_id)[0] == JobStatus.DOWNLOADING  # untouched: the router sets the cancelled state


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_hls_download_reports_progress_and_renames(db, server, tmp_path):
    url, www = server
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=duration=6:size=160x120:rate=10",
         "-f", "lavfi", "-i", "sine=duration=6", "-c:v", "libx264", "-c:a", "aac", "-f", "hls",
         "-hls_time", "2", "-hls_list_size", "0", str(www / "s.m3u8")],
        check=True,
    )
    job_id = make_job(db)
    dest = str(tmp_path / "out" / "Show - S01E01 - 720p.mp4")
    with Session(db) as s:
        ok = asyncio.run(downloader.download_m3u8(job_id, f"{url}/s.m3u8", url + "/", dest, s))
    assert ok, job_state(db, job_id)
    assert os.path.getsize(dest) > 1000 and not os.path.exists(dest + ".part")
    probe = subprocess.run(["ffmpeg", "-v", "error", "-i", dest, "-f", "null", "-"], capture_output=True, text=True)
    assert probe.returncode == 0 and probe.stderr == ""  # a valid, fully readable MP4
    assert job_state(db, job_id)[:2] == (JobStatus.DOWNLOADING, 100)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_hls_failure_cleans_up(db, server, tmp_path):
    url, _ = server
    job_id = make_job(db)
    dest = str(tmp_path / "out" / "bad.mp4")
    with Session(db) as s:
        ok = asyncio.run(downloader.download_m3u8(job_id, f"{url}/missing.m3u8", url + "/", dest, s))
    assert not ok and not os.path.exists(dest) and not os.path.exists(dest + ".part")
    assert job_state(db, job_id)[0] == JobStatus.FAILED
