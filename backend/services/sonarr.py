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


async def is_series_in_sonarr(tvdb_id: int, settings: AppSettings) -> Optional[Dict[str, Any]]:
    """Return the series dict if it exists in Sonarr."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(_url(settings, "/series"), headers=_headers(settings))
        resp.raise_for_status()
        for s in resp.json():
            if s.get("tvdbId") == tvdb_id:
                return s
    return None


async def get_all_series(settings: AppSettings) -> List[Dict[str, Any]]:
    """Return all series in Sonarr."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(_url(settings, "/series"), headers=_headers(settings))
        resp.raise_for_status()
        return resp.json()

async def get_full_queue(settings: AppSettings) -> List[Dict[str, Any]]:
    """Return all records in the Sonarr queue."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(_url(settings, "/queue?pageSize=10000"), headers=_headers(settings))
        resp.raise_for_status()
        data = resp.json()
        return data.get("records", []) if isinstance(data, dict) else data


async def get_episode_queue_status(episode_id: int, settings: AppSettings) -> Optional[Dict[str, Any]]:
    """
    Checks the Sonarr queue for a specific Sonarr episode_id.
    """
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(_url(settings, "/queue?pageSize=10000"), headers=_headers(settings))
        resp.raise_for_status()
        queue_data = resp.json()
        records = queue_data.get("records", []) if isinstance(queue_data, dict) else queue_data
        
        episode_records = [r for r in records if r.get("episodeId") == episode_id]
        if not episode_records:
            return None
            
        for record in episode_records:
            tracked = record.get("trackedDownloadStatus", "").lower()
            if tracked not in ("warning", "error"):
                return record
                
        return episode_records[0]


async def ensure_series_added(tvdb_id: int, title: str, settings: AppSettings) -> Dict[str, Any]:
    """Add series to Sonarr if not present. Returns the series dict."""
    existing = await is_series_in_sonarr(tvdb_id, settings)
    if existing:
        return existing

    async with httpx.AsyncClient(timeout=20) as client:
        lookup = await client.get(
            _url(settings, f"/series/lookup?term=tvdb:{tvdb_id}"), headers=_headers(settings)
        )
        lookup.raise_for_status()
        
        results = lookup.json()
        if not results:
            raise Exception(f"Series with TVDB {tvdb_id} not found in Sonarr lookup")
            
        series_meta = results[0]

        payload = {
            "tvdbId": tvdb_id,
            "title": series_meta.get("title", title),
            "qualityProfileId": settings.sonarr_quality_profile_id,
            "rootFolderPath": settings.sonarr_root_folder,
            "monitored": True,
            "addOptions": {"searchForMissingEpisodes": False},
            "images": series_meta.get("images", []),
            "titleSlug": series_meta.get("titleSlug", ""),
            "languageProfileId": 1,
            "seriesType": series_meta.get("seriesType", "standard")
        }

        add_resp = await client.post(_url(settings, "/series"), headers=_headers(settings), json=payload)
        add_resp.raise_for_status()
        return add_resp.json()


async def get_series_folder(tvdb_id: int, title: str, settings: AppSettings) -> str:
    """Return the folder path Sonarr expects for this series."""
    series = await is_series_in_sonarr(tvdb_id, settings)
    if series and series.get("path"):
        return series["path"]
    safe_title = "".join(c for c in title if c.isalnum() or c in " -_.").strip()
    return f"{settings.sonarr_root_folder.rstrip('/')}/{safe_title}"


async def trigger_rescan(series_id: int, settings: AppSettings) -> bool:
    """Tell Sonarr to rescan a specific series folder."""
    payload = {"name": "RescanSeries", "seriesId": series_id}
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(_url(settings, "/command"), headers=_headers(settings), json=payload)
        resp.raise_for_status()
    return True


async def get_quality_profile_resolution(profile_id: int, settings: AppSettings) -> Optional[str]:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(_url(settings, "/qualityprofile"), headers=_headers(settings))
            resp.raise_for_status()
            profiles = resp.json()
            for p in profiles:
                if p.get("id") == profile_id:
                    name = p.get("name", "").lower()
                    if "1080p" in name: return "1080p"
                    if "720p" in name: return "720p"
                    if "2160p" in name or "4k" in name: return "2160p"
                    if "4k" in name: return "4k"
                    return name
            return None
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Failed to fetch quality profiles: {e}")
        return None


async def get_episodes(series_id: int, settings: AppSettings) -> List[Dict[str, Any]]:
    """Returns all episodes for a given internal series ID."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(_url(settings, f"/episode?seriesId={series_id}"), headers=_headers(settings))
        resp.raise_for_status()
        return resp.json()

async def get_missing_episodes(series_id: int, settings: AppSettings) -> List[Dict[str, Any]]:
    """Returns all monitored, unaired/missing episodes for a series."""
    episodes = await get_episodes(series_id, settings)
    missing = []
    for ep in episodes:
        if ep.get("monitored") and not ep.get("hasFile"):
            missing.append(ep)
    return missing

async def get_episode(series_id: int, season_number: int, episode_number: int, settings: AppSettings) -> Optional[Dict[str, Any]]:
    episodes = await get_episodes(series_id, settings)
    for ep in episodes:
        if ep.get("seasonNumber") == season_number and ep.get("episodeNumber") == episode_number:
            return ep
    return None

async def test_connection(settings: AppSettings) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(_url(settings, "/system/status"), headers=_headers(settings))
        resp.raise_for_status()
        return resp.json()
