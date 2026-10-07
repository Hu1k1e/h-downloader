import re
import qbittorrentapi
import logging
from typing import Optional, Dict, Any, List
from backend.models import AppSettings

logger = logging.getLogger(__name__)

import base64
import binascii

VIDEO_EXTS = ('.mp4', '.mkv', '.avi', '.webm', '.ts')

# Sentinel returned by filter_torrent_files when the torrent's file list is not known yet
# (magnet metadata still downloading). The caller should simply retry later.
NO_METADATA = "NO_METADATA"


class QbittorrentError(Exception):
    """qBittorrent could not be reached / authenticated (distinct from 'torrent not found')."""


def extract_hash_from_magnet(magnet_link: str) -> Optional[str]:
    match = re.search(r'urn:btih:([a-zA-Z0-9]+)', magnet_link, re.IGNORECASE)
    if not match:
        return None
    hash_str = match.group(1).upper()
    if len(hash_str) == 32:
        try:
            return binascii.hexlify(base64.b32decode(hash_str)).decode('utf-8').lower()
        except Exception:
            pass
    return hash_str.lower()


def _client(settings: AppSettings) -> "qbittorrentapi.Client":
    client = qbittorrentapi.Client(
        host=settings.qbittorrent_url,
        username=settings.qbittorrent_username,
        password=settings.qbittorrent_password,
    )
    client.auth_log_in()
    return client


def add_magnet_to_qbittorrent(magnet_link: str, settings: AppSettings, is_tv: bool = False) -> Optional[str]:
    """
    Adds a magnet link to qBittorrent with the configured category (series category for TV).
    Returns the torrent hash if successful, else None.
    """
    if not settings.qbittorrent_url:
        logger.error("qBittorrent URL is not configured.")
        return None

    category = settings.qbittorrent_category_series if is_tv else settings.qbittorrent_category_movies
    try:
        qbt_client = _client(settings)
        logger.info(f"Adding magnet to qBittorrent with category: {category}")
        qbt_client.torrents_add(urls=magnet_link, category=category)
        return extract_hash_from_magnet(magnet_link)
    except Exception as e:
        if "Conflict" in str(e):
            logger.info("Magnet already exists in qBittorrent. Returning hash anyway.")
            return extract_hash_from_magnet(magnet_link)
        logger.error(f"Failed to add magnet to qBittorrent: {e}")
        return None


def _torrent_dict(t) -> Dict[str, Any]:
    return {
        "hash": t.hash,
        "name": t.name,
        "state": t.state,
        "progress": t.progress,
        "downloaded": t.completed,
        "size": t.size,
        "total_size": t.size,
        "eta": getattr(t, "eta", 0) or 0,
    }


def get_torrents_info(torrent_hashes: List[str], settings: AppSettings) -> Dict[str, Dict[str, Any]]:
    """Fetch several torrents in one request. Returns {hash: info}; missing torrents are absent.
    Raises QbittorrentError if qBittorrent cannot be reached."""
    hashes = [h for h in torrent_hashes if h]
    if not settings.qbittorrent_url or not hashes:
        return {}
    try:
        qbt_client = _client(settings)
        torrents = qbt_client.torrents_info(torrent_hashes="|".join(hashes))
    except Exception as e:
        raise QbittorrentError(str(e)) from e
    return {t.hash.lower(): _torrent_dict(t) for t in torrents}


def get_torrent_info(torrent_hash: str, settings: AppSettings) -> Optional[Dict[str, Any]]:
    """
    Fetches the info for a specific torrent by its hash.
    Returns a dict with 'state', 'progress' (0.0-1.0), 'downloaded', 'size', 'eta' ...
    Returns None if the torrent is not found.
    Raises QbittorrentError if qBittorrent is unreachable, so callers never mistake an
    outage for a removed torrent.
    """
    if not settings.qbittorrent_url or not torrent_hash:
        return None
    return get_torrents_info([torrent_hash], settings).get(torrent_hash.lower())


def delete_torrent(torrent_hash: str, settings: AppSettings) -> bool:
    """
    Deletes the torrent and its downloaded data from qBittorrent.
    """
    if not settings.qbittorrent_url or not torrent_hash:
        return False

    try:
        qbt_client = _client(settings)
        qbt_client.torrents_delete(delete_files=True, torrent_hashes=torrent_hash)
        logger.info(f"Deleted invalid/failed torrent {torrent_hash} from qBittorrent.")
        return True
    except Exception as e:
        logger.error(f"Failed to delete torrent {torrent_hash}: {e}")
        return False


def filter_torrent_files(torrent_hash: str, settings: AppSettings, enforce_size: bool = True) -> tuple[bool, Optional[str]]:
    """
    Looks at all files in the torrent. Identifies the largest video file.
    Validates that it is indeed a video file and (optionally) within configured size limits.
    If valid, sets the priority of all other files to 0 (Do Not Download).
    Returns (True, None) if successful.
    Returns (False, NO_METADATA) if the file list is not available yet.
    Returns (False, error_msg) if the torrent is invalid (no video, wrong size).
    """
    if not settings.qbittorrent_url or not torrent_hash:
        return False, "qBittorrent URL or hash missing"

    try:
        qbt_client = _client(settings)

        files = qbt_client.torrents_files(torrent_hash=torrent_hash)
        if not files:
            return False, NO_METADATA

        largest_video = None
        max_size = -1
        for f in files:
            name = f.get('name', '').lower()
            size = f.get('size', 0)
            if name.endswith(VIDEO_EXTS) and size > max_size:
                max_size = size
                largest_video = f

        if not largest_video:
            return False, "No valid video file (.mp4, .mkv, etc.) found in torrent"

        size_mb = max_size / (1024 * 1024)
        if enforce_size:
            if size_mb < settings.min_file_size_mb:
                return False, f"Main video file is too small ({size_mb:.1f} MB < {settings.min_file_size_mb} MB limit)"
            if size_mb > settings.max_file_size_mb:
                return False, f"Main video file is too large ({size_mb:.1f} MB > {settings.max_file_size_mb} MB limit)"

        # Season packs: keep every video file for TV (enforce_size False), only the largest for movies.
        keep = {f.get('index') for f in files if f.get('name', '').lower().endswith(VIDEO_EXTS)} if not enforce_size \
            else {largest_video.get('index')}
        unwanted_indices = [f.get('index') for f in files if f.get('index') not in keep and f.get('priority') != 0]

        if unwanted_indices:
            qbt_client.torrents_file_priority(
                torrent_hash=torrent_hash,
                file_ids='|'.join(str(idx) for idx in unwanted_indices),
                priority=0
            )
            logger.info(f"Filtered torrent {torrent_hash}: keeping {len(keep)} video file(s), ignoring {len(unwanted_indices)} other file(s).")

        return True, None
    except Exception as e:
        # Transient (connection/API) failure: never treat as an invalid torrent, just retry later.
        logger.error(f"Failed to filter torrent files: {e}")
        return False, NO_METADATA
