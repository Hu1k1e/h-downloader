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
