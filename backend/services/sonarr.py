"""
Sonarr API v3 client.
"""
from typing import Optional, Dict, Any, List
import httpx

from backend.models import AppSettings

def _headers(settings: AppSettings) -> Dict[str, str]:
    return {"X-Api-Key": settings.sonarr_api_key, "Content-Type": "application/json"}

def _url(settings: AppSettings, path: str) -> str:
    return f"{settings.sonarr_url.rstrip('/')}/api/v3{path}"

async def is_series_in_sonarr(tmdb_id: int, settings: AppSettings) -> Optional[Dict[str, Any]]:
    """Return the series dict if it exists in Sonarr."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(_url(settings, "/series"), headers=_headers(settings))
        resp.raise_for_status()
        for s in resp.json():
            if s.get("tmdbId") == tmdb_id:
                return s
    return None

async def get_all_series(settings: AppSettings) -> List[Dict[str, Any]]:
    """Return all series in Sonarr."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(_url(settings, "/series"), headers=_headers(settings))
        resp.raise_for_status()
        return resp.json()

async def is_episode_available(series_id: int, season_number: int, episode_number: int, settings: AppSettings) -> bool:
    """Return True if Sonarr already has the episode file downloaded."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(_url(settings, f"/episode?seriesId={series_id}"), headers=_headers(settings))
        resp.raise_for_status()
        for ep in resp.json():
            if ep.get("seasonNumber") == season_number and ep.get("episodeNumber") == episode_number:
                return ep.get("hasFile", False)
    return False

async def get_episodes_for_series(series_id: int, settings: AppSettings) -> List[Dict[str, Any]]:
    """Return all episodes for a given series."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(_url(settings, f"/episode?seriesId={series_id}"), headers=_headers(settings))
        resp.raise_for_status()
        return resp.json()

async def get_episode_queue_status(series_id: int, season_number: int, episode_number: int, settings: AppSettings) -> Optional[Dict[str, Any]]:
    """Checks the Sonarr queue for a specific episode."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(_url(settings, "/queue"), headers=_headers(settings))
        resp.raise_for_status()
        queue_data = resp.json()
        records = queue_data.get("records", []) if isinstance(queue_data, dict) else queue_data
        
        for record in records:
            ep = record.get("episode", {})
            if record.get("seriesId") == series_id and ep.get("seasonNumber") == season_number and ep.get("episodeNumber") == episode_number:
                return record
    return None

async def ensure_series_added(tmdb_id: int, title: str, year: int, settings: AppSettings) -> Dict[str, Any]:
    """Add series to Sonarr if not present. Returns the series dict."""
    existing = await is_series_in_sonarr(tmdb_id, settings)
    if existing:
        return existing

    async with httpx.AsyncClient(timeout=20) as client:
        lookup = await client.get(
            _url(settings, f"/series/lookup?term=tmdb:{tmdb_id}"), headers=_headers(settings)
        )
        lookup.raise_for_status()
        results = lookup.json()
        if not results:
            raise Exception(f"No series found on Sonarr lookup for tmdb:{tmdb_id}")
        series_meta = results[0]

        payload = {
            "tmdbId": tmdb_id,
            "tvdbId": series_meta.get("tvdbId"),
            "title": series_meta.get("title", title),
            "qualityProfileId": settings.sonarr_quality_profile_id,
            "rootFolderPath": settings.sonarr_root_folder,
            "monitored": True,
            "addOptions": {"searchForMissingEpisodes": False},
            "images": series_meta.get("images", []),
            "titleSlug": series_meta.get("titleSlug", ""),
            "languageProfileId": 1, # Typical default
        }

        add_resp = await client.post(_url(settings, "/series"), headers=_headers(settings), json=payload)
        add_resp.raise_for_status()
        return add_resp.json()

async def get_series_folder(tmdb_id: int, title: str, year: int, settings: AppSettings) -> str:
    """Return the folder path Sonarr expects for this series."""
    series = await is_series_in_sonarr(tmdb_id, settings)
    if series and series.get("path"):
        return series["path"]
    safe_title = "".join(c for c in title if c.isalnum() or c in " -_.").strip()
    return f"{settings.sonarr_root_folder.rstrip('/')}/{safe_title} ({year})"

async def trigger_rescan(series_id: int, settings: AppSettings) -> bool:
    """Tell Sonarr to rescan a specific series' folder."""
    payload = {"name": "RescanSeries", "seriesId": series_id}
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(_url(settings, "/command"), headers=_headers(settings), json=payload)
        resp.raise_for_status()
    return True

async def test_connection(settings: AppSettings) -> Dict[str, Any]:
    """Returns Sonarr system status or raises on failure."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(_url(settings, "/system/status"), headers=_headers(settings))
        resp.raise_for_status()
        return resp.json()

async def update_series_monitored(series_id: int, monitored: bool, settings: AppSettings) -> bool:
    """Updates the monitored status of a specific series in Sonarr."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(_url(settings, f"/series/{series_id}"), headers=_headers(settings))
        resp.raise_for_status()
        series = resp.json()
        
        if series.get("monitored") == monitored:
            return True
            
        series["monitored"] = monitored
        
        put_resp = await client.put(_url(settings, f"/series/{series_id}"), headers=_headers(settings), json=series)
        put_resp.raise_for_status()
        return True
