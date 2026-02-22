"""
FastAPI application entry point.
"""
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from backend.database import init_db
from backend.routers import webhook, jobs, settings
from backend import config


from apscheduler.schedulers.asyncio import AsyncIOScheduler
from backend.sync import sync_jellyseerr_requests
from backend.database import get_settings
from sqlmodel import Session
from backend.database import engine

scheduler = AsyncIOScheduler()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: create DB tables and start background scheduler."""
    init_db()
    
    # Read the sync interval from stored settings
    with Session(engine) as session:
        settings = get_settings(session)
        interval_seconds = max(30, settings.sync_interval_seconds)
    
    # Start background job to poll Jellyseerr
    scheduler.add_job(sync_jellyseerr_requests, "interval", seconds=interval_seconds, id="sync_job")
    scheduler.start()
    
    yield
    
    scheduler.shutdown()


app = FastAPI(
    title="H-Downloader",
    description="Auto-downloads regional Indian movies from Einthusan when unavailable on Radarr",
    version=config.APP_VERSION,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── API routers ───────────────────────────────────────────────────────────────
app.include_router(webhook.router)
app.include_router(jobs.router)
app.include_router(settings.router)

# ── Health check ──────────────────────────────────────────────────────────────
@app.get("/health")
def health():
    return {"status": "ok", "version": config.APP_VERSION}

# ── Serve React frontend ──────────────────────────────────────────────────────
STATIC_DIR = Path(__file__).parent.parent / "frontend" / "dist"
PUBLIC_DIR = Path(__file__).parent.parent / "frontend" / "public"

if STATIC_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(STATIC_DIR / "assets")), name="assets")

# Serve public folder files (logo, favicon etc.) from dist root if built, else from public/
_public_src = STATIC_DIR if STATIC_DIR.exists() else PUBLIC_DIR
if _public_src.exists():
    # Mount specific static files that live at the root (logo, favicon)
    app.mount("/logo.png", StaticFiles(directory=str(_public_src)), name="logo_file")

@app.get("/logo.png", include_in_schema=False)
async def serve_logo():
    for d in [STATIC_DIR, PUBLIC_DIR]:
        f = d / "logo.png"
        if f.exists():
            return FileResponse(str(f))

@app.get("/favicon.ico", include_in_schema=False)
async def serve_favicon():
    for d in [STATIC_DIR, PUBLIC_DIR]:
        for name in ["logo.png", "favicon.ico"]:
            f = d / name
            if f.exists():
                return FileResponse(str(f))

if STATIC_DIR.exists():
    @app.get("/{full_path:path}", include_in_schema=False)
    def serve_spa(full_path: str):
        """Serve the React SPA for all non-API routes."""
        index = STATIC_DIR / "index.html"
        return FileResponse(str(index))
