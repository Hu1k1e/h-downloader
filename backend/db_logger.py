import logging
from backend.models import LogEntry, LogLevel
from sqlmodel import Session
from backend.database import engine

logger = logging.getLogger(__name__)

def log_action(action: str, message: str, level: LogLevel = LogLevel.INFO, tmdb_id: int = None, tvdb_id: int = None, job_id: int = None):
    """
    Logs an action to the database and standard console logger.
    """
    if level == LogLevel.ERROR:
        logger.error(f"[{action}] {message}")
    elif level == LogLevel.WARNING:
        logger.warning(f"[{action}] {message}")
    elif level == LogLevel.DEBUG:
        logger.debug(f"[{action}] {message}")
    else:
        logger.info(f"[{action}] {message}")
        
    try:
        with Session(engine) as session:
            entry = LogEntry(
                level=level,
                action=action,
                message=message,
                tmdb_id=tmdb_id,
                tvdb_id=tvdb_id,
                job_id=job_id
            )
            session.add(entry)
            session.commit()
    except Exception as e:
        logger.error(f"Failed to write log to database: {e}")
