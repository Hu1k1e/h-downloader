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

def init_db():
    SQLModel.metadata.create_all(engine)
    
    # Auto-migrate AppSettings table (since SQLite doesn't add columns automatically)
    try:
        from sqlalchemy import text
        with engine.begin() as conn:
            result = conn.execute(text("PRAGMA table_info(appsettings)")).fetchall()
            columns = [row[1] for row in result]
            if result and "download_sources_priority" not in columns:
                conn.execute(text("ALTER TABLE appsettings ADD COLUMN download_sources_priority VARCHAR NOT NULL DEFAULT 'einthusan,1tamilmv'"))
                conn.execute(text("ALTER TABLE appsettings ADD COLUMN qbittorrent_url VARCHAR NOT NULL DEFAULT 'http://localhost:8080'"))
                conn.execute(text("ALTER TABLE appsettings ADD COLUMN qbittorrent_username VARCHAR NOT NULL DEFAULT 'admin'"))
                conn.execute(text("ALTER TABLE appsettings ADD COLUMN qbittorrent_password VARCHAR NOT NULL DEFAULT 'adminadmin'"))
                conn.execute(text("ALTER TABLE appsettings ADD COLUMN qbittorrent_category_movies VARCHAR NOT NULL DEFAULT 'radarr'"))
                conn.execute(text("ALTER TABLE appsettings ADD COLUMN qbittorrent_category_series VARCHAR NOT NULL DEFAULT 'sonarr'"))
            if result and "auto_delete_failed_torrents_hours" not in columns:
                conn.execute(text("ALTER TABLE appsettings ADD COLUMN auto_delete_failed_torrents_hours INTEGER NOT NULL DEFAULT 24"))
                conn.execute(text("ALTER TABLE appsettings ADD COLUMN min_file_size_mb INTEGER NOT NULL DEFAULT 800"))
                conn.execute(text("ALTER TABLE appsettings ADD COLUMN max_file_size_mb INTEGER NOT NULL DEFAULT 15000"))
            if result and "search_delay_seconds" not in columns:
                conn.execute(text("ALTER TABLE appsettings ADD COLUMN search_delay_seconds INTEGER NOT NULL DEFAULT 120"))
            if result and "enable_jellyseerr_auto_request" not in columns:
                conn.execute(text("ALTER TABLE appsettings ADD COLUMN enable_jellyseerr_auto_request BOOLEAN NOT NULL DEFAULT 1"))
                conn.execute(text("ALTER TABLE appsettings ADD COLUMN enable_radarr_auto_search BOOLEAN NOT NULL DEFAULT 1"))
            
            # Auto-migrate DownloadJob table
            dj_result = conn.execute(text("PRAGMA table_info(downloadjob)")).fetchall()
            dj_columns = [row[1] for row in dj_result]
            if dj_result and "source_indexer" not in dj_columns:
                conn.execute(text("ALTER TABLE downloadjob ADD COLUMN source_indexer VARCHAR"))
                conn.execute(text("ALTER TABLE downloadjob ADD COLUMN torrent_hash VARCHAR"))
                conn.execute(text("ALTER TABLE downloadjob ADD COLUMN blacklisted_urls VARCHAR"))
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Auto-migration failed: {e}")
        
    # Initialize settings if table exists but is empty
    with Session(engine) as session:
        settings = session.exec(select(AppSettings)).first()
        if not settings:
            new_settings = AppSettings(
                radarr_url=config.RADARR_URL,
                radarr_api_key=config.RADARR_API_KEY,
                radarr_root_folder=config.RADARR_ROOT_FOLDER,
                radarr_quality_profile_id=config.RADARR_QUALITY_PROFILE_ID,
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
