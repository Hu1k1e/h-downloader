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

def add_magnet_to_qbittorrent(magnet_link: str, settings: AppSettings, rename: Optional[str] = None) -> Optional[str]:
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
        kwargs = {
            "urls": magnet_link,
            "category": settings.qbittorrent_category_movies,
        }
        if rename:
            kwargs["rename"] = rename
            
        qbt_client.torrents_add(**kwargs)
        
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
