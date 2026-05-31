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
    tvdbId: Optional[str] = None
    title: Optional[str] = None
    extra: Optional[list] = None


@router.post("/jellyseerr")
async def jellyseerr_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_hub_signature: Optional[str] = Header(default=None),
    session: Session = Depends(get_session),
):
    """
    Receives Jellyseerr webhook events (media_pending, media_approved, etc.)
    and kicks off the download pipeline for movies and TV shows.
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

    # Only act on pending/approved events
    allowed_types = {"media_pending", "media_approved", "media-pending", "media-approved"}
    if payload.notification_type and payload.notification_type.lower() not in allowed_types:
        return {"status": "skipped", "reason": f"unhandled notification_type: {payload.notification_type}"}

    if not payload.tmdbId and not payload.tvdbId:
        raise HTTPException(status_code=400, detail="tmdbId or tvdbId missing from payload")

    tmdb_id = int(payload.tmdbId) if payload.tmdbId else 0

    media_type = payload.media_type.lower() if payload.media_type else "movie"

    # Fire and forget — don't block the webhook response
    if media_type == "tv":
        if payload.extra:
            for extra_item in payload.extra:
                season = extra_item.get("season")
                episode = extra_item.get("episode")
                if season and episode:
                    background_tasks.add_task(process_request, tmdb_id, None, "series", season, episode)
        else:
            # If no specific episodes, maybe just trigger season 1 episode 1 or generic
            background_tasks.add_task(process_request, tmdb_id, None, "series", 1, 1)
    else:
        background_tasks.add_task(process_request, tmdb_id, None, "movie", None, None)

    return {"status": "accepted", "tmdb_id": tmdb_id, "title": payload.title, "media_type": media_type}
