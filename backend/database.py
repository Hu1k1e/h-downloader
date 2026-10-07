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

# (table, column, DDL type + default). Each column is checked and added independently,
# so a partially-migrated database heals itself on the next start.
_MIGRATIONS = [
    ("appsettings", "download_sources_priority", "VARCHAR NOT NULL DEFAULT 'einthusan,1tamilmv'"),
    ("appsettings", "qbittorrent_url", "VARCHAR NOT NULL DEFAULT 'http://localhost:8080'"),
    ("appsettings", "qbittorrent_username", "VARCHAR NOT NULL DEFAULT 'admin'"),
    ("appsettings", "qbittorrent_password", "VARCHAR NOT NULL DEFAULT 'adminadmin'"),
    ("appsettings", "qbittorrent_category_movies", "VARCHAR NOT NULL DEFAULT 'radarr'"),
    ("appsettings", "qbittorrent_category_series", "VARCHAR NOT NULL DEFAULT 'sonarr'"),
    ("appsettings", "auto_delete_failed_torrents_hours", "INTEGER NOT NULL DEFAULT 24"),
    ("appsettings", "min_file_size_mb", "INTEGER NOT NULL DEFAULT 800"),
    ("appsettings", "max_file_size_mb", "INTEGER NOT NULL DEFAULT 15000"),
    ("appsettings", "search_delay_seconds", "INTEGER NOT NULL DEFAULT 120"),
    ("appsettings", "enable_jellyseerr_auto_request", "BOOLEAN NOT NULL DEFAULT 1"),
    ("appsettings", "enable_radarr_auto_search", "BOOLEAN NOT NULL DEFAULT 1"),
    ("appsettings", "missing_search_interval_hours", "INTEGER NOT NULL DEFAULT 24"),
    ("appsettings", "missing_search_batch_size", "INTEGER NOT NULL DEFAULT 50"),
    ("appsettings", "movie_download_sources_priority", "VARCHAR NOT NULL DEFAULT 'einthusan,1tamilmv'"),
    ("appsettings", "tv_download_sources_priority", "VARCHAR NOT NULL DEFAULT '1tamilmv,bollyzone'"),
    ("appsettings", "sonarr_url", "VARCHAR NOT NULL DEFAULT 'http://localhost:8989'"),
    ("appsettings", "sonarr_api_key", "VARCHAR NOT NULL DEFAULT ''"),
    ("appsettings", "sonarr_root_folder", "VARCHAR NOT NULL DEFAULT '/tv'"),
    ("appsettings", "sonarr_quality_profile_id", "INTEGER NOT NULL DEFAULT 1"),
    ("appsettings", "enable_sonarr_auto_search", "BOOLEAN NOT NULL DEFAULT 1"),
    ("appsettings", "new_release_grace_hours", "INTEGER NOT NULL DEFAULT 48"),
    ("appsettings", "llm_enabled", "BOOLEAN NOT NULL DEFAULT 0"),
    ("appsettings", "llm_api_url", "VARCHAR NOT NULL DEFAULT 'https://api.freellmapi.com/v1'"),
    ("appsettings", "llm_api_key", "VARCHAR NOT NULL DEFAULT ''"),
    ("appsettings", "llm_model", "VARCHAR NOT NULL DEFAULT 'gpt-3.5-turbo'"),
    ("appsettings", "fmovies_base_url", "VARCHAR NOT NULL DEFAULT 'https://www.f-movies.org'"),
    ("downloadjob", "source_indexer", "VARCHAR"),
    ("downloadjob", "torrent_hash", "VARCHAR"),
    ("downloadjob", "blacklisted_urls", "VARCHAR"),
    ("downloadjob", "poster_path", "VARCHAR"),
    ("downloadjob", "discovered_source", "VARCHAR"),
    ("downloadjob", "discovered_url", "VARCHAR"),
    ("downloadjob", "discovered_magnet", "VARCHAR"),
    ("downloadjob", "eta_seconds", "INTEGER"),
    ("downloadjob", "media_type", "VARCHAR NOT NULL DEFAULT 'movie'"),
    ("downloadjob", "tvdb_id", "INTEGER"),
    ("downloadjob", "season_number", "INTEGER"),
    ("downloadjob", "episode_number", "INTEGER"),
    ("downloadjob", "release_date", "DATETIME"),
    ("downloadjob", "arr_id", "INTEGER"),
    ("downloadjob", "in_arr", "BOOLEAN NOT NULL DEFAULT 1"),
    ("downloadjob", "has_file", "BOOLEAN NOT NULL DEFAULT 0"),
    ("downloadjob", "last_synced_at", "DATETIME"),
    ("downloadjob", "sync_error", "VARCHAR"),
    ("logentry", "tvdb_id", "INTEGER"),
    ("logentry", "job_id", "INTEGER"),
]


def _run_migrations():
    from sqlalchemy import text
    import logging
    log = logging.getLogger(__name__)
    with engine.begin() as conn:
        existing: dict = {}
        for table, column, ddl in _MIGRATIONS:
            if table not in existing:
                rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
                existing[table] = {row[1] for row in rows}
            cols = existing[table]
            if not cols or column in cols:  # table missing (fresh DB handled by create_all) or column present
                continue
            try:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
                cols.add(column)
                log.info(f"DB migration: added {table}.{column}")
            except Exception as e:  # keep going so one bad column does not block the rest
                log.error(f"DB migration failed for {table}.{column}: {e}")


def init_db():
    SQLModel.metadata.create_all(engine)

    try:
        _run_migrations()
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Auto-migration failed: {e}")

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
