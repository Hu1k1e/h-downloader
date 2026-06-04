from datetime import datetime, timedelta
from typing import List, Optional
from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, select
from backend.database import get_session
from backend.models import LogEntry, LogEntryRead

router = APIRouter(prefix="/api/logs", tags=["logs"])

@router.get("", response_model=List[LogEntryRead])
def get_logs(
    level: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    session: Session = Depends(get_session)
):
    query = select(LogEntry).order_by(LogEntry.timestamp.desc())
    if level:
        query = query.where(LogEntry.level == level)
    if search:
        query = query.where(LogEntry.message.like(f"%{search}%") | LogEntry.action.like(f"%{search}%"))
        
    query = query.offset(offset).limit(limit)
    return session.exec(query).all()

@router.delete("")
def delete_logs(
    older_than_days: Optional[int] = None,
    session: Session = Depends(get_session)
):
    if older_than_days is not None:
        cutoff = datetime.utcnow() - timedelta(days=older_than_days)
        jobs = session.exec(select(LogEntry).where(LogEntry.timestamp < cutoff)).all()
    else:
        jobs = session.exec(select(LogEntry)).all()
        
    count = len(jobs)
    for j in jobs:
        session.delete(j)
    session.commit()
    return {"deleted": count}
