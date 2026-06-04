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

async def search_movie(title: str, year: int, domain: str) -> str:
    """Searches for a movie and returns the best forum thread URL, or None."""
    try:
        search_url = f"{domain}/search/"
        params = {"q": f"{title} {year}"}
        headers = {"User-Agent": "Mozilla/5.0"}
        
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(search_url, params=params, headers=headers)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            links = soup.find_all('a', href=re.compile(r'/index\.php\?/forums/topic/'))
            
            best_link = None
            for link in links:
                href = link.get('href')
                link_text = link.text.strip().lower()
                
                if title.lower() in link_text and str(year) in link_text:
                    best_link = href
                    break
                    
            if not best_link and links:
                best_link = links[0].get('href')
                
            return best_link
    except Exception as e:
        logger.error(f"Error searching 1TamilMV: {e}")
        return None

async def extract_magnet(thread_url: str) -> str:
    """Fetches the thread and extracts the magnet link."""
    if not thread_url:
        return None
        
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(thread_url, headers=headers)
            response.raise_for_status()
            
            magnet_match = re.search(r'href="(magnet:\?xt=urn:btih:[^"]+)"', response.text)
            if magnet_match:
                return magnet_match.group(1).replace('&amp;', '&')
                
            return None
    except Exception as e:
        logger.error(f"Error extracting magnet from {thread_url}: {e}")
        return None

