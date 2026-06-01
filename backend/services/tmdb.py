"""
TMDB API client — fetches release dates and movie metadata.
"""
from datetime import date, datetime, timedelta
from typing import Optional, Dict, Any, Tuple
import httpx
import asyncio
import logging

logger = logging.getLogger(__name__)

async def _fetch_with_retry(client: httpx.AsyncClient, url: str, headers: Dict[str, str] = None, params: Dict[str, str] = None, retries: int = 3) -> httpx.Response:
    for attempt in range(retries):
        try:
            resp = await client.get(url, headers=headers, params=params)
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", 2))
                logger.warning(f"TMDB rate limit hit. Retrying in {retry_after}s...")
                await asyncio.sleep(retry_after)
                continue
            resp.raise_for_status()
            return resp
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                retry_after = int(e.response.headers.get("Retry-After", 2))
                logger.warning(f"TMDB rate limit hit. Retrying in {retry_after}s...")
                await asyncio.sleep(retry_after)
                continue
            elif attempt < retries - 1 and e.response.status_code >= 500:
                await asyncio.sleep(2 ** attempt)
                continue
            raise
        except Exception as e:
            if attempt < retries - 1:
                await asyncio.sleep(2 ** attempt)
                continue
            raise


from backend.models import AppSettings
from backend import config

# TMDB release type codes
_THEATRICAL = 3
_DIGITAL = 4
_PHYSICAL = 5


def _headers(settings: AppSettings) -> Dict[str, str]:
    return {"Authorization": f"Bearer {settings.tmdb_api_key}"}


def _url(path: str) -> str:
    # We still use config for TMDB_BASE_URL because it's not strictly a user setting
    return f"{config.TMDB_BASE_URL}{path}"


async def get_movie_details(tmdb_id: int, settings: AppSettings) -> Dict[str, Any]:
    """Fetch title, year, original_language, and poster."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await _fetch_with_retry(
            client,
            _url(f"/movie/{tmdb_id}"),
            headers=_headers(settings),
            params={"api_key": settings.tmdb_api_key},
        )
        data = resp.json()
        
    release_date = data.get("release_date", "")
    year = int(release_date[:4]) if release_date else None
    return {
        "tmdb_id": tmdb_id,
        "title": data.get("title", "Unknown"),
        "original_language": data.get("original_language", ""),
        "year": year,
        "poster_path": data.get("poster_path"),  # e.g. "/abc123.jpg"
    }


async def get_digital_release_date(tmdb_id: int, settings: AppSettings) -> Optional[date]:
    """
    Return the best estimated digital release date:
    1. Explicit digital (type=4) release date from any region
    2. Physical (type=5) release date as proxy
    3. Theatrical (type=3) + DIGITAL_RELEASE_FALLBACK_DAYS
    4. None if no theatrical date either
    """
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await _fetch_with_retry(
            client,
            _url(f"/movie/{tmdb_id}/release_dates"),
            params={"api_key": settings.tmdb_api_key},
        )
        resp.raise_for_status()
        data = resp.json()

    digital_date: Optional[date] = None
    physical_date: Optional[date] = None
    theatrical_date: Optional[date] = None

    for result in data.get("results", []):
        for rd in result.get("release_dates", []):
            raw = rd.get("release_date", "")
            if not raw:
                continue
            try:
                d = datetime.fromisoformat(raw[:10]).date()
            except ValueError:
                continue
            rtype = rd.get("type")
            if rtype == _DIGITAL:
                if digital_date is None or d < digital_date:
                    digital_date = d
            elif rtype == _PHYSICAL:
                if physical_date is None or d < physical_date:
                    physical_date = d
            elif rtype == _THEATRICAL:
                if theatrical_date is None or d < theatrical_date:
                    theatrical_date = d

    if digital_date:
        return digital_date
    if physical_date:
        return physical_date
    if theatrical_date:
        return theatrical_date + timedelta(days=settings.digital_release_fallback_days)
    return None


async def has_digital_release_passed(tmdb_id: int, settings: AppSettings) -> Tuple[bool, Optional[date]]:
    """Return (True, release_date) if the estimated digital date has passed."""
    release_date = await get_digital_release_date(tmdb_id, settings)
    if release_date is None:
        return False, None
    return date.today() >= release_date, release_date


async def test_connection(settings: AppSettings) -> Dict[str, Any]:
    """Validate TMDB API key."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            _url("/configuration"),
            params={"api_key": settings.tmdb_api_key},
        )
        resp.raise_for_status()
        return {"status": "ok"}
