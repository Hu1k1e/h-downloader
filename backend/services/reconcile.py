"""
Radarr / Sonarr state reconciliation.

Radarr (movies) and Sonarr (episodes) are the source of truth for: existence, monitored
flag, file presence and download-queue state. `reconcile_job` applies those facts to a
local DownloadJob using one transparent rule set. It performs no I/O, so it is trivially
unit-testable; callers do the HTTP fetching and the DB commit.

Rules (first match wins), for an item that exists in the *arr:
  1. Our own download is in flight (SEARCHING recently / DOWNLOADING from another source) -> leave status alone
  2. *arr reports a file                                  -> DONE
  3. job is IMPORTING                                     -> unchanged (tracker waits for the import)
  4. healthy queue item                                   -> DOWNLOADING (source = radarr/sonarr)
  5. completed queue item, no file yet                    -> IMPORTING
  6. a native download we were tracking vanished/failed   -> MOVIE_MISSING + request fallback search
  7. DONE but the file is gone (after a short grace)      -> MOVIE_MISSING
  8. NOT_IN_RADARR / PENDING and no file                  -> MOVIE_MISSING
For an item that no longer exists in the *arr: NOT_IN_RADARR, unmonitored.
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from backend.models import DownloadJob, JobStatus

# A job we started searching for less than this long ago is assumed to still be running.
SEARCH_GRACE = timedelta(minutes=15)
# After our own download finishes, give the *arr time to rescan before calling the file missing.
RESCAN_GRACE = timedelta(minutes=10)
# A grab can take a moment to show up in the *arr queue API.
QUEUE_GRACE = timedelta(seconds=60)


@dataclass
class ReconcileResult:
    changed: bool = False                 # any field changed
    status_changed: bool = False
    old_status: Optional[JobStatus] = None
    new_status: Optional[JobStatus] = None
    fallback: bool = False                # a native *arr download died -> try our own sources
    notes: List[str] = field(default_factory=list)


def parse_eta(timeleft: Optional[str]) -> int:
    """Parse Radarr/Sonarr 'timeleft' ('[d.]hh:mm:ss') into seconds. 0 if unknown."""
    if not timeleft:
        return 0
    try:
        parts = timeleft.split(":")
        if len(parts) != 3:
            return 0
        h_str, m_str, s_str = parts
        days = 0
        if "." in h_str:
            d, h_str = h_str.split(".", 1)
            days = int(d)
        return int(days * 86400 + int(h_str) * 3600 + int(m_str) * 60 + float(s_str))
    except (ValueError, TypeError):
        return 0


def queue_health(queue_item: Optional[Dict[str, Any]]) -> Optional[str]:
    """Classify a queue record: None (not queued), 'healthy', 'failed' or 'completed'."""
    if not queue_item:
        return None
    status = (queue_item.get("status") or "").lower()
    tracked = (queue_item.get("trackedDownloadStatus") or "").lower()
    if status == "completed":
        return "completed"
    if tracked in ("warning", "error"):
        return "failed"
    return "healthy"


def queue_progress(queue_item: Dict[str, Any]) -> Dict[str, int]:
    size = queue_item.get("size", 0) or 0
    left = queue_item.get("sizeleft", 0) or 0
    pct = int(max(0, min(100, 100 * (1 - left / size)))) if size > 0 else 0
    return {
        "pct": pct,
        "downloaded": max(0, size - left),
        "total": size,
        "eta": parse_eta(queue_item.get("timeleft")),
    }


def derive_status(item: Optional[Dict[str, Any]], queue_item: Optional[Dict[str, Any]] = None) -> str:
    """Pure, user-facing status of an *arr item: not_in_arr | available | downloading |
    importing | missing. Handy for tests and the API; reconcile_job adds local context."""
    if item is None:
        return "not_in_arr"
    if item.get("hasFile"):
        return "available"
    health = queue_health(queue_item)
    if health == "healthy":
        return "downloading"
    if health == "completed":
        return "importing"
    return "missing"


def reconcile_job(
    job: DownloadJob,
    item: Optional[Dict[str, Any]],
    queue_item: Optional[Dict[str, Any]],
    *,
    source: str,
    now: Optional[datetime] = None,
    snapshot_at: Optional[datetime] = None,
) -> ReconcileResult:
    """Apply *arr truth to `job` in place. `item` is the Radarr movie / Sonarr episode dict
    (None if it no longer exists), `queue_item` its best queue record, `source` is
    'radarr' or 'sonarr'. `snapshot_at` is when the *arr data was fetched: a local change
    made after that moment (e.g. a monitored toggle) is not overwritten by older data."""
    now = now or datetime.utcnow()
    res = ReconcileResult(old_status=job.status, new_status=job.status)
    age = (now - job.updated_at) if job.updated_at else timedelta(days=365)

    def set_(attr: str, value: Any) -> None:
        if getattr(job, attr) != value:
            setattr(job, attr, value)
            res.changed = True

    def set_status(status: JobStatus) -> None:
        if job.status != status:
            job.status = status
            res.changed = res.status_changed = True
            res.new_status = status

    # ── Gone from Radarr/Sonarr ────────────────────────────────────────────────
    if item is None:
        set_("in_arr", False)
        set_("has_file", False)
        if job.status != JobStatus.NOT_IN_RADARR:
            set_status(JobStatus.NOT_IN_RADARR)
            set_("monitored", False)
            res.notes.append("not in arr")
        return res

    set_("in_arr", True)
    if item.get("id") is not None:
        set_("arr_id", item.get("id"))
    has_file = bool(item.get("hasFile"))
    set_("has_file", has_file)

    # Monitored: arr value wins, unless we changed it locally after the snapshot was taken.
    locally_newer = snapshot_at is not None and job.updated_at is not None and job.updated_at > snapshot_at
    if not locally_newer:
        set_("monitored", bool(item.get("monitored", False)))

    # ── Our own pipeline owns the job right now ────────────────────────────────
    if job.status == JobStatus.SEARCHING and age < SEARCH_GRACE:
        return res
    if job.status == JobStatus.DOWNLOADING and (job.source_indexer or "") != source:
        return res

    health = queue_health(queue_item)

    # ── File on disk ───────────────────────────────────────────────────────────
    if has_file:
        path = (item.get("movieFile") or {}).get("path")
        set_status(JobStatus.DONE)
        set_("progress_pct", 100)
        set_("error_msg", None)
        if path:
            set_("file_path", path)
        return res

    # ── No file ────────────────────────────────────────────────────────────────
    if job.status == JobStatus.IMPORTING:
        return res

    was_native_download = job.status == JobStatus.DOWNLOADING and (job.source_indexer or "") == source

    if health == "healthy":
        prog = queue_progress(queue_item)
        set_status(JobStatus.DOWNLOADING)
        set_("source_indexer", source)
        set_("error_msg", None)
        set_("progress_pct", prog["pct"])
        set_("downloaded_bytes", prog["downloaded"])
        set_("total_bytes", prog["total"])
        if prog["eta"] > 0:
            set_("eta_seconds", prog["eta"])
        return res

    if health == "completed":
        set_status(JobStatus.IMPORTING)
        set_("source_indexer", source)
        set_("progress_pct", 100)
        return res

    if was_native_download:
        if health is None and age < QUEUE_GRACE:
            res.notes.append("waiting for queue to populate")
            return res
        set_status(JobStatus.MOVIE_MISSING)
        set_("source_indexer", None)
        set_("progress_pct", 0)
        res.fallback = True
        res.notes.append("native download failed" if health == "failed" else "native download vanished")
        return res

    if job.status == JobStatus.DONE:
        if age < RESCAN_GRACE:
            return res
        set_status(JobStatus.MOVIE_MISSING)
        set_("progress_pct", 0)
        set_("file_path", None)
        res.notes.append("file removed")
    elif job.status in (JobStatus.NOT_IN_RADARR, JobStatus.PENDING, JobStatus.SEARCHING):
        # SEARCHING only reaches here once it is older than SEARCH_GRACE, i.e. the search is orphaned.
        set_status(JobStatus.MOVIE_MISSING)
        set_("progress_pct", 0)
    return res
