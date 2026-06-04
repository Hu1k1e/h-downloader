import re
import qbittorrentapi
import logging
from typing import Optional, Dict, Any
from backend.models import AppSettings

logger = logging.getLogger(__name__)

import base64
import binascii

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

def add_magnet_to_qbittorrent(magnet_link: str, settings: AppSettings) -> Optional[str]:
    """
    Adds a magnet link to qBittorrent with the configured category.
    Returns the torrent hash if successful, else None.
    """
    if not settings.qbittorrent_url:
        logger.error("qBittorrent URL is not configured.")
        return None
        
    try:
        qbt_client = qbittorrentapi.Client(
            host=settings.qbittorrent_url,
            username=settings.qbittorrent_username,
            password=settings.qbittorrent_password,
        )
        
        qbt_client.auth_log_in()
        
        logger.info(f"Adding magnet to qBittorrent with category: {settings.qbittorrent_category_movies}")
        qbt_client.torrents_add(
            urls=magnet_link,
            category=settings.qbittorrent_category_movies,
        )
        
        return extract_hash_from_magnet(magnet_link)
    except Exception as e:
        logger.error(f"Failed to add magnet to qBittorrent: {e}")
        return None

def get_torrent_info(torrent_hash: str, settings: AppSettings) -> Optional[Dict[str, Any]]:
    """
    Fetches the info for a specific torrent by its hash.
    Returns a dict with 'state', 'progress' (0.0 to 1.0), 'downloaded', 'total_size', etc.
    Returns None if the torrent is not found.
    """
    if not settings.qbittorrent_url or not torrent_hash:
        return None
        
    try:
        qbt_client = qbittorrentapi.Client(
            host=settings.qbittorrent_url,
            username=settings.qbittorrent_username,
            password=settings.qbittorrent_password,
        )
        qbt_client.auth_log_in()
        
        torrents = qbt_client.torrents_info(torrent_hashes=torrent_hash)
        if not torrents:
            return None
            
        t = torrents[0]
        return {
            "hash": t.hash,
            "name": t.name,
            "state": t.state,
            "progress": t.progress,
            "downloaded": t.completed,
            "total_size": t.size,
        }
    except Exception as e:
        logger.error(f"Failed to get torrent info from qBittorrent: {e}")
        return None

def delete_torrent(torrent_hash: str, settings: AppSettings) -> bool:
    """
    Deletes the torrent and its downloaded data from qBittorrent.
    """
    if not settings.qbittorrent_url or not torrent_hash:
        return False
        
    try:
        qbt_client = qbittorrentapi.Client(
            host=settings.qbittorrent_url,
            username=settings.qbittorrent_username,
            password=settings.qbittorrent_password,
        )
        qbt_client.auth_log_in()
        
        qbt_client.torrents_delete(delete_files=True, torrent_hashes=torrent_hash)
        logger.info(f"Deleted invalid/failed torrent {torrent_hash} from qBittorrent.")
        return True
    except Exception as e:
        logger.error(f"Failed to delete torrent {torrent_hash}: {e}")
        return False

def filter_torrent_files(torrent_hash: str, settings: AppSettings) -> tuple[bool, Optional[str]]:
    """
    Looks at all files in the torrent. Identifies the largest video file.
    Validates that it is indeed a video file and within configured size limits.
    If valid, sets the priority of all other files to 0 (Do Not Download).
    Returns (True, None) if successful.
    Returns (False, error_msg) if the torrent is invalid (no video, wrong size).
    """
    if not settings.qbittorrent_url or not torrent_hash:
        return False, "qBittorrent URL or hash missing"
        
    try:
        qbt_client = qbittorrentapi.Client(
            host=settings.qbittorrent_url,
            username=settings.qbittorrent_username,
            password=settings.qbittorrent_password,
        )
        qbt_client.auth_log_in()
        
        files = qbt_client.torrents_files(torrent_hash=torrent_hash)
        if not files:
            return False, "No files found in torrent metadata"
            
        video_exts = ('.mp4', '.mkv', '.avi', '.webm', '.ts')
        
        # Find the largest video file strictly matching extensions
        largest_video = None
        max_size = -1
        
        for f in files:
            name = f.get('name', '').lower()
            size = f.get('size', 0)
            if name.endswith(video_exts) and size > max_size:
                max_size = size
                largest_video = f
                
        if not largest_video:
            return False, "No valid video file (.mp4, .mkv, etc.) found in torrent"
            
        # Size validation
        size_mb = max_size / (1024 * 1024)
        if size_mb < settings.min_file_size_mb:
            return False, f"Main video file is too small ({size_mb:.1f} MB < {settings.min_file_size_mb} MB limit)"
        if size_mb > settings.max_file_size_mb:
            return False, f"Main video file is too large ({size_mb:.1f} MB > {settings.max_file_size_mb} MB limit)"
            
        # Set priority=0 for all other files
        unwanted_indices = []
        for f in files:
            if f.get('index') != largest_video.get('index'):
                # Only change priority if it's not already 0
                if f.get('priority') != 0:
                    unwanted_indices.append(f.get('index'))
                    
        if unwanted_indices:
            qbt_client.torrents_file_priority(
                torrent_hash=torrent_hash, 
                file_ids='|'.join(str(idx) for idx in unwanted_indices), 
                priority=0
            )
            logger.info(f"Filtered torrent {torrent_hash}: downloading main file '{largest_video.get('name')}', ignoring {len(unwanted_indices)} other file(s).")
            
        return True, None
    except Exception as e:
        logger.error(f"Failed to filter torrent files: {e}")
        return False, str(e)

