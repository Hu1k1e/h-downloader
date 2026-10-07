"""Test setup: point the app at a throwaway data dir BEFORE any backend module is imported."""
import os
import sys
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="hdl-tests-")
os.environ["DATA_DIR"] = _TMP
for var in ("API_AUTH_TOKEN", "WEBHOOK_TOKEN", "CORS_ORIGINS"):
    os.environ.pop(var, None)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402


@pytest.fixture()
def db():
    """Fresh schema for every test."""
    from sqlmodel import SQLModel
    from backend.database import engine, init_db
    SQLModel.metadata.drop_all(engine)
    init_db()
    return engine
