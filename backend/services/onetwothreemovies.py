"""
123movies scraper and MP4 extraction.
"""
import asyncio
import logging
import re
import httpx
from typing import Optional, Tuple
from bs4 import BeautifulSoup
from backend import config

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

_THEATRE_KEYWORDS = ["cam", "ts", "hdcam", "telesync", "hd-ts", "camrip", "tc"]

def _is_theatre_screening(title: str, quality_badge: str) -> bool:
    """Return True if the title or badge suggests a theatre recording."""
    combined = f"{title} {quality_badge}".lower()
    # Tokenize to avoid matching substrings like "webcam" -> "cam"
    tokens = re.findall(r'\b\w+\b', combined)
    for kw in _THEATRE_KEYWORDS:
        if kw in tokens:
            return True
    return False

async def search_media(title: str, year: Optional[int], is_series: bool = False, season: Optional[int] = None, episode: Optional[int] = None) -> Optional[str]:
    """Search 123movies and return the watch page URL."""
    base_url = config.ONETWOTHREEMOVIES_BASE_URL.rstrip('/')
    
    search_query = title.replace(" ", "+")
    if is_series and season is not None:
        search_query += f"+season+{season}"
        
    search_url = f"{base_url}/search/{search_query}.html"
    
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers=_HEADERS) as client:
            resp = await client.get(search_url)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")
            
            items = soup.select(".flw-item, .film-poster, .ml-item, .item")
            
            for item in items:
                a_tag = item.find("a")
                if not a_tag or not a_tag.get("href"):
                    continue
                    
                href = a_tag["href"]
                item_title = a_tag.get("title", "") or a_tag.get_text(strip=True)
                
                quality_tag = item.select_one(".quality, .pick, .film-poster-quality, .tag")
                quality_badge = quality_tag.get_text(strip=True) if quality_tag else ""
                
                if _is_theatre_screening(item_title, quality_badge):
                    logger.info(f"Skipping '{item_title}' - identified as theatre screening (CAM/TS).")
                    continue
                    
                # Basic match validation
                # Ignore punctuation and case
                clean_title = re.sub(r'[^\w\s]', '', title).lower()
                clean_item_title = re.sub(r'[^\w\s]', '', item_title).lower()
                
                if clean_title in clean_item_title:
                    if href.startswith("http"):
                        return href
                    return f"{base_url}{href if href.startswith('/') else '/' + href}"
                    
    except Exception as e:
        logger.error(f"123movies search failed: {e}")
        
    return None

async def extract_mp4_url(watch_url: str, is_series: bool = False, season: Optional[int] = None, episode: Optional[int] = None) -> Optional[str]:
    """
    Extract the direct video stream URL from the watch page.
    """
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers=_HEADERS) as client:
            # If it's a series, we might need to modify the watch url to point to the specific episode
            # Many 123movies clones use URL patterns like /watch-tv/show-name-season-1-episode-2.html
            if is_series and season and episode:
                # Attempt to append or replace episode string
                watch_url = re.sub(r'episode-\d+', f'episode-{episode}', watch_url)
                
            resp = await client.get(watch_url)
            resp.raise_for_status()
            
            soup = BeautifulSoup(resp.text, "lxml")
            
            # Look for common iframe players
            iframe = soup.find("iframe")
            if iframe and iframe.get("src"):
                iframe_src = iframe["src"]
                
                if not iframe_src.startswith("http"):
                    iframe_src = "https:" + iframe_src if iframe_src.startswith("//") else iframe_src
                    
                iframe_resp = await client.get(iframe_src)
                
                match = re.search(r'(https?://[^\s\'"]+\.(?:mp4|m3u8)[^\s\'"]*)', iframe_resp.text)
                if match:
                    return match.group(1)
                    
            # Fallback directly in page
            match = re.search(r'(https?://[^\s\'"]+\.(?:mp4|m3u8)[^\s\'"]*)', resp.text)
            if match:
                return match.group(1)
                
    except Exception as e:
        logger.error(f"123movies MP4 extraction failed: {e}")
        
    return None
