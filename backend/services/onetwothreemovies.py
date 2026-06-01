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
    # API might return 0 results if we append "season X" to the search query, 
    # so we just search for the title and filter the results.
        
    search_url = f"{base_url}/searching?q={search_query}&limit=40&offset=0"
    
    try:
        headers = _HEADERS.copy()
        headers["Accept"] = "application/json, text/plain, */*"
        async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers=headers) as client:
            resp = await client.get(search_url)
            resp.raise_for_status()
            
            try:
                data = resp.json()
                items = data.get("data", [])
            except Exception:
                items = []
            
            for item in items:
                item_title = item.get("t", "")
                slug = item.get("s", "")
                media_type = item.get("d", "")
                
                if not slug:
                    continue
                    
                quality_badge = item.get("q", "")
                
                if _is_theatre_screening(item_title, quality_badge):
                    logger.info(f"Skipping '{item_title}' - identified as theatre screening (CAM/TS).")
                    continue
                    
                # Basic match validation
                # Ignore punctuation and case
                clean_title = re.sub(r'[^\w\s]', '', title).lower()
                clean_item_title = re.sub(r'[^\w\s]', '', item_title).lower()
                
                if clean_title in clean_item_title:
                    if is_series and season is not None:
                        # Ensure the correct season is matched
                        if media_type != "s":
                            continue
                        if f"season {season}" not in clean_item_title:
                            continue
                    else:
                        if media_type == "s" and not is_series:
                            continue
                            
                    href = f"/season/{slug}/" if media_type == "s" else f"/movie/{slug}/"
                    return f"{base_url}{href}"
                    
    except Exception as e:
        logger.error(f"123movies search failed: {e}")
        
    return None

async def extract_mp4_url(watch_url: str, is_series: bool = False, season: Optional[int] = None, episode: Optional[int] = None) -> Optional[str]:
    """
    Extract the direct video stream URL from the watch page using Playwright.
    """
    from playwright.async_api import async_playwright
    import json
    
    stream_url = None
    captured_m3u8 = None
    
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-blink-features=AutomationControlled']
            )
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = await context.new_page()

            async def handle_response(response):
                nonlocal stream_url, captured_m3u8
                url = response.url
                if ".m3u8" in url and "master" in url:
                    captured_m3u8 = url
                if "/get/" in url and response.status == 200:
                    try:
                        text = await response.text()
                        data = json.loads(text)
                        if "info" in data:
                            info_hex = data["info"]
                            decrypted = await page.evaluate('''async ([infoHex, password]) => {
                                const parts = infoHex.split("-");
                                const salt = new Uint8Array(parts[0].match(/.{1,2}/g).map(byte => parseInt(byte, 16)));
                                const iv = new Uint8Array(parts[1].match(/.{1,2}/g).map(byte => parseInt(byte, 16)));
                                const ciphertext = new Uint8Array(parts[2].match(/.{1,2}/g).map(byte => parseInt(byte, 16)));
                                
                                const keyMaterial = await crypto.subtle.importKey(
                                    "raw",
                                    new TextEncoder().encode(password),
                                    "PBKDF2",
                                    false,
                                    ["deriveKey"]
                                );
                                
                                const key = await crypto.subtle.deriveKey(
                                    { name: "PBKDF2", salt: salt, iterations: 1000, hash: "SHA-256" },
                                    keyMaterial,
                                    { name: "AES-GCM", length: 256 },
                                    false,
                                    ["decrypt"]
                                );
                                
                                const decryptedBuffer = await crypto.subtle.decrypt(
                                    { name: "AES-GCM", iv: iv },
                                    key,
                                    ciphertext
                                );
                                
                                return new TextDecoder().decode(decryptedBuffer);
                            }''', [info_hex, "player"])
                            
                            domain = url.split("/get/")[0]
                            stream_url = f"{domain}/hls/{decrypted}/master.m3u8"
                            logger.info(f"Successfully extracted stream URL: {stream_url}")
                    except Exception as e:
                        logger.error(f"Failed to decrypt info: {e}")

            page.on("response", handle_response)
            
            logger.info(f"Navigating to {watch_url}")
            await page.goto(watch_url, timeout=30000)
            
            try:
                # Click play-now if it exists to initialize the player
                await page.wait_for_selector("#play-now", state="attached", timeout=5000)
                await page.locator("#play-now").click()
                await asyncio.sleep(2)
            except Exception:
                pass
                
            # Click the episode after player initialization
            if is_series and episode:
                try:
                    ep_sel = f"#ep-{episode}"
                    await page.wait_for_selector(ep_sel, state="attached", timeout=5000)
                    
                    # Clear stream_url BEFORE clicking to capture the new one
                    stream_url = None
                    captured_m3u8 = None
                    
                    # Use evaluate click to force click even if the element is hidden by CSS
                    await page.locator(ep_sel).evaluate("node => node.click()")
                    
                    # Short sleep to allow network request to fire
                    await asyncio.sleep(2)
                except Exception as e:
                    logger.warning(f"Failed to click episode {episode}: {e}")
                
            for _ in range(15):
                if stream_url:
                    break
                if captured_m3u8:
                    stream_url = captured_m3u8
                    break
                await asyncio.sleep(1)
            
            cookies = await context.cookies()
            cookie_str = "; ".join([f"{c['name']}={c['value']}" for c in cookies])
                
            await browser.close()
            
            if stream_url and cookie_str:
                return f"{stream_url}|cookies={cookie_str}"
            return stream_url
            
    except Exception as e:
        logger.error(f"123movies MP4 extraction failed: {e}")
        
    return stream_url
