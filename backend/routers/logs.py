"""
Logs API router — CRUD for system logs.
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from datetime import datetime, timedelta

from backend.database import get_session
from backend.models import LogEntry, LogEntryRead, LogLevel

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
