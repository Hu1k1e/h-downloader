from backend.database import get_settings
from backend.services.qbittorrent import get_torrent_info
import asyncio

settings = get_settings()
print(get_torrent_info("6b8f3c0c12c1ab7f20bfdc182cbd394875cf5010", settings))
