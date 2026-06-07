"""
Logs API router — CRUD for system logs.
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from datetime import datetime, timedelta

from backend.database import get_session
from backend.models import LogEntry, LogEntryRead, LogLevel
from fastapi.responses import Response
import csv
import io

router = APIRouter(prefix="/api/logs", tags=["logs"])

@router.get("", response_model=List[LogEntryRead])
def list_logs(
    level: Optional[LogLevel] = None,
    limit: int = 500,
    offset: int = 0,
    search: Optional[str] = None,
    session: Session = Depends(get_session)
):
    query = select(LogEntry).order_by(LogEntry.timestamp.desc())
    
    if level:
        query = query.where(LogEntry.level == level)
    if search:
        query = query.where(LogEntry.message.contains(search) | LogEntry.action.contains(search))
        
    query = query.offset(offset).limit(limit)
    return session.exec(query).all()


@router.get("/csv")
def download_logs_csv(
    level: Optional[LogLevel] = None,
    search: Optional[str] = None,
    session: Session = Depends(get_session)
):
    query = select(LogEntry).order_by(LogEntry.timestamp.desc())
    
    if level:
        query = query.where(LogEntry.level == level)
    if search:
        query = query.where(LogEntry.message.contains(search) | LogEntry.action.contains(search))
        
    logs = session.exec(query).all()
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Timestamp", "Level", "Action", "Message", "TMDB ID", "Job ID", "Error"])
    
    for log in logs:
        writer.writerow([
            log.timestamp.isoformat(),
            log.level.value if log.level else "",
            log.action,
            log.message,
            log.tmdb_id or "",
            log.job_id or "",
            log.error_detail or ""
        ])
        
    csv_str = output.getvalue()
    return Response(
        content=csv_str,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=h-downloader-logs-{datetime.utcnow().strftime('%Y%m%d%H%M')}.csv"}
    )

@router.delete("/all")
def delete_all_logs(session: Session = Depends(get_session)):
    session.query(LogEntry).delete()
    session.commit()
    return {"status": "deleted_all"}


@router.delete("/older-than")
def delete_logs_older_than(days: int = 7, session: Session = Depends(get_session)):
    if days < 0:
        raise HTTPException(status_code=400, detail="Days must be >= 0")
        
    cutoff = datetime.utcnow() - timedelta(days=days)
    deleted = session.query(LogEntry).filter(LogEntry.timestamp < cutoff).delete()
    session.commit()
    return {"status": "deleted_older", "deleted_count": deleted}
