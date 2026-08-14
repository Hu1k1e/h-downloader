"""
Downloader service — streams an MP4 URL to disk, updates job progress.
"""
import asyncio
import os
import re
import logging
from datetime import datetime
from typing import Optional

import httpx
from sqlmodel import Session, select

from backend import config
from backend.models import DownloadJob, JobStatus, AppSettings

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://einthusan.tv",
}


def _safe_name(s: str) -> str:
    """Strip path-unsafe characters from a filename component."""
    return re.sub(r'[<>:"/\\|?*]', "", s).strip()


def get_movie_file_path(folder: str, title: str, year: Optional[int]) -> str:
    """Return the full file path where the movie should be saved.

    The filename includes "720p" so that Radarr parses this as a 720p release
    when it rescans after download. This lets Radarr upgrade the file to a
    better quality release grabbed from a proper indexer later.
    """
    folder_name = _safe_name(f"{title} ({year})" if year else title)
    # Tag as 720p so Radarr treats this as upgradeable quality
    filename = f"{folder_name} - 720p.mp4"
    return os.path.join(folder, filename)


ACTIVE_DIRECT_DOWNLOADS = set()
ACTIVE_DOWNLOAD_PROCESSES = {}  # Map job_id to asyncio.subprocess.Process

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

async def download_movie(
    job_id: int, url: str, dest_path: str, session: Session
) -> bool:
    """
    Downloads a file in chunks and updates the DB with progress.
    Returns True if successful, False otherwise.
    """
    logger.info(f"Starting download to {dest_path}")
    ACTIVE_DIRECT_DOWNLOADS.add(job_id)
    try:
        # Ensure parent directory exists
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        
        async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers=_HEADERS) as client:
            async with client.stream("GET", url) as resp:
                resp.raise_for_status()
                total_bytes = int(resp.headers.get("content-length", 0))

                with open(dest_path, "wb") as f:
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
                                _update_job_progress(
                                    session, job_id, downloaded, total_bytes, pct
                                )
                                last_pct = pct
                                
        logger.info(f"Finished download for Job {job_id}")
        return True

    except Exception as e:
        logger.error(f"Download error for Job {job_id}: {e}")
        _update_job_progress(session, job_id, 0, 0, 0, status=JobStatus.FAILED, error=str(e))
        # Clean up partial file
        if os.path.exists(dest_path):
            os.remove(dest_path)
        return False
    finally:
        ACTIVE_DIRECT_DOWNLOADS.discard(job_id)
        ACTIVE_DOWNLOAD_PROCESSES.pop(job_id, None)


async def download_m3u8(
    job_id: int, url: str, referer: str, dest_path: str, session: Session
) -> bool:
    """
    Downloads an HLS stream (.m3u8) to MP4 using ffmpeg.
    """
    logger.info(f"Starting m3u8 ffmpeg download to {dest_path}")
    ACTIVE_DIRECT_DOWNLOADS.add(job_id)
    try:
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        
        # We don't easily know total duration, so we will just show 'Downloading...' with 50% progress
        # to indicate it's active.
        _update_job_progress(session, job_id, 0, 0, 50, status=JobStatus.DOWNLOADING)
        
        headers_arg = f"Referer: {referer}\r\nUser-Agent: {_HEADERS['User-Agent']}\r\n"
        
        cmd = [
            "ffmpeg",
            "-nostdin",
            "-y", # Overwrite output files
            "-rw_timeout", "15000000",
            "-reconnect", "1",
            "-reconnect_streamed", "1",
            "-reconnect_at_eof", "1",
            "-reconnect_on_network_error", "1",
            "-reconnect_on_http_error", "4xx,5xx",
            "-reconnect_delay_max", "5",
            "-allowed_extensions", "ALL",
            "-allowed_segment_extensions", "ALL",
            "-headers", headers_arg,
            "-i", url,
            "-c", "copy",
            "-bsf:a", "aac_adtstoasc",
            dest_path
        ]
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE
        )
        
        ACTIVE_DOWNLOAD_PROCESSES[job_id] = process
        
        try:
            # We will read stderr line by line to track progress
            import time
            from backend.db_logger import log_action
            
            last_log_time = time.time()
            stderr_output = []
            
            while True:
                try:
                    line_bytes = await asyncio.wait_for(process.stderr.readline(), timeout=3600)
                except asyncio.TimeoutError:
                    process.kill()
                    logger.error(f"ffmpeg timed out reading stderr after 1 hour for Job {job_id}")
                    raise Exception("FFMPEG download timed out")
                    
                if not line_bytes:
                    break
                    
                line = line_bytes.decode('utf-8', errors='ignore').strip()
                stderr_output.append(line)
                
                # ffmpeg progress lines usually start with 'frame=' or 'size='
                if line.startswith("frame=") or line.startswith("size="):
                    current_time = time.time()
                    # Log to database every 30 seconds to prevent spam, but give user tracking
                    if current_time - last_log_time > 30:
                        # Extract time=... if present to give a readable progress
                        import re
                        time_match = re.search(r"time=(\d{2}:\d{2}:\d{2})", line)
                        size_match = re.search(r"size=\s*(\d+kB)", line)
                        
                        prog_str = []
                        if time_match: prog_str.append(f"Time: {time_match.group(1)}")
                        if size_match: prog_str.append(f"Size: {size_match.group(1)}")
                        
                        if prog_str:
                            log_action(
                                action="download_progress", 
                                message=f"FFmpeg downloading: {', '.join(prog_str)}",
                                job_id=job_id
                            )
                        last_log_time = current_time

            await process.wait()
            stderr_text = "\n".join(stderr_output)
            
        except Exception as e:
            process.kill()
            raise e
            
        if process.returncode != 0:
            logger.error(f"ffmpeg failed with code {process.returncode}: {stderr_text}")
            raise Exception("FFMPEG download failed")
            
        logger.info(f"Finished m3u8 download for Job {job_id}")
        _update_job_progress(session, job_id, 0, 0, 100, status=JobStatus.DOWNLOADING)
        return True

    except Exception as e:
        logger.error(f"M3U8 Download error for Job {job_id}: {e}")
        _update_job_progress(session, job_id, 0, 0, 0, status=JobStatus.FAILED, error=str(e))
        if os.path.exists(dest_path):
            os.remove(dest_path)
        return False
    finally:
        ACTIVE_DIRECT_DOWNLOADS.discard(job_id)
        ACTIVE_DOWNLOAD_PROCESSES.pop(job_id, None)

def cancel_download(job_id: int):
    """
    Cancels an active download process for the given job_id.
    """
    ACTIVE_DIRECT_DOWNLOADS.discard(job_id)
    process = ACTIVE_DOWNLOAD_PROCESSES.get(job_id)
    if process:
        logger.info(f"Killing active download process for job {job_id}")
        try:
            process.kill()
        except:
            pass
