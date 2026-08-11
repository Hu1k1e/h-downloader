import re
import base64
import httpx
from datetime import datetime
from bs4 import BeautifulSoup
import logging
from typing import Optional, Tuple, List

logger = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

def _generate_date_variants(date_str: str) -> List[str]:
    """Generates variants of the date string to match against bollyzone titles."""
    if not date_str:
        return []
        
    try:
        from datetime import timedelta
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        
        def ordinal(n):
            return f"{n}{'tsnrhtdd'[(n//10%10!=1)*(n%10<4)*n%10::4]}"
            
        variants = []
        # Generate for exact date, +1 day, and -1 day (timezone differences)
        for d in [dt, dt + timedelta(days=1), dt - timedelta(days=1)]:
            variants.extend([
                f"{ordinal(d.day)} {d.strftime('%B')} {d.year}", # 9th August 2026
                f"{d.day:02d} {d.strftime('%B')} {d.year}",      # 09 August 2026
                f"{d.day} {d.strftime('%B')} {d.year}",          # 9 August 2026
                f"{ordinal(d.day)} {d.strftime('%b')} {d.year}", # 9th Aug 2026
                f"{d.day:02d}-{d.month:02d}-{d.year}",           # 09-08-2026
                f"{d.day}-{d.month}-{d.year}",                   # 9-8-2026
            ])
        return variants
    except Exception as e:
        logger.warning(f"Failed to generate date variants for {date_str}: {e}")
        return []


def unpack_juicy(payload: str) -> str:
    """Decodes a JuicyCodes payload containing base64 + eval unpacking logic."""
    try:
        parts = re.findall(r'"([^"]+)"', payload)
        encoded = "".join(parts)
        decoded = base64.b64decode(encoded).decode("utf-8")
        
        match = re.search(r"}\('(.*?)',\s*(\d+),\s*(\d+),\s*'(.*?)'\.split\('\|'\)", decoded, re.DOTALL)
        if not match:
            return ""
            
        p = match.group(1)
        a = int(match.group(2))
        c = int(match.group(3))
        k = match.group(4).split("|")
        
        def to_base36(num):
            chars = '0123456789abcdefghijklmnopqrstuvwxyz'
            if num < 36: return chars[num]
            return to_base36(num // 36) + chars[num % 36]
            
        def e_fixed(c_val):
            part1 = "" if c_val < a else e_fixed(c_val // a)
            c_mod = c_val % a
            part2 = chr(c_mod + 29) if c_mod > 35 else to_base36(c_mod)
            return part1 + part2

        while c > 0:
            c -= 1
            if c < len(k) and k[c]:
                search_str = r'\b' + e_fixed(c) + r'\b'
                p = re.sub(search_str, k[c], p)
        
        return p
    except Exception as e:
        logger.error(f"Failed to unpack JuicyCodes payload: {e}")
        return ""


async def search_series(title: str, air_date: str, season: int = None, episode: int = None) -> Optional[str]:
    """
    Search BollyZone for a TV series episode matching the title and air date.
    Returns the episode URL if found.
    """
    url = f"https://www.bollyzone.to/?s={httpx.URL(title).query.decode('utf-8') if httpx.URL(title).query else title.replace(' ', '+')}"
    headers = {"User-Agent": USER_AGENT}
    
    date_variants = _generate_date_variants(air_date)
    
    # Fallback variants
    fallback_variants = []
    if episode is not None:
        if season is not None:
            fallback_variants.extend([
                f"season {season} episode {episode}",
                f"s{season:02d}e{episode:02d}",
                f"s{season}e{episode}"
            ])
        fallback_variants.extend([
            f"episode {episode}",
            f"ep {episode}"
        ])
    
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            
            soup = BeautifulSoup(resp.text, "html.parser")
            
            for a_tag in soup.find_all("a", href=True):
                href = a_tag["href"]
                text = a_tag.get_text().strip().lower()
                href_lower = href.lower()
                
                # Filter out obvious non-episode links like pagination or categories
                if "/category/" in href_lower or "/tag/" in href_lower or "/page/" in href_lower:
                    continue
                    
                # 1. Match by Date
                    for variant in date_variants:
                        variant_lower = variant.lower()
                        # Match variant in either the link text or the URL slug itself
                        if variant_lower in text or variant_lower.replace(" ", "-") in href_lower:
                            return href
                            
                    # 2. Match by Fallback Variants (Season/Episode)
                    for variant in fallback_variants:
                        variant_lower = variant.lower()
                        if variant_lower in text or variant_lower.replace(" ", "-") in href_lower:
                            # Verify title also loosely matches to avoid false positives
                            if any(word.lower() in text for word in title.split()):
                                return href
            
            return None
    except Exception as e:
        logger.error(f"BollyZone search failed for '{title}': {e}")
        return None


async def extract_url(episode_url: str) -> Optional[Tuple[str, str, str]]:
    """
    Extracts the final streaming URL from a BollyZone episode page.
    Follows the ad-wall redirects (groundbanks.net) to the tvlogy player.
    Returns (m3u8_url, referer_to_use, user_agent_to_use)
    """
    headers = {"User-Agent": USER_AGENT}
    
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            # 1. Fetch episode page
            resp = await client.get(episode_url, headers=headers)
            resp.raise_for_status()
            
            soup = BeautifulSoup(resp.text, "html.parser")
            groundbanks_links = []
            
            # Find all groundbanks.net links on the page
            for a_tag in soup.find_all("a", href=True):
                if "groundbanks.net" in a_tag["href"]:
                    if a_tag["href"] not in groundbanks_links:
                        groundbanks_links.append(a_tag["href"])
                    
            if not groundbanks_links:
                logger.error(f"No groundbanks.net links found on {episode_url}")
                return None
                
            # Prefer link 2 or 3 (Dailymotion/Netflix wrapper) as they often work better than flash wrapper
            target_link = groundbanks_links[0]
            for link in groundbanks_links:
                if "2814692" in link or "2814693" in link:
                    target_link = link
                    
            # 2. Fetch groundbanks link WITH referer to bypass ad wall
            headers["Referer"] = episode_url
            resp = await client.get(target_link, headers=headers)
            resp.raise_for_status()
            
            iframe_match = re.search(r"<IFRAME SRC='([^']+)'", resp.text, re.IGNORECASE)
            if not iframe_match:
                logger.error(f"No iframe found in groundbanks response for {target_link}")
                return None
                
            tvlogy_url = iframe_match.group(1)
            if not tvlogy_url.startswith("http"):
                tvlogy_url = "https:" + tvlogy_url if tvlogy_url.startswith("//") else tvlogy_url
                
            # 3. Fetch tvlogy player page WITH referer to groundbanks
            headers["Referer"] = target_link
            resp = await client.get(tvlogy_url, headers=headers)
            resp.raise_for_status()
            
            juicy_match = re.search(r'JuicyCodes\.Run\((.*?)\);', resp.text, re.DOTALL)
            if not juicy_match:
                logger.error(f"No JuicyCodes payload found in tvlogy response for {tvlogy_url}")
                return None
                
            unpacked = unpack_juicy(juicy_match.group(1))
            
            # Extract .m3u8 from the unpacked json config
            # Format: sources:[{"file":"https://.../video.m3u8?token=...","label":"HD","type":"application/x-mpegURL"}]
            file_match = re.search(r'\"file\":\"(https?://[^\"]+\.m3u8[^\"]*)\"', unpacked)
            if not file_match:
                logger.error(f"Failed to find .m3u8 file in unpacked player config")
                return None
                
            m3u8_url = file_match.group(1).replace('\\/', '/')
            
            return m3u8_url, tvlogy_url, USER_AGENT
            
    except Exception as e:
        logger.error(f"Failed to extract streaming URL from BollyZone: {e}")
        return None
