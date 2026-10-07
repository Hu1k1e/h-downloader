"""
FastAPI application entry point.
"""
import asyncio
import hmac
import logging
from contextlib import asynccontextmanager
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s:\t  %(name)s - %(message)s")
# httpx logs every request URL at INFO — that would write TMDB/API keys passed as query params to the logs.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

from backend.database import init_db
from backend.routers import webhook, jobs, settings, logs
from backend import config
from backend.sync import (
    active_job_tracker_loop, discovery_tracker_loop, radarr_state_sync_loop,
    sonarr_state_sync_loop, recover_orphaned_jobs,
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: create/migrate DB tables, recover interrupted jobs and start background loops."""
    init_db()
    try:
        recover_orphaned_jobs()
    except Exception as e:
        logger.error(f"Startup recovery failed: {e}")

    tasks = [
        asyncio.create_task(active_job_tracker_loop(), name="active_job_tracker"),
        asyncio.create_task(discovery_tracker_loop(), name="discovery_tracker"),
        asyncio.create_task(radarr_state_sync_loop(), name="radarr_state_sync"),
        asyncio.create_task(sonarr_state_sync_loop(), name="sonarr_state_sync"),
    ]

    yield

    for t in tasks:
        t.cancel()
    # Never let a stuck loop block shutdown (container stop): wait briefly, then report and move on.
    _, pending = await asyncio.wait(tasks, timeout=10)
    for t in pending:
        logger.warning(f"Background task {t.get_name()} did not stop within 10s: {t.get_stack(limit=6)}")


app = FastAPI(
    title="H-Downloader",
    description="Keeps Radarr/Sonarr libraries complete by falling back to regional sources (Einthusan, 1TamilMV, BollyZone, FMovies)",
    version=config.APP_VERSION,
    lifespan=lifespan,
)

# The bundled UI is served from the same origin, so no CORS is needed by default.
if config.CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.CORS_ORIGINS,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.middleware("http")
async def api_auth(request: Request, call_next):
    """Optional API protection: set API_AUTH_TOKEN to require it on every /api/* request."""
    token = config.API_AUTH_TOKEN
    if token and request.url.path.startswith("/api/") and request.method != "OPTIONS":
        supplied = request.headers.get("x-api-key") or ""
        auth = request.headers.get("authorization") or ""
        if not supplied and auth.lower().startswith("bearer "):
            supplied = auth[7:]
        if not hmac.compare_digest(supplied.encode(), token.encode()):
            return JSONResponse(status_code=401, content={"detail": "Invalid or missing API token"})
    return await call_next(request)


# ── API routers ───────────────────────────────────────────────────────────────
app.include_router(webhook.router)
app.include_router(jobs.router)
app.include_router(settings.router)
app.include_router(logs.router)


# ── Health check ──────────────────────────────────────────────────────────────
@app.get("/health")
def health():
    return {"status": "ok", "version": config.APP_VERSION}


# ── Serve React frontend ──────────────────────────────────────────────────────
STATIC_DIR = Path(__file__).parent.parent / "frontend" / "dist"
PUBLIC_DIR = Path(__file__).parent.parent / "frontend" / "public"

if STATIC_DIR.exists() and (STATIC_DIR / "assets").exists():
    app.mount("/assets", StaticFiles(directory=str(STATIC_DIR / "assets")), name="assets")


@app.get("/logo.png", include_in_schema=False)
async def serve_logo():
    for d in [STATIC_DIR, PUBLIC_DIR]:
        f = d / "logo.png"
        if f.exists():
            return FileResponse(str(f))
    raise HTTPException(status_code=404)


@app.get("/favicon.ico", include_in_schema=False)
async def serve_favicon():
    for d in [STATIC_DIR, PUBLIC_DIR]:
        for name in ["logo.png", "favicon.ico"]:
            f = d / name
            if f.exists():
                return FileResponse(str(f))
    raise HTTPException(status_code=404)


if STATIC_DIR.exists():
    @app.get("/{full_path:path}", include_in_schema=False)
    def serve_spa(full_path: str):
        """Serve the React SPA for all non-API routes."""
        if full_path.startswith(("api/", "webhook/")):
            raise HTTPException(status_code=404, detail="Not found")
        return FileResponse(str(STATIC_DIR / "index.html"))
