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
APP_VERSION: str = "1.1.0"

# ── Security (all optional / opt-in) ───────────────────────────────────────────
# If set, every /api/* request must send this token as `X-API-Key: <token>`
# or `Authorization: Bearer <token>`. Leave empty to keep the API open.
API_AUTH_TOKEN: str = os.getenv("API_AUTH_TOKEN", "")
# If set, Radarr/Sonarr webhooks must send `X-Webhook-Token: <token>` (or ?token=).
WEBHOOK_TOKEN: str = os.getenv("WEBHOOK_TOKEN", "")
# Comma-separated list of extra browser origins allowed by CORS. Default: same-origin only.
CORS_ORIGINS: List[str] = _get_list("CORS_ORIGINS", "")

# ── Tuning ──────────────────────────────────────────────────────────────────────
MAX_CONCURRENT_DOWNLOADS: int = max(1, int(os.getenv("MAX_CONCURRENT_DOWNLOADS", "3")))
TAMILMV_BASE_URL: str = os.getenv("TAMILMV_BASE_URL", "https://www.1tamilmv.fi/")

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
