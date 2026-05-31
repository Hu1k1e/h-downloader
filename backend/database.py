"""
Database session management.
"""
import os
from sqlmodel import create_engine, SQLModel, Session, select
from sqlalchemy.pool import NullPool
from backend import config
from backend.models import AppSettings

os.makedirs(config.DATA_DIR, exist_ok=True)
DATABASE_URL = f"sqlite:///{config.DATA_DIR}/einthusan_downloader.db"

engine = create_engine(
    DATABASE_URL, 
    echo=False,
    poolclass=NullPool,
    connect_args={"check_same_thread": False, "timeout": 30.0}
)

from sqlalchemy import text
from sqlalchemy.exc import OperationalError

def init_db():
    SQLModel.metadata.create_all(engine)
    
    # Simple auto-migration for newly added columns
    with engine.begin() as conn:
        for stmt in [
            "ALTER TABLE appsettings ADD COLUMN sonarr_url VARCHAR",
            "ALTER TABLE appsettings ADD COLUMN sonarr_api_key VARCHAR",
            "ALTER TABLE appsettings ADD COLUMN sonarr_root_folder VARCHAR",
            "ALTER TABLE appsettings ADD COLUMN sonarr_quality_profile_id INTEGER",
            "ALTER TABLE downloadjob ADD COLUMN media_type VARCHAR DEFAULT 'movie'",
            "ALTER TABLE downloadjob ADD COLUMN season_number INTEGER",
            "ALTER TABLE downloadjob ADD COLUMN episode_number INTEGER",
        ]:
            try:
                conn.execute(text(stmt))
            except OperationalError:
                pass
                
        # Fill NULL values with defaults for existing rows that were altered
        conn.execute(text("UPDATE appsettings SET sonarr_url = 'http://localhost:8989' WHERE sonarr_url IS NULL"))
        conn.execute(text("UPDATE appsettings SET sonarr_api_key = '' WHERE sonarr_api_key IS NULL"))
        conn.execute(text("UPDATE appsettings SET sonarr_root_folder = '/tv' WHERE sonarr_root_folder IS NULL"))
        conn.execute(text("UPDATE appsettings SET sonarr_quality_profile_id = 1 WHERE sonarr_quality_profile_id IS NULL"))
        conn.execute(text("UPDATE downloadjob SET media_type = 'movie' WHERE media_type IS NULL"))
                
    # Initialize settings if table exists but is empty
    with Session(engine) as session:
        settings = session.exec(select(AppSettings)).first()
        if not settings:
            new_settings = AppSettings(
                radarr_url=config.RADARR_URL,
                radarr_api_key=config.RADARR_API_KEY,
                radarr_root_folder=config.RADARR_ROOT_FOLDER,
                radarr_quality_profile_id=config.RADARR_QUALITY_PROFILE_ID,
                sonarr_url=config.SONARR_URL,
                sonarr_api_key=config.SONARR_API_KEY,
                sonarr_root_folder=config.SONARR_ROOT_FOLDER,
                sonarr_quality_profile_id=config.SONARR_QUALITY_PROFILE_ID,
                jellyseerr_url=config.JELLYSEERR_URL,
                jellyseerr_api_key=config.JELLYSEERR_API_KEY,
                webhook_secret=config.WEBHOOK_SECRET,
                tmdb_api_key=config.TMDB_API_KEY,
                einthusan_languages_str=",".join(config.EINTHUSAN_LANGUAGES),
                digital_release_fallback_days=config.DIGITAL_RELEASE_FALLBACK_DAYS,
            )
            session.add(new_settings)
            session.commit()

def get_session():
    with Session(engine) as session:
        yield session

def get_settings(session: Session) -> AppSettings:
    """Helper to always return the singleton AppSettings row."""
    # Since init_db handles creation, it should always exist.
    # Fallback just in case:
    settings = session.exec(select(AppSettings)).first()
    if not settings:
        settings = AppSettings()
        session.add(settings)
        session.commit()
        session.refresh(settings)
    return settings
