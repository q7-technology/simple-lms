import os
from datetime import date

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

# The compose db listens on 127.0.0.1:5435 (Simple WMS has 5433, Simple TMS
# 5434), user lms.
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://lms:lms-dev@127.0.0.1:5435/lms_test"
)
os.environ["LMS_DATABASE_URL"] = TEST_DATABASE_URL

# Every test runs on this day unless it moves the clock itself.
TODAY = date(2026, 10, 12)


def _ensure_database():
    admin_url = TEST_DATABASE_URL.rsplit("/", 1)[0] + "/postgres"
    name = TEST_DATABASE_URL.rsplit("/", 1)[1]
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        exists = conn.execute(
            text("select 1 from pg_database where datname = :n"), {"n": name}
        ).scalar()
        if not exists:
            conn.execute(text(f'create database "{name}"'))
    engine.dispose()


@pytest.fixture(scope="session")
def engine():
    _ensure_database()
    engine = create_engine(TEST_DATABASE_URL)
    with engine.begin() as conn:
        conn.execute(text("drop schema public cascade"))
        conn.execute(text("create schema public"))
    from alembic import command
    from alembic.config import Config

    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    cfg.attributes["configure_logger"] = False
    command.upgrade(cfg, "head")
    yield engine
    engine.dispose()


@pytest.fixture
def db(engine):
    from lms.models import Base

    with Session(engine) as session:
        yield session
        session.rollback()
    tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    if tables:
        with engine.begin() as conn:
            # TRUNCATE is not UPDATE or DELETE, so the append-only trigger lets it by
            conn.execute(text(f"truncate {tables} restart identity cascade"))


@pytest.fixture
def client(engine):
    from fastapi.testclient import TestClient

    from lms.api.app import app

    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def today(monkeypatch):
    """The API's today is TODAY. A test can call today.set(...) to move it."""
    from lms.services import clock

    class Clock:
        value = TODAY

        def set(self, d: date):
            self.value = d

    c = Clock()
    monkeypatch.setattr(clock, "today", lambda: c.value)
    return c
