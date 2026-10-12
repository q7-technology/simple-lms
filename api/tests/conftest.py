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


@pytest.fixture
def beaten_to_it(engine):
    """Another request, at the same moment, commits `row` after this one's
    check and before its insert: arm(row, "key") waits for an object like
    `row` with the same key to be flushed, and commits `row` first."""
    from sqlalchemy import event

    armed = []

    def before_flush(session, context, instances):
        for row, field in list(armed):
            if any(type(o) is type(row) and getattr(o, field) == getattr(row, field)
                   for o in [*session.new, *session.dirty] if o is not row):
                armed.remove((row, field))
                with Session(engine) as other:
                    other.add(row)
                    other.commit()

    event.listen(Session, "before_flush", before_flush)
    yield lambda row, field: armed.append((row, field))
    event.remove(Session, "before_flush", before_flush)


# --- people -----------------------------------------------------------------

PASSWORD = "correct horse battery"
PIN = "2468"


def make_person(db, code: str, name: str, permission: str = "learner", *,
                email: str | None = None, password: str | None = None, pin: str | None = None,
                supervisor=None):
    from lms.models import Person
    from lms.services.access import hash_password

    person = Person(code=code, name=name, permission=permission, email=email,
                    password_hash=hash_password(password) if password else None,
                    pin_hash=hash_password(pin) if pin else None,
                    supervisor_id=supervisor.id if supervisor else None)
    db.add(person)
    db.commit()
    return person


@pytest.fixture
def admin(db):
    return make_person(db, "AD001", "Leighton Lauton", "admin",
                       email="leighton@example.com.au", password=PASSWORD)


@pytest.fixture
def manager(db):
    return make_person(db, "MG001", "Mel Grant", "manager",
                       email="mel@example.com.au", password=PASSWORD)


@pytest.fixture
def supervisor(db):
    return make_person(db, "SV001", "Sam Vu", "supervisor",
                       email="sam@example.com.au", password=PASSWORD, pin=PIN)


@pytest.fixture
def learner(db, supervisor):
    """Kim, on Sam's team, signs in with a code and PIN."""
    return make_person(db, "LL042", "Kim Lee", pin=PIN, supervisor=supervisor)


def login(client, email: str, password: str = PASSWORD) -> dict:
    r = client.post("/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


def pin_login(client, code: str, pin: str = PIN) -> dict:
    r = client.post("/v1/auth/pin-login", json={"code": code, "pin": pin})
    assert r.status_code == 200, r.text
    return r.json()


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin_headers(client, admin):
    return bearer(login(client, admin.email)["token"])


@pytest.fixture
def manager_headers(client, manager):
    return bearer(login(client, manager.email)["token"])


@pytest.fixture
def supervisor_headers(client, supervisor):
    return bearer(login(client, supervisor.email)["token"])


@pytest.fixture
def learner_headers(client, learner):
    return bearer(pin_login(client, learner.code)["token"])


def all_at_once(n: int, call):
    """Run call() n times on n threads released together; return the results."""
    import threading
    from concurrent.futures import ThreadPoolExecutor

    start = threading.Barrier(n)

    def one():
        start.wait()
        return call()

    with ThreadPoolExecutor(max_workers=n) as pool:
        return [f.result() for f in [pool.submit(one) for _ in range(n)]]


def fresh_client():
    """A test client of its own, for one thread."""
    from fastapi.testclient import TestClient

    from lms.api.app import app

    return TestClient(app)
