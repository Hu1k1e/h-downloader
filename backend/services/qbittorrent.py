import qbittorrentapi
import logging
from backend.models import AppSettings

logger = logging.getLogger(__name__)

def add_magnet_to_qbittorrent(magnet_link: str, settings: AppSettings) -> bool:
    """
    Adds a magnet link to qBittorrent with the configured category.
    """
    if not settings.qbittorrent_url:
        logger.error("qBittorrent URL is not configured.")
        return False
        
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
        
        return True
    except Exception as e:
        logger.error(f"Failed to add magnet to qBittorrent: {e}")
        return False
