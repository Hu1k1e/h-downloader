"""
SQLModel database models.
"""
from datetime import datetime
from enum import Enum
from typing import Optional, List
import json

from sqlmodel import Field, SQLModel


class LogLevel(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    DEBUG = "debug"


class LogEntry(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    timestamp: datetime = Field(default_factory=datetime.utcnow, index=True)
    level: LogLevel = LogLevel.INFO
    action: str = Field(index=True)
    message: str
    tmdb_id: Optional[int] = None
    tvdb_id: Optional[int] = None
    job_id: Optional[int] = None


class LogEntryRead(SQLModel):
    id: int
    timestamp: datetime
    level: LogLevel
    action: str
    message: str
    tmdb_id: Optional[int]
    tvdb_id: Optional[int]
    job_id: Optional[int]


class JobStatus(str, Enum):
    PENDING = "pending"
    CHECKING_RADARR = "checking_radarr"
    SEARCHING = "searching"
    DOWNLOADING = "downloading"
    IMPORTING = "importing"
    DONE = "done"
    MOVIE_MISSING = "movie_missing"   # Radarr has movie entry but file is gone from disk
    NOT_FOUND = "not_found"
    NOT_IN_RADARR = "not_in_radarr"   # Movie has been deleted from Radarr
    FAILED = "failed"
    SKIPPED = "skipped"
    DISCOVERED = "discovered"


class DownloadJob(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    media_type: str = Field(default="movie", index=True) # "movie" or "tv"
    tmdb_id: Optional[int] = Field(default=None, index=True)
    tvdb_id: Optional[int] = Field(default=None, index=True)
    season_number: Optional[int] = None
    episode_number: Optional[int] = None
    title: str
    year: Optional[int] = None
    language: Optional[str] = None          # e.g. "malayalam"
    status: JobStatus = JobStatus.PENDING
    einthusan_url: Optional[str] = Field(default=None)
    direct_url: Optional[str] = Field(default=None)
    
    # Discovery fields
    discovered_source: Optional[str] = Field(default=None)
    discovered_url: Optional[str] = Field(default=None)
    discovered_magnet: Optional[str] = Field(default=None)
    file_path: Optional[str] = None         # final saved path
    progress_pct: int = 0                   # 0-100
    downloaded_bytes: int = 0
    total_bytes: int = 0
    eta_seconds: Optional[int] = None
    error_msg: Optional[str] = None
    monitored: bool = Field(default=True, index=True)
    poster_path: Optional[str] = None         # TMDB poster path e.g. /abc123.jpg
    source_indexer: Optional[str] = None      # e.g., '1tamilmv', 'einthusan'
    torrent_hash: Optional[str] = None        # qBittorrent info hash
    blacklisted_urls: Optional[str] = None    # comma separated skipped/failed hashes/urls
    release_date: Optional[datetime] = None   # For TV: airDateUtc, For Movies: TMDB digital date
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow, sa_column_kwargs={"onupdate": datetime.utcnow})


class DownloadJobRead(SQLModel):
    """Public schema returned by the API (same fields, no table=True)."""
    id: int
    media_type: str
    tmdb_id: Optional[int]
    tvdb_id: Optional[int]
    season_number: Optional[int]
    episode_number: Optional[int]
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
    eta_seconds: Optional[int]
    error_msg: Optional[str]
    monitored: bool
    poster_path: Optional[str]
    source_indexer: Optional[str]
    release_date: Optional[datetime]
    torrent_hash: Optional[str]
    blacklisted_urls: Optional[str]
    created_at: datetime
    updated_at: datetime


class AppSettings(SQLModel, table=True):
    """Stores a single row containing UI-configurable application settings."""
    id: Optional[int] = Field(default=None, primary_key=True)
    
    radarr_url: str = Field(default="http://localhost:7878")
    radarr_api_key: str = Field(default="")
    radarr_root_folder: str = Field(default="/movies")
    radarr_quality_profile_id: int = Field(default=1)
    
    sonarr_url: str = Field(default="http://localhost:8989")
    sonarr_api_key: str = Field(default="")
    sonarr_root_folder: str = Field(default="/tv")
    sonarr_quality_profile_id: int = Field(default=1)
    
    jellyseerr_url: str = Field(default="http://localhost:5055")
    jellyseerr_api_key: str = Field(default="")
    webhook_secret: str = Field(default="")
    
    tmdb_api_key: str = Field(default="")
    
    # Store languages as a comma-separated string in DB
    einthusan_languages_str: str = Field(default="malayalam,tamil,telugu")
    
    # Digital release window settings
    digital_release_fallback_days: int = Field(default=90)
    
    # Automation intervals
    search_delay_seconds: int = Field(default=120)
    missing_search_interval_hours: int = Field(default=24)
    missing_search_batch_size: int = Field(default=50)
    new_release_grace_hours: int = Field(default=48)
    
    movie_download_sources_priority: str = Field(default="einthusan,1tamilmv,fmovies")
    tv_download_sources_priority: str = Field(default="1tamilmv,bollyzone,fmovies")
    
    qbittorrent_url: str = Field(default="http://localhost:8080")
    qbittorrent_username: str = Field(default="admin")
    qbittorrent_password: str = Field(default="adminadmin")
    qbittorrent_category_movies: str = Field(default="radarr")
    qbittorrent_category_series: str = Field(default="sonarr")
    
    auto_delete_failed_torrents_hours: int = Field(default=24)
    min_file_size_mb: int = Field(default=800)
    max_file_size_mb: int = Field(default=15000)
    
    enable_jellyseerr_auto_request: bool = Field(default=True)
    enable_radarr_auto_search: bool = Field(default=True)
    enable_sonarr_auto_search: bool = Field(default=True)

    # LLM Settings
    llm_enabled: bool = Field(default=False)
    llm_api_url: str = Field(default="https://api.freellmapi.com/v1")
    llm_api_key: str = Field(default="")
    llm_model: str = Field(default="gpt-3.5-turbo")
    
    # FMovies Settings
    fmovies_base_url: str = Field(default="https://www.f-movies.org")

class AppSettingsRead(SQLModel):
    radarr_url: str
    radarr_root_folder: str
    radarr_api_key_set: bool
    sonarr_url: str
    sonarr_root_folder: str
    sonarr_api_key_set: bool
    jellyseerr_url: str
    jellyseerr_api_key_set: bool
    tmdb_api_key_set: bool
    einthusan_languages: List[str]
    digital_release_fallback_days: int
    search_delay_seconds: int
    missing_search_interval_hours: int
    missing_search_batch_size: int
    new_release_grace_hours: int
    app_version: str
    webhook_url_hint: str
    movie_download_sources_priority: List[str]
    tv_download_sources_priority: List[str]
    qbittorrent_url: str
    qbittorrent_username: str
    qbittorrent_category_movies: str
    qbittorrent_category_series: str
    qbittorrent_password_set: bool
    
    auto_delete_failed_torrents_hours: int
    min_file_size_mb: int
    max_file_size_mb: int
    
    enable_jellyseerr_auto_request: bool
    enable_radarr_auto_search: bool
    enable_sonarr_auto_search: bool
    
    llm_enabled: bool
    llm_api_url: str
    llm_api_key_set: bool
    llm_model: str
    fmovies_base_url: str


class AppSettingsUpdate(SQLModel):
    radarr_url: Optional[str] = None
    radarr_root_folder: Optional[str] = None
    radarr_api_key: Optional[str] = None # Empty string means don't update
    
    sonarr_url: Optional[str] = None
    sonarr_root_folder: Optional[str] = None
    sonarr_api_key: Optional[str] = None
    
    jellyseerr_url: Optional[str] = None
    jellyseerr_api_key: Optional[str] = None
    
    tmdb_api_key: Optional[str] = None
    
    einthusan_languages: Optional[List[str]] = None
    digital_release_fallback_days: Optional[int] = None
    search_delay_seconds: Optional[int] = None
    missing_search_interval_hours: Optional[int] = None
    missing_search_batch_size: Optional[int] = None
    new_release_grace_hours: Optional[int] = None
    movie_download_sources_priority: Optional[List[str]] = None
    tv_download_sources_priority: Optional[List[str]] = None
    
    qbittorrent_url: Optional[str] = None
    qbittorrent_username: Optional[str] = None
    qbittorrent_password: Optional[str] = None
    qbittorrent_category_movies: Optional[str] = None
    qbittorrent_category_series: Optional[str] = None
    
    auto_delete_failed_torrents_hours: Optional[int] = None
    min_file_size_mb: Optional[int] = None
    max_file_size_mb: Optional[int] = None
    
    enable_jellyseerr_auto_request: Optional[bool] = None
    enable_radarr_auto_search: Optional[bool] = None
    enable_sonarr_auto_search: Optional[bool] = None

    llm_enabled: Optional[bool] = None
    llm_api_url: Optional[str] = None
    llm_api_key: Optional[str] = None
    llm_model: Optional[str] = None
    fmovies_base_url: Optional[str] = None

