import os
import sys
import tempfile
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[3] / "gb-6107" / "backend"
sys.path.insert(0, str(BACKEND))

_db_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
DB_PATH = _db_file.name
_db_file.close()
os.unlink(DB_PATH)

for key, default in {
    "DATABASE_URL": f"sqlite:///{DB_PATH}",
    "JWT_SECRET": "shipment-test-secret",
    "DEMO_PASSWORD": "Shipment-Test-2026",
    "SEED_DEMO": "false",
    "REDIS_URL": "redis://127.0.0.1:6399/0",
}.items():
    os.environ.setdefault(key, default)


@pytest.fixture()
def engine():
    from src.config.resources import engine as test_engine
    from src.models.base import metadata
    from migrations import v001_workbench
    import migrations.v001_workbench  # noqa: F401  registers all tables

    metadata.drop_all(test_engine)
    with test_engine.begin() as db:
        v001_workbench.upgrade(db)
    yield test_engine


@pytest.fixture()
def db(engine):
    connection = engine.connect().execution_options(isolation_level="AUTOCOMMIT")
    yield connection
    connection.close()
