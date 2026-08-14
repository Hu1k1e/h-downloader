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
import asyncio
from playwright.async_api import async_playwright

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
    
    # Method 1: Try direct TMDB ID routing
    # FMovies clones often use the format /movie/{slug}-{tmdb_id}
    slug = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')
    direct_urls = [
        f"{base_url}/movie/{slug}-{tmdb_id}",
        f"{base_url}/movie/{tmdb_id}"
    ]
    
    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
        for url in direct_urls:
            try:
                resp = await client.get(url, headers=_HEADERS)
                if resp.status_code == 200 and "iframe" in resp.text.lower():
                    logger.info(f"FMovies direct TMDB match: {url}")
                    return url
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
    slug = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')
    direct_urls = [
        f"{base_url}/tv/{slug}-{tmdb_id}?season={season}&episode={episode}",
        f"{base_url}/tv/{slug}-{tmdb_id}/{season}/{episode}",
        f"{base_url}/tv/{tmdb_id}/{season}/{episode}"
    ]
    
    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
        for url in direct_urls:
            try:
                resp = await client.get(url, headers=_HEADERS)
                if resp.status_code == 200 and "iframe" in resp.text.lower():
                    logger.info(f"FMovies direct TMDB TV match: {url}")
                    return url
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
    Extract the actual m3u8 stream from an FMovies watch page using Playwright.
    This bypasses JavaScript obfuscation and waits for the m3u8 network request.
    """
    logger.info(f"FMovies launching Playwright for {watch_url}")
    
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-setuid-sandbox'])
            context = await browser.new_context(
                user_agent=_HEADERS["User-Agent"],
                viewport={'width': 1280, 'height': 720}
            )
            page = await context.new_page()
            
            m3u8_url = None
            referer = watch_url

            async def handle_request(request):
                nonlocal m3u8_url, referer
                if request.resource_type in ["xhr", "fetch", "other"]:
                    url = request.url
                    if ".m3u8" in url and not m3u8_url:
                        m3u8_url = url
                        req_headers = request.headers
                        if "referer" in req_headers:
                            referer = req_headers["referer"]

            page.on("request", handle_request)

            try:
                await page.goto(watch_url, wait_until="domcontentloaded", timeout=20000)
                
                for _ in range(150):
                    if m3u8_url:
                        break
                    await asyncio.sleep(0.1)
                    
                if not m3u8_url:
                    frames = page.frames
                    for frame in frames:
                        if "embos.top" in frame.url or "vidsrc" in frame.url or "vidlink" in frame.url or "embed" in frame.url:
                            logger.info(f"Found player frame: {frame.url}")
                            try:
                                await frame.click("body", timeout=2000, force=True)
                            except Exception:
                                pass
                                
                    for _ in range(50):
                        if m3u8_url:
                            break
                        await asyncio.sleep(0.1)

            except Exception as e:
                logger.error(f"Playwright navigation error on {watch_url}: {e}")
            finally:
                await browser.close()
                
            if m3u8_url:
                logger.info(f"FMovies successfully extracted m3u8 via Playwright: {m3u8_url[:50]}...")
                return m3u8_url, referer, _HEADERS["User-Agent"]
            else:
                logger.error(f"FMovies failed to intercept m3u8 via Playwright from {watch_url}")
                return None
                
    except Exception as e:
        logger.error(f"FMovies Playwright launch error: {e}")
        return None
