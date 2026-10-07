from datetime import datetime

from sqlmodel import Session, select

from backend import sync
from backend.models import DownloadJob, JobStatus


def snapshot(episodes, queue=None, failed=()):
    series = [{"id": 3, "tvdbId": 77, "title": "Cool Show", "images": [{"coverType": "poster", "remoteUrl": "http://p/x.jpg"}]}]
    return sync.SonarrSnapshot(series, queue or [], {3: {(e["seasonNumber"], e["episodeNumber"]): e for e in episodes}}, set(failed))


def ep(i, s, n, **kw):
    base = {"id": i, "seasonNumber": s, "episodeNumber": n, "monitored": True, "hasFile": False, "airDateUtc": "2020-01-02T10:00:00Z"}
    base.update(kw)
    return base


def tv_job(session, s, e, **kw):
    j = DownloadJob(media_type="tv", tmdb_id=0, tvdb_id=77, season_number=s, episode_number=e, title=f"Cool Show S{s:02d}E{e:02d}", **kw)
    session.add(j)
    session.commit()
    session.refresh(j)
    return j


def test_sonarr_state_applies_files_queue_deletions_and_creates_missing(db):
    with Session(db) as s:
        done = tv_job(s, 1, 1, status=JobStatus.MOVIE_MISSING)
        downloading = tv_job(s, 1, 2, status=JobStatus.MOVIE_MISSING)
        removed = tv_job(s, 1, 9, status=JobStatus.DONE, has_file=True)
        unmon = tv_job(s, 1, 3, status=JobStatus.MOVIE_MISSING, monitored=True)

        now = datetime.utcnow()  # snapshot taken after the local rows were written
        eps = [
            ep(11, 1, 1, hasFile=True),
            ep(12, 1, 2),
            ep(13, 1, 3, monitored=False),
            ep(14, 1, 4),                      # unknown monitored+missing -> gets created
            ep(15, 0, 1, hasFile=True),        # special with a file -> only created by manual import
        ]
        queue = [{"episodeId": 12, "status": "downloading", "trackedDownloadStatus": "ok", "size": 100, "sizeleft": 25}]
        stats = sync.apply_sonarr_state(s, snapshot(eps, queue), now, now)

        s.refresh(done), s.refresh(downloading), s.refresh(removed), s.refresh(unmon)
        assert done.status == JobStatus.DONE
        assert downloading.status == JobStatus.DOWNLOADING and downloading.source_indexer == "sonarr" and downloading.progress_pct == 75
        assert removed.status == JobStatus.NOT_IN_RADARR and removed.in_arr is False
        assert unmon.monitored is False  # Sonarr is the source of truth
        assert stats.created == 1 and stats.deleted == 1
        created = s.exec(select(DownloadJob).where(DownloadJob.episode_number == 4)).first()
        assert created.status == JobStatus.MOVIE_MISSING and created.release_date == datetime(2020, 1, 2, 10, 0)
        assert s.exec(select(DownloadJob).where(DownloadJob.season_number == 0)).first() is None

        # Manual import also brings in downloaded episodes, specials included
        sync.apply_sonarr_state(s, snapshot(eps, queue), now, now, create_all=True)
        special = s.exec(select(DownloadJob).where(DownloadJob.season_number == 0)).first()
        assert special.status == JobStatus.DONE


def test_series_whose_episodes_could_not_be_fetched_are_left_alone(db):
    now = datetime.utcnow()
    with Session(db) as s:
        job = tv_job(s, 1, 1, status=JobStatus.DONE, has_file=True)
        sync.apply_sonarr_state(s, snapshot([], failed=[3]), now, now)
        s.refresh(job)
        assert job.status == JobStatus.DONE  # no data != "deleted"
