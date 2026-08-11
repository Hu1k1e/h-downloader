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

async def search_movie(title: str, year: int, domain: str, langs: list[str] = None, radarr_resolution: str = None) -> str:
    """Searches for a movie and returns the best forum thread URL, or None."""
    try:
        search_url = f"{domain}/index.php?/search/&q={title} {year}&search_and_or=and"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
        
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            response = await client.get(search_url, headers=headers)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            # 1TamilMV search results usually have class 'ipsStreamItem_title' or similar, containing a link
            results = soup.select('.ipsStreamItem_title a[href*="/forums/topic/"]')
            
            from backend.services.llm import generate_search_variants_with_llm
            llm_variants = await generate_search_variants_with_llm(
                target_title=title,
                target_year=year
            )
            if llm_variants:
                logger.info(f"LLM generated {len(llm_variants)} search variants for 1TamilMV: {llm_variants}")
            else:
                llm_variants = []
            
            valid_links = []
            title_lower = title.lower()
            for a_tag in results:
                href = a_tag.get('href')
                text = a_tag.text.lower()
                
                is_match = False
                # Title and year check
                if re.search(r'\b' + re.escape(title_lower) + r'\b', text):
                    if (str(year) in text or str(year - 1) in text or str(year + 1) in text):
                        is_match = True

                # Loose check
                if not is_match:
                    title_parts = title_lower.split()
                    if all(part in text for part in title_parts):
                        is_match = True
                        
                # LLM variant check
                if not is_match and llm_variants:
                    for variant in llm_variants:
                        if variant.lower() in text or variant.lower().replace(" ", "-") in href.lower():
                            is_match = True
                            break
                
                if not is_match:
                    continue
                    
                # Exclude camprints
                if any(bad in text for bad in BAD_KEYWORDS):
                    continue
                    
                valid_links.append((href, text))
                
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

async def extract_magnet(thread_url: str) -> str:
    """Fetches the thread and extracts the first magnet link."""
    if not thread_url:
        return None
        
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as client:
            response = await client.get(thread_url, headers=headers)
            response.raise_for_status()
            
            # Broader regex to catch full magnet links including trackers
            magnet_matches = re.finditer(r'(magnet:\?xt=urn:btih:[^\s"\'<>]+)', response.text, re.IGNORECASE)
            for match in magnet_matches:
                return match.group(1)
                
            return None
    except Exception as e:
        logger.error(f"Error extracting magnet from {thread_url}: {e}")
        return None

