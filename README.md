# Einthusan Downloader

A Docker-hosted web service that auto-downloads regional Indian movies from **Einthusan.tv** when they're not available through your standard indexers, bridging **Jellyseerr → Radarr → Einthusan** seamlessly.

## Features
- 🔔 Listens for Jellyseerr webhook movie requests
- ✅ Checks Radarr — skips if already downloaded
- 📅 Checks TMDB digital release date before searching
- 🔍 Searches Einthusan.tv with fuzzy title matching
- ⬇ Extracts signed MP4 URL and streams download directly
- 📥 Triggers Radarr import when complete
- 🖥 Dark-themed web GUI at port 8756

## Supported Languages
Malayalam, Tamil, Telugu, Hindi, Kannada, Bengali, Marathi, Punjabi

## Quick Start

The easiest way to deploy is using Docker Compose. The image is publicly available on GitHub Container Registry (`ghcr.io/svijaymohan745/h-downloader`).

### 1. Create `docker-compose.yml`
Create a folder for the project and make a `docker-compose.yml` file with this content:

```yaml
version: "3.9"

services:
  einthusan-downloader:
    image: ghcr.io/svijaymohan745/h-downloader:latest
    container_name: einthusan-downloader
    restart: unless-stopped
    ports:
      - "8756:8000"
    volumes:
      - /mnt/nas/media:/media   # Matches Radarr's media mapping
      - ./data:/app/data        # Database mapping for the downloader
    env_file:
      - .env
    networks:
      - media-network

networks:
  media-network:
    external: true   # Join your existing Docker media server network
```

### 2. Create `.env` file
In the same folder, create a `.env` file and fill in your API keys:

```bash
# ── Radarr ──────────────────────────────────────────────────────────
RADARR_URL=http://YOUR_SERVER_IP:7878
RADARR_API_KEY=your_radarr_api_key_here
RADARR_ROOT_FOLDER=/media
RADARR_QUALITY_PROFILE_ID=1

# ── Jellyseerr ───────────────────────────────────────────────────────
JELLYSEERR_URL=http://YOUR_SERVER_IP:5055
JELLYSEERR_API_KEY=your_jellyseerr_api_key_here

# ── TMDB ─────────────────────────────────────────────────────────────
TMDB_API_KEY=your_tmdb_api_key_here

# ── Einthusan ────────────────────────────────────────────────────────
EINTHUSAN_LANGUAGES=malayalam,tamil,telugu,hindi

# ── Optional ─────────────────────────────────────────────────────────
DIGITAL_RELEASE_FALLBACK_DAYS=90
# WEBHOOK_SECRET=your_random_secret_here

# ── Internal ─────────────────────────────────────────────────────────
DATA_DIR=/app/data
```

### 3. Start the container
```bash
docker compose up -d
```

Open **http://your-server:8756**

### 4. Configure Jellyseerr webhook

In Jellyseerr → **Settings → Notifications → Webhook**:

- **URL**: `http://your-server:8756/webhook/jellyseerr`
- **Enable**: Media Pending, Media Approved
- **JSON Payload**:
```json
{
  "notification_type": "{{notification_type}}",
  "media_type": "{{media_type}}",
  "tmdbId": "{{media_tmdbid}}",
  "title": "{{subject}}"
}
```

## How It Works

```
[Trigger 1] Jellyseerr Webhook (Optional)
    → POST /webhook/jellyseerr  (Instantly receives Media Pending/Approved)
    
[Trigger 2] Background API Polling (Default)
    → Every 15 mins, polls Jellyseerr /api/v1/request for Approved movies
    
    → Check Radarr: already downloaded? → skip
    → Check TMDB: digital release passed? → skip if not yet
    → Search Einthusan.tv (fuzzy match)
        → Found? Extract MP4 URL via internal AJAX API
            → Stream download → Radarr movies folder
                → Trigger Radarr DownloadedMoviesScan
                    → Radarr imports → Jellyfin sees it ✅
```

## API Endpoints

| Method | Path | Description |
|---|---|---|
| POST | `/webhook/jellyseerr` | Jellyseerr webhook receiver |
| GET | `/api/jobs` | List all jobs |
| GET | `/api/stats` | Dashboard stats |
| POST | `/api/jobs/trigger` | Manual trigger by title or TMDB ID |
| POST | `/api/jobs/{id}/retry` | Retry a failed job |
| DELETE | `/api/jobs/{id}` | Remove a job |
| GET | `/api/settings` | Current configuration |
| GET | `/api/test/radarr` | Test Radarr connection |
| GET | `/api/test/tmdb` | Test TMDB connection |
| GET | `/health` | Health check |

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `RADARR_URL` | — | Radarr base URL |
| `RADARR_API_KEY` | — | Radarr API key |
| `RADARR_ROOT_FOLDER` | `/movies` | Root folder for downloads |
| `JELLYSEERR_URL` | — | Jellyseerr base URL |
| `JELLYSEERR_API_KEY` | — | Jellyseerr API key |
| `TMDB_API_KEY` | — | TMDB API key (free at themoviedb.org) |
| `EINTHUSAN_LANGUAGES` | `malayalam,tamil,telugu` | Languages to search |
| `DIGITAL_RELEASE_FALLBACK_DAYS` | `90` | Days after theatrical if no digital date |
| `WEBHOOK_SECRET` | _(empty)_ | Optional HMAC secret for webhook |
