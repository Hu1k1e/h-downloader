"""
FMovies scraper (and its various clones).

Aggregator site that embeds video players (like VidSrc) via iframes.
Uses TMDB IDs and title searches.
"""
import logging
import re
from typing import Optional, Tuple
from urllib.parse import quote_plus

import httpx
from bs4 import BeautifulSoup
from rapidfuzz import fuzz

from backend.services.llm import generate_search_variants_with_llm
from backend.services.bollyzone import unpack_juicy

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

async def search_movie(tmdb_id: int, title: str, year: Optional[int], settings) -> Optional[str]:
    """Search for a movie on FMovies."""
    base_url = getattr(settings, "fmovies_base_url", "https://www.f-movies.org").rstrip("/")
    
    # Method 1: Try direct TMDB ID routing (common on VidSrc wrappers)
    direct_url = f"{base_url}/movie/{tmdb_id}"
    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
        try:
            resp = await client.get(direct_url, headers=_HEADERS)
            if resp.status_code == 200 and "iframe" in resp.text.lower():
                logger.info(f"FMovies direct TMDB match: {direct_url}")
                return direct_url
        except Exception:
            pass

    # Method 2: Search by title variants
    variants = [title]
    if settings.llm_enabled and settings.llm_api_key:
        try:
            from backend.services.llm import generate_search_variants_with_llm
            llm_vars = await generate_search_variants_with_llm(title, year)
            for v in llm_vars:
                if v and v.lower() not in [x.lower() for x in variants]:
                    variants.append(v)
        except Exception as e:
            logger.warning(f"FMovies LLM variant generation failed: {e}")

    for variant in variants:
        url = await _search_fmovies(base_url, variant, year, tmdb_id, "movie")
        if url:
            return url

    return None

async def search_tv(tmdb_id: int, title: str, season: int, episode: int, settings) -> Optional[str]:
    """Search for a TV episode on FMovies."""
    base_url = getattr(settings, "fmovies_base_url", "https://www.f-movies.org").rstrip("/")
    
    # Method 1: Direct TMDB ID
    direct_url = f"{base_url}/tv/{tmdb_id}/{season}/{episode}"
    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
        try:
            resp = await client.get(direct_url, headers=_HEADERS)
            if resp.status_code == 200 and "iframe" in resp.text.lower():
                logger.info(f"FMovies direct TMDB TV match: {direct_url}")
                return direct_url
        except Exception:
            pass

    variants = [title]
    for variant in variants:
        url = await _search_fmovies(base_url, variant, None, tmdb_id, "tv")
        if url:
            # Append season/episode if the url is a base TV show url
            # e.g. /series/some-show -> /series/some-show/season/1/episode/1 (this depends on the clone)
            return f"{url}/{season}/{episode}"

    return None

async def _search_fmovies(base_url: str, query_str: str, year: Optional[int], tmdb_id: int, media_type: str) -> Optional[str]:
    """Internal search function."""
    query = quote_plus(query_str)
    search_url = f"{base_url}/search/{query}"
    if media_type == "movie":
        search_url = f"{base_url}/search?keyword={query}"
        
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(search_url, headers=_HEADERS)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")
    except Exception as e:
        logger.warning(f"FMovies search failed for {query_str}: {e}")
        return None

    anchors = soup.find_all("a", href=True)
    best_score = 0
    best_url = None

    for a in anchors:
        href = a.get("href", "")
        if media_type == "movie" and "/movie/" not in href and "/film/" not in href:
            continue
        if media_type == "tv" and "/tv/" not in href and "/series/" not in href:
            continue
            
        card_title = a.get_text(strip=True)
        if not card_title:
            img = a.find("img")
            if img:
                card_title = img.get("alt", "").strip()
                
        if not card_title:
            continue
            
        score = fuzz.token_sort_ratio(query_str.lower(), card_title.lower())
        if score > best_score:
            best_score = score
            best_url = href if href.startswith("http") else f"{base_url.rstrip('/')}/{href.lstrip('/')}"
            
    if best_score > 85 and best_url:
        logger.info(f"FMovies search match: {best_url} (score={best_score})")
        return best_url
        
    return None

async def extract_stream_url(watch_url: str, settings) -> Optional[Tuple[str, str, str]]:
    """
    Extract the actual m3u8 stream from an FMovies watch page.
    Follows iframe redirects and parses embed pages.
    """
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        try:
            resp = await client.get(watch_url, headers=_HEADERS)
            resp.raise_for_status()
        except Exception as e:
            logger.error(f"FMovies failed to fetch watch page {watch_url}: {e}")
            return None

        soup = BeautifulSoup(resp.text, "lxml")
        
        # 1. Find iframe embed
        iframe = soup.find("iframe")
        if not iframe or not iframe.get("src"):
            # Try to find a player div with data-src
            player_div = soup.find("div", {"id": "player"})
            if player_div and player_div.get("data-src"):
                embed_url = player_div["data-src"]
            else:
                logger.error("FMovies no iframe or player found on watch page")
                return None
        else:
            embed_url = iframe["src"]
            
        if embed_url.startswith("//"):
            embed_url = "https:" + embed_url
        elif embed_url.startswith("/"):
            base = "/".join(watch_url.split("/")[:3])
            embed_url = base + embed_url

        logger.info(f"FMovies found embed URL: {embed_url}")

        # 2. Fetch embed page
        try:
            embed_resp = await client.get(embed_url, headers={"Referer": watch_url, **_HEADERS})
            embed_resp.raise_for_status()
            html = embed_resp.text
        except Exception as e:
            logger.error(f"FMovies failed to fetch embed page {embed_url}: {e}")
            return None

        # 3. Look for JuicyCodes or direct m3u8
        m3u8_url = None
        
        # Check for unpacked m3u8
        m3u8_match = re.search(r'file:\s*["\'](https?://[^"\']+\.m3u8[^"\']*)["\']', html)
        if m3u8_match:
            m3u8_url = m3u8_match.group(1)
        else:
            # Check for juicycodes packing
            packed_match = re.search(r"eval\((function\(p,a,c,k,e,d\).*?)\)", html)
            if packed_match:
                packed_code = packed_match.group(1)
                unpacked = unpack_juicy(packed_code)
                if unpacked:
                    src_match = re.search(r'src["\']\s*:\s*["\'](https?://[^"\']+\.m3u8[^"\']*)["\']', unpacked)
                    if src_match:
                        m3u8_url = src_match.group(1)
                        
        if m3u8_url:
            if m3u8_url.startswith("//"):
                m3u8_url = "https:" + m3u8_url
            logger.info(f"FMovies successfully extracted m3u8: {m3u8_url[:50]}...")
            return m3u8_url, embed_url, _HEADERS["User-Agent"]
            
        logger.error(f"FMovies failed to extract m3u8 from {embed_url}")
        return None
