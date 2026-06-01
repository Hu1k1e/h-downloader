"""
SQLModel database models.
"""
from datetime import datetime
from enum import Enum
from typing import Optional, List
import json

from sqlmodel import Field, SQLModel


class JobStatus(str, Enum):
    PENDING = "pending"
    CHECKING_RADARR = "checking_radarr"
    SEARCHING = "searching"
    DOWNLOADING = "downloading"
    IMPORTING = "importing"
    DONE = "done"
    MOVIE_MISSING = "movie_missing"   # Radarr has movie entry but file is gone from disk
    NOT_FOUND = "not_found"
    FAILED = "failed"
    SKIPPED = "skipped"


class DownloadJob(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    tmdb_id: int = Field(index=True)
    title: str
    year: Optional[int] = None
    language: Optional[str] = None          # e.g. "malayalam"
    status: JobStatus = JobStatus.PENDING
    einthusan_url: Optional[str] = None     # watch page URL
    direct_url: Optional[str] = None        # CDN MP4 URL
    file_path: Optional[str] = None         # final saved path
    progress_pct: int = 0                   # 0-100
    downloaded_bytes: int = 0
    total_bytes: int = 0
    error_msg: Optional[str] = None
    monitored: bool = Field(default=True, index=True)
    poster_path: Optional[str] = None         # TMDB poster path e.g. /abc123.jpg
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class DownloadJobRead(SQLModel):
    """Public schema returned by the API (same fields, no table=True)."""
    id: int
    tmdb_id: int
    title: str
    year: Optional[int]
    language: Optional[str]
    status: JobStatus
    einthusan_url: Optional[str]
    direct_url: Optional[str]
    file_path: Optional[str]
    progress_pct: int
    downloaded_bytes: int
    total_bytes: int
    error_msg: Optional[str]
    monitored: bool
    poster_path: Optional[str]
    created_at: datetime
    updated_at: datetime


class AppSettings(SQLModel, table=True):
    """Stores a single row containing UI-configurable application settings."""
    id: Optional[int] = Field(default=None, primary_key=True)
    
    radarr_url: str = Field(default="http://localhost:7878")
    radarr_api_key: str = Field(default="")
    radarr_root_folder: str = Field(default="/movies")
    radarr_quality_profile_id: int = Field(default=1)
    
    jellyseerr_url: str = Field(default="http://localhost:5055")
    jellyseerr_api_key: str = Field(default="")
    webhook_secret: str = Field(default="")
    
    tmdb_api_key: str = Field(default="")
    
    # Store languages as a comma-separated string in DB
    einthusan_languages_str: str = Field(default="malayalam,tamil,telugu")
    
    digital_release_fallback_days: int = Field(default=90)
    sync_interval_seconds: int = Field(default=900)  # 15 minutes by default


class AppSettingsRead(SQLModel):
    radarr_url: str
    radarr_root_folder: str
    radarr_api_key_set: bool
    jellyseerr_url: str
    jellyseerr_api_key_set: bool
    tmdb_api_key_set: bool
    einthusan_languages: List[str]
    digital_release_fallback_days: int
    sync_interval_seconds: int
    app_version: str
    webhook_url_hint: str


class AppSettingsUpdate(SQLModel):
    radarr_url: Optional[str] = None
    radarr_root_folder: Optional[str] = None
    radarr_api_key: Optional[str] = None # Empty string means don't update
    
    jellyseerr_url: Optional[str] = None
    jellyseerr_api_key: Optional[str] = None
    
    tmdb_api_key: Optional[str] = None
    
    einthusan_languages: Optional[List[str]] = None
    digital_release_fallback_days: Optional[int] = None
    sync_interval_seconds: Optional[int] = None  # min 30 s
