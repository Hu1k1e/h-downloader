"""
FMovies API scraper.

This directly accesses the vidlink.pro API (which powers f-movies.org) 
using native PyNaCl AES encryption to bypass Cloudflare and JS execution.
Uses TMDB IDs for exact matches.
"""
import logging
import time
import base64
import struct
from typing import Optional, Tuple

import httpx
import nacl.secret

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Origin": "https://vidlink.pro",
    "Referer": "https://vidlink.pro/"
}

# The hardcoded key used by the vidlink player to authenticate API requests
_VIDLINK_KEY_HEX = "c75136c5668bbfe65a7ecad431a745db68b5f381555b38d8f6c699449cf11fcd"
_VIDLINK_KEY = bytes.fromhex(_VIDLINK_KEY_HEX)
_BOX = nacl.secret.SecretBox(_VIDLINK_KEY)
_NONCE = bytes(24)

def _encrypt_token(media_id: str) -> str:
    """Generates an encrypted time-based token for the API."""
    timestamp = int(time.time() + 480)
    message = media_id.encode("utf-8") + struct.pack(">Q", timestamp)
    encrypted = _BOX.encrypt(message, _NONCE)
    full_payload = _NONCE + encrypted.ciphertext
    return base64.urlsafe_b64encode(full_payload).decode("utf-8").rstrip("=")

async def search_movie(tmdb_id: int, title: str, year: Optional[int], settings) -> Optional[str]:
    """Search for a movie on FMovies (vidlink). Returns the TMDB ID as a string if successful."""
    token = _encrypt_token(str(tmdb_id))
    url = f"https://vidlink.pro/api/b/movie/{token}?multiLang=1"
    
    async with httpx.AsyncClient(timeout=15) as client:
        try:
            resp = await client.get(url, headers=_HEADERS)
            if resp.status_code == 200:
                data = resp.json()
                if data and "stream" in data:
                    logger.info(f"FMovies (vidlink) found movie source for TMDB {tmdb_id}")
                    return str(tmdb_id)
        except Exception as e:
            logger.warning(f"FMovies (vidlink) search failed for movie {tmdb_id}: {e}")
            
    return None

async def search_tv(tmdb_id: int, title: str, season: int, episode: int, settings) -> Optional[str]:
    """Search for a TV episode on FMovies (vidlink). Returns the routing string if successful."""
    token = _encrypt_token(str(tmdb_id))
    url = f"https://vidlink.pro/api/b/tv/{token}/{season}/{episode}?multiLang=1"
    
    async with httpx.AsyncClient(timeout=15) as client:
        try:
            resp = await client.get(url, headers=_HEADERS)
            if resp.status_code == 200:
                data = resp.json()
                if data and "stream" in data:
                    logger.info(f"FMovies (vidlink) found TV source for TMDB {tmdb_id} S{season}E{episode}")
                    return f"{tmdb_id}/{season}/{episode}"
        except Exception as e:
            logger.warning(f"FMovies (vidlink) search failed for TV {tmdb_id} S{season}E{episode}: {e}")
            
    return None

async def extract_stream_url(watch_url_or_id: str, settings) -> Optional[Tuple[str, str, str]]:
    """
    Extract the actual m3u8/mp4 stream from the vidlink API.
    Since we return the TMDB ID from search_*, watch_url_or_id is just the ID or 'id/season/episode'.
    """
    parts = watch_url_or_id.split("/")
    
    if len(parts) == 3:
        # TV Show
        tmdb_id, season, episode = parts[0], parts[1], parts[2]
        token = _encrypt_token(tmdb_id)
        url = f"https://vidlink.pro/api/b/tv/{token}/{season}/{episode}?multiLang=1"
    else:
        # Movie
        tmdb_id = parts[0]
        token = _encrypt_token(tmdb_id)
        url = f"https://vidlink.pro/api/b/movie/{token}?multiLang=1"
        
    logger.info(f"FMovies (vidlink) extracting stream via API for {watch_url_or_id}")
    
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, headers=_HEADERS)
            resp.raise_for_status()
            data = resp.json()
            
            stream = data.get("stream", {})
            qualities = stream.get("qualities", {})
            
            if not qualities:
                logger.error(f"FMovies (vidlink) returned no qualities for {watch_url_or_id}")
                return None
                
            # Pick highest quality (1080p > 720p > 480p > 360p)
            best_quality = None
            best_resolution = 0
            
            for q_str, q_data in qualities.items():
                if q_str.isdigit():
                    res = int(q_str)
                    if res > best_resolution:
                        best_resolution = res
                        best_quality = q_data
            
            if best_quality and "url" in best_quality:
                stream_url = best_quality["url"]
                
                # Some servers require specific headers returned in the API response
                stream_headers = best_quality.get("headers", {})
                referer = stream_headers.get("referer", _HEADERS["Referer"])
                
                logger.info(f"FMovies successfully extracted {best_resolution}p stream via API: {stream_url[:50]}...")
                return stream_url, referer, _HEADERS["User-Agent"]
                
            logger.error(f"FMovies (vidlink) no valid URL found in qualities for {watch_url_or_id}")
            return None
            
    except Exception as e:
        logger.error(f"FMovies (vidlink) API extraction error: {e}")
        return None
