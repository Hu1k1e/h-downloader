"""
Settings API router — read/write app configuration.
"""
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session
from pydantic import BaseModel

from backend import config
from backend.database import get_session, get_settings
from backend.models import AppSettingsRead, AppSettingsUpdate

router = APIRouter(prefix="/api/settings", tags=["settings"])

@router.get("", response_model=AppSettingsRead)
def get_current_settings(session: Session = Depends(get_session)):
    settings = get_settings(session)
    return AppSettingsRead(
        radarr_url=settings.radarr_url,
        radarr_root_folder=settings.radarr_root_folder,
        radarr_api_key_set=bool(settings.radarr_api_key),
        jellyseerr_url=settings.jellyseerr_url,
        jellyseerr_api_key_set=bool(settings.jellyseerr_api_key),
        tmdb_api_key_set=bool(settings.tmdb_api_key),
        einthusan_languages=[lang.strip().lower() for lang in settings.einthusan_languages_str.split(",") if lang.strip().lower() in config.LANGUAGE_SLUG_MAP],
        digital_release_fallback_days=settings.digital_release_fallback_days,
        search_delay_seconds=settings.search_delay_seconds,
        app_version=config.APP_VERSION,
        webhook_url_hint="/webhook/jellyseerr",
        download_sources_priority=[s.strip() for s in settings.download_sources_priority.split(",") if s.strip()],
        qbittorrent_url=settings.qbittorrent_url,
        qbittorrent_username=settings.qbittorrent_username,
        qbittorrent_category_movies=settings.qbittorrent_category_movies,
        qbittorrent_category_series=settings.qbittorrent_category_series,
        qbittorrent_password_set=bool(settings.qbittorrent_password),
        auto_delete_failed_torrents_hours=settings.auto_delete_failed_torrents_hours,
        min_file_size_mb=settings.min_file_size_mb,
        max_file_size_mb=settings.max_file_size_mb,
        enable_jellyseerr_auto_request=settings.enable_jellyseerr_auto_request,
        enable_radarr_auto_search=settings.enable_radarr_auto_search,
    )


@router.post("", response_model=AppSettingsRead)
def update_settings(update_data: AppSettingsUpdate, session: Session = Depends(get_session)):
    settings = get_settings(session)
    
    if update_data.radarr_url is not None:
        settings.radarr_url = update_data.radarr_url
    if update_data.radarr_root_folder is not None:
        settings.radarr_root_folder = update_data.radarr_root_folder
    if update_data.radarr_api_key is not None and update_data.radarr_api_key != "":
        settings.radarr_api_key = update_data.radarr_api_key
        
    if update_data.jellyseerr_url is not None:
        settings.jellyseerr_url = update_data.jellyseerr_url
    if update_data.jellyseerr_api_key is not None and update_data.jellyseerr_api_key != "":
        settings.jellyseerr_api_key = update_data.jellyseerr_api_key
        
    if update_data.tmdb_api_key is not None and update_data.tmdb_api_key != "":
        settings.tmdb_api_key = update_data.tmdb_api_key
        
    if update_data.search_delay_seconds is not None:
        settings.search_delay_seconds = max(0, update_data.search_delay_seconds)
        
    if update_data.download_sources_priority is not None:
        settings.download_sources_priority = ",".join(update_data.download_sources_priority)
        
    if update_data.einthusan_languages is not None:
        settings.einthusan_languages_str = ",".join(update_data.einthusan_languages)
        
    if update_data.digital_release_fallback_days is not None:
        settings.digital_release_fallback_days = update_data.digital_release_fallback_days
        

    if update_data.download_sources_priority is not None:
        settings.download_sources_priority = ",".join(update_data.download_sources_priority)
        
    if update_data.qbittorrent_url is not None:
        settings.qbittorrent_url = update_data.qbittorrent_url
    if update_data.qbittorrent_username is not None:
        settings.qbittorrent_username = update_data.qbittorrent_username
    if update_data.qbittorrent_password is not None and update_data.qbittorrent_password != "":
        settings.qbittorrent_password = update_data.qbittorrent_password
    if update_data.qbittorrent_category_movies is not None:
        settings.qbittorrent_category_movies = update_data.qbittorrent_category_movies
    if update_data.qbittorrent_category_series is not None:
        settings.qbittorrent_category_series = update_data.qbittorrent_category_series
        
    if update_data.auto_delete_failed_torrents_hours is not None:
        settings.auto_delete_failed_torrents_hours = update_data.auto_delete_failed_torrents_hours
    if update_data.min_file_size_mb is not None:
        settings.min_file_size_mb = update_data.min_file_size_mb
    if update_data.max_file_size_mb is not None:
        settings.max_file_size_mb = update_data.max_file_size_mb
        
    if update_data.enable_jellyseerr_auto_request is not None:
        settings.enable_jellyseerr_auto_request = update_data.enable_jellyseerr_auto_request
    if update_data.enable_radarr_auto_search is not None:
        settings.enable_radarr_auto_search = update_data.enable_radarr_auto_search
        
    session.add(settings)
    session.commit()
    session.refresh(settings)
    
    return get_current_settings(session)

class QbittorrentTestRequest(BaseModel):
    url: str
    username: str
    password: str

@router.post("/test-qbittorrent")
def test_qbittorrent_connection(req: QbittorrentTestRequest):
    try:
        import qbittorrentapi
        qbt_client = qbittorrentapi.Client(
            host=req.url,
            username=req.username,
            password=req.password,
        )
        qbt_client.auth_log_in()
        
        # Fetch categories
        categories = qbt_client.torrents_categories()
        cat_names = list(categories.keys())
        return {"status": "ok", "categories": cat_names}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
