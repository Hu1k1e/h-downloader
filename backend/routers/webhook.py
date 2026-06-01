"""
Webhook router — receives Jellyseerr notification events.
"""
import hashlib
import hmac
import json
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request, Depends
from pydantic import BaseModel
from sqlmodel import Session

from backend import config
from backend.database import get_session, get_settings
from backend.models import AppSettings
from backend.orchestrator import process_request

router = APIRouter(prefix="/webhook", tags=["webhook"])


class JellyseerrPayload(BaseModel):
    notification_type: Optional[str] = None
    media_type: Optional[str] = None
    tmdbId: Optional[str] = None
    title: Optional[str] = None


@router.post("/jellyseerr")
async def jellyseerr_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_hub_signature: Optional[str] = Header(default=None),
    session: Session = Depends(get_session),
):
    """
    Receives Jellyseerr webhook events (media_pending, media_approved, etc.)
    and kicks off the download pipeline for movies.
    """
    settings = get_settings(session)
    raw_body = await request.body()

    # ── Optional HMAC verification ────────────────────────────────────────
    if settings.webhook_secret:
        if not x_hub_signature:
            raise HTTPException(status_code=401, detail="Missing signature")
        expected = "sha256=" + hmac.new(
            settings.webhook_secret.encode(), raw_body, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected, x_hub_signature):
            raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        payload_data = json.loads(raw_body)
        payload = JellyseerrPayload(**payload_data)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    # Only handle movie requests
    if payload.media_type and payload.media_type.lower() != "movie":
        return {"status": "skipped", "reason": "not a movie"}

    # Only act on pending/approved events
    allowed_types = {"media_pending", "media_approved", "media-pending", "media-approved"}
    if payload.notification_type and payload.notification_type.lower() not in allowed_types:
        return {"status": "skipped", "reason": f"unhandled notification_type: {payload.notification_type}"}

    if not payload.tmdbId:
        raise HTTPException(status_code=400, detail="tmdbId missing from payload")

    tmdb_id = int(payload.tmdbId)

    # Fire and forget — don't block the webhook response
    background_tasks.add_task(process_request, tmdb_id)

    return {"status": "accepted", "tmdb_id": tmdb_id, "title": payload.title}
