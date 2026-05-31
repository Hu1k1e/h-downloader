"""
Settings API router — read/write app configuration.
"""
from typing import List

from fastapi import APIRouter, Depends
from sqlmodel import Session

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
        sonarr_url=settings.sonarr_url,
        sonarr_root_folder=settings.sonarr_root_folder,
        sonarr_api_key_set=bool(settings.sonarr_api_key),
        jellyseerr_url=settings.jellyseerr_url,
        jellyseerr_api_key_set=bool(settings.jellyseerr_api_key),
        tmdb_api_key_set=bool(settings.tmdb_api_key),
        einthusan_languages=[lang.strip() for lang in settings.einthusan_languages_str.split(",") if lang.strip()],
        digital_release_fallback_days=settings.digital_release_fallback_days,
        sync_interval_seconds=settings.sync_interval_seconds,
        app_version=config.APP_VERSION,
        webhook_url_hint="/webhook/jellyseerr",
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
        
    if update_data.sonarr_url is not None:
        settings.sonarr_url = update_data.sonarr_url
    if update_data.sonarr_root_folder is not None:
        settings.sonarr_root_folder = update_data.sonarr_root_folder
    if update_data.sonarr_api_key is not None and update_data.sonarr_api_key != "":
        settings.sonarr_api_key = update_data.sonarr_api_key
        
    if update_data.jellyseerr_url is not None:
        settings.jellyseerr_url = update_data.jellyseerr_url
    if update_data.jellyseerr_api_key is not None and update_data.jellyseerr_api_key != "":
        settings.jellyseerr_api_key = update_data.jellyseerr_api_key
        
    if update_data.tmdb_api_key is not None and update_data.tmdb_api_key != "":
        settings.tmdb_api_key = update_data.tmdb_api_key
        
    if update_data.einthusan_languages is not None:
        settings.einthusan_languages_str = ",".join(update_data.einthusan_languages)
        
    if update_data.digital_release_fallback_days is not None:
        settings.digital_release_fallback_days = update_data.digital_release_fallback_days
        
    if update_data.sync_interval_seconds is not None:
        # Enforce minimum of 30 seconds
        new_interval = max(30, update_data.sync_interval_seconds)
        settings.sync_interval_seconds = new_interval
        # Reschedule the running APScheduler job immediately so the new interval
        # takes effect without requiring a server restart
        try:
            from backend.main import scheduler
            from backend.sync import sync_jellyseerr_requests
            scheduler.reschedule_job(
                "sync_job",
                trigger="interval",
                seconds=new_interval,
            )
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Could not reschedule sync job: {e}")
        
    session.add(settings)
    session.commit()
    session.refresh(settings)
    
    return get_current_settings(session)
