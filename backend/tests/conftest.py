import os

# Point the app at the TEST database *before* importing it.
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", "postgresql+psycopg://app:app@localhost:5432/eventdb_test")
os.environ["ENABLE_SCHEDULER"] = "false"
os.environ["UPLOAD_DIR"] = "/tmp/eventhub_test_uploads"
os.environ["MAX_UPLOAD_MB"] = "1"
os.environ["BCRYPT_ROUNDS"] = "4"  # fast hashing in tests only

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db.session import Base, engine
import app.models  # noqa
from app.main import app

from tests.helpers import World


@pytest.fixture(scope="session", autouse=True)
def _schema():
    with engine.begin() as c:
        c.execute(text("CREATE EXTENSION IF NOT EXISTS btree_gist"))
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    engine.dispose()


@pytest.fixture(autouse=True)
def _clean():
    yield
    with engine.begin() as c:
        names = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
        c.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))


@pytest.fixture()
def client():
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture()
def w(client) -> World:
    """A populated world: org A (admin, manager, staff, 4 participants), org B (isolated admin)."""
    return World(client)
