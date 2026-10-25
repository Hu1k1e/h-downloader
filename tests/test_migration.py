from sqlalchemy import text

# Columns that existed from the very first release (never part of _MIGRATIONS).
OLD_APPSETTINGS = (
    "id INTEGER PRIMARY KEY, radarr_url VARCHAR NOT NULL DEFAULT 'x', radarr_api_key VARCHAR NOT NULL DEFAULT '', "
    "radarr_root_folder VARCHAR NOT NULL DEFAULT '/movies', radarr_quality_profile_id INTEGER NOT NULL DEFAULT 1, "
    "jellyseerr_url VARCHAR NOT NULL DEFAULT '', jellyseerr_api_key VARCHAR NOT NULL DEFAULT '', "
    "webhook_secret VARCHAR NOT NULL DEFAULT '', tmdb_api_key VARCHAR NOT NULL DEFAULT '', "
    "einthusan_languages_str VARCHAR NOT NULL DEFAULT 'tamil', digital_release_fallback_days INTEGER NOT NULL DEFAULT 90, "
    "qbittorrent_url VARCHAR NOT NULL DEFAULT 'q'"  # one migrated column present, the rest missing
)
OLD_JOB = (
    "id INTEGER PRIMARY KEY, tmdb_id INTEGER, title VARCHAR NOT NULL, year INTEGER, language VARCHAR, "
    "status VARCHAR NOT NULL DEFAULT 'PENDING', einthusan_url VARCHAR, direct_url VARCHAR, file_path VARCHAR, "
    "progress_pct INTEGER NOT NULL DEFAULT 0, downloaded_bytes INTEGER NOT NULL DEFAULT 0, "
    "total_bytes INTEGER NOT NULL DEFAULT 0, error_msg VARCHAR, monitored BOOLEAN NOT NULL DEFAULT 1, "
    "created_at DATETIME, updated_at DATETIME"
)


def test_partial_old_schema_is_healed_column_by_column(db):
    from backend.database import engine, init_db, _MIGRATIONS, get_settings
    from sqlmodel import Session, select
    from backend.models import DownloadJob

    with engine.begin() as c:
        c.execute(text("DROP TABLE appsettings"))
        c.execute(text("DROP TABLE downloadjob"))
        c.execute(text(f"CREATE TABLE appsettings ({OLD_APPSETTINGS})"))
        c.execute(text("INSERT INTO appsettings (id) VALUES (1)"))
        c.execute(text(f"CREATE TABLE downloadjob ({OLD_JOB})"))
        c.execute(text("INSERT INTO downloadjob (title, created_at, updated_at) VALUES ('old', '2026-01-01', '2026-01-01')"))
    init_db()
    with engine.begin() as c:
        for table in ("appsettings", "downloadjob"):
            cols = {r[1] for r in c.execute(text(f"PRAGMA table_info({table})")).fetchall()}
            wanted = {col for t, col, _ in _MIGRATIONS if t == table}
            assert wanted <= cols, wanted - cols

    # The ORM can read the migrated rows with the new columns' defaults
    with Session(engine) as s:
        job = s.exec(select(DownloadJob)).first()
        assert (job.title, job.in_arr, job.has_file, job.media_type) == ("old", True, False, "movie")
        assert get_settings(s).sonarr_url == "http://localhost:8989"
    init_db()  # idempotent


def test_hidden_auto_search_toggle_is_reenabled_once(db):
    """enable_radarr_auto_search was hidden from the UI with a stale 'off' value, which silently
    blocked every automatic movie search. Existing DBs get it reset once; later choices stick."""
    from backend.database import engine, init_db, get_settings
    from backend.models import DATA_VERSION
    from sqlmodel import Session

    with engine.begin() as c:
        c.execute(text("DROP TABLE appsettings"))
        c.execute(text(f"CREATE TABLE appsettings ({OLD_APPSETTINGS}, "
                       "enable_radarr_auto_search BOOLEAN NOT NULL DEFAULT 1)"))
        c.execute(text("INSERT INTO appsettings (id, enable_radarr_auto_search) VALUES (1, 0)"))
    init_db()
    with Session(engine) as s:
        st = get_settings(s)
        assert st.enable_radarr_auto_search is True and st.data_version == DATA_VERSION
        st.enable_radarr_auto_search = False  # the user turns it off again from Settings
        s.add(st)
        s.commit()
    init_db()
    with Session(engine) as s:
        assert get_settings(s).enable_radarr_auto_search is False


def test_fresh_db_needs_no_data_migration(db):
    from backend.database import engine, init_db, get_settings
    from backend.models import DATA_VERSION
    from sqlmodel import Session
    init_db()
    with Session(engine) as s:
        st = get_settings(s)
        assert st.data_version == DATA_VERSION and st.enable_radarr_auto_search is True
