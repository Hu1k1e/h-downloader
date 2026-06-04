import httpx
from bs4 import BeautifulSoup
import re
import logging

logger = logging.getLogger(__name__)

async def get_current_domain() -> str:
    """Gets the active 1TamilMV domain by following redirects."""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
        async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as client:
            response = await client.get("https://www.1tamilmv.fi/", headers=headers)
            domain = str(response.url).rstrip('/')
            logger.info(f"Resolved 1TamilMV domain to: {domain}")
            return domain
    except Exception as e:
        logger.error(f"Failed to resolve 1TamilMV domain: {e}")
        # Fallback to known domain if resolution fails
        return "https://www.1tamilmv.cards"

BAD_KEYWORDS = ['predvd', 'cam', 'hdts', 'hd-ts', 'hdcam', 'hd-cam', 'pdvd', 'scr']

async def search_movie(title: str, year: int, domain: str, langs: list[str] = None, radarr_resolution: str = None, blacklisted_urls: list[str] = None) -> str:
    """Searches for a movie and returns the best forum thread URL, or None."""
    try:
        search_url = f"{domain}/search/"
        params = {"q": f"{title} {year}"}
        headers = {"User-Agent": "Mozilla/5.0"}
        
        async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as client:
            response = await client.get(search_url, params=params, headers=headers)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            links = soup.find_all('a', href=re.compile(r'/index\.php\?/forums/topic/'))
            
            valid_links = []
            for link in links:
                href = link.get('href')
                link_text = link.text.strip().lower()
                
                # Title and year check
                if title.lower() not in link_text:
                    continue
                if not (str(year) in link_text or str(year - 1) in link_text or str(year + 1) in link_text):
                    continue
                    
                # Exclude camprints
                if any(bad in link_text for bad in BAD_KEYWORDS):
                    continue
                    
                # Exclude blacklisted threads
                if blacklisted_urls and any(href == b or href.endswith(b) for b in blacklisted_urls):
                    continue
                    
                valid_links.append((href, link_text))
                
            if not valid_links:
                return None
                
            # Scoring logic: higher is better
            best_score = -1
            best_href = None
            
            for href, text in valid_links:
                score = 0
                if langs and any(l.lower() in text for l in langs):
                    score += 10
                if radarr_resolution and radarr_resolution.lower() in text:
                    score += 5
                    
                if score > best_score:
                    best_score = score
                    best_href = href
                            
            return best_href or valid_links[0][0]
    except Exception as e:
        logger.error(f"Error searching 1TamilMV: {e}")
        return None

async def extract_magnet(thread_url: str, blacklisted_urls: list[str] = None) -> str:
    """Fetches the thread and extracts the first non-blacklisted magnet link."""
    if not thread_url:
        return None
        
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as client:
            response = await client.get(thread_url, headers=headers)
            response.raise_for_status()
            
            # Broader regex to catch magnet links in text or href
            magnet_matches = re.finditer(r'(magnet:\?xt=urn:btih:[a-zA-Z0-9]+)', response.text, re.IGNORECASE)
            for match in magnet_matches:
                magnet = match.group(1)
                
                # Check if this specific magnet or its hash is blacklisted
                match_hash = re.search(r'urn:btih:([a-zA-Z0-9]+)', magnet, re.IGNORECASE)
                hash_val = match_hash.group(1).lower() if match_hash else ""
                
                is_blacklisted = False
                if blacklisted_urls:
                    for b in blacklisted_urls:
                        if b.lower() in magnet.lower() or b.lower() == hash_val:
                            is_blacklisted = True
                            break
                            
                if not is_blacklisted:
                    return magnet
                
            return None
    except Exception as e:
        logger.error(f"Error extracting magnet from {thread_url}: {e}")
        return None

