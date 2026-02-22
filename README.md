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

### 1. Download configuration
Download the `docker-compose.yml` and `.env.example` files from this repository to your server:
```bash
curl -O https://raw.githubusercontent.com/svijaymohan745/h-downloader/main/docker-compose.yml
curl -o .env https://raw.githubusercontent.com/svijaymohan745/h-downloader/main/.env.example
```

### 2. Configure environment
Edit `.env` with your API keys and server IP where required.
Edit `docker-compose.yml` if you need to change the Radarr media mounting path.

### 3. Authenticate with GitHub Docker Registry
Because this is a private repository, you need to log in to GitHub's container registry to pull the image. You will need a [Personal Access Token (classic)](https://github.com/settings/tokens) with the `read:packages` permission.

```bash
docker login ghcr.io -u YOUR_GITHUB_USERNAME
# When prompted for a password, paste your Personal Access Token
```

### 4. Start the container
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
