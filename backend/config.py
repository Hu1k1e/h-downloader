"""
Configuration — reads all settings from environment variables.
"""
import os
from typing import List


def _get_list(key: str, default: str = "") -> List[str]:
    raw = os.getenv(key, default)
    return [v.strip() for v in raw.split(",") if v.strip()]


# ── Radarr ──────────────────────────────────────────────────────────────────
RADARR_URL: str = os.getenv("RADARR_URL", "http://localhost:7878")
RADARR_API_KEY: str = os.getenv("RADARR_API_KEY", "")
RADARR_ROOT_FOLDER: str = os.getenv("RADARR_ROOT_FOLDER", "/movies")
RADARR_QUALITY_PROFILE_ID: int = int(os.getenv("RADARR_QUALITY_PROFILE_ID", "1"))

# ── Jellyseerr ───────────────────────────────────────────────────────────────
JELLYSEERR_URL: str = os.getenv("JELLYSEERR_URL", "http://localhost:5055")
JELLYSEERR_API_KEY: str = os.getenv("JELLYSEERR_API_KEY", "")
WEBHOOK_SECRET: str = os.getenv("WEBHOOK_SECRET", "")

# ── TMDB ─────────────────────────────────────────────────────────────────────
TMDB_API_KEY: str = os.getenv("TMDB_API_KEY", "")
TMDB_BASE_URL: str = "https://api.themoviedb.org/3"

# ── Einthusan ────────────────────────────────────────────────────────────────
EINTHUSAN_LANGUAGES: List[str] = _get_list(
    "EINTHUSAN_LANGUAGES", "malayalam,tamil,telugu"
)

# ── Download behaviour ────────────────────────────────────────────────────────
# Fallback: if no digital release date exists, check this many days after
# the theatrical release before attempting Einthusan search
DIGITAL_RELEASE_FALLBACK_DAYS: int = int(
    os.getenv("DIGITAL_RELEASE_FALLBACK_DAYS", "90")
)

# ── App ───────────────────────────────────────────────────────────────────────
DATA_DIR: str = os.getenv("DATA_DIR", "/app/data")
APP_VERSION: str = "1.0.0"

# Map from spoken language name → Einthusan URL slug
LANGUAGE_SLUG_MAP = {
    "malayalam": "malayalam",
    "tamil": "tamil",
    "telugu": "telugu",
    "hindi": "hindi",
    "kannada": "kannada",
    "bengali": "bengali",
    "marathi": "marathi",
    "punjabi": "punjabi",
    "korean": "korean",
}

# TMDB spoken language codes → Einthusan language slug
TMDB_LANG_TO_EINTHUSAN = {
    "ml": "malayalam",
    "ta": "tamil",
    "te": "telugu",
    "hi": "hindi",
    "kn": "kannada",
    "bn": "bengali",
    "mr": "marathi",
    "pa": "punjabi",
    "ko": "korean",
}
