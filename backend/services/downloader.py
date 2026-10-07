"""
Downloader service — streams an MP4 URL (or an HLS stream via ffmpeg) to disk and
updates job progress.

Files are written to `<dest>.part` and atomically renamed on success, so Radarr/Sonarr
can never import a half-downloaded file.
"""
import asyncio
import os
import re
import shutil
import time
import logging
from typing import Optional

import httpx
from sqlmodel import Session

from backend import config
from backend.models import DownloadJob, JobStatus

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://einthusan.tv",
    "Accept-Encoding": "identity",  # we stream raw bytes and compare against Content-Length
}

_MIN_FREE_BYTES = 200 * 1024 * 1024  # keep this much free on top of the download size
_FFMPEG_STALL_SECONDS = 900          # no progress for this long -> give up


def _safe_name(s: str) -> str:
    """Strip path-unsafe characters from a filename component."""
    return re.sub(r'[<>:"/\\|?*]', "", s).strip()


def get_movie_file_path(folder: str, title: str, year: Optional[int], resolution: str = "720p") -> str:
    """Return the full file path where the movie should be saved.

    The filename includes the resolution so that Radarr parses it correctly
    when it rescans after download. This lets Radarr upgrade the file to a
    better quality release grabbed from a proper indexer later.
    """
    folder_name = _safe_name(f"{title} ({year})" if year else title)
    filename = f"{folder_name} - {resolution}.mp4"
    return os.path.join(folder, filename)


def get_episode_file_path(folder: str, series_title: str, season: int, episode: int, resolution: str = "720p") -> str:
    """Full path for a TV episode, named so Sonarr can parse it: 'Show - S01E02 - 720p.mp4'."""
    safe_title = "".join(c for c in (series_title or "") if c.isalnum() or c in " -_.").strip()
    return f"{folder.rstrip('/')}/{safe_title} - S{int(season):02d}E{int(episode):02d} - {resolution}.mp4"


ACTIVE_DIRECT_DOWNLOADS = set()
ACTIVE_DOWNLOAD_PROCESSES = {}  # Map job_id to asyncio.subprocess.Process
_CANCELLED = set()              # job ids the user cancelled (their status is set by the router)

# Cap simultaneous downloads so bulk triggers don't open dozens of streams / ffmpeg processes.
_DOWNLOAD_SEM = asyncio.Semaphore(config.MAX_CONCURRENT_DOWNLOADS)


def is_direct_download_active(job_id: int) -> bool:
    return job_id in ACTIVE_DIRECT_DOWNLOADS


def _update_job_progress(session: Session, job_id: int, downloaded: int, total: int, pct: int, status: JobStatus = JobStatus.DOWNLOADING, error: Optional[str] = None):
    job = session.get(DownloadJob, job_id)
    if not job:
        return
    job.downloaded_bytes = downloaded
    job.total_bytes = total
    job.progress_pct = pct
    job.status = status
    if error:
        job.error_msg = error
    session.add(job)
    session.commit()


def _check_disk_space(directory: str, needed: int) -> None:
    if not needed:
        return
    try:
        free = shutil.disk_usage(directory).free
    except OSError:
        return
    if free < needed + _MIN_FREE_BYTES:
        raise Exception(
            f"Not enough disk space in {directory}: {free // (1024 * 1024)} MB free, "
            f"need about {needed // (1024 * 1024)} MB"
        )


def _remove(path: str) -> None:
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError as e:
        logger.warning(f"Could not remove partial file {path}: {e}")


def _fail(session: Session, job_id: int, error: str) -> None:
    """Record a failed download unless the user cancelled it (the router already set that state)."""
    if job_id in _CANCELLED:
        return
    _update_job_progress(session, job_id, 0, 0, 0, status=JobStatus.FAILED, error=error)


async def download_movie(
    job_id: int, url: str, dest_path: str, session: Session
) -> bool:
    """
    Downloads a file in chunks and updates the DB with progress.
    Returns True if successful, False otherwise.
    """
    ACTIVE_DIRECT_DOWNLOADS.add(job_id)
    _CANCELLED.discard(job_id)
    tmp_path = dest_path + ".part"
    try:
        async with _DOWNLOAD_SEM:
            if job_id not in ACTIVE_DIRECT_DOWNLOADS:  # cancelled while queued
                raise Exception("Download cancelled by user")
            logger.info(f"Starting download to {dest_path}")
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)

            async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers=_HEADERS) as client:
                async with client.stream("GET", url) as resp:
                    resp.raise_for_status()
                    total_bytes = int(resp.headers.get("content-length", 0))
                    _check_disk_space(os.path.dirname(dest_path), total_bytes)

                    with open(tmp_path, "wb") as f:
                        downloaded = 0
                        last_pct = -1

                        async for chunk in resp.aiter_bytes(chunk_size=1024 * 1024):  # 1MB chunks
                            if job_id not in ACTIVE_DIRECT_DOWNLOADS:
                                raise Exception("Download cancelled by user")

                            f.write(chunk)
                            downloaded += len(chunk)

                            if total_bytes:
                                pct = int((downloaded / total_bytes) * 100)
                                if pct > last_pct:
                                    _update_job_progress(session, job_id, downloaded, total_bytes, pct)
                                    last_pct = pct

                    if total_bytes and not resp.headers.get("content-encoding") and downloaded != total_bytes:
                        raise Exception(f"Incomplete download: got {downloaded} of {total_bytes} bytes")

            os.replace(tmp_path, dest_path)
        logger.info(f"Finished download for Job {job_id}")
        return True

    except Exception as e:
        logger.error(f"Download error for Job {job_id}: {e}")
        _fail(session, job_id, str(e))
        _remove(tmp_path)
        return False
    finally:
        ACTIVE_DIRECT_DOWNLOADS.discard(job_id)
        ACTIVE_DOWNLOAD_PROCESSES.pop(job_id, None)
        _CANCELLED.discard(job_id)


async def _drain_stderr(stream, state: dict) -> None:
    """Keep ffmpeg's stderr drained (so it never blocks) and remember the duration + tail."""
    while True:
        line = await stream.readline()
        if not line:
            return
        text = line.decode("utf-8", errors="ignore").strip()
        state["tail"].append(text)
        del state["tail"][:-40]
        if not state["duration"]:
            m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", text)
            if m:
                state["duration"] = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))


async def download_m3u8(
    job_id: int, url: str, referer: str, dest_path: str, session: Session
) -> bool:
    """
    Downloads an HLS stream (.m3u8) to MP4 using ffmpeg, reporting real progress.
    """
    ACTIVE_DIRECT_DOWNLOADS.add(job_id)
    _CANCELLED.discard(job_id)
    tmp_path = dest_path + ".part"
    try:
        async with _DOWNLOAD_SEM:
            if job_id not in ACTIVE_DIRECT_DOWNLOADS:  # cancelled while queued
                raise Exception("Download cancelled by user")
            logger.info(f"Starting m3u8 ffmpeg download to {dest_path}")
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            _update_job_progress(session, job_id, 0, 0, 1, status=JobStatus.DOWNLOADING)

            headers_arg = f"Referer: {referer}\r\nUser-Agent: {_HEADERS['User-Agent']}\r\n"

            cmd = [
                "ffmpeg",
                "-nostdin",
                "-nostats",
                "-progress", "pipe:1",
                "-y",  # Overwrite output files
                "-rw_timeout", "15000000",
                "-reconnect", "1",
                "-reconnect_streamed", "1",
                # NB: no -reconnect_at_eof — with it ffmpeg never exits after the last segment on
                # servers that close the connection at EOF, so downloads hang after finishing.
                "-reconnect_on_network_error", "1",
                "-reconnect_on_http_error", "4xx,5xx",
                "-reconnect_delay_max", "5",
                "-headers", headers_arg,
                "-i", url,
                "-c", "copy",
                "-bsf:a", "aac_adtstoasc",
                "-f", "mp4",
                tmp_path,
            ]

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=1024 * 1024,
            )
            ACTIVE_DOWNLOAD_PROCESSES[job_id] = process

            state = {"duration": 0.0, "tail": []}
            err_task = asyncio.create_task(_drain_stderr(process.stderr, state))
            last_pct, last_write, size_bytes = 1, 0.0, 0
            finished = False  # ffmpeg reported progress=end
            try:
                while True:
                    try:
                        raw = await asyncio.wait_for(process.stdout.readline(), timeout=_FFMPEG_STALL_SECONDS)
                    except asyncio.TimeoutError:
                        process.kill()
                        raise Exception("FFMPEG download stalled (no progress for 15 minutes)")
                    if not raw:
                        break
                    key, _, value = raw.decode("utf-8", errors="ignore").strip().partition("=")
                    if key == "progress" and value == "end":
                        finished = True
                    elif key == "total_size" and value.isdigit():
                        size_bytes = int(value)
                    elif key == "out_time_us" and value.lstrip("-").isdigit() and state["duration"]:
                        pct = max(1, min(99, int(int(value) / 1_000_000 / state["duration"] * 100)))
                        now = time.monotonic()
                        if pct != last_pct and now - last_write >= 3:
                            _update_job_progress(session, job_id, size_bytes, 0, pct)
                            last_pct, last_write = pct, now
                try:
                    await asyncio.wait_for(process.wait(), timeout=60)
                except asyncio.TimeoutError:
                    # Output is complete (progress=end) but ffmpeg did not exit: stop it ourselves.
                    process.kill()
                    await process.wait()
                await asyncio.wait_for(err_task, timeout=5)
            except BaseException:
                if process.returncode is None:
                    process.kill()
                err_task.cancel()
                raise

            if job_id in _CANCELLED or job_id not in ACTIVE_DIRECT_DOWNLOADS:
                raise Exception("Download cancelled by user")
            if process.returncode != 0 and not finished:
                logger.error(f"ffmpeg failed with code {process.returncode}: {chr(10).join(state['tail'][-10:])}")
                raise Exception(f"FFMPEG download failed (exit code {process.returncode})")

            os.replace(tmp_path, dest_path)
        logger.info(f"Finished m3u8 download for Job {job_id}")
        _update_job_progress(session, job_id, 0, 0, 100, status=JobStatus.DOWNLOADING)
        return True

    except Exception as e:
        logger.error(f"M3U8 Download error for Job {job_id}: {e}")
        _fail(session, job_id, str(e))
        _remove(tmp_path)
        return False
    finally:
        ACTIVE_DIRECT_DOWNLOADS.discard(job_id)
        ACTIVE_DOWNLOAD_PROCESSES.pop(job_id, None)
        _CANCELLED.discard(job_id)


def cancel_download(job_id: int):
    """
    Cancels an active (or queued) download for the given job_id.
    """
    was_active = job_id in ACTIVE_DIRECT_DOWNLOADS
    ACTIVE_DIRECT_DOWNLOADS.discard(job_id)
    if was_active:
        _CANCELLED.add(job_id)
    process = ACTIVE_DOWNLOAD_PROCESSES.get(job_id)
    if process:
        logger.info(f"Killing active download process for job {job_id}")
        try:
            process.kill()
        except ProcessLookupError:
            pass
        except Exception as e:
            logger.warning(f"Failed to kill download process for job {job_id}: {e}")
