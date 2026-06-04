"""
Radarr API v3 client.
"""
from typing import Optional, Dict, Any, List
import httpx

from backend.models import AppSettings


def _headers(settings: AppSettings) -> Dict[str, str]:
    return {"X-Api-Key": settings.radarr_api_key, "Content-Type": "application/json"}


def _url(settings: AppSettings, path: str) -> str:
    return f"{settings.radarr_url.rstrip('/')}/api/v3{path}"


async def is_movie_available(tmdb_id: int, settings: AppSettings) -> bool:
    """Return True if Radarr already has the movie downloaded (hasFile=True)."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(_url(settings, "/movie"), headers=_headers(settings))
        resp.raise_for_status()
        movies = resp.json()
        for m in movies:
            if m.get("tmdbId") == tmdb_id and m.get("hasFile"):
                return True
    return False


async def is_movie_in_radarr(tmdb_id: int, settings: AppSettings) -> Optional[Dict[str, Any]]:
    """Return the movie dict if it exists in Radarr (regardless of hasFile)."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(_url(settings, "/movie"), headers=_headers(settings))
        resp.raise_for_status()
        for m in resp.json():
            if m.get("tmdbId") == tmdb_id:
                return m
    return None


async def get_all_movies(settings: AppSettings) -> List[Dict[str, Any]]:
    """Return all movies in Radarr."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(_url(settings, "/movie"), headers=_headers(settings))
        resp.raise_for_status()
        return resp.json()

async def get_full_queue(settings: AppSettings) -> List[Dict[str, Any]]:
    """Return all records in the Radarr queue."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(_url(settings, "/queue?pageSize=10000"), headers=_headers(settings))
        resp.raise_for_status()
        data = resp.json()
        return data.get("records", []) if isinstance(data, dict) else data


async def get_movie_queue_status(movie_id: int, settings: AppSettings) -> Optional[Dict[str, Any]]:
    """
    Checks the Radarr queue for a specific Radarr movie_id.
    Returns the queue status dict if found, else None.
    A queue item contains fields like 'status': 'downloading', 'trackedDownloadStatus': 'Warning', etc.
    """
    async with httpx.AsyncClient(timeout=15) as client:
        # Get all records in queue
        resp = await client.get(_url(settings, "/queue?pageSize=10000"), headers=_headers(settings))
        resp.raise_for_status()
        queue_data = resp.json()
        
        # queue_data might be a list of records or an object with 'records' list
        records = queue_data.get("records", []) if isinstance(queue_data, dict) else queue_data
        
        for record in records:
            if record.get("movieId") == movie_id:
                return record
                
    return None


async def ensure_movie_added(tmdb_id: int, title: str, year: int, settings: AppSettings) -> Dict[str, Any]:
    """Add movie to Radarr if not present. Returns the movie dict."""
    existing = await is_movie_in_radarr(tmdb_id, settings)
    if existing:
        return existing

    # Look up via Radarr's own TMDB lookup to get proper metadata
    async with httpx.AsyncClient(timeout=20) as client:
        lookup = await client.get(
            _url(settings, f"/movie/lookup/tmdb?tmdbId={tmdb_id}"), headers=_headers(settings)
        )
        lookup.raise_for_status()
        movie_meta = lookup.json()

        payload = {
            "tmdbId": tmdb_id,
            "title": movie_meta.get("title", title),
            "year": movie_meta.get("year", year),
            "qualityProfileId": settings.radarr_quality_profile_id,
            "rootFolderPath": settings.radarr_root_folder,
            "monitored": True,
            "addOptions": {"searchForMovie": False},
            "images": movie_meta.get("images", []),
            "titleSlug": movie_meta.get("titleSlug", ""),
        }

        add_resp = await client.post(_url(settings, "/movie"), headers=_headers(settings), json=payload)
        add_resp.raise_for_status()
        return add_resp.json()


async def get_movie_folder(tmdb_id: int, title: str, year: int, settings: AppSettings) -> str:
    """Return the folder path Radarr expects for this movie."""
    movie = await is_movie_in_radarr(tmdb_id, settings)
    if movie and movie.get("path"):
        return movie["path"]
    # Construct a sensible default path
    safe_title = "".join(c for c in title if c.isalnum() or c in " -_.").strip()
    return f"{settings.radarr_root_folder.rstrip('/')}/{safe_title} ({year})"


async def trigger_rescan(movie_id: int, settings: AppSettings) -> bool:
    """Tell Radarr to rescan a specific movie's folder to detect the downloaded file."""
    payload = {"name": "RescanMovie", "movieId": movie_id}
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(_url(settings, "/command"), headers=_headers(settings), json=payload)
        resp.raise_for_status()
    return True


async def get_quality_profile_resolution(profile_id: int, settings: AppSettings) -> Optional[str]:
    """
    Fetches the quality profile by ID and tries to extract a resolution keyword
    like '1080p', '720p', '2160p', '4k' from its name.
    """
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(_url(settings, "/qualityprofile"), headers=_headers(settings))
            resp.raise_for_status()
            profiles = resp.json()
            for p in profiles:
                if p.get("id") == profile_id:
                    name = p.get("name", "").lower()
                    if "1080p" in name:
                        return "1080p"
                    if "720p" in name:
                        return "720p"
                    if "2160p" in name or "4k" in name:
                        return "2160p"  # common fallback mapping for 4k is 2160p/4k, let's just return what we find
                    if "4k" in name:
                        return "4k"
                    return name
            return None
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Failed to fetch quality profiles: {e}")
        return None

async def test_connection(settings: AppSettings) -> Dict[str, Any]:
    """Returns Radarr system status or raises on failure."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(_url(settings, "/system/status"), headers=_headers(settings))
        resp.raise_for_status()
        return resp.json()


async def update_movie_monitored(movie_id: int, monitored: bool, settings: AppSettings) -> bool:
    """Updates the monitored status of a specific movie in Radarr."""
    async with httpx.AsyncClient(timeout=15) as client:
        # Fetch the full movie object first as required by Radarr's PUT endpoint
        resp = await client.get(_url(settings, f"/movie/{movie_id}"), headers=_headers(settings))
        resp.raise_for_status()
        movie = resp.json()
        
        # Only update if the status is actually different
        if movie.get("monitored") == monitored:
            return True
            
        movie["monitored"] = monitored
        
        # Push the updated movie object back
        put_resp = await client.put(_url(settings, f"/movie/{movie_id}"), headers=_headers(settings), json=movie)
        put_resp.raise_for_status()
        return True
