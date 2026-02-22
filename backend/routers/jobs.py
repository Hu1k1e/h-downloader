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
def update_monitor_status(job_id: int, update: MonitorUpdate, session: Session = Depends(get_session)):
    job = session.get(DownloadJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
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
    background_tasks.add_task(process_request, job.tmdb_id, job.language)
    return {"status": "retrying", "tmdb_id": job.tmdb_id}

@router.post("/jobs/sync")
async def sync_jellyseerr(background_tasks: BackgroundTasks):
    """Manually trigger a sync with Jellyseerr requests."""
    from backend.sync import sync_jellyseerr_requests
    background_tasks.add_task(sync_jellyseerr_requests)
    return {"status": "sync_started"}


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
