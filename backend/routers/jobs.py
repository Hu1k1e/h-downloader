"""
Jobs API router — CRUD for download jobs and manual trigger.
"""
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from backend.database import get_session, get_settings
from backend.models import DownloadJob, DownloadJobRead, JobStatus, AppSettings
from backend.orchestrator import process_request
from backend.services import radarr as radarr_svc
from backend.services import tmdb as tmdb_svc
from backend import config

router = APIRouter(prefix="/api", tags=["jobs"])

# ── Jobs list & detail ───────────────────────────────────────────────────────

@router.get("/jobs", response_model=List[DownloadJobRead])
def list_jobs(
    status: Optional[str] = None,
    language: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    session: Session = Depends(get_session),
):
    query = select(DownloadJob).order_by(DownloadJob.created_at.desc())
    if status:
        query = query.where(DownloadJob.status == status)
    if language:
        query = query.where(DownloadJob.language == language)
    query = query.offset(offset).limit(limit)
    return session.exec(query).all()


@router.get("/jobs/{job_id}", response_model=DownloadJobRead)
def get_job(job_id: int, session: Session = Depends(get_session)):
    job = session.get(DownloadJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.delete("/jobs/{job_id}")
def delete_job(job_id: int, session: Session = Depends(get_session)):
    job = session.get(DownloadJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    session.delete(job)
    session.commit()
    return {"status": "deleted"}


class MonitorUpdate(BaseModel):
    monitored: bool

@router.put("/jobs/{job_id}/monitor")
async def update_monitor_status(job_id: int, update: MonitorUpdate, session: Session = Depends(get_session)):
    job = session.get(DownloadJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
        
    settings = get_settings(session)
    
    try:
        # Push update to Radarr
        radarr_movie = await radarr_svc.is_movie_in_radarr(job.tmdb_id, settings)
        if radarr_movie:
            await radarr_svc.update_movie_monitored(radarr_movie["id"], update.monitored, settings)
    except Exception as e:
        # Log the error but still update local state if preferred, or fail.
        # It's better to fail if Radarr is authoritative.
        import logging
        logging.getLogger(__name__).error(f"Failed to update monitored status in Radarr: {e}")
        raise HTTPException(status_code=502, detail="Failed to update Radarr")
        
    job.monitored = update.monitored
    session.add(job)
    session.commit()
    session.refresh(job)
    return {"status": "updated", "monitored": job.monitored}

# ── Stats ────────────────────────────────────────────────────────────────────

@router.get("/stats")
def get_stats(session: Session = Depends(get_session)):
    jobs = session.exec(select(DownloadJob)).all()
    return {
        "total": len(jobs),
        "active": sum(1 for j in jobs if j.status in (JobStatus.DOWNLOADING, JobStatus.SEARCHING)),
        "completed": sum(1 for j in jobs if j.status == JobStatus.DONE),
        "failed": sum(1 for j in jobs if j.status == JobStatus.FAILED),
        "not_found": sum(1 for j in jobs if j.status == JobStatus.NOT_FOUND),
        "skipped": sum(1 for j in jobs if j.status == JobStatus.SKIPPED),
    }


# ── Manual trigger ───────────────────────────────────────────────────────────

class TriggerRequest(BaseModel):
    tmdb_id: Optional[int] = None
    title: Optional[str] = None
    language: Optional[str] = None


@router.post("/jobs/trigger")
async def trigger_download(req: TriggerRequest, background_tasks: BackgroundTasks, session: Session = Depends(get_session)):
    if not req.tmdb_id and not req.title:
        raise HTTPException(status_code=400, detail="Provide tmdb_id or title")

    settings = get_settings(session)
    tmdb_id = req.tmdb_id

    # If no TMDB ID, search TMDB by title
    if not tmdb_id and req.title:
        if not settings.tmdb_api_key:
            raise HTTPException(status_code=400, detail="TMDB API key is not configured. Please go to Settings and save your TMDB API key first.")
        import httpx
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{config.TMDB_BASE_URL}/search/movie",
                    params={"api_key": settings.tmdb_api_key, "query": req.title},
                )
                resp.raise_for_status()
                results = resp.json().get("results", [])
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                raise HTTPException(status_code=400, detail="TMDB API key is invalid. Please update it in Settings.")
            raise HTTPException(status_code=502, detail=f"TMDB search failed: {e}")
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"TMDB search failed: {e}")
        if not results:
            raise HTTPException(status_code=404, detail=f"No TMDB results for '{req.title}'")
        tmdb_id = results[0]["id"]

    background_tasks.add_task(process_request, tmdb_id, req.language)
    return {"status": "accepted", "tmdb_id": tmdb_id}

@router.post("/jobs/trigger-all")
async def trigger_all_monitored(background_tasks: BackgroundTasks, session: Session = Depends(get_session)):
    """Manually trigger orchestrator for all monitored movies."""
    jobs = session.exec(select(DownloadJob).where(DownloadJob.monitored == True)).all()
    triggered = 0
    for job in jobs:
        # Avoid re-triggering jobs that are already actively processing
        if job.status not in (JobStatus.DOWNLOADING, JobStatus.SEARCHING):
             background_tasks.add_task(process_request, job.tmdb_id, job.language)
             triggered += 1
             
    return {"status": "accepted", "triggered": triggered}

@router.post("/jobs/{job_id}/retry")
async def retry_job(job_id: int, background_tasks: BackgroundTasks, session: Session = Depends(get_session)):
    job = session.get(DownloadJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
        
    job.status = JobStatus.PENDING
    job.progress_pct = 0
    job.error_msg = None
    session.add(job)
    session.commit()
    
    background_tasks.add_task(process_request, job.tmdb_id, job.language)
    return {"status": "retrying", "tmdb_id": job.tmdb_id}

@router.post("/jobs/sync")
async def sync_jellyseerr(background_tasks: BackgroundTasks):
    """Manually trigger a sync with Jellyseerr requests."""
    from backend.sync import sync_jellyseerr_requests
    background_tasks.add_task(sync_jellyseerr_requests)
    return {"status": "sync_started"}


@router.post("/jobs/import-radarr")
async def trigger_import_radarr(background_tasks: BackgroundTasks, session: Session = Depends(get_session)):
    """Import all movies from Radarr that match configured regional languages."""
    settings = get_settings(session)
    if not settings.radarr_api_key:
        raise HTTPException(status_code=400, detail="Radarr API key is not configured.")

    try:
        movies = await radarr_svc.get_all_movies(settings)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch movies from Radarr: {e}")

    # Parse configured languages (e.g. "malayalam,tamil")
    configured_langs = [l.strip().lower() for l in settings.einthusan_languages_str.split(",") if l.strip()]
    if not configured_langs:
        raise HTTPException(status_code=400, detail="No Einthusan languages configured in settings.")

    imported_count = 0
    for movie in movies:
        # Radarr language comes as {"id": 4, "name": "Malayalam"}
        lang_obj = movie.get("originalLanguage")
        if not lang_obj:
            continue
        
        lang_name = lang_obj.get("name", "").lower()
        if lang_name in configured_langs:
            tmdb_id = movie.get("tmdbId")
            if not tmdb_id:
                continue

            # Check if job already exists
            existing_job = session.exec(select(DownloadJob).where(DownloadJob.tmdb_id == tmdb_id)).first()
            if existing_job:
                continue

            # Add it to jobs
            poster_path = None
            for img in movie.get("images", []):
                if img.get("coverType") == "poster":
                    remote_url = img.get("remoteUrl", "")
                    if remote_url and "tmdb.org" in remote_url:
                        poster_path = "/" + remote_url.split("/")[-1]
                    break

            # Check if job already exists
            existing_job = session.exec(select(DownloadJob).where(DownloadJob.tmdb_id == tmdb_id)).first()
            if existing_job:
                # Heal previously imported jobs missing poster or stuck in PENDING
                updated = False
                if not existing_job.poster_path and poster_path:
                    existing_job.poster_path = poster_path
                    updated = True
                if existing_job.status == JobStatus.PENDING and not movie.get("hasFile"):
                    existing_job.status = JobStatus.MOVIE_MISSING
                    updated = True
                if updated:
                    session.add(existing_job)
                    imported_count += 1
                continue

            new_job = DownloadJob(
                tmdb_id=tmdb_id,
                title=movie.get("title", "Unknown"),
                year=movie.get("year"),
                language=lang_name,
                monitored=movie.get("monitored", True),
                status=JobStatus.DONE if movie.get("hasFile") else JobStatus.MOVIE_MISSING,
                poster_path=poster_path
            )

            session.add(new_job)
            imported_count += 1

    if imported_count > 0:
        session.commit()
        
    return {"status": "success", "imported": imported_count}


# ── Connection tests ─────────────────────────────────────────────────────────

@router.get("/test/radarr")
async def test_radarr(session: Session = Depends(get_session)):
    settings = get_settings(session)
    try:
        result = await radarr_svc.test_connection(settings)
        return {"status": "ok", "version": result.get("version")}
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/test/tmdb")
async def test_tmdb(session: Session = Depends(get_session)):
    settings = get_settings(session)
    try:
        await tmdb_svc.test_connection(settings)
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))
