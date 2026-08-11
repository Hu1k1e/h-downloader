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
            "-y", # Overwrite output files
            "-allowed_extensions", "ALL,juicycodes",
            "-allowed_segment_extensions", "ALL,juicycodes",
            "-headers", headers_arg,
            "-i", url,
            "-c", "copy",
            "-bsf:a", "aac_adtstoasc",
            dest_path
        ]
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            logger.error(f"ffmpeg failed with code {process.returncode}: {stderr.decode('utf-8', errors='ignore')}")
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
