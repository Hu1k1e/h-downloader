"""
Einthusan.tv scraper.

Implements two steps:
1. search(title, year, lang)  → returns the Einthusan watch URL or None
2. extract_mp4_url(watch_url) → returns the signed CDN MP4 URL

The MP4 extraction replicates the technique from the open-source
einthusan-dl project: it POSTs to the /ajax/movie/watch/ endpoint
with a CSRF token taken from the page HTML, then base64-decodes the
encoded link to get the direct CDN URL.
"""
import base64
import json
import logging
import re
from typing import Optional
from urllib.parse import quote_plus

import httpx
from bs4 import BeautifulSoup
from rapidfuzz import fuzz

logger = logging.getLogger(__name__)

EINTHUSAN_BASE = "https://einthusan.tv"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": EINTHUSAN_BASE,
}

# Badge strings Einthusan appends inside the <a class="title"> anchor.
# These must be stripped before fuzzy matching or they corrupt the score.
# e.g. "GuppyMust Watch" instead of "Guppy"
_BADGE_STRINGS = ("Must Watch", "Recommended", "Dubbed", "Subtitle", "New", "Premium")


async def search(title: str, year: Optional[int], lang: str) -> Optional[str]:
    """
    Search Einthusan for a movie by title + optional year within a language.
    Returns the full watch URL (e.g. https://einthusan.tv/movie/watch/4ys3/?lang=malayalam)
    or None if not found.

    ROOT CAUSE NOTE (diagnosed 2026-03-07):
    Einthusan's search HTML structure is:
        <a class="title" href="/movie/watch/6uUG/?lang=malayalam">
            <h3>Guppy</h3>
            <span>Must Watch</span>   ← badge in the SAME anchor
        </a>

    Calling anchor.get_text() returns "GuppyMust Watch".
    fuzz.token_set_ratio("guppy", "guppymust watch") ≈ 67 → fails the 85 threshold.
    The fix: always read the <h3> child directly, never the full anchor text.
    """
    query = quote_plus(title)
    search_url = f"{EINTHUSAN_BASE}/movie/results/?lang={lang}&query={query}"

    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        resp = await client.get(search_url, headers=_HEADERS)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

    # Select all watch-link anchors that have class="title"
    # This is the canonical selector for the movie title links on Einthusan search pages.
    title_anchors = soup.select("a.title[href*='/movie/watch/']")

    if not title_anchors:
        # Fallback: any link pointing to /movie/watch/
        title_anchors = soup.find_all("a", href=re.compile(r"/movie/watch/"))

    logger.debug(
        f"Einthusan search: lang={lang!r} title={title!r} → {len(title_anchors)} candidates"
    )

    best_score = 0
    best_url: Optional[str] = None

    for anchor in title_anchors:
        href = anchor.get("href", "")
        if not href:
            continue

        # ── Extract CLEAN title ──────────────────────────────────────────────
        # MUST use only the <h3> text, not anchor.get_text() which combines
        # title + badge into a single mangled string (e.g. "GuppyMust Watch")
        h3 = anchor.find("h3")
        if h3:
            card_title = h3.get_text(strip=True)
        else:
            # No h3 — use img alt or raw anchor text, then strip known badge strings
            img = anchor.find("img")
            raw = img.get("alt", "").strip() if img else anchor.get_text(strip=True)
            for badge in _BADGE_STRINGS:
                raw = raw.replace(badge, "").strip()
            card_title = raw

        if not card_title:
            continue

        # ── Score title similarity ───────────────────────────────────────────
        title_lower = title.lower()
        card_lower = card_title.lower()

        # Start with token-based scores
        token_set = fuzz.token_set_ratio(title_lower, card_lower)
        token_sort = fuzz.token_sort_ratio(title_lower, card_lower)
        strict = fuzz.ratio(title_lower, card_lower)

        # token_set_ratio is dangerously generous with subset matches:
        # e.g. token_set_ratio("kochi rajavu", "kochi") ≈ 100 because "kochi"
        # is a perfect subset of "kochi rajavu" tokens.
        # Guard against this by blending with strict ratio.
        score = max(token_set, token_sort)

        # Token count mismatch penalty: if search has more words than candidate,
        # the candidate is likely a shorter, different movie.
        search_tokens = title_lower.split()
        card_tokens = card_lower.split()
        if len(search_tokens) > len(card_tokens):
            missing_count = len(search_tokens) - len(card_tokens)
            # Heavy penalty per missing word — e.g. "Kochi" vs "Kochi Rajavu" loses 25 points
            score -= missing_count * 25

        # If strict ratio is very low, cap the score — prevents subset false positives
        # e.g. strict ratio of "kochi" vs "kochi rajavu" ≈ 46, way below 70
        if strict < 70:
            score = min(score, strict + 20)

        # Exact match override (including stripping all punctuation/spaces for edge cases like "NH10" vs "NH 10")
        title_alphanum = re.sub(r'[^a-z0-9]', '', title_lower)
        card_alphanum = re.sub(r'[^a-z0-9]', '', card_lower)

        if title_lower == card_lower or (title_alphanum and title_alphanum == card_alphanum):
            score = 100
        else:
            # Penalize if there is a mismatch in standalone numbers (e.g., sequels like '2')
            title_numbers = set(re.findall(r'\b\d+\b', title_lower))
            card_numbers = set(re.findall(r'\b\d+\b', card_lower))
            unmatched_numbers = (card_numbers - title_numbers).union(title_numbers - card_numbers)
            
            if unmatched_numbers:
                score -= 30  # Apply penalty for mismatched numbers

        # ── Year bonus (bonus only — never penalise) ─────────────────────────
        # Penalising year mismatches caused valid movies to be rejected when
        # Einthusan listed a slightly different year than TMDB.
        if isinstance(year, int):
            # Walk up from the anchor to its parent li/section to get full card text
            parent = anchor.parent
            for _ in range(5):
                if parent is None or parent.name in ("li", "section", "body"):
                    break
                parent = parent.parent
            card_text = parent.get_text() if parent else ""
            years_in_card = [int(y) for y in re.findall(r'\b(19\d{2}|20\d{2})\b', card_text)]
            if years_in_card and any(abs(y - year) <= 1 for y in years_in_card):
                score += 15  # Confirmed year match — boost confidence

        logger.debug(f"  candidate: {card_title!r} href={href!r} score={score}")

        if score > best_score:
            best_score = score
            if href.startswith("http"):
                best_url = href
            else:
                best_url = f"{EINTHUSAN_BASE}{href}"
                if "lang=" not in best_url:
                    sep = "&" if "?" in best_url else "?"
                    best_url = f"{best_url}{sep}lang={lang}"

    # 85 threshold guards against false positives while accepting valid results
    if best_score >= 85 and best_url:
        logger.info(f"Einthusan match: '{best_url}' (score={best_score}) for '{title}' (year={year})")
        return best_url

    logger.info(
        f"No valid Einthusan match for '{title}' "
        f"(year={year}, lang={lang!r}, best_score={best_score})"
    )
    return None


async def extract_mp4_url(watch_url: str) -> Optional[str]:
    """
    Given an Einthusan watch page URL, return the signed CDN MP4 URL.

    Technique:
    1. GET the watch page — extract data-pageid (CSRF) and data-ejpingables
    2. POST to /ajax/movie/watch/{id}/ — get encoded EJLinks
    3. base64-decode + JSON parse → MP4Link
    """
    movie_id_match = re.search(r"/movie/watch/([^/?]+)", watch_url)
    if not movie_id_match:
        return None
    movie_id = movie_id_match.group(1)

    async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers=_HEADERS) as client:
        # Step 1: Request the watch page to get CSRF token and player parameters
        try:
            resp = await client.get(watch_url)
            resp.raise_for_status()
        except Exception as e:
            logging.error(f"Failed to fetch watch page {watch_url}: {e}")
            return None

        soup = BeautifulSoup(resp.text, "lxml")

        # Einthusan stores the gorilla CSRF token in the html tag
        html_tag = soup.find("html")
        page_id = html_tag.get("data-pageid", "") if html_tag else ""

        # Einthusan stores player pingables in a data attribute
        pingables = ""
        for tag in soup.find_all(lambda t: t.has_attr("data-ejpingables")):
            pingables = tag["data-ejpingables"]
            break

        # Step 2: POST to the AJAX endpoint to get the video metadata
        ajax_url = f"{EINTHUSAN_BASE}/ajax/movie/watch/{movie_id}/"
        headers = dict(_HEADERS)
        headers.update({
            "Referer": watch_url,
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/x-www-form-urlencoded"
        })

        data = {
            "xEvent": "UIVideoPlayer.PingOutcome",
            "xJson": f'{{"EJOutcomes": "{pingables}", "NativeHLS": false}}',
            "gorilla.csrf.Token": page_id
        }

        try:
            ajax_resp = await client.post(ajax_url, headers=headers, data=data)
            ajax_resp.raise_for_status()
        except Exception as e:
            logging.error(f"Failed to fetch AJAX data for {movie_id}: {e}")
            return None

        try:
            resp_json = ajax_resp.json()
        except Exception:
            logging.error("Failed to parse AJAX JSON response")
            return None

        if not isinstance(resp_json, dict):
            logging.error(f"Einthusan AJAX response is not a dict: {resp_json}")
            raise Exception(f"Einthusan API Invalid Response: {str(resp_json)[:100]}")

        # Step 3: Decrypt the EJLinks payload
        data_block = resp_json.get("Data", {})
        if not isinstance(data_block, dict):
            error_msg = str(data_block).strip() if data_block else "Unknown Einthusan error"
            logging.error(f"Einthusan AJAX returned error message: {error_msg}")
            raise Exception(f"Einthusan API Error: {error_msg}")

        ej_links_enc = data_block.get("EJLinks", "")
        if not ej_links_enc:
            logging.error("No EJLinks found in JSON response")
            return None

        try:
            # Decryption algorithm: take first 10 chars + last char + chars from index 12 to 2nd to last
            dec_string = ej_links_enc[:10] + ej_links_enc[-1] + ej_links_enc[12:-1]
            decrypted_json_str = base64.b64decode(dec_string).decode('utf-8')
            video_data = json.loads(decrypted_json_str)
            if isinstance(video_data, str):
                video_data = json.loads(video_data)
                
            if not isinstance(video_data, dict):
                raise Exception(f"Decrypted EJLinks is not a dict: {video_data}")
                
            return video_data.get("MP4Link")
        except Exception as e:
            logging.error(f"Failed to decrypt or parse EJLinks: {e}")
            raise e
