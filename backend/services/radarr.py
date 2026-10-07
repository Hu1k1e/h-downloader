"""
Radarr API v3 client.
"""
import logging
import time
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


_cache: Dict[str, Any] = {}


async def get_all_movies(settings: AppSettings, max_age: float = 0) -> List[Dict[str, Any]]:
    """Return all movies in Radarr. `max_age` (seconds) allows a short-lived cached copy
    for polling callers; the default (0) always hits Radarr."""
    key = f"movies:{settings.radarr_url}"
    hit = _cache.get(key)
    if max_age > 0 and hit and time.monotonic() - hit[0] < max_age:
        return hit[1]
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(_url(settings, "/movie"), headers=_headers(settings))
        resp.raise_for_status()
        data = resp.json()
    _cache[key] = (time.monotonic(), data)
    return data


async def get_full_queue(settings: AppSettings, max_age: float = 0) -> List[Dict[str, Any]]:
    """Return all records in the Radarr queue (same `max_age` semantics as get_all_movies)."""
    key = f"queue:{settings.radarr_url}"
    hit = _cache.get(key)
    if max_age > 0 and hit and time.monotonic() - hit[0] < max_age:
        return hit[1]
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(_url(settings, "/queue?pageSize=10000"), headers=_headers(settings))
        resp.raise_for_status()
        data = resp.json()
    records = data.get("records", []) if isinstance(data, dict) else data
    _cache[key] = (time.monotonic(), records)
    return records


def pick_queue_record(records: List[Dict[str, Any]], key: str, value: Any) -> Optional[Dict[str, Any]]:
    """From queue `records`, choose the best one whose `key` equals `value`.

    Prefers a healthy item (not warning/error); falls back to the first match so the
    caller can tell that every grab for the item is failing. Returns None if absent."""
    matches = [r for r in records or [] if r.get(key) == value]
    if not matches:
        return None
    for record in matches:
        if (record.get("trackedDownloadStatus") or "").lower() not in ("warning", "error"):
            return record
    return matches[0]


async def get_movie_queue_status(movie_id: int, settings: AppSettings) -> Optional[Dict[str, Any]]:
    """Return the best queue record for a Radarr movie id, or None if it is not queued."""
    return pick_queue_record(await get_full_queue(settings), "movieId", movie_id)


async def ensure_movie_added(tmdb_id: int, title: str, year: int, settings: AppSettings,
                             existing: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Add movie to Radarr if not present. Returns the movie dict.
    Pass `existing` (already-fetched Radarr movie) to skip the library lookup."""
    if existing is None:
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


async def get_movie_folder(tmdb_id: int, title: str, year: int, settings: AppSettings,
                           movie: Optional[Dict[str, Any]] = None) -> str:
    """Return the folder path Radarr expects for this movie (pass `movie` to skip the lookup)."""
    if movie is None:
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


def resolution_from_profile_name(name: str) -> Optional[str]:
    """Extract a resolution keyword from a quality-profile name; None if there isn't one."""
    name = (name or "").lower()
    if "1080p" in name:
        return "1080p"
    if "720p" in name:
        return "720p"
    if "2160p" in name or "4k" in name:
        return "2160p"
    return None


async def get_quality_profile_resolution(profile_id: int, settings: AppSettings) -> Optional[str]:
    """Resolution (1080p/720p/2160p) implied by the Radarr quality profile name, else None."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(_url(settings, "/qualityprofile"), headers=_headers(settings))
            resp.raise_for_status()
            for p in resp.json():
                if p.get("id") == profile_id:
                    return resolution_from_profile_name(p.get("name", ""))
            return None
    except Exception as e:
        logging.getLogger(__name__).error(f"Failed to fetch quality profiles: {e}")
        return None


async def test_connection(settings: AppSettings) -> Dict[str, Any]:
    """Returns Radarr system status or raises on failure."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(_url(settings, "/system/status"), headers=_headers(settings))
        resp.raise_for_status()
        return resp.json()


async def update_movie_monitored(movie_id: int, monitored: bool, settings: AppSettings) -> bool:
    """Set the monitored flag in Radarr and return the value Radarr confirms afterwards."""
    async with httpx.AsyncClient(timeout=15) as client:
        # Fetch the full movie object first as required by Radarr's PUT endpoint
        resp = await client.get(_url(settings, f"/movie/{movie_id}"), headers=_headers(settings))
        resp.raise_for_status()
        movie = resp.json()

        if movie.get("monitored") != monitored:
            movie["monitored"] = monitored
            put_resp = await client.put(_url(settings, f"/movie/{movie_id}"), headers=_headers(settings), json=movie)
            put_resp.raise_for_status()

        # Read back so the caller stores what Radarr really has, not what we asked for.
        confirm = await client.get(_url(settings, f"/movie/{movie_id}"), headers=_headers(settings))
        confirm.raise_for_status()
        return bool(confirm.json().get("monitored", monitored))


async def delete_movie_file(movie_file_id: int, settings: AppSettings) -> bool:
    """Delete a movie's file from disk via Radarr (the movie entry itself stays)."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.delete(_url(settings, f"/moviefile/{movie_file_id}"), headers=_headers(settings))
        resp.raise_for_status()
        return True
