# Simple LMS step 1: Skeleton — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build step 1 of `docs/plans/2026-10-12-simple-lms-design.md`: the repo, Docker, people who sign in with a code and PIN or an email and password, roles and the competencies each requires, extras and waivers, completions recorded by hand from the desktop, the matrix (with a CSV export), and a learner app that shows each person's training. Usable end to end: an admin sets up competencies, roles and people on the desktop, records a completion, sees the matrix go green, and the learner sees it in **My training** at `/learn/`.

**Architecture:** One FastAPI app (`api/`, package `lms`) over PostgreSQL 16, laid out like Simple TMS's `api/tms`: `config.py` (pydantic-settings, `LMS_` prefix), `db.py`, `models/`, `services/`, `api/` (deps with `require(scope)`, errors, routes), `cli.py`, Alembic migrations run on every API start. A person's status for a competency is never stored: `lms/services/status.py` works it out from their roles, their latest extra or waiver, their latest record and today's date, and `lms/services/standing.py` loads what it needs for a whole matrix in four queries. `competency_record` and `person_override` are append-only, enforced by a Postgres trigger. Two Vite + React + TypeScript + Tailwind apps, `apps/desktop` (served at `/`) and `apps/learner` (a PWA at `/learn/`), are ordinary API clients with a session token. Docker Compose runs `db`, `api` and `caddy`; the worker arrives with step 2.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, psycopg 3, pytest against a real PostgreSQL 16; Vite 6, React 19, TypeScript 5, Tailwind 4, Vitest 3 with Testing Library; Docker Compose, Caddy 2, GitHub Actions.

---

## Context

The design is settled; this plan does not change any of its decisions. Patterns come from Simple TMS (`/Users/leightonlauton/Q7 Technology/Software/q7/simple-tms/`, paths relative to it), from the code as shipped rather than its step 1 plan where the two differ.

### Patterns copied from Simple TMS

- **Settings, engine, naming convention:** `api/tms/config.py`, `api/tms/db.py`, `api/tms/models/base.py` (`ix_`, `uq_`, `ck_`, `fk_`, `pk_` names; `created_at_column()`). No `Dec` types: nothing in the LMS is a quantity.
- **Password and PIN hashing:** `api/tms/services/access.py` as shipped: PBKDF2-SHA256, 600 000 iterations, a `DUMMY_HASH` checked for unknown people so an unknown email or code takes as long as a wrong one, and a damaged hash is a wrong password, never a 500.
- **Sign-in:** `api/tms/api/routes/auth.py` as shipped: the person's row is locked `with_for_update()` while an attempt is counted, so guesses sent all at once still lock after five; an unknown code and a wrong PIN answer alike, with no tries-left count.
- **`Principal`, `get_principal`, `require(scope)`:** `api/tms/api/deps.py`; `has_scope` takes `*` and `area:*`.
- **Errors:** `api/tms/api/errors.py` (`FieldError` → 422 list, `NotFound`, `Conflict` → 409 with a code, `Unauthorised`, `Forbidden`). `Forbidden` here carries a code too (`own_record`, `admin_only`).
- **Append-only trigger:** `block_change()` in `api/alembic/versions/0001_skeleton.py`, and `api/tests/test_history.py`.
- **Tests on a real Postgres:** `api/tests/conftest.py` makes and resets its own `*_test` database, truncates every table after each test (TRUNCATE gets past the trigger), and `api/tests/test_migrations.py` runs up, down, up and checks the models against a fresh database. `all_at_once` and `fresh_client` for the lock-out race.
- **Migrations on start:** `docker-compose.yml`'s `api` runs `alembic upgrade head` before `uvicorn`.
- **Caddy:** `deploy/Caddyfile` as shipped: host ports as settings, its own https redirect naming the port, security headers, a CSP for the apps, the app's page asked for afresh (`Cache-Control: no-cache`) and `/sw.js` checked on every launch, and a PWA under a sub-path with `handle_path` and `try_files {path} /index.html`.
- **CI:** `.github/workflows/ci.yml`: API tests against a Postgres service, each app tested and built, and a Compose start that checks the triggers are there.
- **Apps:** `apps/desktop` (package.json, vite.config.ts with a `/v1` proxy, tsconfig.json, Manrope from `@fontsource`, Vitest in jsdom) and `apps/driver` (base path, manifest, `public/sw.js` that keeps the app shell and fetches the page fresh, `scripts/make_icons.py` drawing PNG icons with the standard library).

### Ports on one machine

Simple WMS has `127.0.0.1:5433` (database) and `127.0.0.1:8011` (API) in its local `.env`; Simple TMS has `5434` and `8022` (not 8021: macOS's ftp-proxy holds it), and its Caddy is on 8180 and 8543 locally. Simple LMS takes **5435** for the database and **8033** for the API (both checked free), keeps Caddy's host ports as settings (`LMS_HTTP_PORT`, `LMS_HTTPS_PORT`, 80 and 443 by default; **8280** and **8643** for local work), and runs Vite on **5176** (desktop) and **5177** (learner, preview 4177), beside Simple WMS's 5173 and Simple TMS's 5174 and 5175.

### Decisions this plan makes that the design leaves open

- **No worker in Compose for step 1.** Nothing queues yet: the outbox, the daily job and email come with step 2. A loop with nothing to drain is just another thing to watch. Compose has a comment where it goes.
- **One opaque session token per device, no refresh token.** The design names one `session` table and asks for idle expiry and sign-out, which a stored row gives directly. The token (`lms_s.` + 32 random bytes) is kept only as its SHA-256; there is no signing key, so no `LMS_SECRET_KEY`. A **PIN session** ends after **15 minutes idle** (as the design says) or 12 hours in all; a **password session** after **12 hours idle** or 14 days in all. `last_seen_at` is written at most once a minute. A new PIN ends that person's PIN sessions, a new password their password sessions, deactivation all of them.
- **A PIN session carries `training:read` only**, whatever the person's permission. That is how "code and PIN: learner app only" is enforced at the API (rule 4): a PIN cannot reach anything the desktop does. Step 4 will add the sign-off scope to supervisors' PIN sessions.
- **Scopes** (from the design's permissions table): learner `training:read`; supervisor adds `matrix:read`, `roles:read`, `competencies:read`; manager adds `people:read`, `people:write`, `roles:write`, `competencies:write`, `records:write`; admin `*`. A supervisor sees their team (people whose supervisor they are) in the matrix, the training lists and the history; managers and admins see everyone.
- **Managers look after learners and supervisors; only an admin adds or changes a manager or an admin** (permission, password, PIN, roles, deactivation). Otherwise a manager could make themselves an admin.
- **A supervisor must have the supervisor, manager or admin permission**, so they can see their team.
- **Password lock:** five wrong passwords lock the password for 15 minutes, as in Simple TMS. The design only speaks of the PIN; a password needs the same guard.
- **Codes** are stored upper case (`ll042` signs in as `LL042`, checked by the database), **emails** lower case, **role and competency keys** lower case (`[a-z0-9-]`). Keys are the ids in URLs.
- **The latest row counts** for both records and overrides (by id, i.e. the order they were recorded). A wrong date is put right by recording the completion again with the right date; a wrong grant by a revoke with a note. Rule 1 holds: nothing is changed in place.
- **Overrides have three kinds:** `extra`, `waive` and `clear`. The design's extras and waivers need a way back to "what the roles say" without deleting a row; `clear` is that way. A note is required for each.
- **`expires_on` is the last good day.** Status: `lapsed` the day after it; `expiring` from 30 days before it up to and including it. Without one, `granted_on` plus the competency's `refresher_months` (calendar months, 31 January + 1 = end of February); without either, it never runs out. The refresher is read from the competency each time, so changing it moves everyone at once (rule 2).
- **Waived only shows where something is asked for.** A waiver of a competency no role or extra asks for leaves the cell `not_required`.
- **Today** is the date in `LMS_TIMEZONE` (default `Australia/Melbourne`); `tzdata` is a dependency so a slim image knows the zone. `lms/services/clock.py` is the one place the API asks, so tests can move the clock.
- **The matrix** shows every active person by name (someone with no roles yet shows too, all grey, a nudge to give them one); its columns are what any of them is asked for. A cell is `{status, granted_on, expires_on}`. Filters: `role`, `supervisor`, `status` (people with at least one cell in it). The CSV has a status and an expiry column per competency and escapes cells that look like formulas.
- **Recording rules:** `granted_on` can't be in the future, `expires_on` must be after it, a deactivated person (409) or competency (422) can't be granted, and nobody records their own (403 `own_record`), admins included. Revoking needs a grant that counts now.
- **`GET /v1/people/{code}/records`** is the history route. The design reserves `GET /v1/people/{code}/competencies[/{key}]` for the step 6 competency API, so this plan stays off that path.
- **`GET /v1/people/{code}/training`** returns the flat list; the learner app groups it into Overdue (lapsed, oldest first, then missing), Due soon (soonest first) and Done. Someone you can't see is a 404, not a 403.
- **No settings switches for sign-in methods yet.** Both methods are on; the switches come with the Settings screen (with Entra, step 5). `person.entra_oid` is there now, unique, unused.
- **No roles deactivate or delete.** A role nobody holds asks nothing of anyone; YAGNI until someone needs it.
- **The desktop refuses a learner** who signs in there ("Your training is in the learner app at /learn/") and signs them out again. It opens on the matrix (Game Mode is step 7), with plain tables and a drawer for a cell's history and for editing.
- **The learner app forgets an idle person on the device as well**, after the session's own idle time, so a shared tablet stops showing the last person's training even if nobody taps it. My training is never kept by the service worker; only the app shell is.
- **Colours:** the siblings' bones with training blue (`#2F6FB8`) for the LMS, and the shared green, amber, red and grey for status. The mark is an open book with a tick.

---

## Before you start

```
cd "/Users/leightonlauton/Q7 Technology/Software/q7/simple-lms"
git switch -c step-1-skeleton
```

You need `uv`, Node 22 and Docker. All `pytest` commands run from `api/` and need the compose `db` (Task 1 starts it on 127.0.0.1:5435). If the LMS database listens somewhere else, set `TEST_DATABASE_URL`. `npm` commands run from the app's folder.

---

### Task 1: Repo skeleton, CLAUDE.md and a health check

**Files:**
- Create: `.gitignore`, `LICENSE`, `CLAUDE.md`
- Create: `docker-compose.yml` (db only for now), `.env.example` (database part for now)
- Create: `api/.python-version`, `api/.dockerignore`, `api/pyproject.toml`
- Create: `api/alembic.ini`, `api/alembic/env.py`, `api/alembic/script.py.mako`, `api/alembic/versions/` (empty directory)
- Create: `api/lms/__init__.py`, `api/lms/config.py`, `api/lms/db.py`
- Create: `api/lms/models/__init__.py`, `api/lms/models/base.py`
- Create: `api/lms/services/__init__.py`, `api/lms/services/clock.py`
- Create: `api/lms/api/__init__.py`, `api/lms/api/errors.py`, `api/lms/api/deps.py`, `api/lms/api/app.py`, `api/lms/api/routes/__init__.py`
- Test: `api/tests/conftest.py`, `api/tests/test_health.py`, `api/tests/test_config.py`

**Step 1: Project files and the database**

`.gitignore`:
```
.env
__pycache__/
.venv/
*.pyc
.DS_Store
.pytest_cache/
*.egg-info/
node_modules/
dist/
*.tsbuildinfo
```

`LICENSE`: the same MIT licence as Simple TMS:
```
cp "/Users/leightonlauton/Q7 Technology/Software/q7/simple-tms/LICENSE" LICENSE
```

`CLAUDE.md`:
````markdown
# Simple LMS — instructions for Claude Code

Read `docs/plans/2026-10-12-simple-lms-design.md` before touching anything. It
is the design, and the decisions in it are settled unless a human changes them
there first.

## What this is
An open source, self-hosted learning management system by Q7 Technology, for
workplace training: inductions, online modules, practical sign-offs, outside
tickets and licences, and signed policies. It answers one question for a
business and its auditors: is each person current for everything their job
needs? Desktop web app (managers, supervisors, admins), learner PWA (phone or
shared tablet), one Python API, one PostgreSQL database. It sits beside
Simple WMS, Simple TMS and Platen and works without any of them. Other
systems only ever talk to the API.

## Four rules that never bend
1. **The training record is append-only.** Never UPDATE or DELETE a
   `competency_record`, `quiz_attempt` or `signoff` row (nor a
   `person_override`). A mistake is corrected by a new row (`revoked`, with a
   note). People are deactivated, never deleted.
2. **Status is worked out, never stored by hand.** It comes from the records
   and the date, so it cannot drift. `competency.expiring` and
   `competency.lapsed` fire from the daily job, each once, each with an event
   id.
3. **Nobody grants their own competency.** A practical is signed off by a
   supervisor who is not the learner; a ticket is verified by a manager who is
   not the learner. A module pass is the only thing a learner earns alone.
4. **The API is the only door.** The desktop and the learner app are ordinary
   API clients with a session token, whichever way the person signed in. If
   the UI can do it, a partner can too.

## Stack (decided)
- API: Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic.
- Database: PostgreSQL 16.
- Queue: a Postgres table drained by a Python worker with backoff (1 min, 5,
  30, 2 h), for webhooks, email and print jobs, and the daily job. No Redis
  or RabbitMQ. (The worker arrives with build step 2.)
- Front ends: Vite + React + TypeScript + Tailwind. One repo, two entry
  points: `apps/desktop` and `apps/learner`. The learner app is a PWA at
  `/learn/` whose service worker caches the app shell, as the Simple TMS
  driver app's does.
- Hosting: Ubuntu + Docker Compose: `api`, `worker`, `db`, `caddy`, static
  builds for both apps. Secrets in `.env` on the host.

## Repo layout
```
CLAUDE.md            this file
docs/plans/          the design and the implementation plans
docs/api.md          every endpoint: keep it in step with the routes
.github/workflows/   CI: the tests, both apps' builds, and a Compose start
api/                 FastAPI app (package lms), migrations, tests
apps/desktop/        the desktop app for managers, supervisors and admins
apps/learner/        the learner app, a PWA served at /learn/
deploy/Caddyfile     the only door in
docker-compose.yml   api, db, caddy (the worker comes with step 2)
```
`npm` commands run from the app's folder (`apps/desktop/` or `apps/learner/`):
`npm test`, `npm run typecheck`, `npm run build` (Caddy serves each app's
`dist`).

## Conventions
- Status: `current`, `expiring` (within 30 days), `lapsed`, `missing`,
  `waived`, `not_required`, worked out by `lms/services/status.py` and
  nowhere else. The latest record for a person and competency is the one
  that counts.
- Sister apps: nothing in Simple WMS or Simple TMS changes for Simple LMS. It
  publishes signed events and a competency API (build step 6).
- Printing: Simple LMS never renders a document. Certificates and skills
  cards go to Platen (or any print service) as `template` + JSON `data`
  through the queue.
- Build order is in the design under "Build order". Finish a step so it is
  usable before starting the next.
- Tests: pytest for the API against a real PostgreSQL, Vitest for the apps.
- Australian English in copy. No "utilise", no "leverage".
- Git: no `Co-Authored-By` lines, no tooling or generated-by trailers, no
  session links. A commit message is the subject line and, if needed, a
  short body about the change. Nothing else.
````

`docker-compose.yml` (Task 13 adds `api` and `caddy`):
```yaml
services:
  db:
    image: postgres:16
    restart: unless-stopped
    environment:
      POSTGRES_DB: ${POSTGRES_DB:-lms}
      POSTGRES_USER: ${POSTGRES_USER:-lms}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?set POSTGRES_PASSWORD in .env}
    volumes:
      - pgdata:/var/lib/postgresql/data
    # 5435 so it sits beside Simple WMS's (5433) and Simple TMS's (5434) on one machine
    ports:
      - "127.0.0.1:${POSTGRES_PORT:-5435}:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-lms} -d ${POSTGRES_DB:-lms}"]
      interval: 5s
      timeout: 3s
      retries: 20


volumes:
  pgdata:
```

`.env.example` (Task 13 replaces it with the full file):
```
# Copy to .env and fill in. Nothing here is committed.

# Postgres (used by the db and api containers)
POSTGRES_DB=lms
POSTGRES_USER=lms
POSTGRES_PASSWORD=change-me
# Host port the database is published on (127.0.0.1 only). 5435 sits beside
# Simple WMS's 5433 and Simple TMS's 5434. The tests expect
# POSTGRES_PASSWORD=lms-dev on this port unless TEST_DATABASE_URL says otherwise.
POSTGRES_PORT=5435
```

`api/.python-version`:
```
3.12
```

`api/.dockerignore`:
```
.venv
__pycache__
*.pyc
tests
.pytest_cache
```

`api/pyproject.toml`:
```toml
[project]
name = "simple-lms-api"
version = "0.1.0"
description = "Simple LMS API"
requires-python = ">=3.12"
dependencies = [
  "fastapi>=0.115",
  "uvicorn[standard]>=0.30",
  "pydantic>=2.8",
  "pydantic-settings>=2.4",
  "sqlalchemy>=2.0.30",
  "psycopg[binary]>=3.2",
  "alembic>=1.13",
  # the time zone's rules, so "today" is right in a slim image too
  "tzdata>=2024.1",
]

[project.optional-dependencies]
# httpx2: what newer Starlette test clients want, as in Simple WMS and Simple TMS
dev = ["pytest>=8", "pytest-timeout>=2.3", "httpx2>=0.1"]

[project.scripts]
lms = "lms.cli:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["lms"]

[tool.pytest.ini_options]
testpaths = ["tests"]
timeout = 60
filterwarnings = [
  "error",
  # third-party: Starlette's test client still uses an old anyio alias
  "ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning",
]
```

`api/alembic.ini`:
```ini
[alembic]
script_location = alembic
prepend_sys_path = .
path_separator = os
file_template = %%(rev)s_%%(slug)s
# Overridden by LMS_DATABASE_URL in env.py
sqlalchemy.url = postgresql+psycopg://lms:lms@127.0.0.1:5432/lms

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARNING
handlers = console
qualname =

[logger_sqlalchemy]
level = WARNING
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
```

`api/alembic/env.py` (Simple TMS's, with `lms`; the `configure_logger` switch lets tests run migrations without silencing the app's loggers):
```python
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from lms.models import Base

config = context.config
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name)

if os.environ.get("LMS_DATABASE_URL"):
    config.set_main_option("sqlalchemy.url", os.environ["LMS_DATABASE_URL"])

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    try:
        with connectable.connect() as connection:
            context.configure(connection=connection, target_metadata=target_metadata)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

`api/alembic/script.py.mako`: copy Simple TMS's unchanged:
```
mkdir -p api/alembic/versions
cp "/Users/leightonlauton/Q7 Technology/Software/q7/simple-tms/api/alembic/script.py.mako" api/alembic/script.py.mako
```

Start the database and make the package so the venv can install it:
```
mkdir -p api/lms && touch api/lms/__init__.py
cp .env.example .env
sed -i '' 's/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=lms-dev/' .env
docker compose up -d db
cd api && uv venv -p 3.12 && uv pip install -e ".[dev]"
```

**Step 2: Write the failing tests**

`api/tests/conftest.py` (Task 3 adds people to it):
```python
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
```

`api/tests/test_health.py`:
```python
def test_health_answers_ok_once_the_database_is_there(client):
    r = client.get("/v1/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
```

`api/tests/test_config.py`:
```python
import pytest
from pydantic import ValidationError

from lms.config import Settings


def test_today_is_melbournes_unless_told_otherwise():
    assert Settings().timezone == "Australia/Melbourne"


def test_an_unknown_time_zone_refuses_to_start():
    with pytest.raises(ValidationError, match="not a time zone"):
        Settings(timezone="Australia/Ballarat")


def test_another_real_time_zone_is_fine():
    assert Settings(timezone="Australia/Perth").timezone == "Australia/Perth"
```

**Step 3: Run them to see them fail**

Run: `cd api && .venv/bin/pytest tests/test_health.py tests/test_config.py -v`
Expected: ERROR, `ModuleNotFoundError: No module named 'lms.config'` (collecting `test_config.py`) and `No module named 'lms.services'` (the autouse `today` fixture).

**Step 4: Minimal implementation**

`api/lms/services/__init__.py`, `api/lms/api/__init__.py`, `api/lms/api/routes/__init__.py`: empty files.

`api/lms/config.py`:
```python
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LMS_", extra="ignore")

    database_url: str = "postgresql+psycopg://lms:lms@127.0.0.1:5432/lms"
    # Whose "today" decides what is current, expiring or lapsed.
    timezone: str = "Australia/Melbourne"

    @field_validator("timezone")
    @classmethod
    def _known_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(f"LMS_TIMEZONE {value!r} is not a time zone, e.g. Australia/Melbourne")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

`api/lms/db.py`:
```python
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from lms.config import get_settings


@lru_cache
def get_engine():
    return create_engine(get_settings().database_url, pool_pre_ping=True)


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)
```

`api/lms/services/clock.py`:
```python
"""Today, where the business is. One place, so tests can move the clock."""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from lms.config import get_settings


def today() -> date:
    return datetime.now(ZoneInfo(get_settings().timezone)).date()
```

`api/lms/models/base.py`:
```python
from datetime import datetime

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.orm import DeclarativeBase, mapped_column

naming = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=naming)


def created_at_column():
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
```

`api/lms/models/__init__.py` (Task 2 replaces it):
```python
from lms.models.base import Base

__all__ = ["Base"]
```

`api/lms/api/errors.py`:
```python
"""Every validation problem is a 422 with a list of field errors."""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class FieldError(Exception):
    """A domain validation problem on one field, e.g. a code already taken."""

    def __init__(self, field: str, message: str):
        self.field = field
        self.message = message
        super().__init__(f"{field}: {message}")


class NotFound(Exception):
    def __init__(self, message: str = "not found"):
        self.message = message
        super().__init__(message)


class Conflict(Exception):
    """Well formed, but not possible as things stand: nothing to revoke, say.
    `code` is for programs, `message` for people."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


class Unauthorised(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class Forbidden(Exception):
    """Signed in, but not allowed. `code` says why when a program may care."""

    def __init__(self, message: str, code: str = "forbidden"):
        self.message = message
        self.code = code
        super().__init__(message)


def field_errors(errors: list[dict]) -> list[dict]:
    out = []
    for e in errors:
        loc = [str(x) for x in e.get("loc", []) if x not in ("body",)]
        out.append({"field": ".".join(loc) or "body", "message": e.get("msg", "invalid")})
    return out


def install(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):
        return JSONResponse(status_code=422, content={"errors": field_errors(exc.errors())})

    @app.exception_handler(FieldError)
    async def _field(request: Request, exc: FieldError):
        return JSONResponse(
            status_code=422, content={"errors": [{"field": exc.field, "message": exc.message}]}
        )

    @app.exception_handler(NotFound)
    async def _not_found(request: Request, exc: NotFound):
        return JSONResponse(status_code=404, content={"detail": exc.message})

    @app.exception_handler(Conflict)
    async def _conflict(request: Request, exc: Conflict):
        return JSONResponse(status_code=409, content={"detail": exc.message, "code": exc.code})

    @app.exception_handler(Unauthorised)
    async def _unauthorised(request: Request, exc: Unauthorised):
        return JSONResponse(status_code=401, content={"detail": exc.message},
                            headers={"WWW-Authenticate": "Bearer"})

    @app.exception_handler(Forbidden)
    async def _forbidden(request: Request, exc: Forbidden):
        return JSONResponse(status_code=403, content={"detail": exc.message, "code": exc.code})
```

`api/lms/api/deps.py` (Task 4 adds the principal):
```python
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session as Db

from lms.db import get_sessionmaker


def get_db():
    with get_sessionmaker()() as session:
        yield session


DB = Annotated[Db, Depends(get_db)]
```

`api/lms/api/app.py` (each later task adds its router):
```python
import logging

from fastapi import APIRouter, FastAPI
from sqlalchemy import text

from lms.api import errors
from lms.api.deps import DB

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

app = FastAPI(
    title="Simple LMS",
    version="0.1.0",
    description="Open source, self-hosted workplace training. The API is the only door.",
    docs_url="/docs",
    redoc_url=None,
)
errors.install(app)

v1 = APIRouter(prefix="/v1")


@v1.get("/health", tags=["system"])
def health(db: DB):
    db.execute(text("select 1"))
    return {"status": "ok"}


app.include_router(v1)
```

**Step 5: Run them to see them pass**

Run: `cd api && .venv/bin/pytest tests/test_health.py tests/test_config.py -v`
Expected: `4 passed`.

**Step 6: Commit**

```
git add .gitignore LICENSE CLAUDE.md docker-compose.yml .env.example api/.python-version \
  api/.dockerignore api/pyproject.toml api/alembic.ini api/alembic/env.py \
  api/alembic/script.py.mako api/lms/__init__.py api/lms/config.py api/lms/db.py \
  api/lms/models/__init__.py api/lms/models/base.py api/lms/services/__init__.py \
  api/lms/services/clock.py api/lms/api/__init__.py api/lms/api/errors.py api/lms/api/deps.py \
  api/lms/api/app.py api/lms/api/routes/__init__.py api/tests/conftest.py \
  api/tests/test_health.py api/tests/test_config.py
git commit -m "Start the API: settings, database, health check and tests" \
  -m "Laid out like Simple TMS. The tests make and reset an lms_test database on the compose db, on 5435 beside Simple WMS's and Simple TMS's."
```

---

### Task 2: Models, the first migration and the append-only record

**Files:**
- Create: `api/lms/models/people.py`, `api/lms/models/catalogue.py`, `api/lms/models/records.py`
- Modify: `api/lms/models/__init__.py` (replace)
- Create: `api/alembic/versions/0001_skeleton.py`
- Test: `api/tests/test_migrations.py`, `api/tests/test_append_only.py`

**Step 1: Write the failing tests**

`api/tests/test_migrations.py`:
```python
"""A fresh install must work, and so must going back. Runs the migrations
up, down and up again on a database of its own, and checks the models agree."""
import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from conftest import TEST_DATABASE_URL

MIGRATION_URL = TEST_DATABASE_URL.rsplit("/", 1)[0] + "/lms_migration_check"
TABLES = {"person", "session", "role", "person_role", "competency", "role_requirement",
          "person_override", "competency_record", "alembic_version"}


@pytest.fixture
def blank_database(monkeypatch):
    admin = TEST_DATABASE_URL.rsplit("/", 1)[0] + "/postgres"
    name = MIGRATION_URL.rsplit("/", 1)[1]
    engine = create_engine(admin, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        conn.execute(text(f'drop database if exists "{name}" with (force)'))
        conn.execute(text(f'create database "{name}"'))
    engine.dispose()
    # alembic/env.py prefers this over the ini, so point it at the blank one
    monkeypatch.setenv("LMS_DATABASE_URL", MIGRATION_URL)
    yield MIGRATION_URL
    engine = create_engine(admin, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        conn.execute(text(f'drop database if exists "{name}" with (force)'))
    engine.dispose()


def alembic_config(url: str) -> Config:
    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url)
    cfg.attributes["configure_logger"] = False
    return cfg


def _tables(engine) -> set[str]:
    with engine.connect() as conn:
        return set(conn.execute(text(
            "select table_name from information_schema.tables where table_schema='public'"
        )).scalars())


def test_migrations_go_up_down_and_up_again(blank_database):
    cfg = alembic_config(blank_database)
    engine = create_engine(blank_database)

    command.upgrade(cfg, "head")
    assert _tables(engine) == TABLES
    with engine.connect() as conn:
        triggers = set(conn.execute(text(
            "select tgname from pg_trigger where not tgisinternal")).scalars())
    assert triggers == {"competency_record_append_only", "person_override_append_only"}

    command.downgrade(cfg, "base")
    assert _tables(engine) == {"alembic_version"}

    command.upgrade(cfg, "head")
    assert _tables(engine) == TABLES
    engine.dispose()


def test_the_models_match_the_migrations(blank_database):
    """No drift: what the models say is what a fresh database gets."""
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    from lms.models import Base

    command.upgrade(alembic_config(blank_database), "head")
    engine = create_engine(blank_database)
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    engine.dispose()
    assert diff == [], f"the models and the migrations disagree: {diff}"
```

`api/tests/test_append_only.py`:
```python
"""The training record and the overrides are append-only, and the database
says so (rule 1)."""
from datetime import date

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.exc import DBAPIError, IntegrityError

from lms.models import Competency, CompetencyRecord, Person, PersonOverride


@pytest.fixture
def setting(db):
    boss = Person(code="MG001", name="Mel Grant", permission="manager")
    kim = Person(code="LL042", name="Kim Lee")
    forklift = Competency(key="forklift-licence", name="Forklift licence", kind="ticket")
    db.add_all([boss, kim, forklift])
    db.flush()
    db.add(CompetencyRecord(person_id=kim.id, competency_id=forklift.id, kind="granted",
                            granted_on=date(2026, 3, 1), expires_on=date(2031, 3, 1),
                            recorded_by_id=boss.id))
    db.add(PersonOverride(person_id=kim.id, competency_id=forklift.id, kind="extra",
                          note="drives the yard forklift on Saturdays", recorded_by_id=boss.id))
    db.commit()
    return boss, kim, forklift


@pytest.mark.parametrize("model", [CompetencyRecord, PersonOverride])
def test_rows_cannot_be_updated(db, setting, model):
    with pytest.raises(DBAPIError, match="append-only"):
        db.execute(update(model).values(note="changed afterwards"))
        db.commit()


@pytest.mark.parametrize("model", [CompetencyRecord, PersonOverride])
def test_rows_cannot_be_deleted(db, setting, model):
    with pytest.raises(DBAPIError, match="append-only"):
        db.execute(delete(model))
        db.commit()


def test_a_correction_is_a_new_row(db, setting):
    boss, kim, forklift = setting
    db.add(CompetencyRecord(person_id=kim.id, competency_id=forklift.id, kind="revoked",
                            note="card was for a different licence class",
                            recorded_by_id=boss.id))
    db.commit()
    kinds = db.execute(select(CompetencyRecord.kind).order_by(CompetencyRecord.id)).scalars()
    assert list(kinds) == ["granted", "revoked"]


def test_a_revoke_needs_a_note_and_a_grant_needs_a_date(db, setting):
    boss, kim, forklift = setting
    db.add(CompetencyRecord(person_id=kim.id, competency_id=forklift.id, kind="revoked",
                            note="  ", recorded_by_id=boss.id))
    with pytest.raises(IntegrityError, match="ck_competency_record_revoke_note"):
        db.commit()
    db.rollback()
    db.add(CompetencyRecord(person_id=kim.id, competency_id=forklift.id, kind="granted",
                            recorded_by_id=boss.id))
    with pytest.raises(IntegrityError, match="ck_competency_record_granted_on"):
        db.commit()
```

**Step 2: Run them to see them fail**

Run: `cd api && .venv/bin/pytest tests/test_migrations.py tests/test_append_only.py -v`
Expected: `test_append_only.py` errors with `ImportError: cannot import name 'Competency' from 'lms.models'`; `test_migrations_go_up_down_and_up_again` fails on `assert _tables(engine) == TABLES` (only `alembic_version` exists).

**Step 3: Minimal implementation**

`api/lms/models/people.py`:
```python
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from lms.models.base import Base, created_at_column

PERMISSIONS = ("learner", "supervisor", "manager", "admin")


class Person(Base):
    """Everyone: learners, supervisors, managers and admins. One record serves
    every way of signing in. Deactivated, never deleted."""

    __tablename__ = "person"
    __table_args__ = (
        CheckConstraint("code = upper(code)", name="code_upper"),
        CheckConstraint("email = lower(email)", name="email_lower"),
        CheckConstraint("permission in ('learner', 'supervisor', 'manager', 'admin')",
                        name="permission"),
        CheckConstraint("supervisor_id <> id", name="not_own_supervisor"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # e.g. LL042: kept upper case, matched however it is typed
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str | None] = mapped_column(String(254), unique=True)
    # Microsoft Entra object id, matched on first sign-in (build step 5)
    entra_oid: Mapped[str | None] = mapped_column(String(64), unique=True)
    # learner, supervisor, manager, admin: what they may do, not what they need
    permission: Mapped[str] = mapped_column(String(16), default="learner")
    supervisor_id: Mapped[int | None] = mapped_column(ForeignKey("person.id"), index=True)

    pin_hash: Mapped[str | None] = mapped_column(String(200))
    pin_failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    # five wrong PINs: locked until a manager sets a new one
    pin_locked: Mapped[bool] = mapped_column(Boolean, default=False)
    password_hash: Mapped[str | None] = mapped_column(String(200))
    password_failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    password_locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = created_at_column()
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    supervisor: Mapped[Person | None] = relationship(remote_side=[id])
    roles: Mapped[list[Role]] = relationship(secondary="person_role", order_by="Role.name")


class Session(Base):
    """One signed-in device. Only the token's hash is kept. A PIN session ends
    after 15 minutes idle, a password one after 12 hours."""

    __tablename__ = "session"
    __table_args__ = (CheckConstraint("method in ('password', 'pin')", name="method"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("person.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    method: Mapped[str] = mapped_column(String(8))
    created_at: Mapped[datetime] = created_at_column()
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
```

`api/lms/models/catalogue.py`:
```python
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from lms.models.base import Base, created_at_column

KINDS = ("module", "practical", "ticket", "policy")


class Role(Base):
    """A job, e.g. forklift-operator, and the competencies it requires."""

    __tablename__ = "role"
    __table_args__ = (CheckConstraint("key = lower(key)", name="key_lower"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = created_at_column()

    competencies: Mapped[list[Competency]] = relationship(
        secondary="role_requirement", order_by="Competency.name")


class PersonRole(Base):
    __tablename__ = "person_role"

    person_id: Mapped[int] = mapped_column(ForeignKey("person.id"), primary_key=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("role.id"), primary_key=True, index=True)
    created_at: Mapped[datetime] = created_at_column()


class Competency(Base):
    """Anything a person can be current for. Deactivated, never deleted: its
    records stay."""

    __tablename__ = "competency"
    __table_args__ = (
        CheckConstraint("key = lower(key)", name="key_lower"),
        CheckConstraint("kind in ('module', 'practical', 'ticket', 'policy')", name="kind"),
        CheckConstraint("refresher_months between 1 and 240", name="refresher_months"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    # module, practical, ticket, policy: how it is earned (by hand in step 1)
    kind: Mapped[str] = mapped_column(String(16))
    # a refresher after this many months; none means it never runs out unless
    # the record itself says when (a ticket's card)
    refresher_months: Mapped[int | None] = mapped_column(Integer)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = created_at_column()


class RoleRequirement(Base):
    __tablename__ = "role_requirement"

    role_id: Mapped[int] = mapped_column(ForeignKey("role.id"), primary_key=True)
    competency_id: Mapped[int] = mapped_column(ForeignKey("competency.id"), primary_key=True,
                                               index=True)
    created_at: Mapped[datetime] = created_at_column()
```

`api/lms/models/records.py`:
```python
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from lms.models.base import Base, created_at_column
from lms.models.catalogue import Competency
from lms.models.people import Person


class PersonOverride(Base):
    """An extra (required for this person alone), a waiver (not required, for
    a reason) or a clear (back to what their roles say). Append-only: the
    latest row for a person and competency is the one that counts."""

    __tablename__ = "person_override"
    __table_args__ = (
        CheckConstraint("kind in ('extra', 'waive', 'clear')", name="kind"),
        CheckConstraint("length(trim(note)) > 0", name="note"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("person.id"), index=True)
    competency_id: Mapped[int] = mapped_column(ForeignKey("competency.id"), index=True)
    kind: Mapped[str] = mapped_column(String(8))
    note: Mapped[str] = mapped_column(String(500))
    recorded_by_id: Mapped[int] = mapped_column(ForeignKey("person.id"))
    created_at: Mapped[datetime] = created_at_column()

    competency: Mapped[Competency] = relationship()
    recorded_by: Mapped[Person] = relationship(foreign_keys=[recorded_by_id])


class CompetencyRecord(Base):
    """The training record. Append-only: a trigger refuses UPDATE and DELETE.
    The latest row for a person and competency is the one that counts; a
    mistake is put right by a new row, a grant with the right dates or a
    revoke with a note."""

    __tablename__ = "competency_record"
    __table_args__ = (
        CheckConstraint("kind in ('granted', 'revoked')", name="kind"),
        CheckConstraint("kind = 'revoked' or granted_on is not null", name="granted_on"),
        CheckConstraint("kind = 'granted' or length(trim(note)) > 0", name="revoke_note"),
        CheckConstraint("expires_on > granted_on", name="expires_after_granted"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("person.id"), index=True)
    competency_id: Mapped[int] = mapped_column(ForeignKey("competency.id"), index=True)
    kind: Mapped[str] = mapped_column(String(8))
    granted_on: Mapped[date | None] = mapped_column(Date)
    # the last day it is good for, when the record says (a ticket's card);
    # otherwise worked out from the competency's refresher
    expires_on: Mapped[date | None] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(String(500))
    recorded_by_id: Mapped[int] = mapped_column(ForeignKey("person.id"))
    created_at: Mapped[datetime] = created_at_column()

    competency: Mapped[Competency] = relationship()
    recorded_by: Mapped[Person] = relationship(foreign_keys=[recorded_by_id])
```

`api/lms/models/__init__.py` (replace):
```python
from lms.models.base import Base
from lms.models.people import PERMISSIONS, Person, Session
from lms.models.catalogue import KINDS, Competency, PersonRole, Role, RoleRequirement
from lms.models.records import CompetencyRecord, PersonOverride

__all__ = [
    "Base", "PERMISSIONS", "KINDS", "Person", "Session", "Role", "PersonRole", "Competency",
    "RoleRequirement", "PersonOverride", "CompetencyRecord",
]
```

`api/alembic/versions/0001_skeleton.py` (written by hand so the triggers sit with the tables; `test_the_models_match_the_migrations` proves it matches the models):
```python
"""skeleton: people, sessions, roles, competencies, overrides, the training record

Revision ID: 0001
Revises:
Create Date: 2026-10-12
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

APPEND_ONLY = ("competency_record", "person_override")


def _created_at() -> sa.Column:
    return sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
                     nullable=False)


def upgrade() -> None:
    op.create_table(
        "person",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=True),
        sa.Column("entra_oid", sa.String(length=64), nullable=True),
        sa.Column("permission", sa.String(length=16), nullable=False),
        sa.Column("supervisor_id", sa.Integer(), nullable=True),
        sa.Column("pin_hash", sa.String(length=200), nullable=True),
        sa.Column("pin_failed_attempts", sa.Integer(), nullable=False),
        sa.Column("pin_locked", sa.Boolean(), nullable=False),
        sa.Column("password_hash", sa.String(length=200), nullable=True),
        sa.Column("password_failed_attempts", sa.Integer(), nullable=False),
        sa.Column("password_locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        _created_at(),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("code = upper(code)", name=op.f("ck_person_code_upper")),
        sa.CheckConstraint("email = lower(email)", name=op.f("ck_person_email_lower")),
        sa.CheckConstraint("permission in ('learner', 'supervisor', 'manager', 'admin')",
                           name=op.f("ck_person_permission")),
        sa.CheckConstraint("supervisor_id <> id", name=op.f("ck_person_not_own_supervisor")),
        sa.ForeignKeyConstraint(["supervisor_id"], ["person.id"],
                                name=op.f("fk_person_supervisor_id_person")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_person")),
        sa.UniqueConstraint("code", name=op.f("uq_person_code")),
        sa.UniqueConstraint("email", name=op.f("uq_person_email")),
        sa.UniqueConstraint("entra_oid", name=op.f("uq_person_entra_oid")),
    )
    op.create_index(op.f("ix_person_supervisor_id"), "person", ["supervisor_id"])
    op.create_table(
        "session",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("person_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("method", sa.String(length=8), nullable=False),
        _created_at(),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("method in ('password', 'pin')", name=op.f("ck_session_method")),
        sa.ForeignKeyConstraint(["person_id"], ["person.id"],
                                name=op.f("fk_session_person_id_person")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_session")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_session_token_hash")),
    )
    op.create_index(op.f("ix_session_person_id"), "session", ["person_id"])
    op.create_table(
        "role",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        _created_at(),
        sa.CheckConstraint("key = lower(key)", name=op.f("ck_role_key_lower")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_role")),
        sa.UniqueConstraint("key", name=op.f("uq_role_key")),
    )
    op.create_table(
        "competency",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("refresher_months", sa.Integer(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        _created_at(),
        sa.CheckConstraint("key = lower(key)", name=op.f("ck_competency_key_lower")),
        sa.CheckConstraint("kind in ('module', 'practical', 'ticket', 'policy')",
                           name=op.f("ck_competency_kind")),
        sa.CheckConstraint("refresher_months between 1 and 240",
                           name=op.f("ck_competency_refresher_months")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_competency")),
        sa.UniqueConstraint("key", name=op.f("uq_competency_key")),
    )
    op.create_table(
        "person_role",
        sa.Column("person_id", sa.Integer(), nullable=False),
        sa.Column("role_id", sa.Integer(), nullable=False),
        _created_at(),
        sa.ForeignKeyConstraint(["person_id"], ["person.id"],
                                name=op.f("fk_person_role_person_id_person")),
        sa.ForeignKeyConstraint(["role_id"], ["role.id"], name=op.f("fk_person_role_role_id_role")),
        sa.PrimaryKeyConstraint("person_id", "role_id", name=op.f("pk_person_role")),
    )
    op.create_index(op.f("ix_person_role_role_id"), "person_role", ["role_id"])
    op.create_table(
        "role_requirement",
        sa.Column("role_id", sa.Integer(), nullable=False),
        sa.Column("competency_id", sa.Integer(), nullable=False),
        _created_at(),
        sa.ForeignKeyConstraint(["role_id"], ["role.id"],
                                name=op.f("fk_role_requirement_role_id_role")),
        sa.ForeignKeyConstraint(["competency_id"], ["competency.id"],
                                name=op.f("fk_role_requirement_competency_id_competency")),
        sa.PrimaryKeyConstraint("role_id", "competency_id", name=op.f("pk_role_requirement")),
    )
    op.create_index(op.f("ix_role_requirement_competency_id"), "role_requirement",
                    ["competency_id"])
    op.create_table(
        "person_override",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("person_id", sa.Integer(), nullable=False),
        sa.Column("competency_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=False),
        sa.Column("recorded_by_id", sa.Integer(), nullable=False),
        _created_at(),
        sa.CheckConstraint("kind in ('extra', 'waive', 'clear')",
                           name=op.f("ck_person_override_kind")),
        sa.CheckConstraint("length(trim(note)) > 0", name=op.f("ck_person_override_note")),
        sa.ForeignKeyConstraint(["person_id"], ["person.id"],
                                name=op.f("fk_person_override_person_id_person")),
        sa.ForeignKeyConstraint(["competency_id"], ["competency.id"],
                                name=op.f("fk_person_override_competency_id_competency")),
        sa.ForeignKeyConstraint(["recorded_by_id"], ["person.id"],
                                name=op.f("fk_person_override_recorded_by_id_person")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_person_override")),
    )
    op.create_index(op.f("ix_person_override_person_id"), "person_override", ["person_id"])
    op.create_index(op.f("ix_person_override_competency_id"), "person_override",
                    ["competency_id"])
    op.create_table(
        "competency_record",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("person_id", sa.Integer(), nullable=False),
        sa.Column("competency_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("granted_on", sa.Date(), nullable=True),
        sa.Column("expires_on", sa.Date(), nullable=True),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("recorded_by_id", sa.Integer(), nullable=False),
        _created_at(),
        sa.CheckConstraint("kind in ('granted', 'revoked')", name=op.f("ck_competency_record_kind")),
        sa.CheckConstraint("kind = 'revoked' or granted_on is not null",
                           name=op.f("ck_competency_record_granted_on")),
        sa.CheckConstraint("kind = 'granted' or length(trim(note)) > 0",
                           name=op.f("ck_competency_record_revoke_note")),
        sa.CheckConstraint("expires_on > granted_on",
                           name=op.f("ck_competency_record_expires_after_granted")),
        sa.ForeignKeyConstraint(["person_id"], ["person.id"],
                                name=op.f("fk_competency_record_person_id_person")),
        sa.ForeignKeyConstraint(["competency_id"], ["competency.id"],
                                name=op.f("fk_competency_record_competency_id_competency")),
        sa.ForeignKeyConstraint(["recorded_by_id"], ["person.id"],
                                name=op.f("fk_competency_record_recorded_by_id_person")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_competency_record")),
    )
    op.create_index(op.f("ix_competency_record_person_id"), "competency_record", ["person_id"])
    op.create_index(op.f("ix_competency_record_competency_id"), "competency_record",
                    ["competency_id"])

    # The training record and the overrides are append-only. A mistake is
    # put right by a new row.
    op.execute("""
        create or replace function block_change() returns trigger
        language plpgsql as $$
        begin
            raise exception '% is append-only: rows cannot be updated or deleted', tg_table_name
                using errcode = 'restrict_violation';
        end
        $$
    """)
    for table in APPEND_ONLY:
        op.execute(f"create trigger {table}_append_only before update or delete "
                   f"on {table} for each row execute function block_change()")


def downgrade() -> None:
    for table in APPEND_ONLY:
        op.execute(f"drop trigger if exists {table}_append_only on {table}")
    op.execute("drop function if exists block_change()")
    op.drop_index(op.f("ix_competency_record_competency_id"), table_name="competency_record")
    op.drop_index(op.f("ix_competency_record_person_id"), table_name="competency_record")
    op.drop_table("competency_record")
    op.drop_index(op.f("ix_person_override_competency_id"), table_name="person_override")
    op.drop_index(op.f("ix_person_override_person_id"), table_name="person_override")
    op.drop_table("person_override")
    op.drop_index(op.f("ix_role_requirement_competency_id"), table_name="role_requirement")
    op.drop_table("role_requirement")
    op.drop_index(op.f("ix_person_role_role_id"), table_name="person_role")
    op.drop_table("person_role")
    op.drop_table("competency")
    op.drop_table("role")
    op.drop_index(op.f("ix_session_person_id"), table_name="session")
    op.drop_table("session")
    op.drop_index(op.f("ix_person_supervisor_id"), table_name="person")
    op.drop_table("person")
```

**Step 4: Run them to see them pass**

Run: `cd api && .venv/bin/pytest -v`
Expected: `12 passed`. If the drift test lists differences, fix the migration to match the models, not the other way round.

**Step 5: Commit**

```
git add api/lms/models api/alembic/versions/0001_skeleton.py api/tests/test_migrations.py \
  api/tests/test_append_only.py
git commit -m "Add people, sessions, roles, competencies, overrides and the training record" \
  -m "competency_record and person_override are append-only: a trigger refuses UPDATE and DELETE, as Simple TMS does for consignment_event. Codes are kept upper case and emails lower case by the database."
```

---

### Task 3: Passwords, PINs and sessions

**Files:**
- Create: `api/lms/services/access.py`, `api/lms/services/sessions.py`
- Modify: `api/tests/conftest.py` (append people)
- Test: `api/tests/test_sessions.py`

**Step 1: Write the failing test**

Append to `api/tests/conftest.py` (the sign-in helpers are used from Task 4):
```python
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
```

`api/tests/test_sessions.py`:
```python
from datetime import UTC, datetime, timedelta

import pytest

from conftest import make_person
from lms.services import access, sessions


def test_a_password_hash_checks_the_password_and_nothing_else():
    stored = access.hash_password("correct horse battery")
    assert stored.startswith("pbkdf2_sha256$")
    assert access.verify_password("correct horse battery", stored)
    assert not access.verify_password("Correct horse battery", stored)
    assert not access.verify_password("anything", None)
    assert not access.verify_password("anything", access.DUMMY_HASH)


@pytest.mark.parametrize("stored", [
    "pbkdf2_sha256$600000$not-hex$" + "0" * 64,
    "pbkdf2_sha256$many$" + "0" * 32 + "$" + "0" * 64,
    "pbkdf2_sha256$-5$" + "0" * 32 + "$" + "0" * 64,
    "pbkdf2_sha256$600000$" + "0" * 32 + "$",
    "not a hash",
])
def test_a_damaged_hash_is_a_wrong_password_not_a_crash(stored):
    assert access.verify_password("anything", stored) is False


@pytest.fixture
def kim(db):
    return make_person(db, "LL042", "Kim Lee")


NOW = datetime(2026, 10, 12, 9, 0, tzinfo=UTC)


def test_the_token_is_kept_only_as_its_hash(db, kim):
    raw = sessions.start(db, kim, "pin", now=NOW)
    assert raw.startswith("lms_s.")
    row = sessions.find(db, raw, now=NOW)
    assert row.person_id == kim.id and row.method == "pin"
    assert raw not in row.token_hash and len(row.token_hash) == 64


def test_a_pin_session_ends_after_15_minutes_idle(db, kim):
    raw = sessions.start(db, kim, "pin", now=NOW)
    assert sessions.find(db, raw, now=NOW + timedelta(minutes=14)) is not None
    # that use counted: 14 more minutes from there is still fine
    assert sessions.find(db, raw, now=NOW + timedelta(minutes=28)) is not None
    assert sessions.find(db, raw, now=NOW + timedelta(minutes=44)) is None


def test_a_password_session_ends_after_12_hours_idle(db, kim):
    raw = sessions.start(db, kim, "password", now=NOW)
    assert sessions.find(db, raw, now=NOW + timedelta(hours=11)) is not None
    assert sessions.find(db, raw, now=NOW + timedelta(hours=23, minutes=1)) is None


def test_a_busy_pin_session_still_ends_after_12_hours(db, kim):
    raw = sessions.start(db, kim, "pin", now=NOW)
    t = NOW
    while t < NOW + timedelta(hours=12):
        assert sessions.find(db, raw, now=t) is not None
        t += timedelta(minutes=10)
    assert sessions.find(db, raw, now=t) is None


def test_ending_one_session_or_all_of_them(db, kim):
    a = sessions.start(db, kim, "pin", now=NOW)
    b = sessions.start(db, kim, "password", now=NOW)
    c = sessions.start(db, kim, "pin", now=NOW)
    sessions.end(db, a)
    assert sessions.find(db, a, now=NOW) is None
    sessions.end_all(db, kim, "pin")
    assert sessions.find(db, c, now=NOW) is None
    assert sessions.find(db, b, now=NOW) is not None
    sessions.end_all(db, kim)
    assert sessions.find(db, b, now=NOW) is None


def test_someone_elses_token_is_nothing(db):
    assert sessions.find(db, "tms_s.abc.def", now=NOW) is None
    assert sessions.find(db, "lms_s.never-issued", now=NOW) is None


def test_a_pin_session_only_reads_training_whoever_has_it():
    assert sessions.scopes_for("admin", "pin") == ["training:read"]
    assert sessions.scopes_for("admin", "password") == ["*"]
    assert sessions.scopes_for("learner", "password") == ["training:read"]
```

**Step 2: Run it to see it fail**

Run: `cd api && .venv/bin/pytest tests/test_sessions.py -v`
Expected: ERROR, `ImportError: cannot import name 'access' from 'lms.services'`.

**Step 3: Minimal implementation**

`api/lms/services/access.py` (Simple TMS's as shipped, plus `MIN_PASSWORD`):
```python
"""Passwords and PINs. Hashes only, never the secret."""
from __future__ import annotations

import hashlib
import hmac
import secrets

# PBKDF2 from the standard library, no extra dependency. Same scheme as
# Simple WMS and Simple TMS.
_ITERATIONS = 600_000
MIN_PASSWORD = 12

# Checked when there is no real hash to check, so an unknown person takes as
# long as a wrong password. Same work as a real hash; nothing matches it.
DUMMY_HASH = f"pbkdf2_sha256${_ITERATIONS}${'0' * 32}${'0' * 64}"


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), _ITERATIONS)
    return f"pbkdf2_sha256${_ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        algo, iterations, salt, digest = stored.split("$")
    except ValueError:
        return False
    if algo != "pbkdf2_sha256" or not digest:
        return False
    try:
        candidate = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt), int(iterations)
        )
    except (ValueError, OverflowError):
        # a damaged hash matches nothing; it must not turn a sign-in into a 500
        return False
    return hmac.compare_digest(candidate.hex(), digest)
```

`api/lms/services/sessions.py`:
```python
"""Sessions: one random token per signed-in device, kept only as its hash.
A PIN session (the learner app, perhaps a shared tablet) ends after 15
minutes idle; a password session after 12 hours idle. Either ends on
sign-out, or when its PIN or password is changed."""
from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session as Db

from lms.models import Person, Session

PREFIX = "lms_s."
IDLE = {"password": timedelta(hours=12), "pin": timedelta(minutes=15)}
LIFETIME = {"password": timedelta(days=14), "pin": timedelta(hours=12)}
# last_seen_at is written at most once a minute, not on every request
TOUCH_EVERY = timedelta(minutes=1)

# What each permission level may do (the design's table). Admin-only areas
# (users, sign-in settings, webhooks, API keys) arrive with their steps.
SCOPES: dict[str, list[str]] = {
    "learner": ["training:read"],
    "supervisor": ["training:read", "matrix:read", "roles:read", "competencies:read"],
    "manager": ["training:read", "matrix:read", "roles:read", "competencies:read",
                "people:read", "people:write", "roles:write", "competencies:write",
                "records:write"],
    "admin": ["*"],
}
# A PIN is short, so a PIN session is for the learner app's own training,
# whoever signs in with it.
PIN_SCOPES = ["training:read"]


def scopes_for(permission: str, method: str) -> list[str]:
    if method == "pin":
        return list(PIN_SCOPES)
    return list(SCOPES.get(permission, []))


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def start(db: Db, person: Person, method: str, now: datetime | None = None) -> str:
    """A new session; the raw token is returned once and never stored."""
    now = now or datetime.now(UTC)
    raw = PREFIX + secrets.token_urlsafe(32)
    db.add(Session(person_id=person.id, token_hash=_hash(raw), method=method,
                   last_seen_at=now, expires_at=now + LIFETIME[method]))
    db.flush()
    return raw


def find(db: Db, raw: str, now: datetime | None = None) -> Session | None:
    """The live session for this token, marked as just used; None if it is
    not ours, ended, too old or idle too long."""
    if not raw.startswith(PREFIX):
        return None
    now = now or datetime.now(UTC)
    row = db.execute(select(Session).where(Session.token_hash == _hash(raw))).scalar_one_or_none()
    if (row is None or row.revoked_at is not None or row.expires_at <= now
            or now - row.last_seen_at > IDLE[row.method]):
        return None
    if now - row.last_seen_at >= TOUCH_EVERY:
        row.last_seen_at = now
        db.flush()
    return row


def end(db: Db, raw: str) -> None:
    db.execute(update(Session).where(Session.token_hash == _hash(raw),
                                     Session.revoked_at.is_(None))
               .values(revoked_at=datetime.now(UTC)))
    db.flush()


def end_all(db: Db, person: Person, method: str | None = None) -> None:
    """End every session of this person (or only their PIN or password ones)."""
    q = update(Session).where(Session.person_id == person.id, Session.revoked_at.is_(None))
    if method is not None:
        q = q.where(Session.method == method)
    db.execute(q.values(revoked_at=datetime.now(UTC)))
    db.flush()
```

**Step 4: Run it to see it pass**

Run: `cd api && .venv/bin/pytest tests/test_sessions.py -v`
Expected: `13 passed`.

**Step 5: Commit**

```
git add api/lms/services/access.py api/lms/services/sessions.py api/tests/conftest.py \
  api/tests/test_sessions.py
git commit -m "Hash passwords and PINs, and keep sessions that end when left idle" \
  -m "One random token per device, kept only as its hash. A PIN session ends after 15 minutes idle, a password one after 12 hours. A PIN session only reads training."
```

---

### Task 4: Signing in with a password or a PIN, and `require(scope)`

**Files:**
- Modify: `api/lms/api/deps.py` (replace)
- Create: `api/lms/api/schemas.py`, `api/lms/api/routes/auth.py`
- Modify: `api/lms/api/app.py`
- Test: `api/tests/test_auth.py`

**Step 1: Write the failing test**

`api/tests/test_auth.py`:
```python
from datetime import UTC, datetime, timedelta

from sqlalchemy import update

from conftest import PASSWORD, PIN, all_at_once, bearer, fresh_client, login, pin_login
from lms.models import Session


def test_email_and_password_give_a_session_that_says_who_you_are(client, manager):
    out = login(client, "Mel@Example.com.au ")
    assert out["token"].startswith("lms_s.")
    assert out["person"]["code"] == "MG001" and out["person"]["method"] == "password"
    me = client.get("/v1/auth/me", headers=bearer(out["token"])).json()
    assert me["permission"] == "manager"
    assert "records:write" in me["scopes"] and me["idle_seconds"] == 12 * 3600


def test_code_and_pin_give_a_learner_session(client, learner):
    out = pin_login(client, " ll042")
    me = client.get("/v1/auth/me", headers=bearer(out["token"])).json()
    assert (me["code"], me["method"], me["scopes"]) == ("LL042", "pin", ["training:read"])
    assert me["idle_seconds"] == 15 * 60


def test_a_supervisor_signed_in_by_pin_only_reads_training(client, supervisor):
    by_pin = pin_login(client, supervisor.code)["person"]
    assert (by_pin["permission"], by_pin["scopes"]) == ("supervisor", ["training:read"])
    by_password = login(client, supervisor.email)["person"]
    assert "matrix:read" in by_password["scopes"]


def test_a_wrong_password_and_an_unknown_email_look_alike(client, manager):
    wrong = client.post("/v1/auth/login", json={"email": manager.email, "password": "nope"})
    unknown = client.post("/v1/auth/login", json={"email": "who@example.com", "password": "nope"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json() == {"detail": "wrong email or password",
                                              "code": "wrong_password"}


def test_someone_without_a_password_cannot_use_one(client, learner):
    r = client.post("/v1/auth/login", json={"email": "kim@example.com", "password": PASSWORD})
    assert r.status_code == 401 and r.json()["code"] == "wrong_password"


def test_five_wrong_passwords_lock_it_for_15_minutes(client, db, manager):
    for _ in range(4):
        client.post("/v1/auth/login", json={"email": manager.email, "password": "nope"})
    r = client.post("/v1/auth/login", json={"email": manager.email, "password": "nope"})
    assert r.status_code == 401 and r.json()["code"] == "locked"
    r = client.post("/v1/auth/login", json={"email": manager.email, "password": PASSWORD})
    assert r.json()["code"] == "locked"
    # 15 minutes on, the right password works
    manager.password_locked_until = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    assert login(client, manager.email)["token"]


def test_five_wrong_pins_lock_the_pin_until_a_manager_resets_it(client, db, learner):
    for _ in range(4):
        r = client.post("/v1/auth/pin-login", json={"code": "LL042", "pin": "0000"})
        assert r.status_code == 401 and r.json()["code"] == "wrong_pin"
    r = client.post("/v1/auth/pin-login", json={"code": "LL042", "pin": "0000"})
    assert r.json()["code"] == "locked"
    r = client.post("/v1/auth/pin-login", json={"code": "LL042", "pin": PIN})
    assert r.status_code == 401 and r.json()["code"] == "locked"
    db.refresh(learner)
    assert learner.pin_locked is True


def test_an_unknown_code_looks_like_a_wrong_pin(client, learner):
    r = client.post("/v1/auth/pin-login", json={"code": "NOBODY", "pin": PIN})
    assert r.status_code == 401 and r.json() == {"detail": "wrong code or PIN",
                                                 "code": "wrong_pin"}


def test_a_right_pin_clears_the_count(client, db, learner):
    client.post("/v1/auth/pin-login", json={"code": "LL042", "pin": "0000"})
    pin_login(client, "LL042")
    db.refresh(learner)
    assert learner.pin_failed_attempts == 0


def test_wrong_pins_sent_all_at_once_still_lock_after_five(client, db, learner):
    def guess():
        return fresh_client().post("/v1/auth/pin-login",
                                   json={"code": "LL042", "pin": "0000"}).json()["code"]

    codes = all_at_once(8, guess)
    assert codes.count("wrong_pin") == 4 and codes.count("locked") == 4


def test_signing_out_ends_the_session(client, learner):
    token = pin_login(client, "LL042")["token"]
    assert client.post("/v1/auth/logout", headers=bearer(token)).status_code == 204
    assert client.get("/v1/auth/me", headers=bearer(token)).status_code == 401
    # again, or with nothing at all, is still fine
    assert client.post("/v1/auth/logout", headers=bearer(token)).status_code == 204
    assert client.post("/v1/auth/logout").status_code == 204


def test_15_minutes_idle_ends_a_pin_session(client, db, learner):
    token = pin_login(client, "LL042")["token"]
    db.execute(update(Session).values(last_seen_at=datetime.now(UTC) - timedelta(minutes=16)))
    db.commit()
    assert client.get("/v1/auth/me", headers=bearer(token)).status_code == 401


def test_no_token_or_a_bad_one_is_401(client):
    assert client.get("/v1/auth/me").status_code == 401
    assert client.get("/v1/auth/me", headers=bearer("lms_s.forged")).status_code == 401
    assert client.get("/v1/auth/me", headers=bearer("tms_s.someone-elses")).status_code == 401


def test_a_deactivated_person_loses_their_session(client, db, learner):
    token = pin_login(client, "LL042")["token"]
    learner.active = False
    db.commit()
    assert client.get("/v1/auth/me", headers=bearer(token)).status_code == 401
    r = client.post("/v1/auth/pin-login", json={"code": "LL042", "pin": PIN})
    assert r.json()["code"] == "wrong_pin"
```

**Step 2: Run it to see it fail**

Run: `cd api && .venv/bin/pytest tests/test_auth.py -v`
Expected: FAIL. The `login` and `pin_login` helpers' `assert r.status_code == 200` see `404`, and the rest get `404` where they expect `401`.

**Step 3: Minimal implementation**

`api/lms/api/deps.py` (replace):
```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy.orm import Session as Db

from lms.api.errors import Forbidden, Unauthorised
from lms.db import get_sessionmaker
from lms.models import Person
from lms.services import sessions


def get_db():
    with get_sessionmaker()() as session:
        yield session


DB = Annotated[Db, Depends(get_db)]


@dataclass(slots=True)
class Principal:
    """Whoever is calling: a person with a session, signed in by password or PIN."""

    person: Person
    method: str  # password | pin
    scopes: list[str]

    def has_scope(self, scope: str) -> bool:
        area = scope.split(":")[0]
        return "*" in self.scopes or scope in self.scopes or f"{area}:*" in self.scopes

    @property
    def sees_everyone(self) -> bool:
        return self.has_scope("matrix:read") and self.person.permission in ("manager", "admin")

    def sees(self, other: Person) -> bool:
        """Their own training; their team's (a supervisor); everyone's (a
        manager or admin). A supervisor's team is the people whose supervisor
        they are."""
        if other.id == self.person.id:
            return True
        if not self.has_scope("matrix:read"):
            return False
        return self.sees_everyone or other.supervisor_id == self.person.id


def bearer_token(authorization: str | None) -> str | None:
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    return authorization.split(" ", 1)[1].strip()


def get_principal(db: DB, authorization: Annotated[str | None, Header()] = None) -> Principal:
    raw = bearer_token(authorization)
    if raw is None:
        raise Unauthorised("missing bearer token")
    row = sessions.find(db, raw)
    person = db.get(Person, row.person_id) if row else None
    if row is None or person is None or not person.active:
        raise Unauthorised("session expired or invalid")
    db.commit()  # keeps the touch on last_seen_at
    return Principal(person=person, method=row.method,
                     scopes=sessions.scopes_for(person.permission, row.method))


Who = Annotated[Principal, Depends(get_principal)]


def require(scope: str):
    """Dependency: the caller must carry this scope."""

    def _check(who: Who) -> Principal:
        if not who.has_scope(scope):
            raise Forbidden(f"you do not have the {scope} scope")
        return who

    return Depends(_check)
```

`api/lms/api/schemas.py` (shapes and patterns the routes share):
```python
"""Shapes more than one route uses."""
from __future__ import annotations

from pydantic import BaseModel

from lms.models import Competency, Person, Role

KEY = r"^[a-z0-9][a-z0-9-]*$"
CODE = r"^[A-Za-z0-9._-]+$"
PIN = r"^[0-9]{4,8}$"
EMAIL = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class Page[T](BaseModel):
    items: list[T]
    total: int


class PersonRef(BaseModel):
    code: str
    name: str


class RoleRef(BaseModel):
    key: str
    name: str


class CompetencyRef(BaseModel):
    key: str
    name: str
    kind: str


def person_ref(p: Person | None) -> PersonRef | None:
    return None if p is None else PersonRef(code=p.code, name=p.name)


def role_ref(r: Role) -> RoleRef:
    return RoleRef(key=r.key, name=r.name)


def competency_ref(c: Competency) -> CompetencyRef:
    return CompetencyRef(key=c.key, name=c.name, kind=c.kind)


def normal_code(value: str) -> str:
    """'ll042 ' and 'LL042' are the same person."""
    return value.strip().upper()


def normal_key(value: str) -> str:
    return value.strip().lower()
```

`api/lms/api/routes/auth.py`:
```python
"""Sign in with an email and password (either app) or a code and PIN (the
learner app). Either way the session token is all a client holds."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Header, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from lms.api.deps import DB, Who, bearer_token
from lms.api.schemas import normal_code
from lms.models import Person
from lms.services import access, sessions

router = APIRouter(prefix="/auth", tags=["auth"])

TRIES = 5
PASSWORD_LOCK_MINUTES = 15


class LoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(max_length=254)
    password: str = Field(max_length=200)


class PinLoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(max_length=32)
    pin: str = Field(max_length=8)


class MeOut(BaseModel):
    id: int
    code: str
    name: str
    email: str | None
    permission: str
    method: str
    scopes: list[str]
    # the session ends after this long without a request
    idle_seconds: int


class SessionOut(BaseModel):
    token: str
    person: MeOut


def me_out(p: Person, method: str) -> MeOut:
    return MeOut(id=p.id, code=p.code, name=p.name, email=p.email, permission=p.permission,
                 method=method, scopes=sessions.scopes_for(p.permission, method),
                 idle_seconds=int(sessions.IDLE[method].total_seconds()))


def _refused(detail: str, code: str) -> JSONResponse:
    return JSONResponse(status_code=401, content={"detail": detail, "code": code},
                        headers={"WWW-Authenticate": "Bearer"})


def _signed_in(db, person: Person, method: str) -> SessionOut:
    token = sessions.start(db, person, method)
    person.last_login_at = datetime.now(UTC)
    db.commit()
    return SessionOut(token=token, person=me_out(person, method))


def _one_at_a_time(db, where) -> Person | None:
    # the row stays locked until this attempt is counted, so guesses sent all
    # at once are weighed one after another and cannot get past the limit
    return db.execute(select(Person).where(where).with_for_update()).scalar_one_or_none()


@router.post("/login", response_model=SessionOut)
def login(body: LoginIn, db: DB):
    """Five wrong passwords lock the password for 15 minutes."""
    person = _one_at_a_time(db, Person.email == body.email.strip().lower())
    if person is None or not person.active or not person.password_hash:
        # an unknown email and a wrong password look alike, and take as long
        access.verify_password(body.password, access.DUMMY_HASH)
        return _refused("wrong email or password", "wrong_password")
    if person.password_locked_until and person.password_locked_until > datetime.now(UTC):
        return _refused("too many wrong passwords; try again in a few minutes", "locked")
    if not access.verify_password(body.password, person.password_hash):
        person.password_failed_attempts += 1
        if person.password_failed_attempts >= TRIES:
            person.password_failed_attempts = 0
            person.password_locked_until = (datetime.now(UTC)
                                            + timedelta(minutes=PASSWORD_LOCK_MINUTES))
            db.commit()
            return _refused(f"too many wrong passwords; locked for {PASSWORD_LOCK_MINUTES} "
                            "minutes", "locked")
        db.commit()
        return _refused("wrong email or password", "wrong_password")
    person.password_failed_attempts = 0
    person.password_locked_until = None
    return _signed_in(db, person, "password")


@router.post("/pin-login", response_model=SessionOut)
def pin_login(body: PinLoginIn, db: DB):
    """Five wrong PINs lock the PIN until a manager sets a new one."""
    person = _one_at_a_time(db, Person.code == normal_code(body.code))
    if person is None or not person.active or not person.pin_hash:
        access.verify_password(body.pin, access.DUMMY_HASH)
        return _refused("wrong code or PIN", "wrong_pin")
    if person.pin_locked:
        return _refused("this PIN is locked after too many wrong tries; ask your manager to "
                        "reset it", "locked")
    if not access.verify_password(body.pin, person.pin_hash):
        person.pin_failed_attempts += 1
        if person.pin_failed_attempts >= TRIES:
            person.pin_locked = True
            db.commit()
            return _refused(f"wrong PIN {TRIES} times; it is locked until your manager resets it",
                            "locked")
        db.commit()
        # no tries left count: an unknown code could not say it without giving itself away
        return _refused("wrong code or PIN", "wrong_pin")
    person.pin_failed_attempts = 0
    return _signed_in(db, person, "pin")


@router.post("/logout", status_code=204)
def logout(db: DB, authorization: Annotated[str | None, Header()] = None):
    """Ends this session. Answers 204 even for a session that already ended."""
    raw = bearer_token(authorization)
    if raw:
        sessions.end(db, raw)
        db.commit()
    return Response(status_code=204)


@router.get("/me", response_model=MeOut)
def me(who: Who):
    return me_out(who.person, who.method)
```

In `api/lms/api/app.py`, add under `from lms.api.deps import DB`:
```python
from lms.api.routes import auth
```
and under `v1 = APIRouter(prefix="/v1")`:
```python
v1.include_router(auth.router)
```

**Step 4: Run it to see it pass**

Run: `cd api && .venv/bin/pytest tests/test_auth.py -v`
Expected: `14 passed`.

**Step 5: Commit**

```
git add api/lms/api/deps.py api/lms/api/schemas.py api/lms/api/routes/auth.py api/lms/api/app.py \
  api/tests/test_auth.py
git commit -m "Sign in with an email and password or a code and PIN" \
  -m "Five wrong passwords lock the password for 15 minutes; five wrong PINs lock the PIN until a manager resets it. Attempts are counted one at a time. require(scope) as in Simple TMS."
```

---
### Task 5: `lms create-user`

**Files:**
- Create: `api/lms/cli.py`
- Test: `api/tests/test_cli.py`

**Step 1: Write the failing test**

`api/tests/test_cli.py`:
```python
from sqlalchemy import select

from lms.cli import main
from lms.models import Person


def test_create_user_makes_someone_who_can_sign_in(client, db, capsys):
    assert main(["create-user", "--code", "ad001", "--name", "Leighton Lauton",
                 "--email", "Leighton@Example.com.au", "--password",
                 "a long enough password"]) == 0
    assert "AD001 Leighton Lauton <leighton@example.com.au> created as admin" in capsys.readouterr().out
    person = db.execute(select(Person)).scalar_one()
    assert person.permission == "admin" and person.pin_hash is None
    r = client.post("/v1/auth/login", json={"email": "leighton@example.com.au",
                                            "password": "a long enough password"})
    assert r.status_code == 200


def test_create_user_refuses_a_short_password(db, capsys):
    assert main(["create-user", "--code", "AD001", "--name", "L", "--email", "l@example.com",
                 "--password", "short"]) == 1
    assert "at least 12" in capsys.readouterr().err
    assert db.execute(select(Person)).first() is None


def test_create_user_refuses_a_code_or_email_already_taken(db, admin, capsys):
    assert main(["create-user", "--code", admin.code, "--name", "Another",
                 "--email", "another@example.com", "--password", "a long enough password"]) == 1
    assert main(["create-user", "--code", "AD002", "--name", "Another",
                 "--email", admin.email, "--password", "a long enough password"]) == 1
    assert capsys.readouterr().err.count("already exists") == 2
```

**Step 2: Run it to see it fail**

Run: `cd api && .venv/bin/pytest tests/test_cli.py -v`
Expected: ERROR, `ModuleNotFoundError: No module named 'lms.cli'`.

**Step 3: Minimal implementation**

`api/lms/cli.py`:
```python
"""Command line for what has to happen before anyone can sign in."""
from __future__ import annotations

import argparse
import getpass
import sys

from sqlalchemy import or_, select

from lms.api.schemas import normal_code
from lms.db import get_sessionmaker
from lms.models import PERMISSIONS, Person
from lms.services import access


def cmd_create_user(args) -> int:
    code, email = normal_code(args.code), args.email.strip().lower()
    password = args.password or getpass.getpass("Password: ")
    if len(password) < access.MIN_PASSWORD:
        print(f"create-user: the password needs at least {access.MIN_PASSWORD} characters",
              file=sys.stderr)
        return 1
    with get_sessionmaker()() as db:
        taken = db.execute(select(Person).where(
            or_(Person.code == code, Person.email == email))).scalars().first()
        if taken:
            print(f"create-user: {taken.code} <{taken.email}> already exists", file=sys.stderr)
            return 1
        person = Person(code=code, name=args.name, email=email, permission=args.permission,
                        password_hash=access.hash_password(password), pin_failed_attempts=0,
                        pin_locked=False, password_failed_attempts=0, active=True)
        db.add(person)
        db.commit()
        print(f"{person.code} {person.name} <{person.email}> created as {person.permission}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lms")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("create-user", help="add a person who signs in with an email and password")
    p.add_argument("--code", required=True, help="their person code, e.g. LL001")
    p.add_argument("--name", required=True)
    p.add_argument("--email", required=True)
    p.add_argument("--permission", default="admin", choices=list(PERMISSIONS))
    p.add_argument("--password", help="prompted for if omitted")
    p.set_defaults(func=cmd_create_user)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
```

**Step 4: Run it to see it pass**

Run: `cd api && .venv/bin/pytest tests/test_cli.py -v && .venv/bin/lms --help`
Expected: `3 passed`, then the usage line `usage: lms [-h] {create-user} ...`.

**Step 5: Commit**

```
git add api/lms/cli.py api/tests/test_cli.py
git commit -m "Add lms create-user for the first sign-in"
```

---

### Task 6: A person's status for each competency, worked out

The heart of rule 2: one pure function, no database, every case in one table.

**Files:**
- Create: `api/lms/services/status.py`
- Test: `api/tests/test_status.py`

**Step 1: Write the failing test**

`api/tests/test_status.py`:
```python
"""Status is worked out from the requirement, the latest override, the latest
record and today's date. Every case the matrix can show, in one table."""
from datetime import date

import pytest

from lms.services.status import Latest, add_months, expiry, work_out

TODAY = date(2026, 10, 12)
D = date.fromisoformat


def granted(on: str, expires: str | None = None) -> Latest:
    return Latest("granted", D(on), D(expires) if expires else None)


REVOKED = Latest("revoked")

CASES = [
    # (why, by_role, override, latest, refresher_months, status, expires_on)
    ("nothing asks for it", False, None, None, None, "not_required", None),
    ("a record alone does not make it required", False, None, granted("2026-01-01"), None,
     "not_required", None),
    ("a waiver of something not required changes nothing", False, "waive", None, None,
     "not_required", None),
    ("a role asks, nothing recorded", True, None, None, None, "missing", None),
    ("an extra asks, nothing recorded", False, "extra", None, None, "missing", None),
    ("the latest record is a revoke", True, None, REVOKED, 12, "missing", None),
    ("waived, with nothing recorded", True, "waive", None, None, "waived", None),
    ("waived beats a lapsed record", True, "waive", granted("2020-01-01", "2021-01-01"), None,
     "waived", None),
    ("granted, no expiry and no refresher: never runs out", True, None,
     granted("2019-05-01"), None, "current", None),
    ("an extra, granted and current", False, "extra", granted("2026-01-01", "2027-01-01"), None,
     "current", "2027-01-01"),
    ("card date 31 days away", True, None, granted("2025-01-01", "2026-11-12"), None,
     "current", "2026-11-12"),
    ("card date 30 days away", True, None, granted("2025-01-01", "2026-11-11"), None,
     "expiring", "2026-11-11"),
    ("card date is today: still good today", True, None, granted("2025-01-01", "2026-10-12"),
     None, "expiring", "2026-10-12"),
    ("card date was yesterday", True, None, granted("2025-01-01", "2026-10-11"), None,
     "lapsed", "2026-10-11"),
    ("24-month refresher, due tomorrow", True, None, granted("2024-10-13"), 24, "expiring",
     "2026-10-13"),
    ("24-month refresher, due yesterday", True, None, granted("2024-10-11"), 24, "lapsed",
     "2026-10-11"),
    ("12-month refresher, done six months ago", True, None, granted("2026-04-12"), 12,
     "current", "2027-04-12"),
    ("the record's own date beats the refresher", True, None,
     granted("2020-01-01", "2027-06-30"), 12, "current", "2027-06-30"),
]


@pytest.mark.parametrize("why,by_role,override,latest,months,status,expires",
                         CASES, ids=[c[0] for c in CASES])
def test_status(why, by_role, override, latest, months, status, expires):
    s = work_out(by_role=by_role, override=override, latest=latest, refresher_months=months,
                 today=TODAY)
    assert s.status == status
    assert s.expires_on == (D(expires) if expires else None)
    if status in ("current", "expiring", "lapsed"):
        assert s.granted_on == latest.granted_on


@pytest.mark.parametrize("start,months,end", [
    ("2026-01-15", 1, "2026-02-15"),
    ("2026-11-15", 2, "2027-01-15"),
    ("2024-01-31", 1, "2024-02-29"),   # a leap year
    ("2023-01-31", 1, "2023-02-28"),
    ("2024-02-29", 12, "2025-02-28"),
    ("2026-10-12", 240, "2046-10-12"),
])
def test_months_are_added_as_a_calendar_does(start, months, end):
    assert add_months(D(start), months) == D(end)


def test_expiry_is_the_record_then_the_refresher_then_never():
    assert expiry(D("2026-01-01"), D("2026-06-30"), 12) == D("2026-06-30")
    assert expiry(D("2026-01-01"), None, 12) == D("2027-01-01")
    assert expiry(D("2026-01-01"), None, None) is None
```

**Step 2: Run it to see it fail**

Run: `cd api && .venv/bin/pytest tests/test_status.py -v`
Expected: ERROR, `ModuleNotFoundError: No module named 'lms.services.status'`.

**Step 3: Minimal implementation**

`api/lms/services/status.py`:
```python
"""A person's status for one competency, worked out from what their roles
require, their latest override and latest record, and today's date. Never
stored, so it cannot drift (rule 2)."""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date

EXPIRING_DAYS = 30
STATUSES = ("current", "expiring", "lapsed", "missing", "waived", "not_required")


@dataclass(frozen=True, slots=True)
class Latest:
    """The latest record for a person and competency."""

    kind: str  # granted | revoked
    granted_on: date | None = None
    expires_on: date | None = None


@dataclass(frozen=True, slots=True)
class Status:
    status: str
    granted_on: date | None = None
    expires_on: date | None = None


def add_months(d: date, months: int) -> date:
    """31 January plus a month is the last day of February."""
    years, month0 = divmod(d.month - 1 + months, 12)
    year, month = d.year + years, month0 + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def expiry(granted_on: date, expires_on: date | None, refresher_months: int | None) -> date | None:
    """The last day a grant is good for: the record's own date if it has one
    (a ticket's card), else the refresher after the grant, else never."""
    if expires_on is not None:
        return expires_on
    if refresher_months:
        return add_months(granted_on, refresher_months)
    return None


def work_out(*, by_role: bool, override: str | None, latest: Latest | None,
             refresher_months: int | None, today: date) -> Status:
    """Required is roles plus extras, less waivers. `override` is the latest
    override's kind: extra, waive, or None (none, or cleared)."""
    if not (by_role or override == "extra"):
        return Status("not_required")
    if override == "waive":
        return Status("waived")
    if latest is None or latest.kind != "granted" or latest.granted_on is None:
        return Status("missing")
    ends = expiry(latest.granted_on, latest.expires_on, refresher_months)
    if ends is None:
        return Status("current", latest.granted_on, None)
    if today > ends:
        return Status("lapsed", latest.granted_on, ends)
    if (ends - today).days <= EXPIRING_DAYS:
        return Status("expiring", latest.granted_on, ends)
    return Status("current", latest.granted_on, ends)
```

**Step 4: Run it to see it pass**

Run: `cd api && .venv/bin/pytest tests/test_status.py -v`
Expected: `25 passed`, each case named by its "why".

**Step 5: Commit**

```
git add api/lms/services/status.py api/tests/test_status.py
git commit -m "Work out a person's status for each competency" \
  -m "From what their roles and extras ask, their latest waiver, their latest record and today's date. Expiring within 30 days of the last good day; the record's own date beats the refresher. Never stored."
```

---

### Task 7: Competencies

**Files:**
- Create: `api/lms/api/routes/competencies.py`
- Modify: `api/lms/api/app.py`
- Test: `api/tests/test_competencies.py`

**Step 1: Write the failing test**

`api/tests/test_competencies.py`:
```python
INDUCTION = {"key": "Site-Induction", "name": "Site induction", "kind": "module",
             "refresher_months": 24}


def make_competency(client, headers, body=INDUCTION):
    r = client.post("/v1/competencies", headers=headers, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_a_manager_adds_a_competency(client, manager_headers):
    out = make_competency(client, manager_headers)
    assert (out["key"], out["name"], out["kind"]) == ("site-induction", "Site induction", "module")
    assert out["refresher_months"] == 24 and out["active"] is True


def test_four_kinds_only(client, manager_headers):
    r = client.post("/v1/competencies", headers=manager_headers, json={**INDUCTION, "kind": "quiz"})
    assert r.status_code == 422


def test_a_refresher_is_1_to_240_months_or_none(client, manager_headers):
    for months in (0, 241):
        r = client.post("/v1/competencies", headers=manager_headers,
                        json={**INDUCTION, "refresher_months": months})
        assert r.status_code == 422
    out = make_competency(client, manager_headers,
                          {"key": "forklift-licence", "name": "Forklift licence", "kind": "ticket"})
    assert out["refresher_months"] is None


def test_a_key_is_used_once(client, manager_headers):
    make_competency(client, manager_headers)
    r = client.post("/v1/competencies", headers=manager_headers,
                    json={**INDUCTION, "key": "site-induction"})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "key"


def test_a_key_is_letters_digits_and_dashes(client, manager_headers):
    r = client.post("/v1/competencies", headers=manager_headers,
                    json={**INDUCTION, "key": "site induction"})
    assert r.status_code == 422


def test_the_name_and_refresher_change_but_the_kind_stays(client, manager_headers):
    make_competency(client, manager_headers)
    r = client.patch("/v1/competencies/site-induction", headers=manager_headers,
                     json={"name": "Site induction (Ballarat)", "refresher_months": None})
    assert r.status_code == 200
    assert r.json()["name"] == "Site induction (Ballarat)" and r.json()["refresher_months"] is None
    r = client.patch("/v1/competencies/site-induction", headers=manager_headers,
                     json={"kind": "policy"})
    assert r.status_code == 422


def test_list_by_name_and_filter_by_kind(client, manager_headers):
    make_competency(client, manager_headers)
    make_competency(client, manager_headers,
                    {"key": "forklift-licence", "name": "Forklift licence", "kind": "ticket"})
    r = client.get("/v1/competencies", headers=manager_headers).json()
    assert [c["key"] for c in r["items"]] == ["forklift-licence", "site-induction"]
    r = client.get("/v1/competencies?kind=ticket", headers=manager_headers).json()
    assert r["total"] == 1


def test_deactivated_not_deleted(client, manager_headers):
    make_competency(client, manager_headers)
    r = client.post("/v1/competencies/site-induction/deactivate", headers=manager_headers)
    assert r.json()["active"] is False
    assert client.get("/v1/competencies?active=true", headers=manager_headers).json()["total"] == 0
    assert client.post("/v1/competencies/site-induction/reactivate",
                       headers=manager_headers).json()["active"] is True
    assert client.delete("/v1/competencies/site-induction",
                         headers=manager_headers).status_code == 405


def test_a_supervisor_reads_but_does_not_change(client, manager_headers, supervisor_headers):
    make_competency(client, manager_headers)
    assert client.get("/v1/competencies/site-induction", headers=supervisor_headers).status_code == 200
    r = client.patch("/v1/competencies/site-induction", headers=supervisor_headers,
                     json={"name": "x"})
    assert r.status_code == 403


def test_a_learner_cannot_see_the_list(client, learner_headers):
    assert client.get("/v1/competencies", headers=learner_headers).status_code == 403


def test_an_unknown_competency_is_404(client, manager_headers):
    assert client.get("/v1/competencies/nope", headers=manager_headers).status_code == 404
```

**Step 2: Run it to see it fail**

Run: `cd api && .venv/bin/pytest tests/test_competencies.py -v`
Expected: FAIL, `404` from `POST /v1/competencies` where `201`, `422` or `403` are expected.

**Step 3: Minimal implementation**

`api/lms/api/routes/competencies.py`:
```python
"""Competencies: anything a person can be current for. Deactivated, never deleted."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select

from lms.api.deps import DB, Principal, require
from lms.api.errors import FieldError, NotFound
from lms.api.schemas import KEY, Page, normal_key
from lms.models import Competency

router = APIRouter(tags=["competencies"])

Kind = Literal["module", "practical", "ticket", "policy"]


class CompetencyIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    key: str = Field(min_length=1, max_length=64, pattern=KEY)
    name: str = Field(min_length=1, max_length=120)
    kind: Kind
    refresher_months: int | None = Field(default=None, ge=1, le=240)

    @field_validator("key", mode="before")
    @classmethod
    def _key(cls, v):
        return normal_key(v) if isinstance(v, str) else v


class CompetencyPatch(BaseModel):
    """The kind stays: it says how the competency is earned."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    refresher_months: int | None = Field(default=None, ge=1, le=240)


class CompetencyOut(BaseModel):
    id: int
    key: str
    name: str
    kind: str
    refresher_months: int | None
    active: bool
    created_at: datetime


def competency_out(c: Competency) -> CompetencyOut:
    return CompetencyOut(id=c.id, key=c.key, name=c.name, kind=c.kind,
                         refresher_months=c.refresher_months, active=c.active,
                         created_at=c.created_at)


def get_competency(db, key: str) -> Competency:
    c = db.execute(select(Competency).where(Competency.key == normal_key(key))).scalar_one_or_none()
    if c is None:
        raise NotFound(f"no competency {key}")
    return c


@router.post("/competencies", status_code=201, response_model=CompetencyOut)
def create_competency(body: CompetencyIn, db: DB, who: Principal = require("competencies:write")):
    if db.execute(select(Competency).where(Competency.key == body.key)).scalar_one_or_none():
        raise FieldError("key", f"competency {body.key} already exists")
    c = Competency(key=body.key, name=body.name, kind=body.kind,
                   refresher_months=body.refresher_months, active=True)
    db.add(c)
    db.commit()
    return JSONResponse(status_code=201, content=competency_out(c).model_dump(mode="json"))


@router.get("/competencies", response_model=Page[CompetencyOut])
def list_competencies(db: DB, kind: Kind | None = None, active: bool | None = None,
                      who: Principal = require("competencies:read")):
    q = select(Competency)
    if kind is not None:
        q = q.where(Competency.kind == kind)
    if active is not None:
        q = q.where(Competency.active.is_(active))
    rows = db.execute(q.order_by(Competency.name)).scalars().all()
    return Page(items=[competency_out(c) for c in rows], total=len(rows))


@router.get("/competencies/{key}", response_model=CompetencyOut)
def read_competency(key: str, db: DB, who: Principal = require("competencies:read")):
    return competency_out(get_competency(db, key))


@router.patch("/competencies/{key}", response_model=CompetencyOut)
def update_competency(key: str, body: CompetencyPatch, db: DB,
                      who: Principal = require("competencies:write")):
    c = get_competency(db, key)
    if body.name is not None:
        c.name = body.name
    if "refresher_months" in body.model_fields_set:
        # null takes the refresher away: worked out again for everyone at once
        c.refresher_months = body.refresher_months
    db.commit()
    return competency_out(c)


@router.post("/competencies/{key}/deactivate", response_model=CompetencyOut)
def deactivate_competency(key: str, db: DB, who: Principal = require("competencies:write")):
    """No longer asked of anyone. Its records stay."""
    c = get_competency(db, key)
    c.active = False
    db.commit()
    return competency_out(c)


@router.post("/competencies/{key}/reactivate", response_model=CompetencyOut)
def reactivate_competency(key: str, db: DB, who: Principal = require("competencies:write")):
    c = get_competency(db, key)
    c.active = True
    db.commit()
    return competency_out(c)
```

In `api/lms/api/app.py`, make the routes import:
```python
from lms.api.routes import auth, competencies
```
and add after `v1.include_router(auth.router)`:
```python
v1.include_router(competencies.router)
```

**Step 4: Run it to see it pass**

Run: `cd api && .venv/bin/pytest tests/test_competencies.py -v`
Expected: `11 passed`.

**Step 5: Commit**

```
git add api/lms/api/routes/competencies.py api/lms/api/app.py api/tests/test_competencies.py
git commit -m "Add competencies: module, practical, ticket or policy, with a refresher" \
  -m "Deactivated, never deleted. The kind stays once made; the name and refresher can change."
```

---

### Task 8: Roles and what each requires

**Files:**
- Create: `api/lms/api/routes/roles.py`
- Modify: `api/lms/api/app.py`
- Test: `api/tests/test_roles.py`

**Step 1: Write the failing test**

`api/tests/test_roles.py`:
```python
import pytest

from test_competencies import make_competency


@pytest.fixture
def catalogue(client, manager_headers):
    make_competency(client, manager_headers,
                    {"key": "site-induction", "name": "Site induction", "kind": "module"})
    make_competency(client, manager_headers,
                    {"key": "forklift-licence", "name": "Forklift licence", "kind": "ticket"})
    r = client.post("/v1/roles", headers=manager_headers,
                    json={"key": "Forklift-Operator", "name": "Forklift operator"})
    assert r.status_code == 201, r.text
    return r.json()


def test_a_manager_adds_a_role(catalogue):
    assert catalogue["key"] == "forklift-operator"
    assert catalogue["competencies"] == [] and catalogue["people"] == 0


def test_a_role_key_is_used_once(client, manager_headers, catalogue):
    r = client.post("/v1/roles", headers=manager_headers,
                    json={"key": "forklift-operator", "name": "Again"})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "key"


def test_requirements_are_set_in_full(client, manager_headers, catalogue):
    r = client.put("/v1/roles/forklift-operator/requirements", headers=manager_headers,
                   json={"competencies": ["site-induction", "forklift-licence", "site-induction"]})
    assert r.status_code == 200
    assert [c["key"] for c in r.json()["competencies"]] == ["forklift-licence", "site-induction"]
    r = client.put("/v1/roles/forklift-operator/requirements", headers=manager_headers,
                   json={"competencies": ["site-induction"]})
    assert [c["key"] for c in r.json()["competencies"]] == ["site-induction"]


def test_an_unknown_or_deactivated_competency_is_refused(client, manager_headers, catalogue):
    r = client.put("/v1/roles/forklift-operator/requirements", headers=manager_headers,
                   json={"competencies": ["nope"]})
    assert r.status_code == 422 and "no competency nope" in r.json()["errors"][0]["message"]
    client.post("/v1/competencies/forklift-licence/deactivate", headers=manager_headers)
    r = client.put("/v1/roles/forklift-operator/requirements", headers=manager_headers,
                   json={"competencies": ["forklift-licence"]})
    assert r.status_code == 422 and "deactivated" in r.json()["errors"][0]["message"]


def test_rename_and_list(client, manager_headers, supervisor_headers, catalogue):
    r = client.patch("/v1/roles/forklift-operator", headers=manager_headers,
                     json={"name": "Forklift operator (LF)"})
    assert r.json()["name"] == "Forklift operator (LF)"
    r = client.get("/v1/roles", headers=supervisor_headers)
    assert r.status_code == 200 and r.json()["total"] == 1
    assert client.post("/v1/roles", headers=supervisor_headers,
                       json={"key": "x", "name": "X"}).status_code == 403


def test_an_unknown_role_is_404(client, manager_headers):
    assert client.get("/v1/roles/nope", headers=manager_headers).status_code == 404
```

**Step 2: Run it to see it fail**

Run: `cd api && .venv/bin/pytest tests/test_roles.py -v`
Expected: FAIL, the `catalogue` fixture's `assert r.status_code == 201` sees `404` from `POST /v1/roles`.

**Step 3: Minimal implementation**

`api/lms/api/routes/roles.py`:
```python
"""Roles, and the competencies each requires."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select

from lms.api.deps import DB, Principal, require
from lms.api.errors import FieldError, NotFound
from lms.api.schemas import KEY, CompetencyRef, Page, competency_ref, normal_key
from lms.models import Competency, PersonRole, Role

router = APIRouter(tags=["roles"])


class RoleIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    key: str = Field(min_length=1, max_length=64, pattern=KEY)
    name: str = Field(min_length=1, max_length=120)

    @field_validator("key", mode="before")
    @classmethod
    def _key(cls, v):
        return normal_key(v) if isinstance(v, str) else v


class RolePatch(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=120)


class RequirementsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    competencies: list[str] = Field(max_length=500)


class RoleOut(BaseModel):
    id: int
    key: str
    name: str
    competencies: list[CompetencyRef]
    people: int
    created_at: datetime


def role_out(db, r: Role) -> RoleOut:
    people = db.execute(select(func.count()).select_from(PersonRole)
                        .where(PersonRole.role_id == r.id)).scalar_one()
    return RoleOut(id=r.id, key=r.key, name=r.name,
                   competencies=[competency_ref(c) for c in r.competencies], people=people,
                   created_at=r.created_at)


def get_role(db, key: str) -> Role:
    r = db.execute(select(Role).where(Role.key == normal_key(key))).scalar_one_or_none()
    if r is None:
        raise NotFound(f"no role {key}")
    return r


@router.post("/roles", status_code=201, response_model=RoleOut)
def create_role(body: RoleIn, db: DB, who: Principal = require("roles:write")):
    if db.execute(select(Role).where(Role.key == body.key)).scalar_one_or_none():
        raise FieldError("key", f"role {body.key} already exists")
    r = Role(key=body.key, name=body.name)
    db.add(r)
    db.commit()
    return JSONResponse(status_code=201, content=role_out(db, r).model_dump(mode="json"))


@router.get("/roles", response_model=Page[RoleOut])
def list_roles(db: DB, who: Principal = require("roles:read")):
    rows = db.execute(select(Role).order_by(Role.name)).scalars().all()
    return Page(items=[role_out(db, r) for r in rows], total=len(rows))


@router.get("/roles/{key}", response_model=RoleOut)
def read_role(key: str, db: DB, who: Principal = require("roles:read")):
    return role_out(db, get_role(db, key))


@router.patch("/roles/{key}", response_model=RoleOut)
def update_role(key: str, body: RolePatch, db: DB, who: Principal = require("roles:write")):
    r = get_role(db, key)
    r.name = body.name
    db.commit()
    return role_out(db, r)


@router.put("/roles/{key}/requirements", response_model=RoleOut)
def set_requirements(key: str, body: RequirementsIn, db: DB,
                     who: Principal = require("roles:write")):
    """Everything this role requires, in full: what is left out is no longer required."""
    r = get_role(db, key)
    keys = list(dict.fromkeys(normal_key(k) for k in body.competencies))
    found = {c.key: c for c in db.execute(
        select(Competency).where(Competency.key.in_(keys))).scalars()}
    for k in keys:
        if k not in found:
            raise FieldError("competencies", f"no competency {k}")
        if not found[k].active:
            raise FieldError("competencies", f"{k} is deactivated")
    r.competencies = [found[k] for k in keys]
    db.commit()
    db.refresh(r)
    return role_out(db, r)
```

In `api/lms/api/app.py`, make the routes import:
```python
from lms.api.routes import auth, competencies, roles
```
and the router lines:
```python
v1.include_router(auth.router)
v1.include_router(roles.router)
v1.include_router(competencies.router)
```

**Step 4: Run it to see it pass**

Run: `cd api && .venv/bin/pytest tests/test_roles.py tests/test_competencies.py -v`
Expected: `17 passed`.

**Step 5: Commit**

```
git add api/lms/api/routes/roles.py api/lms/api/app.py api/tests/test_roles.py
git commit -m "Add roles and the competencies each requires" \
  -m "Requirements are set in full each time; an unknown or deactivated competency is refused."
```

---

### Task 9: People: added, given roles and a supervisor, a new PIN or password, deactivated

**Files:**
- Create: `api/lms/api/routes/people.py`
- Modify: `api/lms/api/app.py`
- Test: `api/tests/test_people.py`, `api/tests/test_people_access.py`

**Step 1: Write the failing tests**

`api/tests/test_people.py`:
```python
import pytest

from conftest import PIN, bearer, pin_login

KIM = {"code": "ll042", "name": "Kim Lee", "pin": PIN}


def make(client, headers, body):
    r = client.post("/v1/people", headers=headers, json=body)
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
def roles(client, manager_headers):
    for key, name in (("forklift-operator", "Forklift operator"), ("picker", "Picker")):
        client.post("/v1/roles", headers=manager_headers, json={"key": key, "name": name})


def test_a_manager_adds_a_learner_whose_pin_is_never_shown(client, manager_headers):
    out = make(client, manager_headers, KIM)
    assert (out["code"], out["name"], out["permission"]) == ("LL042", "Kim Lee", "learner")
    assert out["has_pin"] is True and out["has_password"] is False and out["active"] is True
    assert "pin" not in out and "pin_hash" not in out
    assert pin_login(client, "LL042")["person"]["code"] == "LL042"


def test_with_roles_a_supervisor_and_an_email(client, manager_headers, supervisor, roles):
    out = make(client, manager_headers, {**KIM, "email": "Kim@Example.com", "supervisor": "sv001",
                                         "roles": ["picker", "forklift-operator"]})
    assert out["email"] == "kim@example.com"
    assert out["supervisor"] == {"code": "SV001", "name": "Sam Vu"}
    assert [r["key"] for r in out["roles"]] == ["forklift-operator", "picker"]


def test_a_code_and_an_email_are_used_once(client, manager_headers, manager):
    make(client, manager_headers, KIM)
    r = client.post("/v1/people", headers=manager_headers, json={**KIM, "code": "LL042"})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "code"
    r = client.post("/v1/people", headers=manager_headers,
                    json={"code": "LL043", "name": "Lee", "email": "MEL@example.com.au"})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "email"


def test_a_pin_is_four_to_eight_digits(client, manager_headers):
    for pin in ("123", "12a4", "123456789"):
        r = client.post("/v1/people", headers=manager_headers, json={**KIM, "pin": pin})
        assert r.status_code == 422


def test_a_supervisor_must_be_able_to_supervise(client, manager_headers, learner):
    r = client.post("/v1/people", headers=manager_headers,
                    json={"code": "LL050", "name": "Ash", "supervisor": "LL042"})
    assert r.status_code == 422
    assert "give them the supervisor permission" in r.json()["errors"][0]["message"]
    r = client.post("/v1/people", headers=manager_headers,
                    json={"code": "LL050", "name": "Ash", "supervisor": "NOBODY"})
    assert r.status_code == 422


def test_an_unknown_role_is_refused(client, manager_headers):
    r = client.post("/v1/people", headers=manager_headers, json={**KIM, "roles": ["nope"]})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "roles"


def test_edit_name_email_and_supervisor_and_clear_them(client, manager_headers, supervisor):
    make(client, manager_headers, {**KIM, "email": "kim@example.com"})
    r = client.patch("/v1/people/ll042", headers=manager_headers,
                     json={"name": "Kim Lee-Smith", "supervisor": "SV001"})
    assert r.json()["name"] == "Kim Lee-Smith" and r.json()["supervisor"]["code"] == "SV001"
    assert r.json()["email"] == "kim@example.com"
    r = client.patch("/v1/people/LL042", headers=manager_headers,
                     json={"supervisor": None, "email": None})
    assert r.json()["supervisor"] is None and r.json()["email"] is None


def test_nobody_supervises_themselves(client, manager_headers, supervisor):
    r = client.patch("/v1/people/SV001", headers=manager_headers, json={"supervisor": "SV001"})
    assert r.status_code == 422 and "own supervisor" in r.json()["errors"][0]["message"]


def test_roles_are_set_in_full(client, manager_headers, roles):
    make(client, manager_headers, {**KIM, "roles": ["picker"]})
    r = client.put("/v1/people/LL042/roles", headers=manager_headers,
                   json={"roles": ["forklift-operator"]})
    assert [x["key"] for x in r.json()["roles"]] == ["forklift-operator"]
    r = client.put("/v1/people/LL042/roles", headers=manager_headers, json={"roles": []})
    assert r.json()["roles"] == []


def test_list_search_and_filter(client, manager_headers, manager, roles):
    make(client, manager_headers, {**KIM, "roles": ["picker"]})
    make(client, manager_headers, {"code": "LL043", "name": "Ash Patel"})
    names = [p["name"] for p in client.get("/v1/people", headers=manager_headers).json()["items"]]
    assert names == ["Ash Patel", "Kim Lee", "Mel Grant"]
    r = client.get("/v1/people?q=ll04", headers=manager_headers).json()
    assert r["total"] == 2
    r = client.get("/v1/people?role=picker", headers=manager_headers).json()
    assert [p["code"] for p in r["items"]] == ["LL042"]


def test_deactivated_not_deleted_and_signed_out(client, manager_headers):
    make(client, manager_headers, KIM)
    token = pin_login(client, "LL042")["token"]
    r = client.post("/v1/people/LL042/deactivate", headers=manager_headers)
    assert r.status_code == 200 and r.json()["active"] is False
    assert client.get("/v1/auth/me", headers=bearer(token)).status_code == 401
    assert client.get("/v1/people?active=false", headers=manager_headers).json()["total"] == 1
    assert client.post("/v1/people/LL042/reactivate",
                       headers=manager_headers).json()["active"] is True
    assert client.delete("/v1/people/LL042", headers=manager_headers).status_code == 405


def test_nobody_deactivates_themselves(client, admin_headers):
    r = client.post("/v1/people/AD001/deactivate", headers=admin_headers)
    assert r.status_code == 409 and r.json()["code"] == "self"


def test_a_supervisor_cannot_see_or_change_the_people_list(client, supervisor_headers):
    assert client.get("/v1/people", headers=supervisor_headers).status_code == 403
    assert client.post("/v1/people", headers=supervisor_headers, json=KIM).status_code == 403


def test_an_unknown_person_is_404(client, manager_headers):
    assert client.get("/v1/people/NOBODY", headers=manager_headers).status_code == 404
```

`api/tests/test_people_access.py`:
```python
"""New PINs and passwords, and who may change whom."""
from conftest import PIN, bearer, login, pin_login


def test_a_new_pin_unlocks_a_locked_one_and_ends_pin_sessions(client, db, manager_headers,
                                                               learner):
    old = pin_login(client, "LL042")["token"]
    for _ in range(5):
        client.post("/v1/auth/pin-login", json={"code": "LL042", "pin": "0000"})
    db.refresh(learner)
    assert learner.pin_locked
    r = client.post("/v1/people/LL042/pin", headers=manager_headers, json={"pin": "97531"})
    assert r.status_code == 200 and r.json()["pin_locked"] is False
    assert client.get("/v1/auth/me", headers=bearer(old)).status_code == 401
    assert client.post("/v1/auth/pin-login", json={"code": "LL042", "pin": PIN}).status_code == 401
    assert pin_login(client, "LL042", "97531")["token"]


def test_a_new_password_lifts_a_lock_and_ends_password_sessions(client, manager_headers,
                                                                 supervisor):
    old = login(client, supervisor.email)["token"]
    pin = pin_login(client, supervisor.code)["token"]
    r = client.post("/v1/people/SV001/password", headers=manager_headers,
                    json={"password": "a brand new password"})
    assert r.status_code == 200 and r.json()["has_password"] is True
    assert client.get("/v1/auth/me", headers=bearer(old)).status_code == 401
    assert client.get("/v1/auth/me", headers=bearer(pin)).status_code == 200
    assert login(client, supervisor.email, "a brand new password")["token"]


def test_a_password_is_at_least_12_characters(client, manager_headers, supervisor):
    r = client.post("/v1/people/SV001/password", headers=manager_headers,
                    json={"password": "too short"})
    assert r.status_code == 422


def test_a_manager_looks_after_learners_and_supervisors_only(client, manager_headers, admin):
    r = client.post("/v1/people", headers=manager_headers,
                    json={"code": "MG002", "name": "Max", "permission": "manager"})
    assert r.status_code == 403 and r.json()["code"] == "admin_only"
    r = client.post("/v1/people", headers=manager_headers,
                    json={"code": "SV002", "name": "Sue", "permission": "supervisor",
                          "email": "sue@example.com", "password": "a long enough password"})
    assert r.status_code == 201
    r = client.patch("/v1/people/SV002", headers=manager_headers, json={"permission": "admin"})
    assert r.status_code == 403
    assert client.patch("/v1/people/AD001", headers=manager_headers,
                        json={"name": "x"}).status_code == 403
    assert client.post("/v1/people/AD001/password", headers=manager_headers,
                       json={"password": "a long enough password"}).status_code == 403
    assert client.post("/v1/people/AD001/deactivate", headers=manager_headers).status_code == 403

def test_an_admin_looks_after_everyone(client, admin_headers, manager):
    r = client.patch("/v1/people/MG001", headers=admin_headers, json={"permission": "admin"})
    assert r.status_code == 200 and r.json()["permission"] == "admin"
    r = client.post("/v1/people", headers=admin_headers,
                    json={"code": "MG002", "name": "Max", "permission": "manager"})
    assert r.status_code == 201
```

**Step 2: Run them to see them fail**

Run: `cd api && .venv/bin/pytest tests/test_people.py tests/test_people_access.py -v`
Expected: FAIL, `404` from `POST /v1/people`, `PATCH /v1/people/...` and the rest.

**Step 3: Minimal implementation**

`api/lms/api/routes/people.py`:
```python
"""People: added, changed, given roles and a supervisor, deactivated. Never
deleted. A manager looks after learners and supervisors; only an admin adds
or changes a manager or an admin."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import or_, select

from lms.api.deps import DB, Principal, require
from lms.api.errors import Conflict, FieldError, Forbidden, NotFound
from lms.api.schemas import (
    CODE, EMAIL, PIN, Page, PersonRef, RoleRef, normal_code, normal_key, person_ref, role_ref,
)
from lms.models import Person, PersonRole, Role
from lms.services import access, sessions

router = APIRouter(tags=["people"])

Permission = Literal["learner", "supervisor", "manager", "admin"]
SUPERVISES = ("supervisor", "manager", "admin")
ABOVE_MANAGERS = ("manager", "admin")


class PersonIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    code: str = Field(min_length=1, max_length=32, pattern=CODE)
    name: str = Field(min_length=1, max_length=120)
    email: str | None = Field(default=None, max_length=254, pattern=EMAIL)
    permission: Permission = "learner"
    supervisor: str | None = Field(default=None, max_length=32)
    roles: list[str] = Field(default_factory=list, max_length=50)
    pin: str | None = Field(default=None, pattern=PIN)
    password: str | None = Field(default=None, min_length=access.MIN_PASSWORD, max_length=200)

    @field_validator("email", mode="before")
    @classmethod
    def _email(cls, v):
        # kept lower case, so an email matches however it is typed
        return v.strip().lower() if isinstance(v, str) else v


class PersonPatch(BaseModel):
    """Leave a field out to keep it; send null to clear an email or a supervisor."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    email: str | None = Field(default=None, max_length=254, pattern=EMAIL)
    permission: Permission | None = None
    supervisor: str | None = Field(default=None, max_length=32)

    @field_validator("email", mode="before")
    @classmethod
    def _email(cls, v):
        # kept lower case, so an email matches however it is typed
        return v.strip().lower() if isinstance(v, str) else v


class RolesIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    roles: list[str] = Field(max_length=50)


class PinIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pin: str = Field(pattern=PIN)


class PasswordIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: str = Field(min_length=access.MIN_PASSWORD, max_length=200)


class PersonOut(BaseModel):
    id: int
    code: str
    name: str
    email: str | None
    permission: str
    supervisor: PersonRef | None
    roles: list[RoleRef]
    active: bool
    has_pin: bool
    pin_locked: bool
    has_password: bool
    created_at: datetime
    last_login_at: datetime | None


def person_out(p: Person) -> PersonOut:
    return PersonOut(id=p.id, code=p.code, name=p.name, email=p.email, permission=p.permission,
                     supervisor=person_ref(p.supervisor), roles=[role_ref(r) for r in p.roles],
                     active=p.active, has_pin=p.pin_hash is not None, pin_locked=p.pin_locked,
                     has_password=p.password_hash is not None, created_at=p.created_at,
                     last_login_at=p.last_login_at)


def get_person(db, code: str) -> Person:
    p = db.execute(select(Person).where(Person.code == normal_code(code))).scalar_one_or_none()
    if p is None:
        raise NotFound(f"no person {code}")
    return p


def may_manage(who: Principal, current: str | None, new: str | None = None) -> None:
    """A manager looks after learners and supervisors; managers and admins
    are an admin's to add and change."""
    if who.person.permission == "admin":
        return
    if current in ABOVE_MANAGERS or new in ABOVE_MANAGERS:
        raise Forbidden("only an admin can add or change a manager or an admin", "admin_only")


def _supervisor(db, code: str, person: Person | None = None) -> Person:
    sup = db.execute(select(Person).where(Person.code == normal_code(code))).scalar_one_or_none()
    if sup is None or not sup.active:
        raise FieldError("supervisor", f"no active person {code}")
    if person is not None and sup.id == person.id:
        raise FieldError("supervisor", "a person can't be their own supervisor")
    if sup.permission not in SUPERVISES:
        raise FieldError("supervisor",
                         f"{sup.code} can't supervise yet: give them the supervisor permission")
    return sup


def _roles(db, keys: list[str]) -> list[Role]:
    keys = list(dict.fromkeys(normal_key(k) for k in keys))
    found = {r.key: r for r in db.execute(select(Role).where(Role.key.in_(keys))).scalars()}
    missing = [k for k in keys if k not in found]
    if missing:
        raise FieldError("roles", f"no role {missing[0]}")
    return [found[k] for k in keys]


def _email_free(db, email: str | None, person: Person | None = None) -> None:
    if email is None:
        return
    other = db.execute(select(Person).where(Person.email == email)).scalar_one_or_none()
    if other is not None and other is not person:
        raise FieldError("email", f"{email} is already {other.code}'s")


@router.post("/people", status_code=201, response_model=PersonOut)
def create_person(body: PersonIn, db: DB, who: Principal = require("people:write")):
    may_manage(who, None, body.permission)
    code = normal_code(body.code)
    if db.execute(select(Person).where(Person.code == code)).scalar_one_or_none():
        raise FieldError("code", f"{code} is already taken")
    _email_free(db, body.email)
    p = Person(code=code, name=body.name, email=body.email, permission=body.permission,
               pin_hash=access.hash_password(body.pin) if body.pin else None,
               password_hash=access.hash_password(body.password) if body.password else None,
               pin_failed_attempts=0, pin_locked=False, password_failed_attempts=0, active=True)
    if body.supervisor:
        p.supervisor = _supervisor(db, body.supervisor)
    p.roles = _roles(db, body.roles)
    db.add(p)
    db.commit()
    db.refresh(p)
    return JSONResponse(status_code=201, content=person_out(p).model_dump(mode="json"))


@router.get("/people", response_model=Page[PersonOut])
def list_people(db: DB, active: bool | None = None,
                q: str | None = Query(default=None, max_length=120), role: str | None = None,
                who: Principal = require("people:read")):
    """By name. `q` matches part of the code, name or email."""
    query = select(Person)
    if active is not None:
        query = query.where(Person.active.is_(active))
    if q:
        like = f"%{q.strip()}%"
        query = query.where(or_(Person.code.ilike(like), Person.name.ilike(like),
                                Person.email.ilike(like)))
    if role:
        query = query.join(PersonRole, PersonRole.person_id == Person.id).join(
            Role, Role.id == PersonRole.role_id).where(Role.key == normal_key(role))
    rows = db.execute(query.order_by(Person.name, Person.code)).scalars().all()
    return Page(items=[person_out(p) for p in rows], total=len(rows))


@router.get("/people/{code}", response_model=PersonOut)
def read_person(code: str, db: DB, who: Principal = require("people:read")):
    return person_out(get_person(db, code))


@router.patch("/people/{code}", response_model=PersonOut)
def update_person(code: str, body: PersonPatch, db: DB, who: Principal = require("people:write")):
    p = get_person(db, code)
    may_manage(who, p.permission, body.permission)
    if body.name is not None:
        p.name = body.name
    if "email" in body.model_fields_set:
        _email_free(db, body.email, p)
        p.email = body.email
    if body.permission is not None:
        p.permission = body.permission
    if "supervisor" in body.model_fields_set:
        p.supervisor = _supervisor(db, body.supervisor, p) if body.supervisor else None
    db.commit()
    return person_out(p)


@router.put("/people/{code}/roles", response_model=PersonOut)
def set_roles(code: str, body: RolesIn, db: DB, who: Principal = require("people:write")):
    """All of this person's roles, in full: what is left out is taken away."""
    p = get_person(db, code)
    may_manage(who, p.permission)
    p.roles = _roles(db, body.roles)
    db.commit()
    db.refresh(p)
    return person_out(p)


@router.post("/people/{code}/pin", response_model=PersonOut)
def reset_pin(code: str, body: PinIn, db: DB, who: Principal = require("people:write")):
    """A new PIN, which also unlocks one locked after five wrong tries. Their
    PIN sessions end."""
    p = get_person(db, code)
    may_manage(who, p.permission)
    p.pin_hash = access.hash_password(body.pin)
    p.pin_failed_attempts = 0
    p.pin_locked = False
    sessions.end_all(db, p, "pin")
    db.commit()
    return person_out(p)


@router.post("/people/{code}/password", response_model=PersonOut)
def set_password(code: str, body: PasswordIn, db: DB, who: Principal = require("people:write")):
    """A new password, which also lifts a lock. Their password sessions end."""
    p = get_person(db, code)
    may_manage(who, p.permission)
    p.password_hash = access.hash_password(body.password)
    p.password_failed_attempts = 0
    p.password_locked_until = None
    sessions.end_all(db, p, "password")
    db.commit()
    return person_out(p)


@router.post("/people/{code}/deactivate", response_model=PersonOut)
def deactivate_person(code: str, db: DB, who: Principal = require("people:write")):
    """They have left. Their records stay; their sessions end."""
    p = get_person(db, code)
    may_manage(who, p.permission)
    if p.id == who.person.id:
        raise Conflict("self", "you can't deactivate yourself")
    p.active = False
    sessions.end_all(db, p)
    db.commit()
    return person_out(p)


@router.post("/people/{code}/reactivate", response_model=PersonOut)
def reactivate_person(code: str, db: DB, who: Principal = require("people:write")):
    p = get_person(db, code)
    may_manage(who, p.permission)
    p.active = True
    db.commit()
    return person_out(p)
```

In `api/lms/api/app.py`, make the routes import:
```python
from lms.api.routes import auth, competencies, people, roles
```
and add `v1.include_router(people.router)` straight after `v1.include_router(auth.router)`.

**Step 4: Run them to see them pass**

Run: `cd api && .venv/bin/pytest tests/test_people.py tests/test_people_access.py -v`
Expected: `19 passed`.

**Step 5: Commit**

```
git add api/lms/api/routes/people.py api/lms/api/app.py api/tests/test_people.py \
  api/tests/test_people_access.py
git commit -m "Add people with roles, a supervisor, a PIN or a password, deactivated not deleted" \
  -m "A new PIN unlocks a locked one and ends the old PIN's sessions; likewise a new password. A manager looks after learners and supervisors; managers and admins are an admin's."
```

---

### Task 10: Extras and waivers, with a note

**Files:**
- Create: `api/lms/services/standing.py` (the newest rows; Task 12 adds the rest)
- Create: `api/lms/api/routes/overrides.py`
- Modify: `api/lms/api/app.py`
- Create: `api/tests/yard.py` (a small training yard, made through the API, for this task and the next two)
- Test: `api/tests/test_overrides.py`

**Step 1: Write the failing test**

`api/tests/yard.py`:
```python
"""A small training yard for the record and matrix tests, made through the API."""

COMPETENCIES = [
    {"key": "site-induction", "name": "Site induction", "kind": "module", "refresher_months": 24},
    {"key": "forklift-licence", "name": "Forklift licence", "kind": "ticket"},
    {"key": "first-aid", "name": "First aid", "kind": "ticket", "refresher_months": 36},
    {"key": "whs-policy", "name": "WHS policy", "kind": "policy"},
]
ROLES = {
    "forklift-operator": ("Forklift operator", ["site-induction", "forklift-licence"]),
    "picker": ("Picker", ["site-induction"]),
}


def build(client, headers):
    for c in COMPETENCIES:
        assert client.post("/v1/competencies", headers=headers, json=c).status_code == 201
    for key, (name, needs) in ROLES.items():
        assert client.post("/v1/roles", headers=headers, json={"key": key, "name": name}).status_code == 201
        r = client.put(f"/v1/roles/{key}/requirements", headers=headers,
                       json={"competencies": needs})
        assert r.status_code == 200


def give_roles(client, headers, code: str, *roles: str):
    r = client.put(f"/v1/people/{code}/roles", headers=headers, json={"roles": list(roles)})
    assert r.status_code == 200, r.text


def grant(client, headers, code: str, competency: str, granted_on: str, **more):
    r = client.post(f"/v1/people/{code}/records", headers=headers,
                    json={"competency": competency, "granted_on": granted_on, **more})
    assert r.status_code == 201, r.text
    return r.json()
```

`api/tests/test_overrides.py`:
```python
import pytest

import yard


@pytest.fixture
def kim(client, manager_headers, learner):
    yard.build(client, manager_headers)
    yard.give_roles(client, manager_headers, "LL042", "picker")
    return learner


def override(client, headers, kind, competency="first-aid", note="covers the night shift"):
    return client.post("/v1/people/LL042/overrides", headers=headers,
                       json={"competency": competency, "kind": kind, "note": note})


def test_an_extra_with_a_note(client, manager_headers, kim):
    r = override(client, manager_headers, "extra")
    assert r.status_code == 201
    assert r.json()["kind"] == "extra" and r.json()["recorded_by"]["code"] == "MG001"
    now = client.get("/v1/people/LL042/overrides", headers=manager_headers).json()
    assert [(o["competency"]["key"], o["kind"]) for o in now] == [("first-aid", "extra")]


def test_a_note_is_required(client, manager_headers, kim):
    assert override(client, manager_headers, "waive", note="   ").status_code == 422


def test_the_latest_counts_and_a_clear_puts_it_back(client, manager_headers, kim):
    override(client, manager_headers, "extra")
    override(client, manager_headers, "waive", note="first aid officer on site already")
    now = client.get("/v1/people/LL042/overrides", headers=manager_headers).json()
    assert [o["kind"] for o in now] == ["waive"]
    assert override(client, manager_headers, "clear", note="back to the role").status_code == 201
    assert client.get("/v1/people/LL042/overrides", headers=manager_headers).json() == []


def test_nothing_to_clear_is_409(client, manager_headers, kim):
    r = override(client, manager_headers, "clear")
    assert r.status_code == 409 and r.json()["code"] == "nothing_to_clear"


def test_a_supervisor_cannot_waive(client, supervisor_headers, kim):
    assert override(client, supervisor_headers, "waive").status_code == 403


def test_an_unknown_competency_is_404(client, manager_headers, kim):
    assert override(client, manager_headers, "extra", competency="nope").status_code == 404
```

**Step 2: Run it to see it fail**

Run: `cd api && .venv/bin/pytest tests/test_overrides.py -v`
Expected: FAIL, `404` from `/v1/people/LL042/overrides` (the yard is built; the override routes are not there).

**Step 3: Minimal implementation**

`api/lms/services/standing.py` (Task 12 replaces it with the whole file):
```python
"""Where a group of people stand. For now, the newest rows."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session as Db


def latest_rows(db: Db, model, person_ids: list[int]):
    """The newest row per person and competency: the one that counts."""
    newest = (select(func.max(model.id)).where(model.person_id.in_(person_ids))
              .group_by(model.person_id, model.competency_id))
    return db.execute(select(model).where(model.id.in_(newest))).scalars().all()
```

`api/lms/api/routes/overrides.py`:
```python
"""Extras and waivers: one person asked for a competency their roles don't
require, or let off one they do, always with a note. Append-only; the latest
for a person and competency counts, and a clear puts it back to their roles."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from lms.api.deps import DB, Principal, require
from lms.api.errors import Conflict
from lms.api.routes.competencies import get_competency
from lms.api.routes.people import get_person, may_manage
from lms.api.schemas import CompetencyRef, PersonRef, competency_ref, person_ref
from lms.models import PersonOverride
from lms.services.standing import latest_rows

router = APIRouter(tags=["overrides"])


class OverrideIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    competency: str = Field(max_length=64)
    kind: Literal["extra", "waive", "clear"]
    note: str = Field(min_length=1, max_length=500)


class OverrideOut(BaseModel):
    id: int
    competency: CompetencyRef
    kind: str
    note: str
    recorded_by: PersonRef
    created_at: datetime


def override_out(o: PersonOverride) -> OverrideOut:
    return OverrideOut(id=o.id, competency=competency_ref(o.competency), kind=o.kind, note=o.note,
                       recorded_by=person_ref(o.recorded_by), created_at=o.created_at)


def latest_overrides(db, person_id: int) -> list[PersonOverride]:
    return latest_rows(db, PersonOverride, [person_id])


@router.get("/people/{code}/overrides", response_model=list[OverrideOut])
def current_overrides(code: str, db: DB, who: Principal = require("people:read")):
    """The extras and waivers in force now, by competency name."""
    p = get_person(db, code)
    rows = [o for o in latest_overrides(db, p.id) if o.kind != "clear"]
    return [override_out(o) for o in sorted(rows, key=lambda o: o.competency.name)]


@router.post("/people/{code}/overrides", status_code=201, response_model=OverrideOut)
def add_override(code: str, body: OverrideIn, db: DB, who: Principal = require("people:write")):
    p = get_person(db, code)
    may_manage(who, p.permission)
    c = get_competency(db, body.competency)
    if body.kind == "clear":
        now = next((o for o in latest_overrides(db, p.id) if o.competency_id == c.id), None)
        if now is None or now.kind == "clear":
            raise Conflict("nothing_to_clear", f"{p.code} has no extra or waiver for {c.key}")
    o = PersonOverride(person_id=p.id, competency=c, kind=body.kind, note=body.note,
                       recorded_by=who.person)
    db.add(o)
    db.commit()
    return JSONResponse(status_code=201, content=override_out(o).model_dump(mode="json"))
```

In `api/lms/api/app.py`, make the routes import:
```python
from lms.api.routes import auth, competencies, overrides, people, roles
```
and add `v1.include_router(overrides.router)` after `v1.include_router(competencies.router)`.

**Step 4: Run it to see it pass**

Run: `cd api && .venv/bin/pytest tests/test_overrides.py -v`
Expected: `6 passed`.

**Step 5: Commit**

```
git add api/lms/services/standing.py api/lms/api/routes/overrides.py api/lms/api/app.py \
  api/tests/yard.py api/tests/test_overrides.py
git commit -m "Ask one person for an extra competency, or waive one, with a note" \
  -m "Append-only like the record: the latest override for a competency counts, and a clear puts them back to what their roles say."
```

---

### Task 11: Completions recorded by hand, revoked with a note, never your own

**Files:**
- Create: `api/lms/api/routes/records.py`
- Modify: `api/lms/api/app.py`
- Test: `api/tests/test_records.py`

**Step 1: Write the failing test**

`api/tests/test_records.py`:
```python
import pytest

import yard
from conftest import bearer, login, make_person


@pytest.fixture
def kim(client, manager_headers, learner):
    yard.build(client, manager_headers)
    yard.give_roles(client, manager_headers, "LL042", "forklift-operator")
    return learner


def test_a_manager_records_a_completion_by_hand(client, manager_headers, kim):
    out = yard.grant(client, manager_headers, "LL042", "forklift-licence", "2026-03-01",
                     expires_on="2031-03-01", note="LF 0012345, sighted")
    assert out["kind"] == "granted" and out["competency"]["key"] == "forklift-licence"
    assert (out["granted_on"], out["expires_on"]) == ("2026-03-01", "2031-03-01")
    assert out["recorded_by"] == {"code": "MG001", "name": "Mel Grant"}


def test_nobody_records_their_own(client, db, manager_headers, manager, kim):
    r = client.post("/v1/people/MG001/records", headers=manager_headers,
                    json={"competency": "site-induction", "granted_on": "2026-10-01"})
    assert r.status_code == 403 and r.json()["code"] == "own_record"


def test_not_even_an_admin(client, admin_headers, kim):
    r = client.post("/v1/people/AD001/records", headers=admin_headers,
                    json={"competency": "site-induction", "granted_on": "2026-10-01"})
    assert r.status_code == 403


def test_dates_must_make_sense(client, manager_headers, kim):
    def post(**body):
        return client.post("/v1/people/LL042/records", headers=manager_headers,
                           json={"competency": "forklift-licence", **body})

    r = post(granted_on="2026-10-13")
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "granted_on"
    r = post(granted_on="2026-03-01", expires_on="2026-03-01")
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "expires_on"
    assert post(granted_on="2026-10-12").status_code == 201


def test_not_for_a_deactivated_competency_or_person(client, manager_headers, kim):
    client.post("/v1/competencies/whs-policy/deactivate", headers=manager_headers)
    r = client.post("/v1/people/LL042/records", headers=manager_headers,
                    json={"competency": "whs-policy", "granted_on": "2026-10-01"})
    assert r.status_code == 422
    client.post("/v1/people/LL042/deactivate", headers=manager_headers)
    r = client.post("/v1/people/LL042/records", headers=manager_headers,
                    json={"competency": "site-induction", "granted_on": "2026-10-01"})
    assert r.status_code == 409 and r.json()["code"] == "inactive"


def test_revoke_needs_a_note_and_a_grant_to_cancel(client, manager_headers, kim):
    def revoke(note="wrong person ticked"):
        return client.post("/v1/people/LL042/records/revoke", headers=manager_headers,
                           json={"competency": "site-induction", "note": note})

    assert revoke().status_code == 409 and revoke().json()["code"] == "nothing_to_revoke"
    yard.grant(client, manager_headers, "LL042", "site-induction", "2026-09-01")
    assert revoke(note="").status_code == 422
    out = revoke().json()
    assert out["kind"] == "revoked" and out["granted_on"] is None
    assert revoke().status_code == 409


def test_history_is_newest_first(client, manager_headers, kim):
    yard.grant(client, manager_headers, "LL042", "site-induction", "2025-01-10")
    yard.grant(client, manager_headers, "LL042", "forklift-licence", "2026-03-01")
    yard.grant(client, manager_headers, "LL042", "site-induction", "2024-11-02",
               note="date was wrong: induction was in 2024")
    r = client.get("/v1/people/LL042/records?competency=site-induction", headers=manager_headers)
    assert [x["granted_on"] for x in r.json()] == ["2024-11-02", "2025-01-10"]
    assert len(client.get("/v1/people/LL042/records", headers=manager_headers).json()) == 3


def test_who_sees_whose_history(client, db, manager_headers, supervisor_headers, learner_headers,
                                kim):
    yard.grant(client, manager_headers, "LL042", "site-induction", "2026-09-01")
    other = make_person(db, "LL099", "Pat Other", pin="1357")
    path = "/v1/people/LL042/records"
    assert client.get(path, headers=learner_headers).status_code == 200      # their own
    assert client.get(path, headers=supervisor_headers).status_code == 200   # their team
    pat = client.post("/v1/auth/pin-login", json={"code": other.code, "pin": "1357"}).json()
    assert client.get(path, headers=bearer(pat["token"])).status_code == 404
    # a supervisor sees their team only
    assert client.get("/v1/people/LL099/records", headers=supervisor_headers).status_code == 404


def test_a_supervisor_or_learner_cannot_record(client, supervisor_headers, learner_headers, kim):
    for headers in (supervisor_headers, learner_headers):
        r = client.post("/v1/people/LL042/records", headers=headers,
                        json={"competency": "site-induction", "granted_on": "2026-10-01"})
        assert r.status_code == 403
```

**Step 2: Run it to see it fail**

Run: `cd api && .venv/bin/pytest tests/test_records.py -v`
Expected: FAIL, `404` from `POST /v1/people/LL042/records` and the rest.

**Step 3: Minimal implementation**

`api/lms/api/routes/records.py`:
```python
"""The training record, entered by hand from the desktop in step 1: a
completion granted, or revoked with a note. Append-only (rule 1); the
latest row counts, so a wrong date is put right by recording it again.
Nobody records their own (rule 3)."""
from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from lms.api.deps import DB, Principal, require
from lms.api.errors import Conflict, FieldError, Forbidden, NotFound
from lms.api.routes.competencies import get_competency
from lms.api.routes.people import get_person
from lms.api.schemas import CompetencyRef, PersonRef, competency_ref, normal_key, person_ref
from lms.models import Competency, CompetencyRecord
from lms.services import clock

router = APIRouter(tags=["records"])


class GrantIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    competency: str = Field(max_length=64)
    granted_on: date
    # a ticket's card date; otherwise leave it out and the refresher decides
    expires_on: date | None = None
    note: str | None = Field(default=None, max_length=500)


class RevokeIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    competency: str = Field(max_length=64)
    note: str = Field(min_length=1, max_length=500)


class RecordOut(BaseModel):
    id: int
    competency: CompetencyRef
    kind: str
    granted_on: date | None
    expires_on: date | None
    note: str | None
    recorded_by: PersonRef
    created_at: datetime


def record_out(r: CompetencyRecord) -> RecordOut:
    return RecordOut(id=r.id, competency=competency_ref(r.competency), kind=r.kind,
                     granted_on=r.granted_on, expires_on=r.expires_on, note=r.note,
                     recorded_by=person_ref(r.recorded_by), created_at=r.created_at)


def _latest(db, person_id: int, competency_id: int) -> CompetencyRecord | None:
    return db.execute(
        select(CompetencyRecord)
        .where(CompetencyRecord.person_id == person_id,
               CompetencyRecord.competency_id == competency_id)
        .order_by(CompetencyRecord.id.desc()).limit(1)
    ).scalar_one_or_none()


def _created(r: CompetencyRecord) -> JSONResponse:
    return JSONResponse(status_code=201, content=record_out(r).model_dump(mode="json"))


@router.get("/people/{code}/records", response_model=list[RecordOut])
def list_records(code: str, db: DB, competency: str | None = None,
                 who: Principal = require("training:read")):
    """Newest first: the first is the one that counts. Your own, your team's,
    or (a manager or admin) anyone's."""
    p = get_person(db, code)
    if not who.sees(p):
        raise NotFound(f"no person {code}")
    q = select(CompetencyRecord).where(CompetencyRecord.person_id == p.id)
    if competency:
        q = q.join(Competency).where(Competency.key == normal_key(competency))
    rows = db.execute(q.order_by(CompetencyRecord.id.desc())).scalars().all()
    return [record_out(r) for r in rows]


@router.post("/people/{code}/records", status_code=201, response_model=RecordOut)
def grant(code: str, body: GrantIn, db: DB, who: Principal = require("records:write")):
    p = get_person(db, code)
    if p.id == who.person.id:
        raise Forbidden("nobody records their own competency: ask another manager",
                        "own_record")
    if not p.active:
        raise Conflict("inactive", f"{p.code} is deactivated")
    c = get_competency(db, body.competency)
    if not c.active:
        raise FieldError("competency", f"{c.key} is deactivated")
    if body.granted_on > clock.today():
        raise FieldError("granted_on", "can't be in the future")
    if body.expires_on is not None and body.expires_on <= body.granted_on:
        raise FieldError("expires_on", "must be after the date it was granted")
    r = CompetencyRecord(person_id=p.id, competency=c, kind="granted",
                         granted_on=body.granted_on, expires_on=body.expires_on,
                         note=body.note or None, recorded_by=who.person)
    db.add(r)
    db.commit()
    return _created(r)


@router.post("/people/{code}/records/revoke", status_code=201, response_model=RecordOut)
def revoke(code: str, body: RevokeIn, db: DB, who: Principal = require("records:write")):
    """Cancels the grant that counts now, with a note saying why."""
    p = get_person(db, code)
    c = get_competency(db, body.competency)
    latest = _latest(db, p.id, c.id)
    if latest is None or latest.kind != "granted":
        raise Conflict("nothing_to_revoke", f"{p.code} has no grant of {c.key} to revoke")
    r = CompetencyRecord(person_id=p.id, competency=c, kind="revoked", note=body.note,
                         recorded_by=who.person)
    db.add(r)
    db.commit()
    return _created(r)
```

In `api/lms/api/app.py`, make the routes import:
```python
from lms.api.routes import auth, competencies, overrides, people, records, roles
```
and add `v1.include_router(records.router)` after `v1.include_router(overrides.router)`.

**Step 4: Run it to see it pass**

Run: `cd api && .venv/bin/pytest tests/test_records.py -v`
Expected: `9 passed`.

**Step 5: Commit**

```
git add api/lms/api/routes/records.py api/lms/api/app.py api/tests/test_records.py
git commit -m "Record a completion by hand, or revoke one with a note, never your own" \
  -m "Rule 3 holds for admins too. The latest row counts, so a wrong date is put right by recording it again."
```

---

### Task 12: The matrix, its CSV, and a person's training

**Files:**
- Modify: `api/lms/services/standing.py` (replace)
- Create: `api/lms/api/routes/matrix.py`
- Modify: `api/lms/api/app.py` (in full below)
- Test: `api/tests/test_matrix.py`, `api/tests/test_matrix_csv.py`

**Step 1: Write the failing tests**

`api/tests/test_matrix.py`:
```python
import pytest

import yard
from conftest import bearer, make_person, pin_login


@pytest.fixture
def team(client, db, manager_headers, supervisor, learner):
    """Kim (forklift operator) and Ash (picker) are on Sam's team; Pat
    (picker) is not on anyone's."""
    yard.build(client, manager_headers)
    make_person(db, "LL043", "Ash Patel", supervisor=supervisor)
    make_person(db, "LL099", "Pat Other")
    yard.give_roles(client, manager_headers, "LL042", "forklift-operator")
    yard.give_roles(client, manager_headers, "LL043", "picker")
    yard.give_roles(client, manager_headers, "LL099", "picker")
    return learner


def cells(matrix: dict) -> dict:
    """{code: {key: status}}"""
    return {p["code"]: {k: c["status"] for k, c in p["cells"].items()} for p in matrix["people"]}


def test_people_down_the_side_and_what_they_need_across_the_top(client, manager_headers, team):
    yard.grant(client, manager_headers, "LL042", "site-induction", "2025-06-01")
    m = client.get("/v1/matrix", headers=manager_headers).json()
    assert m["today"] == "2026-10-12"
    assert [c["key"] for c in m["competencies"]] == ["forklift-licence", "site-induction"]
    # every active person, by name: someone asked for nothing yet shows too
    assert [p["code"] for p in m["people"]] == ["LL043", "LL042", "MG001", "LL099", "SV001"]
    grey = {"forklift-licence": "not_required", "site-induction": "not_required"}
    assert cells(m) == {
        "LL042": {"forklift-licence": "missing", "site-induction": "current"},
        "LL043": {"forklift-licence": "not_required", "site-induction": "missing"},
        "LL099": {"forklift-licence": "not_required", "site-induction": "missing"},
        "MG001": grey,
        "SV001": grey,
    }
    kim = next(p for p in m["people"] if p["code"] == "LL042")
    assert kim["cells"]["site-induction"] == {"status": "current", "granted_on": "2025-06-01",
                                              "expires_on": "2027-06-01"}
    assert kim["supervisor"] == {"code": "SV001", "name": "Sam Vu"}
    assert kim["roles"] == [{"key": "forklift-operator", "name": "Forklift operator"}]


def test_the_matrix_goes_green_amber_and_red_with_the_dates(client, manager_headers, team, today):
    yard.grant(client, manager_headers, "LL042", "forklift-licence", "2025-01-01",
               expires_on="2026-11-01")
    yard.grant(client, manager_headers, "LL042", "site-induction", "2025-06-01")

    def kim():
        return cells(client.get("/v1/matrix", headers=manager_headers).json())["LL042"]

    assert kim() == {"forklift-licence": "expiring", "site-induction": "current"}
    today.set(today.value.replace(year=2027, month=5, day=15))
    assert kim() == {"forklift-licence": "lapsed", "site-induction": "expiring"}


def test_a_waiver_and_an_extra_show_in_the_cells(client, manager_headers, team):
    client.post("/v1/people/LL043/overrides", headers=manager_headers,
                json={"competency": "site-induction", "kind": "waive", "note": "visiting auditor"})
    client.post("/v1/people/LL043/overrides", headers=manager_headers,
                json={"competency": "first-aid", "kind": "extra", "note": "first aid officer"})
    m = client.get("/v1/matrix", headers=manager_headers).json()
    assert [c["key"] for c in m["competencies"]] == ["first-aid", "forklift-licence",
                                                     "site-induction"]
    assert cells(m)["LL043"] == {"first-aid": "missing", "forklift-licence": "not_required",
                                 "site-induction": "waived"}


def test_a_revoke_cancels_the_grant(client, manager_headers, team):
    yard.grant(client, manager_headers, "LL042", "site-induction", "2025-06-01")
    client.post("/v1/people/LL042/records/revoke", headers=manager_headers,
                json={"competency": "site-induction", "note": "ticked for the wrong person"})
    m = client.get("/v1/matrix", headers=manager_headers).json()
    assert cells(m)["LL042"]["site-induction"] == "missing"


def test_a_supervisor_sees_their_own_team(client, supervisor_headers, team):
    m = client.get("/v1/matrix", headers=supervisor_headers).json()
    assert [p["code"] for p in m["people"]] == ["LL043", "LL042"]


def test_filter_by_role_supervisor_and_status(client, manager_headers, team):
    yard.grant(client, manager_headers, "LL042", "site-induction", "2025-06-01")
    yard.grant(client, manager_headers, "LL042", "forklift-licence", "2025-06-01")

    def codes(query: str):
        r = client.get(f"/v1/matrix?{query}", headers=manager_headers)
        assert r.status_code == 200, r.text
        return [p["code"] for p in r.json()["people"]]

    assert codes("role=picker") == ["LL043", "LL099"]
    assert codes("supervisor=sv001") == ["LL043", "LL042"]
    assert codes("status=missing") == ["LL043", "LL099"]
    assert codes("status=current") == ["LL042"]
    assert codes("status=lapsed,expiring") == []
    r = client.get("/v1/matrix?role=picker", headers=manager_headers).json()
    assert [c["key"] for c in r["competencies"]] == ["site-induction"]


def test_a_bad_filter_is_422(client, manager_headers, team):
    assert client.get("/v1/matrix?status=green", headers=manager_headers).status_code == 422
    assert client.get("/v1/matrix?supervisor=NOBODY", headers=manager_headers).status_code == 422


def test_deactivated_people_and_competencies_drop_out(client, manager_headers, team):
    client.post("/v1/people/LL099/deactivate", headers=manager_headers)
    client.post("/v1/competencies/forklift-licence/deactivate", headers=manager_headers)
    m = client.get("/v1/matrix", headers=manager_headers).json()
    assert [p["code"] for p in m["people"]] == ["LL043", "LL042", "MG001", "SV001"]
    assert [c["key"] for c in m["competencies"]] == ["site-induction"]


def test_a_learner_has_no_matrix(client, learner_headers, team):
    assert client.get("/v1/matrix", headers=learner_headers).status_code == 403


def test_a_supervisor_signed_in_by_pin_has_no_matrix(client, supervisor, team):
    token = pin_login(client, supervisor.code)["token"]
    assert client.get("/v1/matrix", headers=bearer(token)).status_code == 403


def test_my_training_lists_what_i_need_and_not_what_is_waived(client, manager_headers,
                                                              learner_headers, team):
    yard.grant(client, manager_headers, "LL042", "forklift-licence", "2025-01-01",
               expires_on="2026-11-01")
    client.post("/v1/people/LL042/overrides", headers=manager_headers,
                json={"competency": "whs-policy", "kind": "extra", "note": "covers reception"})
    client.post("/v1/people/LL042/overrides", headers=manager_headers,
                json={"competency": "site-induction", "kind": "waive", "note": "inducted at HQ"})
    r = client.get("/v1/people/ll042/training", headers=learner_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["person"] == {"code": "LL042", "name": "Kim Lee"} and body["today"] == "2026-10-12"
    assert [(i["key"], i["status"], i["expires_on"]) for i in body["items"]] == [
        ("forklift-licence", "expiring", "2026-11-01"),
        ("whs-policy", "missing", None),
    ]


def test_whose_training_who_may_read(client, db, manager_headers, supervisor_headers,
                                     learner_headers, team):
    assert client.get("/v1/people/LL099/training", headers=learner_headers).status_code == 404
    assert client.get("/v1/people/LL043/training", headers=supervisor_headers).status_code == 200
    assert client.get("/v1/people/LL099/training", headers=supervisor_headers).status_code == 404
    assert client.get("/v1/people/LL099/training", headers=manager_headers).status_code == 200
```

`api/tests/test_matrix_csv.py`:
```python
import csv
import io

import yard
from conftest import make_person


def test_the_matrix_as_a_spreadsheet(client, db, manager_headers, learner):
    yard.build(client, manager_headers)
    yard.give_roles(client, manager_headers, "LL042", "forklift-operator")
    yard.grant(client, manager_headers, "LL042", "forklift-licence", "2025-01-01",
               expires_on="2026-11-01")
    r = client.get("/v1/matrix.csv?role=forklift-operator", headers=manager_headers)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert 'filename="matrix-2026-10-12.csv"' in r.headers["content-disposition"]
    rows = list(csv.reader(io.StringIO(r.text)))
    assert rows == [
        ["code", "name", "roles", "supervisor", "Forklift licence", "Forklift licence expires",
         "Site induction", "Site induction expires"],
        ["LL042", "Kim Lee", "Forklift operator", "Sam Vu", "expiring", "2026-11-01",
         "missing", ""],
    ]


def test_a_cell_that_looks_like_a_formula_is_not_one(client, db, manager_headers):
    yard.build(client, manager_headers)
    make_person(db, "LL077", "=HYPERLINK(\"http://example.com\")")
    yard.give_roles(client, manager_headers, "LL077", "picker")
    rows = list(csv.reader(io.StringIO(
        client.get("/v1/matrix.csv", headers=manager_headers).text)))
    assert rows[1][1].startswith("'=")


def test_the_spreadsheet_needs_the_matrix_scope(client, learner_headers):
    assert client.get("/v1/matrix.csv", headers=learner_headers).status_code == 403
```

**Step 2: Run them to see them fail**

Run: `cd api && .venv/bin/pytest tests/test_matrix.py tests/test_matrix_csv.py -v`
Expected: FAIL, `404` from `GET /v1/matrix`, `/v1/matrix.csv` and `/v1/people/.../training` (so `r.json()["today"]` and the like raise `KeyError`).

**Step 3: Minimal implementation**

`api/lms/services/standing.py` (replace):
```python
"""Where a group of people stand: what each is asked for and their status
for it, loaded in a handful of queries for the matrix and the to-do list."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session as Db

from lms.models import Competency, CompetencyRecord, PersonOverride, PersonRole, RoleRequirement
from lms.services.status import Latest, Status, work_out


@dataclass
class Standing:
    today: date
    competencies: dict[int, Competency]  # active ones only
    by_role: set[tuple[int, int]]
    overrides: dict[tuple[int, int], str]
    records: dict[tuple[int, int], CompetencyRecord]

    def asked_for(self, person_id: int) -> set[int]:
        """Competencies their roles or an extra ask for, waived or not."""
        keys = {c for (p, c) in self.by_role if p == person_id}
        keys |= {c for (p, c), kind in self.overrides.items() if p == person_id and kind == "extra"}
        return {c for c in keys if c in self.competencies}

    def status(self, person_id: int, competency_id: int) -> Status:
        record = self.records.get((person_id, competency_id))
        latest = None if record is None else Latest(record.kind, record.granted_on,
                                                    record.expires_on)
        override = self.overrides.get((person_id, competency_id))
        return work_out(
            by_role=(person_id, competency_id) in self.by_role,
            override=None if override == "clear" else override,
            latest=latest,
            refresher_months=self.competencies[competency_id].refresher_months,
            today=self.today,
        )


def latest_rows(db: Db, model, person_ids: list[int]):
    """The newest row per person and competency: the one that counts."""
    newest = (select(func.max(model.id)).where(model.person_id.in_(person_ids))
              .group_by(model.person_id, model.competency_id))
    return db.execute(select(model).where(model.id.in_(newest))).scalars().all()


def load(db: Db, person_ids: list[int], today: date) -> Standing:
    if not person_ids:
        return Standing(today, {}, set(), {}, {})
    competencies = {c.id: c for c in db.execute(
        select(Competency).where(Competency.active.is_(True))).scalars()}
    by_role = {(p, c) for p, c in db.execute(
        select(PersonRole.person_id, RoleRequirement.competency_id)
        .join(RoleRequirement, RoleRequirement.role_id == PersonRole.role_id)
        .where(PersonRole.person_id.in_(person_ids)))}
    overrides = {(o.person_id, o.competency_id): o.kind
                 for o in latest_rows(db, PersonOverride, person_ids)}
    records = {(r.person_id, r.competency_id): r for r in latest_rows(db, CompetencyRecord, person_ids)}
    return Standing(today, competencies, by_role, overrides, records)
```

`api/lms/api/routes/matrix.py`:
```python
"""The matrix (people down the side, what they are asked for across the
top, a status in each cell) and each person's own to-do list. Worked out
on every request from the records and today's date (rule 2)."""
from __future__ import annotations

import csv
import io
from datetime import date

from fastapi import APIRouter, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from lms.api.deps import DB, Principal, require
from lms.api.errors import FieldError, NotFound
from lms.api.routes.people import get_person
from lms.api.schemas import (
    CompetencyRef, PersonRef, RoleRef, competency_ref, normal_code, normal_key, person_ref,
    role_ref,
)
from lms.models import Person, PersonRole, Role
from lms.services import clock, standing
from lms.services.status import STATUSES

router = APIRouter(tags=["matrix"])

# what My training shows: what they are asked for and not let off
TO_DO = ("lapsed", "missing", "expiring", "current")


class CellOut(BaseModel):
    status: str
    granted_on: date | None
    expires_on: date | None


class MatrixRow(BaseModel):
    code: str
    name: str
    roles: list[RoleRef]
    supervisor: PersonRef | None
    # by competency key: every column has a cell
    cells: dict[str, CellOut]


class MatrixOut(BaseModel):
    today: date
    competencies: list[CompetencyRef]
    people: list[MatrixRow]


class TrainingItem(BaseModel):
    key: str
    name: str
    kind: str
    status: str
    granted_on: date | None
    expires_on: date | None


class TrainingOut(BaseModel):
    person: PersonRef
    today: date
    items: list[TrainingItem]


def _statuses(status: str | None) -> set[str] | None:
    if not status:
        return None
    wanted = {s.strip() for s in status.split(",") if s.strip()}
    unknown = wanted - set(STATUSES)
    if unknown:
        raise FieldError("status", f"unknown status {sorted(unknown)[0]}; one of "
                                   f"{', '.join(STATUSES)}")
    return wanted


def build(db, who: Principal, role: str | None, supervisor: str | None,
          status: str | None) -> MatrixOut:
    wanted = _statuses(status)
    q = (select(Person).where(Person.active.is_(True))
         .options(selectinload(Person.roles), selectinload(Person.supervisor)))
    if not who.sees_everyone:
        # a supervisor sees their own team
        q = q.where(Person.supervisor_id == who.person.id)
    if role:
        q = q.join(PersonRole, PersonRole.person_id == Person.id).join(
            Role, Role.id == PersonRole.role_id).where(Role.key == normal_key(role))
    if supervisor:
        boss = db.execute(select(Person.id).where(Person.code == normal_code(supervisor))).scalar()
        if boss is None:
            raise FieldError("supervisor", f"no person {supervisor}")
        q = q.where(Person.supervisor_id == boss)
    people = db.execute(q.order_by(Person.name, Person.code)).scalars().all()

    st = standing.load(db, [p.id for p in people], clock.today())
    rows: list[tuple[Person, set[int]]] = []
    for p in people:
        asked = st.asked_for(p.id)
        if wanted is not None and not any(st.status(p.id, c).status in wanted for c in asked):
            continue
        rows.append((p, asked))
    columns = sorted({c for _, asked in rows for c in asked},
                     key=lambda c: (st.competencies[c].name, st.competencies[c].key))
    return MatrixOut(
        today=st.today,
        competencies=[competency_ref(st.competencies[c]) for c in columns],
        people=[MatrixRow(
            code=p.code, name=p.name, roles=[role_ref(r) for r in p.roles],
            supervisor=person_ref(p.supervisor),
            cells={st.competencies[c].key: CellOut(**_cell(st.status(p.id, c))) for c in columns},
        ) for p, _ in rows],
    )


def _cell(s) -> dict:
    return {"status": s.status, "granted_on": s.granted_on, "expires_on": s.expires_on}


@router.get("/matrix", response_model=MatrixOut)
def matrix(db: DB, role: str | None = None, supervisor: str | None = None,
           status: str | None = None, who: Principal = require("matrix:read")):
    """Active people by name; columns are what any of them is asked for, by
    name. Filters: `role` (key), `supervisor` (code), `status` (comma
    separated: people with at least one cell in it)."""
    return build(db, who, role, supervisor, status)


def _safe(value: str) -> str:
    # a spreadsheet would run a cell that starts like a formula
    return "'" + value if value[:1] in ("=", "+", "-", "@") else value


@router.get("/matrix.csv")
def matrix_csv(db: DB, role: str | None = None, supervisor: str | None = None,
               status: str | None = None, who: Principal = require("matrix:read")):
    """The same matrix as a spreadsheet: a status and an expiry date per competency."""
    m = build(db, who, role, supervisor, status)
    out = io.StringIO()
    w = csv.writer(out)
    head = ["code", "name", "roles", "supervisor"]
    for c in m.competencies:
        head += [_safe(c.name), f"{_safe(c.name)} expires"]
    w.writerow(head)
    for row in m.people:
        line = [_safe(row.code), _safe(row.name), _safe("; ".join(r.name for r in row.roles)),
                _safe(row.supervisor.name) if row.supervisor else ""]
        for c in m.competencies:
            cell = row.cells[c.key]
            line += [cell.status.replace("_", " "),
                     cell.expires_on.isoformat() if cell.expires_on else ""]
        w.writerow(line)
    return Response(content=out.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition":
                             f'attachment; filename="matrix-{m.today.isoformat()}.csv"'})


@router.get("/people/{code}/training", response_model=TrainingOut)
def training(code: str, db: DB, who: Principal = require("training:read")):
    """A person's to-do: everything they are asked for and not let off, by
    name. The learner app sorts it into Overdue, Due soon and Done."""
    p = get_person(db, code)
    if not who.sees(p):
        raise NotFound(f"no person {code}")
    st = standing.load(db, [p.id], clock.today())
    items = []
    for c in st.asked_for(p.id):
        s = st.status(p.id, c)
        if s.status in TO_DO:
            comp = st.competencies[c]
            items.append(TrainingItem(key=comp.key, name=comp.name, kind=comp.kind,
                                      status=s.status, granted_on=s.granted_on,
                                      expires_on=s.expires_on))
    items.sort(key=lambda i: (i.name, i.key))
    return TrainingOut(person=person_ref(p), today=st.today, items=items)
```

`api/lms/api/app.py` now reads, in full:
```python
import logging

from fastapi import APIRouter, FastAPI
from sqlalchemy import text

from lms.api import errors
from lms.api.deps import DB
from lms.api.routes import auth, competencies, matrix, overrides, people, records, roles

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

app = FastAPI(
    title="Simple LMS",
    version="0.1.0",
    description="Open source, self-hosted workplace training. The API is the only door.",
    docs_url="/docs",
    redoc_url=None,
)
errors.install(app)

v1 = APIRouter(prefix="/v1")
v1.include_router(auth.router)
v1.include_router(people.router)
v1.include_router(roles.router)
v1.include_router(competencies.router)
v1.include_router(overrides.router)
v1.include_router(records.router)
v1.include_router(matrix.router)


@v1.get("/health", tags=["system"])
def health(db: DB):
    db.execute(text("select 1"))
    return {"status": "ok"}


app.include_router(v1)
```

**Step 4: Run them, and the whole suite, to see them pass**

Run: `cd api && .venv/bin/pytest tests/test_matrix.py tests/test_matrix_csv.py -v && .venv/bin/pytest -q`
Expected: `15 passed`, then `133 passed`, no warnings (warnings are errors in this suite).

**Step 5: Commit**

```
git add api/lms/services/standing.py api/lms/api/routes/matrix.py api/lms/api/app.py \
  api/tests/test_matrix.py api/tests/test_matrix_csv.py
git commit -m "Show the matrix, as JSON or CSV, and each person's training" \
  -m "Worked out on every request in four queries. A supervisor sees their own team; filter by role, supervisor or status."
```

---

### Task 13: Docker image, Compose, Caddy and settings

**Files:**
- Create: `api/Dockerfile`
- Modify: `docker-compose.yml` (replace)
- Create: `deploy/Caddyfile` (the API only; Task 21 adds the apps)
- Modify: `.env.example` (replace)

**Step 1: The check that fails**

Run: `docker compose up -d --build db api`
Expected: `no such service: api`.

**Step 2: Implementation**

`api/Dockerfile`:
```dockerfile
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml ./
COPY lms ./lms
COPY alembic.ini ./
COPY alembic ./alembic

RUN pip install --no-cache-dir . && rm -rf /root/.cache

EXPOSE 8000
CMD ["uvicorn", "lms.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
```

`docker-compose.yml` (Task 21 adds the apps' builds to `caddy`):
```yaml
services:
  db:
    image: postgres:16
    restart: unless-stopped
    environment:
      POSTGRES_DB: ${POSTGRES_DB:-lms}
      POSTGRES_USER: ${POSTGRES_USER:-lms}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?set POSTGRES_PASSWORD in .env}
    volumes:
      - pgdata:/var/lib/postgresql/data
    # 5435 so it sits beside Simple WMS's (5433) and Simple TMS's (5434) on one machine
    ports:
      - "127.0.0.1:${POSTGRES_PORT:-5435}:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-lms} -d ${POSTGRES_DB:-lms}"]
      interval: 5s
      timeout: 3s
      retries: 20

  api:
    build: ./api
    restart: unless-stopped
    # migrations run on every start, before the API takes requests
    command: sh -c "alembic upgrade head && uvicorn lms.api.app:app --host 0.0.0.0 --port 8000"
    environment:
      LMS_DATABASE_URL: postgresql+psycopg://${POSTGRES_USER:-lms}:${POSTGRES_PASSWORD}@db:5432/${POSTGRES_DB:-lms}
      LMS_TIMEZONE: ${LMS_TIMEZONE:-Australia/Melbourne}
    depends_on:
      db:
        condition: service_healthy
    expose:
      - "8000"
    # Caddy is the only door in a real install. Published on the host as well
    # for local work and CI.
    ports:
      - "127.0.0.1:${LMS_API_PORT:-8033}:8000"
    healthcheck:
      test: ["CMD-SHELL", "python -c \"import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/v1/health')\""]
      interval: 10s
      timeout: 5s
      retries: 10
      start_period: 20s

  # The worker arrives with build step 2, with the queue it drains (the
  # daily job, email reminders, and later the webhooks and print jobs).

  caddy:
    image: caddy:2
    restart: unless-stopped
    environment:
      LMS_DOMAIN: ${LMS_DOMAIN:-localhost}
      LMS_HTTP_PORT: ${LMS_HTTP_PORT:-80}
      LMS_HTTPS_PORT: ${LMS_HTTPS_PORT:-443}
    # The same port inside and out: Caddy names it in its redirect to https.
    ports:
      - "${LMS_HTTP_PORT:-80}:${LMS_HTTP_PORT:-80}"
      - "${LMS_HTTPS_PORT:-443}:${LMS_HTTPS_PORT:-443}"
    volumes:
      - ./deploy/Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy_data:/data
      - caddy_config:/config
    depends_on:
      - api

volumes:
  pgdata:
  caddy_data:
  caddy_config:
```

`deploy/Caddyfile` (Task 21 adds the desktop and the learner app):
```
{
	# Listen on the host's ports (LMS_HTTP_PORT, LMS_HTTPS_PORT), so Simple LMS
	# can run beside a sibling's Caddy, which may already have 80 and 443.
	http_port {$LMS_HTTP_PORT:80}
	https_port {$LMS_HTTPS_PORT:443}
	# Caddy's own redirect leaves the port out, so the one below names it.
	auto_https disable_redirects
}

http://{$LMS_DOMAIN} {
	redir https://{host}:{$LMS_HTTPS_PORT:443}{uri} 308
}

{$LMS_DOMAIN} {
	encode gzip
	header {
		X-Content-Type-Options nosniff
		Referrer-Policy same-origin
	}

	# The API is the only door.
	handle /v1/* {
		reverse_proxy api:8000
	}
	handle /docs* {
		reverse_proxy api:8000
	}
	handle /openapi.json {
		reverse_proxy api:8000
	}

	# The desktop and the learner app arrive with Task 21.
	handle {
		respond "Simple LMS. The API is at /v1, its docs at /docs." 404
	}
}
```

`.env.example`:
```
# Copy to .env and fill in. Nothing here is committed.

# Postgres (used by the db and api containers)
POSTGRES_DB=lms
POSTGRES_USER=lms
POSTGRES_PASSWORD=change-me
# Host port the database is published on (127.0.0.1 only). 5435 sits beside
# Simple WMS's 5433 and Simple TMS's 5434. The tests expect
# POSTGRES_PASSWORD=lms-dev on this port unless TEST_DATABASE_URL says otherwise.
POSTGRES_PORT=5435

# API
# Host port the API is published on, for local work and health checks.
# Caddy is still the only door from outside. 8033, beside Simple WMS's 8011
# and Simple TMS's 8022.
LMS_API_PORT=8033
# Whose "today" decides what is current, expiring or lapsed.
LMS_TIMEZONE=Australia/Melbourne

# Caddy: the public host name. "localhost" gives a self-signed local cert.
LMS_DOMAIN=localhost
# Host ports Caddy listens on. Keep 80 and 443 for a real domain: Let's
# Encrypt only checks those. Other ports (say 8280 and 8643 beside a
# sibling's Caddy) are for local work and a LAN only.
LMS_HTTP_PORT=80
LMS_HTTPS_PORT=443
```

Bring your `.env` up to date (keep `POSTGRES_PASSWORD=lms-dev`, which the tests expect). On this machine Simple WMS's Caddy holds 80 and 443 and Simple TMS's 8180 and 8543, so use 8280 and 8643:
```
cp .env.example .env
sed -i '' 's/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=lms-dev/' .env
sed -i '' 's/^LMS_HTTP_PORT=.*/LMS_HTTP_PORT=8280/; s/^LMS_HTTPS_PORT=.*/LMS_HTTPS_PORT=8643/' .env
```

**Step 3: Run the check to see it pass**

```
docker compose up -d --build
for i in $(seq 1 30); do curl -fsS http://127.0.0.1:8033/v1/health && break; sleep 2; done; echo
curl -sk https://localhost:8643/v1/health; echo
curl -sk -o /dev/null -w '%{http_code}\n' https://localhost:8643/
docker compose exec -T db psql -U lms -d lms -tAc \
  "select count(*) from pg_trigger where tgname like '%_append_only'"
```
Expected: `{"status":"ok"}` twice (straight to the API, then through Caddy), `404` for `/`, then `2`.

```
docker compose exec api lms create-user --code AD001 --name "Leighton Lauton" \
  --email leighton@example.com.au --password 'a long enough password'
curl -s -X POST http://127.0.0.1:8033/v1/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"leighton@example.com.au","password":"a long enough password"}'
```
Expected: `AD001 Leighton Lauton <leighton@example.com.au> created as admin`, then JSON starting `{"token":"lms_s.`.

**Step 4: Commit**

```
git add api/Dockerfile docker-compose.yml deploy/Caddyfile .env.example
git commit -m "Run the API, database and Caddy with Docker Compose" \
  -m "The API runs its migrations on start. Ports 5435 and 8033 sit beside Simple WMS and Simple TMS; Caddy's are settings. No worker until step 2 gives it something to drain."
```

---

### Task 14: `docs/api.md`

**Files:**
- Create: `docs/api.md`

**Step 1: Write it**

`docs/api.md`:
````markdown
# Simple LMS — API

Base path `/v1`. JSON in, JSON out. Dates are `YYYY-MM-DD`, times ISO 8601
in UTC. Interactive docs are at `/docs`.

## Shared rules

- **Auth:** `Authorization: Bearer <token>`. A token comes from
  `POST /v1/auth/login` (email and password) or `POST /v1/auth/pin-login`
  (code and PIN). The desktop and the learner app use these endpoints and
  nothing else: the API is the only door.
- **Errors:** a missing, ended or unknown token is `401`. Signed in but not
  allowed is `403` with `{ "detail", "code" }`. Validation problems are
  `422` with `{ "errors": [{ "field", "message" }] }`. Something that is not
  there (or not yours to see) is `404` with `{ "detail" }`. Well formed but
  not possible as things stand is `409` with `{ "detail", "code" }`.
- **Never deleted:** people and competencies are deactivated, not deleted.
  The training record and the extras and waivers are append-only: the latest
  row for a person and competency is the one that counts.
- **Codes and keys:** a person's code is kept upper case (`ll042` finds
  `LL042`); role and competency keys are kept lower case. Emails are kept
  lower case.

## Who may do what

| Permission | Scopes (signed in with a password) |
| --- | --- |
| `learner` | `training:read` |
| `supervisor` | `training:read`, `matrix:read`, `roles:read`, `competencies:read` |
| `manager` | the supervisor's, plus `people:read`, `people:write`, `roles:write`, `competencies:write`, `records:write` |
| `admin` | `*` |

A session signed in with a **PIN** carries `training:read` only, whoever it
is: a PIN is short, so it opens the learner app's own training and nothing
more. A supervisor sees their own team (the people whose supervisor they
are); a manager or admin sees everyone. Only an admin adds or changes a
manager or an admin (`403 { "code": "admin_only" }`).

## Sign in

### POST /v1/auth/login
`{ "email", "password" }` → `200`
```json
{
  "token": "lms_s.…",
  "person": { "id": 2, "code": "MG001", "name": "Mel Grant", "email": "mel@example.com.au",
              "permission": "manager", "method": "password",
              "scopes": ["training:read", "…"], "idle_seconds": 43200 }
}
```
A wrong password, an unknown email, or someone with no password is `401`
`{ "detail": "wrong email or password", "code": "wrong_password" }`. Five
wrong in a row lock the password for 15 minutes (`"code": "locked"`).

### POST /v1/auth/pin-login
`{ "code": "LL042", "pin": "2468" }` → `200`, the same shape with
`"method": "pin"` and `"idle_seconds": 900`. A wrong PIN or unknown code is
`401 { "code": "wrong_pin" }`. Five wrong PINs lock the PIN
(`"code": "locked"`) until a manager sets a new one.

A session ends on sign-out, after its idle time without a request (15
minutes for a PIN, 12 hours for a password), after 12 hours (PIN) or 14 days
(password) in all, when the person's PIN or password is changed, or when they
are deactivated.

### POST /v1/auth/logout
Ends the session whose token is sent. `204`, even if it had already ended.

### GET /v1/auth/me
The `person` object above, for the session's token.

The first admin is made on the command line:
`lms create-user --code AD001 --name "…" --email … [--permission admin]`
(prompts for the password, at least 12 characters).

## People

`people:read` to list and read, `people:write` to change.

- `POST /v1/people` — `{ "code", "name", "email"?, "permission"?
  ("learner"), "supervisor"? (a code), "roles"? ([keys]), "pin"? (4 to 8
  digits), "password"? (12 or more) }` → `201`. A code or email already
  taken is `422`. A supervisor must be active and have the supervisor,
  manager or admin permission.
- `GET /v1/people?active=true|false&q=&role=` — `{ "items", "total" }` by
  name. `q` matches part of the code, name or email; `role` is a role key.
- `GET /v1/people/{code}`
- `PATCH /v1/people/{code}` — any of `name`, `email`, `permission`,
  `supervisor`; `null` clears an email or a supervisor. Nobody is their own
  supervisor.
- `PUT /v1/people/{code}/roles` — `{ "roles": [keys] }`, in full.
- `POST /v1/people/{code}/pin` — `{ "pin" }`: a new PIN, which also unlocks
  a locked one. Their PIN sessions end.
- `POST /v1/people/{code}/password` — `{ "password" }`: a new password,
  which also lifts a lock. Their password sessions end.
- `POST /v1/people/{code}/deactivate`, `/reactivate` — deactivating ends
  their sessions; their records stay. Nobody deactivates themselves (`409
  { "code": "self" }`).

Each person:
```json
{ "id": 4, "code": "LL042", "name": "Kim Lee", "email": null, "permission": "learner",
  "supervisor": { "code": "SV001", "name": "Sam Vu" },
  "roles": [{ "key": "forklift-operator", "name": "Forklift operator" }],
  "active": true, "has_pin": true, "pin_locked": false, "has_password": false,
  "created_at": "…", "last_login_at": null }
```
A PIN or password is never returned.

## Roles

`roles:read` to list and read, `roles:write` to change.

- `POST /v1/roles` — `{ "key": "forklift-operator", "name": "Forklift operator" }` → `201`.
- `GET /v1/roles` — by name; `GET /v1/roles/{key}`
- `PATCH /v1/roles/{key}` — `{ "name" }`
- `PUT /v1/roles/{key}/requirements` — `{ "competencies": [keys] }`, in
  full. An unknown or deactivated competency is `422`.

Each role: `{ "id", "key", "name", "competencies": [{ "key", "name", "kind" }], "people", "created_at" }`.

## Competencies

`competencies:read` to list and read, `competencies:write` to change.

- `POST /v1/competencies` — `{ "key": "site-induction", "name": "Site
  induction", "kind": "module" | "practical" | "ticket" | "policy",
  "refresher_months"?: 1 to 240 }` → `201`.
- `GET /v1/competencies?kind=&active=` — by name; `GET /v1/competencies/{key}`
- `PATCH /v1/competencies/{key}` — `name` and/or `refresher_months` (`null`
  for none). The kind cannot change.
- `POST /v1/competencies/{key}/deactivate`, `/reactivate` — a deactivated
  competency is asked of nobody; its records stay.

Each competency: `{ "id", "key", "name", "kind", "refresher_months", "active", "created_at" }`.
In step 1 every kind is recorded by hand; modules, practicals, tickets and
policies get their own ways in with later build steps.

## Extras and waivers

- `GET /v1/people/{code}/overrides` (`people:read`) — those in force, by
  competency name: `[{ "id", "competency", "kind": "extra" | "waive", "note", "recorded_by", "created_at" }]`.
- `POST /v1/people/{code}/overrides` (`people:write`) — `{ "competency",
  "kind": "extra" | "waive" | "clear", "note" }` → `201`. An extra asks this
  person for a competency their roles don't; a waiver lets them off one their
  roles do; a clear puts them back to what their roles say (`409 { "code":
  "nothing_to_clear" }` if there is nothing to clear). The note is required.

## The training record

- `GET /v1/people/{code}/records?competency=` (`training:read`; your own,
  your team's, or anyone's for a manager) — newest first; the first for a
  competency is the one that counts:
  ```json
  [{ "id": 7, "competency": { "key": "forklift-licence", "name": "Forklift licence", "kind": "ticket" },
     "kind": "granted", "granted_on": "2026-03-01", "expires_on": "2031-03-01",
     "note": "LF 0012345, sighted", "recorded_by": { "code": "MG001", "name": "Mel Grant" },
     "created_at": "…" }]
  ```
- `POST /v1/people/{code}/records` (`records:write`) — `{ "competency",
  "granted_on", "expires_on"?, "note"? }` → `201`. `granted_on` can't be in
  the future; `expires_on` (the last good day, e.g. a ticket's card date)
  must be after it. Nobody records their own (`403 { "code": "own_record" }`).
  A deactivated person is `409 { "code": "inactive" }`; a deactivated
  competency is `422`. A wrong date is put right by recording the
  completion again with the right one.
- `POST /v1/people/{code}/records/revoke` (`records:write`) — `{
  "competency", "note" }` → `201`, a `revoked` row. Only a grant that counts
  now can be revoked (`409 { "code": "nothing_to_revoke" }`).

## Status

Worked out on every request, never stored:

| Status | When |
| --- | --- |
| `not_required` | no role or extra asks for it (or a waiver of something not asked) |
| `waived` | asked for, and waived |
| `missing` | asked for, and nothing granted (or the latest record is a revoke) |
| `current` | granted, and good for more than 30 days (or it never runs out) |
| `expiring` | granted, and its last good day is within 30 days (today included) |
| `lapsed` | granted, and its last good day has passed |

The last good day is the record's `expires_on` if it has one, else
`granted_on` plus the competency's refresher months, else never. Today is
the date in `LMS_TIMEZONE` (default `Australia/Melbourne`).

## The matrix

### GET /v1/matrix
`matrix:read`. Filters: `role` (key), `supervisor` (code), `status` (comma
separated: people with at least one cell in it). Active people by name; a
supervisor sees their own team. The columns are what any of them is asked
for, by name, and every person has a cell in every column:
```json
{
  "today": "2026-10-12",
  "competencies": [{ "key": "forklift-licence", "name": "Forklift licence", "kind": "ticket" }],
  "people": [{
    "code": "LL042", "name": "Kim Lee",
    "roles": [{ "key": "forklift-operator", "name": "Forklift operator" }],
    "supervisor": { "code": "SV001", "name": "Sam Vu" },
    "cells": { "forklift-licence": { "status": "expiring", "granted_on": "2025-01-01", "expires_on": "2026-11-01" } }
  }]
}
```

### GET /v1/matrix.csv
The same, with the same filters, as `text/csv`: `code, name, roles,
supervisor`, then a status and an expiry column per competency. A cell that
starts like a spreadsheet formula is prefixed with `'`.

### GET /v1/people/{code}/training
`training:read`; your own, your team's, or anyone's for a manager. What the
person is asked for and not let off, by name:
`{ "person": { "code", "name" }, "today", "items": [{ "key", "name", "kind", "status", "granted_on", "expires_on" }] }`.
The learner app shows it as Overdue (`lapsed`, `missing`), Due soon
(`expiring`) and Done (`current`).

## System

- `GET /v1/health` → `{ "status": "ok" }` once the database answers.
````

**Step 2: Check it against the app**

```
cd api && .venv/bin/python -c "
from lms.api.app import app
for path, ops in app.openapi()['paths'].items():
    for m in ops: print(m.upper(), path)" | sort
```
Expected: 33 lines, from `GET /v1/auth/me` to `PUT /v1/roles/{key}/requirements`, every one documented in `docs/api.md`, and nothing in `docs/api.md` missing from the list.

**Step 3: Commit**

```
git add docs/api.md
git commit -m "Document every endpoint in docs/api.md"
```

---
### Task 15: The desktop's skeleton, its API client and the status colours

**Files:**
- Create: `apps/desktop/package.json`, `apps/desktop/vite.config.ts`, `apps/desktop/tsconfig.json`, `apps/desktop/index.html`
- Create: `apps/desktop/public/favicon.svg`
- Create: `apps/desktop/src/vite-env.d.ts`, `apps/desktop/src/index.css`, `apps/desktop/src/test/setup.ts`
- Create: `apps/desktop/src/api/client.ts`, `apps/desktop/src/api/types.ts`, `apps/desktop/src/lib/status.ts`
- Test: `apps/desktop/src/test/client.test.ts`, `apps/desktop/src/test/status.test.ts`

**Step 1: The project**

`apps/desktop/package.json` (Simple TMS's desktop's, renamed):
```json
{
  "name": "simple-lms-desktop",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview",
    "test": "vitest run",
    "typecheck": "tsc -b"
  },
  "dependencies": {
    "@fontsource/manrope": "^5.3.0",
    "react": "^19.1.0",
    "react-dom": "^19.1.0",
    "react-router-dom": "^7.6.0"
  },
  "devDependencies": {
    "@tailwindcss/vite": "^4.1.0",
    "@testing-library/jest-dom": "^6.6.0",
    "@testing-library/react": "^16.3.0",
    "@testing-library/user-event": "^14.6.0",
    "@types/react": "^19.1.0",
    "@types/react-dom": "^19.1.0",
    "@vitejs/plugin-react": "^4.5.0",
    "jsdom": "^26.1.0",
    "tailwindcss": "^4.1.0",
    "typescript": "^5.8.0",
    "vite": "^6.3.0",
    "vitest": "^3.2.0"
  }
}
```

`apps/desktop/vite.config.ts`:
```ts
/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Vite runs this under Node; the app itself never sees process.
declare const process: { env: Record<string, string | undefined> };

// 5176, beside Simple WMS's 5173 and Simple TMS's 5174 and 5175.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5176,
    proxy: {
      "/v1": {
        target: process.env.LMS_API_URL ?? "http://127.0.0.1:8033",
        changeOrigin: true,
      },
    },
  },
  build: { outDir: "dist", sourcemap: false },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: false,
    testTimeout: 20000,
  },
});
```

`apps/desktop/tsconfig.json`:
```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "moduleResolution": "bundler",
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true,
    "skipLibCheck": true,
    "isolatedModules": true,
    "noEmit": true,
    "types": ["vitest/globals", "@testing-library/jest-dom"]
  },
  "include": ["src", "vite.config.ts"]
}
```

`apps/desktop/index.html`:
```html
<!doctype html>
<html lang="en-AU">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <meta name="color-scheme" content="light" />
    <title>Simple LMS</title>
    <link rel="icon" href="/favicon.svg" type="image/svg+xml" />
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

`apps/desktop/public/favicon.svg` (an open book with a tick):
```svg
<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 32 32"><path d="M3 7 15 10V28L3 25Z" fill="#5B93D6"/><path d="M29 7 17 10V28L29 25Z" fill="#2F6FB8"/><path d="M19.5 17.5 22 20l4.5-6" fill="none" stroke="#E8F0FA" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>
```

`apps/desktop/src/vite-env.d.ts`:
```ts
/// <reference types="vite/client" />
```

`apps/desktop/src/test/setup.ts`:
```ts
import "@testing-library/jest-dom/vitest";
```

`apps/desktop/src/index.css`:
```css
@import "tailwindcss";

/* Simple LMS colours: the siblings' bones, training blue for its own. The
 * matrix uses the shared green, amber, red and grey. Amber and red text use
 * their darker ink, never the fill. */
@theme {
  --color-page: #F3F5F8;
  --color-ink: #17202B;
  --color-ink-2: #48566A;
  --color-muted: #5B6778;
  --color-blue: #2F6FB8;
  --color-blue-dark: #23558E;
  --color-tint: #E8F0FA;
  --color-line: #DCE3EC;
  --color-line-2: #C8D3E0;
  --color-green: #1F8A5B;
  --color-green-ink: #146B45;
  --color-green-bg: #E3F3EA;
  --color-amber: #E8A317;
  --color-amber-ink: #8A5A00;
  --color-amber-bg: #FFF3D6;
  --color-red: #C9343D;
  --color-red-ink: #A3242C;
  --color-red-bg: #FCE9EA;
  --color-grey-bg: #EEF1F4;
  --font-sans: Manrope, ui-sans-serif, system-ui, sans-serif;
  --shadow-soft: 0 6px 20px rgba(23, 32, 43, 0.08);
  --shadow-lift: 0 10px 30px rgba(23, 32, 43, 0.12);
}

@layer base {
  html, body, #root { min-height: 100%; }
  body { margin: 0; background: var(--color-page); color: var(--color-ink); font-family: var(--font-sans); -webkit-font-smoothing: antialiased; }
  a { color: var(--color-blue-dark); }
  :focus-visible { outline: 3px solid rgba(47, 111, 184, 0.45); outline-offset: 2px; }
  button, input, select, textarea { font: inherit; color: inherit; }
}

@layer components {
  .sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
  .eyebrow { font-size: 12px; font-weight: 800; letter-spacing: 1.2px; color: var(--color-muted); text-transform: uppercase; }
  .pill { display: inline-flex; align-items: center; gap: 5px; padding: 4px 10px; border-radius: 999px; font-size: 12px; font-weight: 800; white-space: nowrap; line-height: 1.3; }
  .t-green { background: var(--color-green-bg); color: var(--color-green-ink); }
  .t-amber { background: var(--color-amber-bg); color: var(--color-amber-ink); }
  .t-red { background: var(--color-red-bg); color: var(--color-red-ink); }
  .t-grey { background: var(--color-grey-bg); color: var(--color-ink-2); }
  .btn { height: 40px; padding: 0 14px; border-radius: 10px; border: 1px solid var(--color-line-2); background: #fff; font-weight: 700; font-size: 14px; cursor: pointer; display: inline-flex; align-items: center; justify-content: center; gap: 6px; white-space: nowrap; }
  .btn:hover { border-color: var(--color-blue); }
  .btn:disabled { opacity: 0.55; cursor: default; }
  .btn.primary { border: 0; background: var(--color-blue); color: #fff; font-weight: 800; }
  .btn.primary:hover { background: var(--color-blue-dark); }
  .btn.danger { color: var(--color-red-ink); border-color: #F1B9BD; }
  .field { height: 40px; padding: 0 12px; border: 1px solid var(--color-line-2); border-radius: 10px; background: #fff; font-size: 14px; width: 100%; }
  textarea.field { height: 72px; padding: 8px 12px; resize: vertical; }
  .label { display: flex; flex-direction: column; gap: 4px; font-size: 13px; font-weight: 700; color: var(--color-ink-2); }
  .card { background: #fff; border: 1px solid var(--color-line); border-radius: 16px; padding: 16px; }
  .msg { font-size: 13px; border-radius: 10px; padding: 8px 10px; }
  .msg.r { background: var(--color-red-bg); color: var(--color-red-ink); }
  .msg.g { background: var(--color-green-bg); color: var(--color-green-ink); }
  .small { font-size: 12px; color: var(--color-muted); }

  .hdr { display: flex; flex-wrap: wrap; align-items: center; gap: 12px 20px; padding: 12px 24px; background: #fff; border-bottom: 1px solid var(--color-line); }
  .brand { display: flex; align-items: center; gap: 10px; font-size: 18px; font-weight: 800; }
  .nav { display: flex; gap: 4px; flex-wrap: wrap; }
  .nav a { height: 40px; padding: 0 14px; border-radius: 10px; color: var(--color-ink-2); font-weight: 700; font-size: 14px; text-decoration: none; display: flex; align-items: center; }
  .nav a:hover { background: var(--color-page); }
  .nav a.active { background: var(--color-tint); color: var(--color-blue-dark); font-weight: 800; }
  .page { padding: 20px 24px 40px; display: flex; flex-direction: column; gap: 16px; }
  .page h1 { margin: 0; font-size: 24px; font-weight: 800; letter-spacing: -0.3px; }

  .tbl { width: 100%; border-collapse: separate; border-spacing: 0; background: #fff; border: 1px solid var(--color-line); border-radius: 14px; overflow: hidden; font-size: 14px; }
  .tbl th { text-align: left; font-size: 12px; font-weight: 800; color: var(--color-muted); padding: 10px 12px; border-bottom: 1px solid var(--color-line); background: #FAFBFC; }
  .tbl td { padding: 8px 12px; border-bottom: 1px solid var(--color-line); vertical-align: middle; }
  .tbl tr:last-child td { border-bottom: 0; }
  .tbl tr.click { cursor: pointer; }
  .tbl tr.click:hover td { background: #F8FAFC; }
  .matrix th.c { writing-mode: vertical-rl; transform: rotate(180deg); white-space: nowrap; padding: 10px 6px; text-align: left; }
  .cell { width: 100%; min-width: 34px; height: 30px; border-radius: 8px; border: 0; cursor: pointer; font-size: 11px; font-weight: 800; }
  .cell.t-green { background: var(--color-green); color: #fff; }
  .cell.t-amber { background: var(--color-amber); color: #2B1D00; }
  .cell.t-red { background: var(--color-red); color: #fff; }
  .cell.t-grey { background: var(--color-grey-bg); color: var(--color-muted); }

  .dim { position: fixed; inset: 0; background: rgba(23, 32, 43, 0.35); }
  .drawer { position: fixed; top: 0; right: 0; bottom: 0; width: min(560px, 100%); background: #fff; box-shadow: -20px 0 50px rgba(23, 32, 43, 0.2); display: flex; flex-direction: column; }
  .dhead { display: flex; align-items: flex-start; gap: 12px; padding: 20px 24px 12px; }
  .dhead h2 { margin: 0; font-size: 20px; font-weight: 800; }
  .dbody { flex: 1; overflow: auto; padding: 0 24px 32px; display: flex; flex-direction: column; gap: 16px; }
}
```

Install:
```
cd apps/desktop && npm install
```

**Step 2: Write the failing tests**

`apps/desktop/src/test/client.test.ts`:
```ts
import { ApiClient, ApiError, Unreachable } from "../api/client";

function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

describe("ApiClient", () => {
  let calls: { url: string; init: RequestInit }[];
  let answers: (Response | Error)[];
  let client: ApiClient;

  beforeEach(() => {
    calls = [];
    answers = [];
    client = new ApiClient(async (url, init) => {
      calls.push({ url, init });
      const a = answers.shift() ?? json(500, { detail: "no answer queued" });
      if (a instanceof Error) throw a;
      return a;
    });
  });

  it("sends the token and leaves out empty filters", async () => {
    client.token = "lms_s.abc";
    answers.push(json(200, { people: [] }));
    await client.get("/v1/matrix", { role: "picker", status: "" });
    expect(calls[0].url).toBe("/v1/matrix?role=picker");
    expect(new Headers(calls[0].init.headers).get("Authorization")).toBe("Bearer lms_s.abc");
  });

  it("forgets the token and says so when the API stops taking it", async () => {
    const signedOut = vi.fn();
    client.onSignedOut = signedOut;
    client.token = "lms_s.old";
    answers.push(json(401, { detail: "session expired or invalid" }));
    await expect(client.get("/v1/auth/me")).rejects.toBeInstanceOf(ApiError);
    expect(client.token).toBeNull();
    expect(signedOut).toHaveBeenCalled();
  });

  it("gives the API's field errors and code", async () => {
    answers.push(json(422, { errors: [{ field: "granted_on", message: "can't be in the future" }] }));
    const e = (await client.post("/v1/people/LL042/records", {}).catch((x) => x)) as ApiError;
    expect(e.message).toBe("granted_on: can't be in the future");
    answers.push(json(403, { detail: "nobody records their own competency", code: "own_record" }));
    expect(((await client.post("/v1/people/MG001/records", {}).catch((x) => x)) as ApiError).code).toBe("own_record");
  });

  it("says Simple LMS can't be reached when there is no proper answer", async () => {
    answers.push(new TypeError("Failed to fetch"));
    await expect(client.get("/v1/matrix")).rejects.toBeInstanceOf(Unreachable);
    answers.push(new Response("<html>Bad gateway</html>", { status: 502 }));
    await expect(client.get("/v1/matrix")).rejects.toThrow("Can't reach Simple LMS right now.");
  });
});
```

`apps/desktop/src/test/status.test.ts`:
```ts
import { LOOK, STATUSES, describe as say, formatDate } from "../lib/status";

describe("status colours", () => {
  it("is green, amber, red or grey, as the matrix draws it", () => {
    expect(Object.fromEntries(STATUSES.map((s) => [s, LOOK[s].tone]))).toEqual({
      current: "green", expiring: "amber", lapsed: "red", missing: "red",
      waived: "grey", not_required: "grey",
    });
  });

  it("writes dates the Australian way", () => {
    expect(formatDate("2026-11-01")).toBe("1 Nov 2026");
    expect(formatDate(null)).toBe("");
  });

  it("says what a cell means", () => {
    expect(say({ status: "current", granted_on: "2025-06-01", expires_on: "2027-06-01" })).toBe("Current until 1 Jun 2027");
    expect(say({ status: "current", granted_on: "2025-06-01", expires_on: null })).toBe("Current, doesn't run out");
    expect(say({ status: "expiring", granted_on: "2025-01-01", expires_on: "2026-11-01" })).toBe("Expiring: good until 1 Nov 2026");
    expect(say({ status: "lapsed", granted_on: "2024-01-01", expires_on: "2026-01-01" })).toBe("Lapsed: was good until 1 Jan 2026");
    expect(say({ status: "not_required", granted_on: null, expires_on: null })).toBe("Not required");
  });
});
```

**Step 3: Run them to see them fail**

Run: `cd apps/desktop && npm test`
Expected: FAIL, `Failed to resolve import "../api/client"` and `"../lib/status"`.

**Step 4: Minimal implementation**

`apps/desktop/src/api/client.ts`:
```ts
/** The desktop is an ordinary API client with a session token. Nothing here
 * a partner could not do with the same API (rule 4). */

export interface FieldError {
  field: string;
  message: string;
}

export class ApiError extends Error {
  status: number;
  errors: FieldError[];
  /** The API's reason when it gives one: wrong_password, locked, own_record, ... */
  code: string | null;
  constructor(status: number, body: unknown) {
    const errors = ((body as { errors?: FieldError[] })?.errors ?? []) as FieldError[];
    const detail = (body as { detail?: unknown })?.detail;
    super(errors.length > 0 ? errors.map((e) => `${e.field}: ${e.message}`).join("; ")
      : typeof detail === "string" ? detail : `Simple LMS answered ${status}`);
    this.status = status;
    this.errors = errors;
    const code = (body as { code?: unknown })?.code;
    this.code = typeof code === "string" ? code : null;
  }
}

/** The API could not be reached, or did not answer properly. */
export class Unreachable extends Error {
  constructor() {
    super("Can't reach Simple LMS right now.");
  }
}

type Fetcher = (url: string, init: RequestInit) => Promise<Response>;
type Params = Record<string, string | number | boolean | null | undefined>;

const TOKEN_KEY = "lms.desktop.token";

function query(params?: Params): string {
  if (!params) return "";
  const qs = Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== null && v !== "")
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
    .join("&");
  return qs ? `?${qs}` : "";
}

export class ApiClient {
  /** Called when the API stops taking the token: idle too long, or signed out elsewhere. */
  onSignedOut: (() => void) | null = null;
  private fetcher: Fetcher;

  constructor(fetcher?: Fetcher) {
    this.fetcher = fetcher ?? ((url, init) => fetch(url, init));
  }

  get token(): string | null {
    try { return window.localStorage.getItem(TOKEN_KEY); } catch { return null; }
  }

  set token(value: string | null) {
    try {
      if (value) window.localStorage.setItem(TOKEN_KEY, value);
      else window.localStorage.removeItem(TOKEN_KEY);
    } catch { /* private mode: signed in for this page only */ }
  }

  private async send(method: string, path: string, body?: unknown): Promise<Response> {
    const headers: Record<string, string> = { Accept: "application/json" };
    if (body !== undefined) headers["Content-Type"] = "application/json";
    const token = this.token;
    if (token) headers.Authorization = `Bearer ${token}`;
    let res: Response;
    try {
      res = await this.fetcher(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
    } catch {
      throw new Unreachable();
    }
    if (res.status === 401 && token && !path.startsWith("/v1/auth/login")) {
      this.token = null;
      this.onSignedOut?.();
    }
    return res;
  }

  async request<T>(method: string, path: string, body?: unknown): Promise<T> {
    const res = await this.send(method, path, body);
    if (res.status === 204) return undefined as T;
    const text = await res.text();
    let parsed: unknown;
    try {
      parsed = text ? JSON.parse(text) : null;
    } catch {
      // a proxy's error page, say: not the API's own answer
      throw new Unreachable();
    }
    if (!res.ok) throw new ApiError(res.status, parsed);
    return parsed as T;
  }

  get<T>(path: string, params?: Params) { return this.request<T>("GET", path + query(params)); }
  post<T>(path: string, body: unknown = {}) { return this.request<T>("POST", path, body); }
  patch<T>(path: string, body: unknown) { return this.request<T>("PATCH", path, body); }
  put<T>(path: string, body: unknown) { return this.request<T>("PUT", path, body); }

  /** A file the API makes (the matrix as CSV), saved by the browser. */
  async download(path: string, params: Params, filename: string): Promise<void> {
    const res = await this.send("GET", path + query(params));
    if (!res.ok) throw new ApiError(res.status, await res.json().catch(() => null));
    const url = URL.createObjectURL(await res.blob());
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  }
}

export const api = new ApiClient();
```

`apps/desktop/src/api/types.ts`:
```ts
/** What the API answers: docs/api.md. */

export type Permission = "learner" | "supervisor" | "manager" | "admin";
export type Kind = "module" | "practical" | "ticket" | "policy";
export type Status = "current" | "expiring" | "lapsed" | "missing" | "waived" | "not_required";

export interface Me {
  id: number;
  code: string;
  name: string;
  email: string | null;
  permission: Permission;
  method: "password" | "pin";
  scopes: string[];
  idle_seconds: number;
}

export interface SessionOut { token: string; person: Me }
export interface Page<T> { items: T[]; total: number }
export interface PersonRef { code: string; name: string }
export interface RoleRef { key: string; name: string }
export interface CompetencyRef { key: string; name: string; kind: Kind }

export interface Person {
  id: number;
  code: string;
  name: string;
  email: string | null;
  permission: Permission;
  supervisor: PersonRef | null;
  roles: RoleRef[];
  active: boolean;
  has_pin: boolean;
  pin_locked: boolean;
  has_password: boolean;
}

export interface Role {
  id: number;
  key: string;
  name: string;
  competencies: CompetencyRef[];
  people: number;
}

export interface Competency {
  id: number;
  key: string;
  name: string;
  kind: Kind;
  refresher_months: number | null;
  active: boolean;
}

export interface Cell { status: Status; granted_on: string | null; expires_on: string | null }

export interface MatrixRow {
  code: string;
  name: string;
  roles: RoleRef[];
  supervisor: PersonRef | null;
  cells: Record<string, Cell>;
}

export interface Matrix { today: string; competencies: CompetencyRef[]; people: MatrixRow[] }

export interface Override {
  id: number;
  competency: CompetencyRef;
  kind: "extra" | "waive";
  note: string;
  recorded_by: PersonRef;
  created_at: string;
}

export interface CompetencyRecord {
  id: number;
  competency: CompetencyRef;
  kind: "granted" | "revoked";
  granted_on: string | null;
  expires_on: string | null;
  note: string | null;
  recorded_by: PersonRef;
  created_at: string;
}
```

`apps/desktop/src/lib/status.ts`:
```ts
/** How a status looks: green, amber, red or grey, with words for it. */
import type { Cell, Status } from "../api/types";

export type Tone = "green" | "amber" | "red" | "grey";

export const LOOK: Record<Status, { label: string; short: string; tone: Tone }> = {
  current: { label: "Current", short: "✓", tone: "green" },
  expiring: { label: "Expiring", short: "!", tone: "amber" },
  lapsed: { label: "Lapsed", short: "✕", tone: "red" },
  missing: { label: "Missing", short: "–", tone: "red" },
  waived: { label: "Waived", short: "W", tone: "grey" },
  not_required: { label: "Not required", short: "", tone: "grey" },
};

export const STATUSES = Object.keys(LOOK) as Status[];

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "2026-11-01" → "1 Nov 2026", day first as Australians write it, the
 * same in every browser. */
export function formatDate(iso: string | null): string {
  if (!iso) return "";
  const [y, m, d] = iso.split("-").map(Number);
  return `${d} ${MONTHS[m - 1]} ${y}`;
}

/** What a cell's tooltip and the history drawer say about it. */
export function describe(cell: Cell): string {
  const { label } = LOOK[cell.status];
  switch (cell.status) {
    case "current":
      return cell.expires_on ? `${label} until ${formatDate(cell.expires_on)}` : `${label}, doesn't run out`;
    case "expiring":
      return `${label}: good until ${formatDate(cell.expires_on)}`;
    case "lapsed":
      return `${label}: was good until ${formatDate(cell.expires_on)}`;
    default:
      return label;
  }
}
```

**Step 5: Run them to see them pass**

Run: `cd apps/desktop && npm test`
Expected: `Tests  7 passed (7)`.

**Step 6: Commit**

```
git add apps/desktop/package.json apps/desktop/package-lock.json apps/desktop/vite.config.ts \
  apps/desktop/tsconfig.json apps/desktop/index.html apps/desktop/public apps/desktop/src
git commit -m "Start the desktop app: Vite, React, Tailwind, the API client and the status colours" \
  -m "Green for current, amber for expiring, red for lapsed or missing, grey for waived or not required. Dates the Australian way, the same in every browser."
```

---

### Task 16: Sign in to the desktop, and the matrix with each cell's history

**Files:**
- Create: `apps/desktop/src/main.tsx`, `apps/desktop/src/App.tsx`
- Create: `apps/desktop/src/auth/AuthContext.tsx`, `apps/desktop/src/auth/RequireAuth.tsx`
- Create: `apps/desktop/src/ui/Logo.tsx`, `apps/desktop/src/ui/Layout.tsx`, `apps/desktop/src/ui/Drawer.tsx`
- Create: `apps/desktop/src/lib/useLoad.ts`
- Create: `apps/desktop/src/pages/SignIn.tsx`, `apps/desktop/src/pages/Matrix.tsx`, `apps/desktop/src/pages/HistoryDrawer.tsx`
- Test: `apps/desktop/src/test/harness.tsx`, `apps/desktop/src/test/SignIn.test.tsx`, `apps/desktop/src/test/Matrix.test.tsx`

**Step 1: Write the failing tests**

`apps/desktop/src/test/harness.tsx`:
```tsx
import { render } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { api } from "../api/client";
import { AppRoutes } from "../App";
import { AuthProvider } from "../auth/AuthContext";
import type { Me } from "../api/types";

export function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

export const MEL: Me = {
  id: 2, code: "MG001", name: "Mel Grant", email: "mel@example.com.au", permission: "manager", method: "password",
  scopes: ["training:read", "matrix:read", "roles:read", "competencies:read", "people:read", "people:write",
           "roles:write", "competencies:write", "records:write"],
  idle_seconds: 43200,
};

export interface Call { method: string; url: string; body: unknown }
type Handler = (method: string, url: string, body: unknown) => Response | null | Promise<Response | null>;

/** Signed in as `me` (Mel, a manager); `more` answers everything else, or it is a 404. */
export function stubApi(more: Handler = () => null, me: Me = MEL) {
  const calls: Call[] = [];
  const fetchMock = vi.fn(async (url: string, init: RequestInit = {}) => {
    const method = init.method ?? "GET";
    const body = init.body ? JSON.parse(init.body as string) : undefined;
    calls.push({ method, url, body });
    if (url === "/v1/auth/me") return json(200, me);
    if (url === "/v1/auth/logout") return new Response(null, { status: 204 });
    const answer = await more(method, url, body);
    return answer ?? json(404, { detail: `no stub for ${method} ${url}` });
  });
  vi.stubGlobal("fetch", fetchMock);
  return { calls, fetchMock };
}

function Where() {
  return <output data-testid="where">{useLocation().pathname}</output>;
}

export function renderApp(path: string, signedIn = true) {
  api.token = signedIn ? "lms_s.test" : null;
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <AppRoutes />
        <Where />
      </AuthProvider>
    </MemoryRouter>,
  );
}
```

`apps/desktop/src/test/SignIn.test.tsx`:
```tsx
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api } from "../api/client";
import { json, MEL, renderApp, stubApi } from "./harness";

const EMPTY = { today: "2026-10-12", competencies: [], people: [] };

describe("signing in to the desktop", () => {
  afterEach(() => window.localStorage.clear());

  it("sends someone not signed in to the sign-in page", async () => {
    stubApi();
    renderApp("/", false);
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
  });

  it("signs a manager in and opens the matrix", async () => {
    const { calls } = stubApi((_method, url) => {
      if (url === "/v1/auth/login") return json(200, { token: "lms_s.new", person: MEL });
      if (url.startsWith("/v1/matrix")) return json(200, EMPTY);
      if (url === "/v1/roles") return json(200, { items: [], total: 0 });
      return null;
    });
    renderApp("/sign-in", false);
    await userEvent.type(await screen.findByLabelText("Email"), "mel@example.com.au");
    await userEvent.type(screen.getByLabelText("Password"), "correct horse battery");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("heading", { name: "Matrix" })).toBeInTheDocument();
    expect(api.token).toBe("lms_s.new");
    expect(calls.find((c) => c.url === "/v1/auth/login")?.body).toEqual({
      email: "mel@example.com.au", password: "correct horse battery" });
  });

  it("says plainly when the password is wrong", async () => {
    stubApi((_method, url) => url === "/v1/auth/login"
      ? json(401, { detail: "wrong email or password", code: "wrong_password" }) : null);
    renderApp("/sign-in", false);
    await userEvent.type(await screen.findByLabelText("Email"), "mel@example.com.au");
    await userEvent.type(screen.getByLabelText("Password"), "nope");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Wrong email or password.");
  });

  it("sends a learner to the learner app and signs them out again", async () => {
    const { calls } = stubApi((_method, url) => url === "/v1/auth/login"
      ? json(200, { token: "lms_s.kim", person: { ...MEL, code: "LL042", permission: "learner", scopes: ["training:read"] } })
      : null);
    renderApp("/sign-in", false);
    await userEvent.type(await screen.findByLabelText("Email"), "kim@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "correct horse battery");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Your training is in the learner app at /learn/.");
    await waitFor(() => expect(calls.some((c) => c.url === "/v1/auth/logout")).toBe(true));
    expect(api.token).toBeNull();
  });
});
```

`apps/desktop/src/test/Matrix.test.tsx`:
```tsx
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Matrix } from "../api/types";
import { json, renderApp, stubApi } from "./harness";

const MATRIX: Matrix = {
  today: "2026-10-12",
  competencies: [
    { key: "forklift-licence", name: "Forklift licence", kind: "ticket" },
    { key: "site-induction", name: "Site induction", kind: "module" },
  ],
  people: [{
    code: "LL042", name: "Kim Lee", roles: [{ key: "forklift-operator", name: "Forklift operator" }],
    supervisor: { code: "SV001", name: "Sam Vu" },
    cells: {
      "forklift-licence": { status: "missing", granted_on: null, expires_on: null },
      "site-induction": { status: "expiring", granted_on: "2024-10-20", expires_on: "2026-10-20" },
    },
  }],
};

const GRANTED: Matrix = {
  ...MATRIX,
  people: [{ ...MATRIX.people[0], cells: { ...MATRIX.people[0].cells,
    "forklift-licence": { status: "current", granted_on: "2026-10-12", expires_on: "2031-03-01" } } }],
};

describe("the matrix", () => {
  it("colours each cell by its status and says what it means", async () => {
    stubApi((_method, url) => {
      if (url.startsWith("/v1/matrix")) return json(200, MATRIX);
      if (url === "/v1/roles") return json(200, { items: [], total: 0 });
      return null;
    });
    renderApp("/");
    const missing = await screen.findByRole("button", { name: "Kim Lee, Forklift licence: Missing" });
    expect(missing).toHaveClass("t-red");
    const expiring = screen.getByRole("button", { name: "Kim Lee, Site induction: Expiring: good until 20 Oct 2026" });
    expect(expiring).toHaveClass("t-amber");
  });

  it("asks again with the filters", async () => {
    const { calls } = stubApi((_method, url) => {
      if (url.startsWith("/v1/matrix")) return json(200, MATRIX);
      if (url === "/v1/roles") return json(200, { items: [{ key: "picker", name: "Picker", competencies: [], people: 0 }], total: 1 });
      return null;
    });
    renderApp("/");
    await screen.findByRole("button", { name: /Kim Lee, Forklift licence/ });
    await userEvent.selectOptions(screen.getByLabelText("Status"), "lapsed");
    await userEvent.selectOptions(screen.getByLabelText("Role"), "picker");
    await waitFor(() => expect(calls.at(-1)?.url).toBe("/v1/matrix?role=picker&status=lapsed"));
  });

  it("opens a cell's history and records a completion, and the cell goes green", async () => {
    let matrix = MATRIX;
    const records: unknown[] = [];
    const { calls } = stubApi((method, url, body) => {
      if (url.startsWith("/v1/matrix")) return json(200, matrix);
      if (url === "/v1/roles") return json(200, { items: [], total: 0 });
      if (method === "GET" && url.startsWith("/v1/people/LL042/records")) return json(200, records);
      if (method === "POST" && url === "/v1/people/LL042/records") {
        matrix = GRANTED;
        records.unshift({ id: 1, competency: MATRIX.competencies[0], kind: "granted", granted_on: "2026-10-12",
                          expires_on: "2031-03-01", note: (body as { note: string }).note,
                          recorded_by: { code: "MG001", name: "Mel Grant" }, created_at: "2026-10-12T01:00:00Z" });
        return json(201, records[0]);
      }
      return null;
    });
    renderApp("/");
    await userEvent.click(await screen.findByRole("button", { name: "Kim Lee, Forklift licence: Missing" }));
    const drawer = await screen.findByRole("dialog", { name: "Forklift licence" });
    expect(await within(drawer).findByText("Nothing recorded yet.")).toBeInTheDocument();
    await userEvent.type(within(drawer).getByLabelText("Good until (optional)"), "2031-03-01");
    await userEvent.type(within(drawer).getByLabelText("Note (optional)"), "LF 0012345, sighted");
    await userEvent.click(within(drawer).getByRole("button", { name: "Record completion" }));

    expect(calls.find((c) => c.method === "POST")?.body).toEqual({
      competency: "forklift-licence", granted_on: "2026-10-12", expires_on: "2031-03-01", note: "LF 0012345, sighted" });
    expect(await within(drawer).findByText("LF 0012345, sighted")).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Kim Lee, Forklift licence: Current until 1 Mar 2031" })).toHaveClass("t-green");
    // now there is a grant, it can be revoked
    expect(within(drawer).getByRole("button", { name: "Revoke" })).toBeDisabled();
  });

  it("tells a manager they can't record their own", async () => {
    const own = { ...MATRIX, people: [{ ...MATRIX.people[0], code: "MG001", name: "Mel Grant" }] };
    stubApi((_method, url) => {
      if (url.startsWith("/v1/matrix")) return json(200, own);
      if (url === "/v1/roles") return json(200, { items: [], total: 0 });
      if (url.startsWith("/v1/people/MG001/records")) return json(200, []);
      return null;
    });
    renderApp("/");
    await userEvent.click(await screen.findByRole("button", { name: "Mel Grant, Forklift licence: Missing" }));
    expect(await screen.findByText("Nobody records their own competency: ask another manager.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Record completion" })).not.toBeInTheDocument();
  });
});
```

**Step 2: Run them to see them fail**

Run: `cd apps/desktop && npm test`
Expected: FAIL, `Failed to resolve import "../App"` (and `"../auth/AuthContext"`) in `harness.tsx`.

**Step 3: Minimal implementation**

`apps/desktop/src/main.tsx`:
```tsx
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "@fontsource/manrope/latin-400.css";
import "@fontsource/manrope/latin-600.css";
import "@fontsource/manrope/latin-700.css";
import "@fontsource/manrope/latin-800.css";
import "./index.css";
import { App } from "./App";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
```

`apps/desktop/src/App.tsx` (Task 17 adds People, Roles and Competencies):
```tsx
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider } from "./auth/AuthContext";
import { RequireAuth } from "./auth/RequireAuth";
import { Matrix } from "./pages/Matrix";
import { SignIn } from "./pages/SignIn";
import { Layout } from "./ui/Layout";

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/sign-in" element={<SignIn />} />
      <Route element={<RequireAuth />}>
        <Route element={<Layout />}>
          <Route index element={<Matrix />} />
        </Route>
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <AppRoutes />
      </AuthProvider>
    </BrowserRouter>
  );
}
```

`apps/desktop/src/auth/AuthContext.tsx`:
```tsx
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, ApiError } from "../api/client";
import type { Me, SessionOut } from "../api/types";

export const LEARNERS_ELSEWHERE =
  "The desktop is for supervisors, managers and admins. Your training is in the learner app at /learn/.";

interface AuthState {
  ready: boolean;
  me: Me | null;
  /** Why the session could not be checked, when it is kept to try again. */
  trouble: string | null;
  retry: () => void;
  signIn: (email: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
  can: (scope: string) => boolean;
}

const Ctx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [ready, setReady] = useState(false);
  const [me, setMe] = useState<Me | null>(null);
  const [trouble, setTrouble] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    api.onSignedOut = () => setMe(null);
    (async () => {
      try {
        if (api.token) setMe(await api.get<Me>("/v1/auth/me"));
        setTrouble(null);
      } catch (e) {
        // a refused token is already forgotten; anything else is worth another try
        setTrouble(e instanceof ApiError ? null : (e as Error).message);
      } finally {
        setReady(true);
      }
    })();
  }, [attempt]);

  const retry = useCallback(() => { setReady(false); setAttempt((n) => n + 1); }, []);

  const signIn = useCallback(async (email: string, password: string) => {
    const out = await api.post<SessionOut>("/v1/auth/login", { email, password });
    api.token = out.token;
    if (out.person.permission === "learner") {
      await api.post("/v1/auth/logout").catch(() => undefined);
      api.token = null;
      throw new Error(LEARNERS_ELSEWHERE);
    }
    setMe(out.person);
  }, []);

  const signOut = useCallback(async () => {
    try {
      await api.post("/v1/auth/logout");
    } catch { /* signed out here whatever the API says */ }
    api.token = null;
    setMe(null);
  }, []);

  const can = useCallback((scope: string) => {
    if (!me) return false;
    const area = scope.split(":")[0];
    return me.scopes.includes("*") || me.scopes.includes(scope) || me.scopes.includes(`${area}:*`);
  }, [me]);

  const value = useMemo(() => ({ ready, me, trouble, retry, signIn, signOut, can }),
                        [ready, me, trouble, retry, signIn, signOut, can]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useAuth outside AuthProvider");
  return ctx;
}
```

`apps/desktop/src/auth/RequireAuth.tsx`:
```tsx
import { Navigate, Outlet } from "react-router-dom";
import { useAuth } from "./AuthContext";

export function RequireAuth() {
  const { ready, me, trouble, retry } = useAuth();
  if (!ready) return <div className="p-6 small">Loading…</div>;
  if (!me && trouble) {
    return (
      <main className="min-h-screen grid place-items-center p-6">
        <div className="card w-full max-w-sm flex flex-col gap-4">
          <div className="msg r" role="alert">{trouble}</div>
          <button type="button" className="btn primary" onClick={retry}>Try again</button>
        </div>
      </main>
    );
  }
  if (!me) return <Navigate to="/sign-in" replace />;
  return <Outlet />;
}
```

`apps/desktop/src/ui/Logo.tsx`:
```tsx
export function Logo({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
      <path d="M3 7 15 10V28L3 25Z" fill="#5B93D6" />
      <path d="M29 7 17 10V28L29 25Z" fill="#2F6FB8" />
      <path d="M19.5 17.5 22 20l4.5-6" fill="none" stroke="#E8F0FA" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
```

`apps/desktop/src/ui/Layout.tsx` (its People, Roles and Competencies links lead back to the matrix until Task 17):
```tsx
import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { Logo } from "./Logo";

/** Until Game Mode (build step 7) the desktop opens on the matrix. */
export function Layout() {
  const { me, can, signOut } = useAuth();
  return (
    <div className="min-h-screen">
      <header className="hdr">
        <div className="brand"><Logo />Simple LMS</div>
        <nav className="nav" aria-label="Screens">
          <NavLink to="/" end>Matrix</NavLink>
          {can("people:read") && <NavLink to="/people">People</NavLink>}
          {can("roles:read") && <NavLink to="/roles">Roles</NavLink>}
          {can("competencies:read") && <NavLink to="/competencies">Competencies</NavLink>}
        </nav>
        <div className="ml-auto flex items-center gap-3">
          <span className="small">{me?.name} · {me?.permission}</span>
          <button type="button" className="btn" onClick={() => void signOut()}>Sign out</button>
        </div>
      </header>
      <Outlet />
    </div>
  );
}
```

`apps/desktop/src/ui/Drawer.tsx`:
```tsx
import { useEffect, type ReactNode } from "react";

/** A panel over the right of the screen. Escape or the dim closes it. */
export function Drawer({ title, sub, onClose, children }: {
  title: string; sub?: ReactNode; onClose: () => void; children: ReactNode;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <>
      <div className="dim" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-modal="true" aria-label={title}>
        <div className="dhead">
          <div className="flex-1 min-w-0">
            <h2>{title}</h2>
            {sub && <div className="small">{sub}</div>}
          </div>
          <button type="button" className="btn" onClick={onClose} aria-label="Close">✕</button>
        </div>
        <div className="dbody">{children}</div>
      </aside>
    </>
  );
}

/** What went wrong, said plainly; nothing when nothing did. */
export function Problem({ error }: { error: string | null }) {
  return error ? <div className="msg r" role="alert">{error}</div> : null;
}
```

`apps/desktop/src/lib/useLoad.ts`:
```ts
import { useCallback, useEffect, useState } from "react";

/** Load something from the API, again whenever deps change or reload() is called.
 * Only the latest answer is kept, so a slow one can't overwrite a newer one. */
export function useLoad<T>(load: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [n, setN] = useState(0);
  useEffect(() => {
    let live = true;
    setError(null);
    load().then((d) => { if (live) setData(d); },
                (e) => { if (live) setError((e as Error).message); });
    return () => { live = false; };
  }, [...deps, n]);
  const reload = useCallback(() => setN((x) => x + 1), []);
  return { data, error, reload };
}

/** Run a change against the API, one at a time, keeping its error to show. */
export function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = useCallback(async (fn: () => Promise<unknown>): Promise<boolean> => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      return true;
    } catch (e) {
      setError((e as Error).message);
      return false;
    } finally {
      setBusy(false);
    }
  }, []);
  return { busy, error, run };
}
```

`apps/desktop/src/pages/SignIn.tsx`:
```tsx
import { useState, type FormEvent } from "react";
import { Navigate } from "react-router-dom";
import { ApiError } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { Problem } from "../ui/Drawer";
import { Logo } from "../ui/Logo";

function refusal(e: unknown): string {
  if (e instanceof ApiError && e.code === "wrong_password") return "Wrong email or password.";
  if (e instanceof ApiError && e.code === "locked") return "Too many wrong passwords. Try again in 15 minutes.";
  return (e as Error).message;
}

export function SignIn() {
  const { me, signIn } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (me) return <Navigate to="/" replace />;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await signIn(email.trim(), password);
    } catch (err) {
      setError(refusal(err));
      setPassword("");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="min-h-screen grid place-items-center p-6">
      <form onSubmit={submit} className="card w-full max-w-sm flex flex-col gap-4" style={{ boxShadow: "var(--shadow-lift)" }}>
        <div className="brand"><Logo />Simple LMS</div>
        <h1 className="m-0 text-2xl font-extrabold">Sign in</h1>
        <label className="label">Email
          <input className="field" type="email" autoComplete="username" value={email}
                 onChange={(e) => setEmail(e.target.value)} required />
        </label>
        <label className="label">Password
          <input className="field" type="password" autoComplete="current-password" value={password}
                 onChange={(e) => setPassword(e.target.value)} required />
        </label>
        <Problem error={error} />
        <button type="submit" className="btn primary" disabled={busy}>Sign in</button>
      </form>
    </main>
  );
}
```

`apps/desktop/src/pages/Matrix.tsx`:
```tsx
import { useMemo, useState } from "react";
import { api } from "../api/client";
import type { Matrix as MatrixData, Page, PersonRef, Role, Status } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { LOOK, STATUSES, describe } from "../lib/status";
import { useLoad } from "../lib/useLoad";
import { Problem } from "../ui/Drawer";
import { HistoryDrawer } from "./HistoryDrawer";

/** People down the side, what they are asked for across the top. */
export function Matrix() {
  const { me } = useAuth();
  const [role, setRole] = useState("");
  const [supervisor, setSupervisor] = useState("");
  const [status, setStatus] = useState<"" | Status>("");
  const [open, setOpen] = useState<{ code: string; key: string } | null>(null);
  const filters = { role, supervisor, status };
  const matrix = useLoad(() => api.get<MatrixData>("/v1/matrix", filters), [role, supervisor, status]);
  const roles = useLoad(() => api.get<Page<Role>>("/v1/roles"), []);
  const seesEveryone = me?.permission === "manager" || me?.permission === "admin";

  const supervisors = useMemo(() => {
    const all = new Map<string, PersonRef>();
    for (const p of matrix.data?.people ?? []) if (p.supervisor) all.set(p.supervisor.code, p.supervisor);
    return [...all.values()].sort((a, b) => a.name.localeCompare(b.name));
  }, [matrix.data]);

  const m = matrix.data;
  const row = open && m?.people.find((p) => p.code === open.code);
  const competency = open && m?.competencies.find((c) => c.key === open.key);

  return (
    <main className="page">
      <div className="flex flex-wrap items-end gap-3">
        <h1 className="mr-auto">Matrix</h1>
        <label className="label">Role
          <select className="field" value={role} onChange={(e) => setRole(e.target.value)}>
            <option value="">All roles</option>
            {roles.data?.items.map((r) => <option key={r.key} value={r.key}>{r.name}</option>)}
          </select>
        </label>
        {seesEveryone && (
          <label className="label">Supervisor
            <select className="field" value={supervisor} onChange={(e) => setSupervisor(e.target.value)}>
              <option value="">Anyone</option>
              {supervisors.map((s) => <option key={s.code} value={s.code}>{s.name}</option>)}
            </select>
          </label>
        )}
        <label className="label">Status
          <select className="field" value={status} onChange={(e) => setStatus(e.target.value as Status | "")}>
            <option value="">Any</option>
            {STATUSES.filter((s) => s !== "not_required").map((s) => <option key={s} value={s}>{LOOK[s].label}</option>)}
          </select>
        </label>
        <button type="button" className="btn" disabled={!m}
                onClick={() => void api.download("/v1/matrix.csv", filters, `matrix-${m?.today}.csv`)}>
          Export CSV
        </button>
      </div>
      <div className="flex flex-wrap gap-2" aria-label="Key">
        {(["current", "expiring", "lapsed", "missing", "waived"] as Status[]).map((s) => (
          <span key={s} className={`pill t-${LOOK[s].tone}`}>{LOOK[s].label}</span>
        ))}
      </div>
      <Problem error={matrix.error} />
      {m && m.people.length === 0 && <div className="card small">Nobody matches. Try fewer filters.</div>}
      {m && m.people.length > 0 && (
        <div className="overflow-x-auto">
          <table className="tbl matrix">
            <thead>
              <tr>
                <th>Person</th>
                <th>Roles</th>
                {m.competencies.map((c) => <th key={c.key} className="c" scope="col">{c.name}</th>)}
              </tr>
            </thead>
            <tbody>
              {m.people.map((p) => (
                <tr key={p.code}>
                  <td><b>{p.name}</b><div className="small">{p.code}</div></td>
                  <td className="small">{p.roles.map((r) => r.name).join(", ") || "No role yet"}</td>
                  {m.competencies.map((c) => {
                    const cell = p.cells[c.key];
                    const look = LOOK[cell.status];
                    const says = `${p.name}, ${c.name}: ${describe(cell)}`;
                    return (
                      <td key={c.key}>
                        <button type="button" className={`cell t-${look.tone}`} title={says} aria-label={says}
                                onClick={() => setOpen({ code: p.code, key: c.key })}>{look.short}</button>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {row && competency && m && (
        <HistoryDrawer person={row} competency={competency} cell={row.cells[competency.key]} today={m.today}
                       onClose={() => setOpen(null)} onChanged={matrix.reload} />
      )}
    </main>
  );
}
```

`apps/desktop/src/pages/HistoryDrawer.tsx`:
```tsx
import { useState, type FormEvent } from "react";
import { api } from "../api/client";
import type { Cell, CompetencyRecord, CompetencyRef, PersonRef } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { LOOK, describe, formatDate } from "../lib/status";
import { useAction, useLoad } from "../lib/useLoad";
import { Drawer, Problem } from "../ui/Drawer";

/** One person's history for one competency, newest first: the first row is
 * the one that counts. A manager records a completion or revokes one here. */
export function HistoryDrawer({ person, competency, cell, today, onClose, onChanged }: {
  person: PersonRef; competency: CompetencyRef; cell: Cell; today: string;
  onClose: () => void; onChanged: () => void;
}) {
  const { me, can } = useAuth();
  const path = `/v1/people/${encodeURIComponent(person.code)}/records`;
  const history = useLoad(() => api.get<CompetencyRecord[]>(path, { competency: competency.key }),
                          [path, competency.key]);
  const [grantedOn, setGrantedOn] = useState(today);
  const [expiresOn, setExpiresOn] = useState("");
  const [note, setNote] = useState("");
  const [why, setWhy] = useState("");
  const action = useAction();
  const own = me?.code === person.code;
  const granted = history.data?.[0]?.kind === "granted";

  async function changed(fn: () => Promise<unknown>) {
    if (await action.run(fn)) {
      setNote("");
      setWhy("");
      setExpiresOn("");
      history.reload();
      onChanged();
    }
  }

  function record(e: FormEvent) {
    e.preventDefault();
    void changed(() => api.post(path, {
      competency: competency.key, granted_on: grantedOn, expires_on: expiresOn || null, note: note.trim() || null,
    }));
  }

  function revoke(e: FormEvent) {
    e.preventDefault();
    void changed(() => api.post(`${path}/revoke`, { competency: competency.key, note: why.trim() }));
  }

  return (
    <Drawer title={competency.name} sub={`${person.name} · ${person.code}`} onClose={onClose}>
      <div className="flex items-center gap-2">
        <span className={`pill t-${LOOK[cell.status].tone}`}>{LOOK[cell.status].label}</span>
        <span className="small">{describe(cell)}</span>
      </div>
      <Problem error={action.error ?? history.error} />
      {can("records:write") && own && (
        <div className="msg r">Nobody records their own competency: ask another manager.</div>
      )}
      {can("records:write") && !own && (
        <form className="card flex flex-col gap-3" onSubmit={record}>
          <div className="eyebrow">Record completion</div>
          <div className="grid grid-cols-2 gap-3">
            <label className="label">Completed on
              <input className="field" type="date" max={today} value={grantedOn}
                     onChange={(e) => setGrantedOn(e.target.value)} required />
            </label>
            <label className="label">Good until (optional)
              <input className="field" type="date" value={expiresOn} onChange={(e) => setExpiresOn(e.target.value)} />
            </label>
          </div>
          <div className="small">Leave “Good until” empty to use the competency's refresher, or for no expiry.</div>
          <label className="label">Note (optional)
            <input className="field" value={note} maxLength={500} onChange={(e) => setNote(e.target.value)}
                   placeholder="e.g. licence number, who ran the session" />
          </label>
          <button type="submit" className="btn primary" disabled={action.busy}>Record completion</button>
        </form>
      )}
      {can("records:write") && granted && (
        <form className="card flex flex-col gap-3" onSubmit={revoke}>
          <div className="eyebrow">Revoke</div>
          <label className="label">Why
            <input className="field" value={why} maxLength={500} onChange={(e) => setWhy(e.target.value)}
                   placeholder="e.g. ticked for the wrong person" required />
          </label>
          <button type="submit" className="btn danger" disabled={action.busy || !why.trim()}>Revoke</button>
        </form>
      )}
      <section className="flex flex-col gap-2" aria-label="History">
        <div className="eyebrow">History</div>
        {history.data?.length === 0 && <div className="small">Nothing recorded yet.</div>}
        {history.data?.map((r, i) => (
          <div key={r.id} className="card flex flex-col gap-1" style={{ opacity: i === 0 ? 1 : 0.75 }}>
            <div className="flex items-center gap-2">
              <span className={`pill ${r.kind === "granted" ? "t-green" : "t-red"}`}>
                {r.kind === "granted" ? "Completed" : "Revoked"}</span>
              {r.kind === "granted" && (
                <span className="text-sm">{formatDate(r.granted_on)}
                  {r.expires_on && <> · good until {formatDate(r.expires_on)}</>}</span>
              )}
              {i === 0 && <span className="small ml-auto">Counts now</span>}
            </div>
            {r.note && <div className="text-sm">{r.note}</div>}
            <div className="small">by {r.recorded_by.name} · {formatDate(r.created_at.slice(0, 10))}</div>
          </div>
        ))}
      </section>
    </Drawer>
  );
}
```

**Step 4: Run them to see them pass**

Run: `cd apps/desktop && npm test && npm run typecheck`
Expected: `Tests  15 passed (15)`, and the typecheck prints nothing.

**Step 5: Commit**

```
git add apps/desktop/src
git commit -m "Sign in to the desktop and see the matrix, with each cell's history" \
  -m "A manager records a completion or revokes one from the cell's drawer, never their own. A learner signing in here is sent to the learner app. Filter by role, supervisor or status, and export the CSV."
```

---

### Task 17: People, Roles and Competencies on the desktop

**Files:**
- Create: `apps/desktop/src/pages/People.tsx`, `apps/desktop/src/pages/Roles.tsx`, `apps/desktop/src/pages/Competencies.tsx`
- Modify: `apps/desktop/src/App.tsx` (replace)
- Test: `apps/desktop/src/test/People.test.tsx`

**Step 1: Write the failing test**

`apps/desktop/src/test/People.test.tsx`:
```tsx
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Person } from "../api/types";
import { json, renderApp, stubApi } from "./harness";

const SAM: Person = {
  id: 3, code: "SV001", name: "Sam Vu", email: "sam@example.com.au", permission: "supervisor", supervisor: null,
  roles: [], active: true, has_pin: true, pin_locked: false, has_password: true,
};
const KIM: Person = {
  ...SAM, id: 4, code: "LL042", name: "Kim Lee", email: null, permission: "learner",
  supervisor: { code: "SV001", name: "Sam Vu" }, roles: [{ key: "picker", name: "Picker" }], has_password: false,
};
const PICKER = { id: 1, key: "picker", name: "Picker", competencies: [], people: 0 };

describe("people", () => {
  it("adds a learner with a PIN, a supervisor and a role", async () => {
    let people = [SAM];
    const { calls } = stubApi((method, url) => {
      if (method === "GET" && url.startsWith("/v1/people?")) return json(200, { items: people, total: people.length });
      if (url === "/v1/roles") return json(200, { items: [PICKER], total: 1 });
      if (method === "POST" && url === "/v1/people") { people = [KIM, SAM]; return json(201, KIM); }
      if (url === "/v1/people/LL042") return json(200, KIM);
      if (url === "/v1/people/LL042/overrides") return json(200, []);
      if (url.startsWith("/v1/competencies")) return json(200, { items: [], total: 0 });
      return null;
    });
    renderApp("/people");
    await userEvent.click(await screen.findByRole("button", { name: "Add person" }));
    const drawer = await screen.findByRole("dialog", { name: "Add person" });
    await userEvent.type(within(drawer).getByLabelText("Code"), "LL042");
    await userEvent.type(within(drawer).getByLabelText("Name"), "Kim Lee");
    await userEvent.selectOptions(within(drawer).getByLabelText("Supervisor"), "SV001");
    await userEvent.type(within(drawer).getByLabelText("PIN (4 to 8 digits)"), "2468");
    await userEvent.click(await within(drawer).findByLabelText("Picker"));
    await userEvent.click(within(drawer).getByRole("button", { name: "Add person" }));

    expect(calls.find((c) => c.method === "POST")?.body).toEqual({
      code: "LL042", name: "Kim Lee", email: null, permission: "learner", supervisor: "SV001",
      roles: ["picker"], pin: "2468", password: null,
    });
    // the new person opens, ready for extras, waivers and the rest
    expect(await screen.findByRole("dialog", { name: "Kim Lee" })).toBeInTheDocument();
    expect(screen.getByRole("row", { name: /Kim Lee/ })).toBeInTheDocument();
  });

  it("offers a manager learner and supervisor only", async () => {
    stubApi((_method, url) => {
      if (url.startsWith("/v1/people?")) return json(200, { items: [SAM], total: 1 });
      if (url === "/v1/roles") return json(200, { items: [], total: 0 });
      return null;
    });
    renderApp("/people");
    await userEvent.click(await screen.findByRole("button", { name: "Add person" }));
    const options = within(await screen.findByLabelText("Permission")).getAllByRole("option");
    expect(options.map((o) => o.textContent)).toEqual(["learner", "supervisor"]);
  });
});
```

**Step 2: Run it to see it fail**

Run: `cd apps/desktop && npm test -- People`
Expected: FAIL, `Unable to find an accessible element with the role "button" and name "Add person"` (`/people` falls through to the matrix).

**Step 3: Minimal implementation**

`apps/desktop/src/pages/People.tsx`:
```tsx
import { useState, type FormEvent } from "react";
import { api } from "../api/client";
import type { Competency, Override, Page, Permission, Person, Role } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { useAction, useLoad } from "../lib/useLoad";
import { Drawer, Problem } from "../ui/Drawer";

const PERMISSIONS: Permission[] = ["learner", "supervisor", "manager", "admin"];
const SUPERVISES: Permission[] = ["supervisor", "manager", "admin"];

/** People: added, changed, deactivated. Never deleted. */
export function People() {
  const { can } = useAuth();
  const [q, setQ] = useState("");
  const [showInactive, setShowInactive] = useState(false);
  const [open, setOpen] = useState<string | "new" | null>(null);
  const people = useLoad(() => api.get<Page<Person>>("/v1/people", { q, active: showInactive ? undefined : true }),
                         [q, showInactive]);
  const everyone = useLoad(() => api.get<Page<Person>>("/v1/people", { active: true }), []);
  const supervisors = (everyone.data?.items ?? []).filter((p) => SUPERVISES.includes(p.permission));
  const changed = () => { people.reload(); everyone.reload(); };

  return (
    <main className="page">
      <div className="flex flex-wrap items-end gap-3">
        <h1 className="mr-auto">People</h1>
        <input className="field" style={{ width: 260 }} placeholder="Search code, name or email" aria-label="Search"
               value={q} onChange={(e) => setQ(e.target.value)} />
        <label className="small flex items-center gap-2">
          <input type="checkbox" checked={showInactive} onChange={(e) => setShowInactive(e.target.checked)} />
          Show deactivated</label>
        {can("people:write") && <button type="button" className="btn primary" onClick={() => setOpen("new")}>Add person</button>}
      </div>
      <Problem error={people.error} />
      <table className="tbl">
        <thead><tr><th>Name</th><th>Code</th><th>Permission</th><th>Roles</th><th>Supervisor</th><th>Sign-in</th></tr></thead>
        <tbody>
          {people.data?.items.map((p) => (
            <tr key={p.code} className="click" onClick={() => setOpen(p.code)}>
              <td><b>{p.name}</b>{!p.active && <span className="pill t-grey ml-2">Deactivated</span>}</td>
              <td>{p.code}</td>
              <td>{p.permission}</td>
              <td className="small">{p.roles.map((r) => r.name).join(", ")}</td>
              <td className="small">{p.supervisor?.name ?? ""}</td>
              <td className="small">
                {[p.has_pin && "PIN", p.has_password && "password"].filter(Boolean).join(" and ") || "none"}
                {p.pin_locked && <span className="pill t-red ml-2">PIN locked</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {open === "new" && (
        <NewPerson supervisors={supervisors} onClose={() => setOpen(null)}
                   onDone={(code) => { changed(); setOpen(code); }} />
      )}
      {open && open !== "new" && (
        <PersonDrawer code={open} supervisors={supervisors} onClose={() => setOpen(null)} onChanged={changed} />
      )}
    </main>
  );
}

function usePermissionsICanGive(): Permission[] {
  const { me } = useAuth();
  return me?.permission === "admin" ? PERMISSIONS : ["learner", "supervisor"];
}

function SupervisorSelect({ value, onChange, supervisors, not }: {
  value: string; onChange: (v: string) => void; supervisors: Person[]; not?: string;
}) {
  return (
    <label className="label">Supervisor
      <select className="field" value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">Nobody</option>
        {supervisors.filter((s) => s.code !== not).map((s) => <option key={s.code} value={s.code}>{s.name}</option>)}
      </select>
    </label>
  );
}

function RoleBoxes({ roles, chosen, onChange }: { roles: Role[]; chosen: string[]; onChange: (keys: string[]) => void }) {
  return (
    <fieldset className="flex flex-col gap-1">
      <legend className="label mb-1">Roles</legend>
      {roles.length === 0 && <div className="small">No roles yet: add them under Roles.</div>}
      {roles.map((r) => (
        <label key={r.key} className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={chosen.includes(r.key)}
                 onChange={(e) => onChange(e.target.checked ? [...chosen, r.key] : chosen.filter((k) => k !== r.key))} />
          {r.name}
        </label>
      ))}
    </fieldset>
  );
}

function NewPerson({ supervisors, onClose, onDone }: {
  supervisors: Person[]; onClose: () => void; onDone: (code: string) => void;
}) {
  const roles = useLoad(() => api.get<Page<Role>>("/v1/roles"), []);
  const permissions = usePermissionsICanGive();
  const [f, setF] = useState({ code: "", name: "", email: "", permission: "learner" as Permission,
                               supervisor: "", pin: "", password: "" });
  const [chosen, setChosen] = useState<string[]>([]);
  const action = useAction();
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });

  async function submit(e: FormEvent) {
    e.preventDefault();
    let code = "";
    const ok = await action.run(async () => {
      const out = await api.post<Person>("/v1/people", {
        code: f.code, name: f.name, email: f.email || null, permission: f.permission,
        supervisor: f.supervisor || null, roles: chosen, pin: f.pin || null, password: f.password || null,
      });
      code = out.code;
    });
    if (ok) onDone(code);
  }

  return (
    <Drawer title="Add person" onClose={onClose}>
      <form className="flex flex-col gap-3" onSubmit={submit}>
        <div className="grid grid-cols-2 gap-3">
          <label className="label">Code<input className="field" value={f.code} onChange={set("code")} placeholder="e.g. LL042" required /></label>
          <label className="label">Name<input className="field" value={f.name} onChange={set("name")} required /></label>
        </div>
        <label className="label">Email (optional)<input className="field" type="email" value={f.email} onChange={set("email")} /></label>
        <div className="grid grid-cols-2 gap-3">
          <label className="label">Permission
            <select className="field" value={f.permission} onChange={set("permission")}>
              {permissions.map((p) => <option key={p} value={p}>{p}</option>)}
            </select>
          </label>
          <SupervisorSelect value={f.supervisor} onChange={(v) => setF({ ...f, supervisor: v })} supervisors={supervisors} />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <label className="label">PIN (4 to 8 digits)
            <input className="field" inputMode="numeric" pattern="[0-9]{4,8}" value={f.pin} onChange={set("pin")} />
          </label>
          <label className="label">Password (12 or more)
            <input className="field" type="password" minLength={12} autoComplete="new-password" value={f.password} onChange={set("password")} />
          </label>
        </div>
        <RoleBoxes roles={roles.data?.items ?? []} chosen={chosen} onChange={setChosen} />
        <Problem error={action.error} />
        <button type="submit" className="btn primary" disabled={action.busy}>Add person</button>
      </form>
    </Drawer>
  );
}

function PersonDrawer({ code, supervisors, onClose, onChanged }: {
  code: string; supervisors: Person[]; onClose: () => void; onChanged: () => void;
}) {
  const { me } = useAuth();
  const path = `/v1/people/${encodeURIComponent(code)}`;
  const person = useLoad(() => api.get<Person>(path), [path]);
  const roles = useLoad(() => api.get<Page<Role>>("/v1/roles"), []);
  const competencies = useLoad(() => api.get<Page<Competency>>("/v1/competencies", { active: true }), []);
  const overrides = useLoad(() => api.get<Override[]>(`${path}/overrides`), [path]);
  const permissions = usePermissionsICanGive();
  const action = useAction();
  const [said, setSaid] = useState<string | null>(null);
  const p = person.data;
  if (!p) return <Drawer title={code} onClose={onClose}><Problem error={person.error} /></Drawer>;
  const mine = me?.permission === "admin" || !["manager", "admin"].includes(p.permission);

  async function change(what: string, fn: () => Promise<unknown>) {
    setSaid(null);
    if (await action.run(fn)) {
      setSaid(what);
      person.reload();
      overrides.reload();
      onChanged();
    }
  }

  return (
    <Drawer title={p.name} sub={`${p.code} · ${p.permission}${p.active ? "" : " · deactivated"}`} onClose={onClose}>
      <Problem error={action.error} />
      {said && <div className="msg g" role="status">{said}</div>}
      {!mine && <div className="msg r">Only an admin can change a manager or an admin.</div>}
      {mine && (
        <>
          <Details key={`d${p.code}${p.name}${p.email}${p.permission}${p.supervisor?.code}`} person={p}
                   permissions={permissions} supervisors={supervisors} busy={action.busy}
                   onSave={(body) => change("Saved.", () => api.patch(path, body))} />
          <RolesCard key={`r${p.roles.map((r) => r.key).join()}`} person={p} roles={roles.data?.items ?? []} busy={action.busy}
                 onSave={(keys) => change("Roles saved.", () => api.put(`${path}/roles`, { roles: keys }))} />
          <Overrides current={overrides.data ?? []} competencies={competencies.data?.items ?? []} busy={action.busy}
                     onAdd={(body) => change("Saved.", () => api.post(`${path}/overrides`, body))} />
          <Secret label={p.pin_locked ? "New PIN (unlocks it)" : "New PIN"} kind="pin" busy={action.busy}
                  onSave={(pin) => change("PIN set.", () => api.post(`${path}/pin`, { pin }))} />
          <Secret label="New password" kind="password" busy={action.busy}
                  onSave={(password) => change("Password set.", () => api.post(`${path}/password`, { password }))} />
          <div>
            {p.active
              ? <button type="button" className="btn danger" disabled={action.busy}
                        onClick={() => void change("Deactivated. Their records stay.", () => api.post(`${path}/deactivate`))}>Deactivate</button>
              : <button type="button" className="btn" disabled={action.busy}
                        onClick={() => void change("Reactivated.", () => api.post(`${path}/reactivate`))}>Reactivate</button>}
          </div>
        </>
      )}
    </Drawer>
  );
}

function Details({ person, permissions, supervisors, busy, onSave }: {
  person: Person; permissions: Permission[]; supervisors: Person[]; busy: boolean; onSave: (body: unknown) => void;
}) {
  const [name, setName] = useState(person.name);
  const [email, setEmail] = useState(person.email ?? "");
  const [permission, setPermission] = useState(person.permission);
  const [supervisor, setSupervisor] = useState(person.supervisor?.code ?? "");
  return (
    <form className="card flex flex-col gap-3" onSubmit={(e) => {
      e.preventDefault();
      onSave({ name, email: email || null, permission, supervisor: supervisor || null });
    }}>
      <div className="eyebrow">Details</div>
      <label className="label">Name<input className="field" value={name} onChange={(e) => setName(e.target.value)} required /></label>
      <label className="label">Email<input className="field" type="email" value={email} onChange={(e) => setEmail(e.target.value)} /></label>
      <div className="grid grid-cols-2 gap-3">
        <label className="label">Permission
          <select className="field" value={permission} onChange={(e) => setPermission(e.target.value as Permission)}>
            {permissions.map((x) => <option key={x} value={x}>{x}</option>)}
          </select>
        </label>
        <SupervisorSelect value={supervisor} onChange={setSupervisor} supervisors={supervisors} not={person.code} />
      </div>
      <button type="submit" className="btn primary" disabled={busy}>Save details</button>
    </form>
  );
}

function RolesCard({ person, roles, busy, onSave }: { person: Person; roles: Role[]; busy: boolean; onSave: (keys: string[]) => void }) {
  const [chosen, setChosen] = useState(person.roles.map((r) => r.key));
  return (
    <div className="card flex flex-col gap-3">
      <RoleBoxes roles={roles} chosen={chosen} onChange={setChosen} />
      <button type="button" className="btn" disabled={busy} onClick={() => onSave(chosen)}>Save roles</button>
    </div>
  );
}

function Overrides({ current, competencies, busy, onAdd }: {
  current: Override[]; competencies: Competency[]; busy: boolean;
  onAdd: (body: { competency: string; kind: string; note: string }) => void;
}) {
  const [competency, setCompetency] = useState("");
  const [kind, setKind] = useState("extra");
  const [note, setNote] = useState("");
  return (
    <form className="card flex flex-col gap-3" onSubmit={(e) => {
      e.preventDefault();
      onAdd({ competency, kind, note: note.trim() });
      setNote("");
    }}>
      <div className="eyebrow">Extras and waivers</div>
      {current.length === 0 && <div className="small">None: their roles decide what they need.</div>}
      {current.map((o) => (
        <div key={o.id} className="text-sm">
          <span className={`pill ${o.kind === "extra" ? "t-amber" : "t-grey"}`}>{o.kind === "extra" ? "Extra" : "Waived"}</span>{" "}
          <b>{o.competency.name}</b> · {o.note} <span className="small">({o.recorded_by.name})</span>
        </div>
      ))}
      <div className="grid grid-cols-2 gap-3">
        <label className="label">Competency
          <select className="field" value={competency} onChange={(e) => setCompetency(e.target.value)} required>
            <option value="">Choose…</option>
            {competencies.map((c) => <option key={c.key} value={c.key}>{c.name}</option>)}
          </select>
        </label>
        <label className="label">What
          <select className="field" value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="extra">Extra: needed by them too</option>
            <option value="waive">Waive: not needed by them</option>
            <option value="clear">Clear: back to their roles</option>
          </select>
        </label>
      </div>
      <label className="label">Note<input className="field" value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} required /></label>
      <button type="submit" className="btn" disabled={busy || !note.trim() || !competency}>Save</button>
    </form>
  );
}

function Secret({ label, kind, busy, onSave }: { label: string; kind: "pin" | "password"; busy: boolean; onSave: (v: string) => void }) {
  const [value, setValue] = useState("");
  return (
    <form className="card flex items-end gap-3" onSubmit={(e) => { e.preventDefault(); onSave(value); setValue(""); }}>
      <label className="label flex-1">{label}
        {kind === "pin"
          ? <input className="field" inputMode="numeric" pattern="[0-9]{4,8}" value={value} onChange={(e) => setValue(e.target.value)} required />
          : <input className="field" type="password" minLength={12} autoComplete="new-password" value={value} onChange={(e) => setValue(e.target.value)} required />}
      </label>
      <button type="submit" className="btn" disabled={busy}>Set {kind === "pin" ? "PIN" : "password"}</button>
    </form>
  );
}
```

`apps/desktop/src/pages/Roles.tsx`:
```tsx
import { useState, type FormEvent } from "react";
import { api } from "../api/client";
import type { Competency, Page, Role } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { useAction, useLoad } from "../lib/useLoad";
import { Drawer, Problem } from "../ui/Drawer";

/** Roles, and the competencies each requires. */
export function Roles() {
  const { can } = useAuth();
  const roles = useLoad(() => api.get<Page<Role>>("/v1/roles"), []);
  const [open, setOpen] = useState<string | null>(null);
  const [key, setKey] = useState("");
  const [name, setName] = useState("");
  const action = useAction();
  const role = roles.data?.items.find((r) => r.key === open);

  async function add(e: FormEvent) {
    e.preventDefault();
    if (await action.run(() => api.post("/v1/roles", { key, name }))) {
      setOpen(key.trim().toLowerCase());
      setKey("");
      setName("");
      roles.reload();
    }
  }

  return (
    <main className="page">
      <h1>Roles</h1>
      {can("roles:write") && (
        <form className="flex flex-wrap items-end gap-3" onSubmit={add}>
          <label className="label">Key<input className="field" value={key} onChange={(e) => setKey(e.target.value)} placeholder="forklift-operator" required /></label>
          <label className="label">Name<input className="field" value={name} onChange={(e) => setName(e.target.value)} placeholder="Forklift operator" required /></label>
          <button type="submit" className="btn primary" disabled={action.busy}>Add role</button>
        </form>
      )}
      <Problem error={action.error ?? roles.error} />
      <table className="tbl">
        <thead><tr><th>Role</th><th>Requires</th><th>People</th></tr></thead>
        <tbody>
          {roles.data?.items.map((r) => (
            <tr key={r.key} className="click" onClick={() => setOpen(r.key)}>
              <td><b>{r.name}</b><div className="small">{r.key}</div></td>
              <td className="small">{r.competencies.map((c) => c.name).join(", ") || "Nothing yet"}</td>
              <td>{r.people}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {role && <RoleDrawer key={role.key} role={role} onClose={() => setOpen(null)} onChanged={roles.reload} />}
    </main>
  );
}

function RoleDrawer({ role, onClose, onChanged }: { role: Role; onClose: () => void; onChanged: () => void }) {
  const { can } = useAuth();
  const competencies = useLoad(() => api.get<Page<Competency>>("/v1/competencies", { active: true }), []);
  const [name, setName] = useState(role.name);
  const [chosen, setChosen] = useState(role.competencies.map((c) => c.key));
  const action = useAction();
  const [saved, setSaved] = useState(false);
  const path = `/v1/roles/${encodeURIComponent(role.key)}`;

  async function save(e: FormEvent) {
    e.preventDefault();
    setSaved(false);
    const ok = await action.run(async () => {
      if (name !== role.name) await api.patch(path, { name });
      await api.put(`${path}/requirements`, { competencies: chosen });
    });
    if (ok) { setSaved(true); onChanged(); }
  }

  return (
    <Drawer title={role.name} sub={`${role.key} · ${role.people} ${role.people === 1 ? "person" : "people"}`} onClose={onClose}>
      <form className="flex flex-col gap-3" onSubmit={save}>
        <label className="label">Name<input className="field" value={name} onChange={(e) => setName(e.target.value)} disabled={!can("roles:write")} required /></label>
        <fieldset className="card flex flex-col gap-1">
          <legend className="eyebrow">Requires</legend>
          {competencies.data?.items.map((c) => (
            <label key={c.key} className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={chosen.includes(c.key)} disabled={!can("roles:write")}
                     onChange={(e) => setChosen(e.target.checked ? [...chosen, c.key] : chosen.filter((k) => k !== c.key))} />
              {c.name} <span className="small">{c.kind}</span>
            </label>
          ))}
        </fieldset>
        <Problem error={action.error} />
        {saved && <div className="msg g" role="status">Saved. The matrix shows it now.</div>}
        {can("roles:write") && <button type="submit" className="btn primary" disabled={action.busy}>Save</button>}
      </form>
    </Drawer>
  );
}
```

`apps/desktop/src/pages/Competencies.tsx`:
```tsx
import { useState, type FormEvent } from "react";
import { api } from "../api/client";
import type { Competency, Kind, Page } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { useAction, useLoad } from "../lib/useLoad";
import { Drawer, Problem } from "../ui/Drawer";

const KINDS: { kind: Kind; label: string }[] = [
  { kind: "module", label: "Online module" },
  { kind: "practical", label: "Practical sign-off" },
  { kind: "ticket", label: "Ticket or licence" },
  { kind: "policy", label: "Signed policy" },
];
const kindLabel = (k: Kind) => KINDS.find((x) => x.kind === k)?.label ?? k;
const months = (n: number | null) => (n ? `Every ${n} months` : "None");

/** Competencies: in step 1 just what each is called, its kind and its refresher. */
export function Competencies() {
  const { can } = useAuth();
  const list = useLoad(() => api.get<Page<Competency>>("/v1/competencies"), []);
  const [open, setOpen] = useState<string | null>(null);
  const [f, setF] = useState({ key: "", name: "", kind: "module" as Kind, refresher: "" });
  const action = useAction();
  const competency = list.data?.items.find((c) => c.key === open);

  async function add(e: FormEvent) {
    e.preventDefault();
    const ok = await action.run(() => api.post("/v1/competencies", {
      key: f.key, name: f.name, kind: f.kind, refresher_months: f.refresher ? Number(f.refresher) : null,
    }));
    if (ok) { setF({ key: "", name: "", kind: "module", refresher: "" }); list.reload(); }
  }

  return (
    <main className="page">
      <h1>Competencies</h1>
      {can("competencies:write") && (
        <form className="flex flex-wrap items-end gap-3" onSubmit={add}>
          <label className="label">Key<input className="field" value={f.key} onChange={(e) => setF({ ...f, key: e.target.value })} placeholder="site-induction" required /></label>
          <label className="label">Name<input className="field" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder="Site induction" required /></label>
          <label className="label">Kind
            <select className="field" value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value as Kind })}>
              {KINDS.map((k) => <option key={k.kind} value={k.kind}>{k.label}</option>)}
            </select>
          </label>
          <label className="label">Refresher (months)
            <input className="field" style={{ width: 120 }} type="number" min={1} max={240} value={f.refresher}
                   onChange={(e) => setF({ ...f, refresher: e.target.value })} />
          </label>
          <button type="submit" className="btn primary" disabled={action.busy}>Add competency</button>
        </form>
      )}
      <Problem error={action.error ?? list.error} />
      <table className="tbl">
        <thead><tr><th>Competency</th><th>Kind</th><th>Refresher</th><th></th></tr></thead>
        <tbody>
          {list.data?.items.map((c) => (
            <tr key={c.key} className="click" onClick={() => setOpen(c.key)}>
              <td><b>{c.name}</b><div className="small">{c.key}</div></td>
              <td>{kindLabel(c.kind)}</td>
              <td>{months(c.refresher_months)}</td>
              <td>{!c.active && <span className="pill t-grey">Deactivated</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {competency && can("competencies:write") && (
        <CompetencyDrawer key={competency.key} competency={competency} onClose={() => setOpen(null)} onChanged={list.reload} />
      )}
    </main>
  );
}

function CompetencyDrawer({ competency, onClose, onChanged }: {
  competency: Competency; onClose: () => void; onChanged: () => void;
}) {
  const [name, setName] = useState(competency.name);
  const [refresher, setRefresher] = useState(competency.refresher_months?.toString() ?? "");
  const action = useAction();
  const path = `/v1/competencies/${encodeURIComponent(competency.key)}`;
  const done = async (fn: () => Promise<unknown>) => { if (await action.run(fn)) onChanged(); };

  return (
    <Drawer title={competency.name} sub={`${competency.key} · ${kindLabel(competency.kind)}`} onClose={onClose}>
      <form className="flex flex-col gap-3" onSubmit={(e) => {
        e.preventDefault();
        void done(() => api.patch(path, { name, refresher_months: refresher ? Number(refresher) : null }));
      }}>
        <label className="label">Name<input className="field" value={name} onChange={(e) => setName(e.target.value)} required /></label>
        <label className="label">Refresher (months; empty for none)
          <input className="field" type="number" min={1} max={240} value={refresher} onChange={(e) => setRefresher(e.target.value)} />
        </label>
        <div className="small">A new refresher changes everyone's status at once: status is worked out, never stored.</div>
        <Problem error={action.error} />
        <button type="submit" className="btn primary" disabled={action.busy}>Save</button>
      </form>
      {competency.active
        ? <button type="button" className="btn danger" disabled={action.busy}
                  onClick={() => void done(() => api.post(`${path}/deactivate`))}>Deactivate: no longer asked of anyone</button>
        : <button type="button" className="btn" disabled={action.busy}
                  onClick={() => void done(() => api.post(`${path}/reactivate`))}>Reactivate</button>}
    </Drawer>
  );
}
```

`apps/desktop/src/App.tsx` (replace):
```tsx
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider } from "./auth/AuthContext";
import { RequireAuth } from "./auth/RequireAuth";
import { Competencies } from "./pages/Competencies";
import { Matrix } from "./pages/Matrix";
import { People } from "./pages/People";
import { Roles } from "./pages/Roles";
import { SignIn } from "./pages/SignIn";
import { Layout } from "./ui/Layout";

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/sign-in" element={<SignIn />} />
      <Route element={<RequireAuth />}>
        <Route element={<Layout />}>
          <Route index element={<Matrix />} />
          <Route path="/people" element={<People />} />
          <Route path="/roles" element={<Roles />} />
          <Route path="/competencies" element={<Competencies />} />
        </Route>
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <AppRoutes />
      </AuthProvider>
    </BrowserRouter>
  );
}
```

**Step 4: Run it to see it pass, and build**

Run: `cd apps/desktop && npm test && npm run build`
Expected: `Tests  17 passed (17)`, then `✓ built in …` with `dist/index.html` and `dist/assets/index-….js`.

**Step 5: Commit**

```
git add apps/desktop/src
git commit -m "Look after people, roles and competencies from the desktop" \
  -m "Add and edit people, their roles, supervisor, extras and waivers, PIN and password, and deactivate them; the competencies each role requires; and each competency's name and refresher."
```

---

### Task 18: The learner app's skeleton, its client and My training's three parts

**Files:**
- Create: `apps/learner/package.json`, `apps/learner/vite.config.ts`, `apps/learner/tsconfig.json`, `apps/learner/index.html`
- Create: `apps/learner/public/favicon.svg`, `apps/learner/public/manifest.webmanifest`
- Create: `apps/learner/src/vite-env.d.ts`, `apps/learner/src/index.css`, `apps/learner/src/test/setup.ts`
- Create: `apps/learner/src/api/client.ts`, `apps/learner/src/api/types.ts`, `apps/learner/src/lib/training.ts`
- Test: `apps/learner/src/test/training.test.ts`

**Step 1: The project**

`apps/learner/package.json` (the desktop's, renamed, with `--host` so a phone on the LAN can reach `npm run dev`):
```json
{
  "name": "simple-lms-learner",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite --host",
    "build": "tsc -b && vite build",
    "preview": "vite preview --host",
    "test": "vitest run",
    "typecheck": "tsc -b"
  },
  "dependencies": {
    "@fontsource/manrope": "^5.3.0",
    "react": "^19.1.0",
    "react-dom": "^19.1.0",
    "react-router-dom": "^7.6.0"
  },
  "devDependencies": {
    "@tailwindcss/vite": "^4.1.0",
    "@testing-library/jest-dom": "^6.6.0",
    "@testing-library/react": "^16.3.0",
    "@testing-library/user-event": "^14.6.0",
    "@types/react": "^19.1.0",
    "@types/react-dom": "^19.1.0",
    "@vitejs/plugin-react": "^4.5.0",
    "jsdom": "^26.1.0",
    "tailwindcss": "^4.1.0",
    "typescript": "^5.8.0",
    "vite": "^6.3.0",
    "vitest": "^3.2.0"
  }
}
```

`apps/learner/vite.config.ts`:
```ts
/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Vite runs this under Node; the app itself never sees process.
declare const process: { env: Record<string, string | undefined> };

const api = { "/v1": { target: process.env.LMS_API_URL ?? "http://127.0.0.1:8033", changeOrigin: true } };

// Served by Caddy at /learn/ (deploy/Caddyfile). `npm run dev` and
// `npm run preview` send /v1 to the API, so a phone can be pointed at either.
export default defineConfig({
  base: "/learn/",
  plugins: [react(), tailwindcss()],
  server: { port: 5177, proxy: api },
  preview: { port: 4177, proxy: api },
  build: { outDir: "dist", sourcemap: false },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: false,
    testTimeout: 20000,
  },
});
```

`apps/learner/tsconfig.json`, `apps/learner/src/vite-env.d.ts` and `apps/learner/public/favicon.svg`: the desktop's:
```
mkdir -p apps/learner/public apps/learner/src/test
cp apps/desktop/tsconfig.json apps/learner/tsconfig.json
cp apps/desktop/src/vite-env.d.ts apps/learner/src/vite-env.d.ts
cp apps/desktop/public/favicon.svg apps/learner/public/favicon.svg
```

`apps/learner/index.html`:
```html
<!doctype html>
<html lang="en-AU">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover" />
    <meta name="color-scheme" content="light" />
    <meta name="theme-color" content="#F3F5F8" />
    <meta name="mobile-web-app-capable" content="yes" />
    <meta name="apple-mobile-web-app-capable" content="yes" />
    <title>My training</title>
    <link rel="icon" href="/learn/favicon.svg" type="image/svg+xml" />
    <link rel="apple-touch-icon" href="/learn/icon-192.png" />
    <link rel="manifest" href="/learn/manifest.webmanifest" />
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

`apps/learner/public/manifest.webmanifest`:
```json
{
  "name": "Simple LMS: my training",
  "short_name": "My training",
  "description": "What you are current for, and what is due.",
  "start_url": "/learn/",
  "scope": "/learn/",
  "display": "standalone",
  "orientation": "portrait",
  "background_color": "#F3F5F8",
  "theme_color": "#F3F5F8",
  "icons": [
    { "src": "/learn/icon-192.png", "sizes": "192x192", "type": "image/png" },
    { "src": "/learn/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable" }
  ]
}
```

`apps/learner/src/test/setup.ts`:
```ts
import "@testing-library/jest-dom/vitest";

afterEach(() => {
  window.localStorage.clear();
  vi.unstubAllGlobals();
});
```

`apps/learner/src/index.css`:
```css
@import "tailwindcss";

/* The desktop's colours (apps/desktop/src/index.css), phone first: big
 * buttons, one thing at a time. */
@theme {
  --color-page: #F3F5F8;
  --color-ink: #17202B;
  --color-ink-2: #48566A;
  --color-muted: #5B6778;
  --color-blue: #2F6FB8;
  --color-blue-dark: #23558E;
  --color-tint: #E8F0FA;
  --color-line: #DCE3EC;
  --color-line-2: #C8D3E0;
  --color-green-ink: #146B45;
  --color-green-bg: #E3F3EA;
  --color-amber-ink: #8A5A00;
  --color-amber-bg: #FFF3D6;
  --color-red-ink: #A3242C;
  --color-red-bg: #FCE9EA;
  --font-sans: Manrope, ui-sans-serif, system-ui, sans-serif;
}

@layer base {
  html, body, #root { min-height: 100%; }
  body { margin: 0; background: var(--color-page); color: var(--color-ink); font-family: var(--font-sans); -webkit-font-smoothing: antialiased; -webkit-tap-highlight-color: transparent; }
  :focus-visible { outline: 3px solid rgba(47, 111, 184, 0.45); outline-offset: 2px; }
  button, input { font: inherit; color: inherit; }
}

@layer components {
  .screen { max-width: 480px; margin: 0 auto; min-height: 100vh; padding: max(16px, env(safe-area-inset-top)) 16px 32px; display: flex; flex-direction: column; gap: 16px; }
  .top { display: flex; align-items: center; gap: 10px; font-size: 17px; font-weight: 800; }
  .chip { margin-left: auto; padding: 6px 12px; border-radius: 999px; background: var(--color-tint); color: var(--color-blue-dark); font-size: 13px; font-weight: 800; }
  .input { height: 56px; padding: 0 16px; border: 1px solid var(--color-line-2); border-radius: 14px; background: #fff; font-size: 18px; width: 100%; }
  .label { display: flex; flex-direction: column; gap: 6px; font-size: 14px; font-weight: 800; }
  .big { height: 60px; border-radius: 16px; border: 0; font-size: 18px; font-weight: 800; cursor: pointer; width: 100%; }
  .big.primary { background: var(--color-blue); color: #fff; }
  .big:disabled { opacity: 0.55; }
  .link { background: none; border: 0; color: var(--color-blue-dark); font-weight: 700; cursor: pointer; padding: 8px; }
  .msg { font-size: 14px; border-radius: 12px; padding: 10px 12px; }
  .msg.r { background: var(--color-red-bg); color: var(--color-red-ink); }
  .group h2 { margin: 0 0 8px; font-size: 15px; font-weight: 800; display: flex; gap: 8px; align-items: center; }
  .count { padding: 1px 9px; border-radius: 999px; font-size: 13px; }
  .item { background: #fff; border: 1px solid var(--color-line); border-radius: 16px; padding: 14px 16px; display: flex; flex-direction: column; gap: 2px; }
  .item + .item { margin-top: 8px; }
  .item b { font-size: 16px; }
  .item span { font-size: 14px; color: var(--color-ink-2); }
  .t-red { background: var(--color-red-bg); color: var(--color-red-ink); }
  .t-amber { background: var(--color-amber-bg); color: var(--color-amber-ink); }
  .t-green { background: var(--color-green-bg); color: var(--color-green-ink); }
}
```

Install:
```
cd apps/learner && npm install
```

**Step 2: Write the failing test**

`apps/learner/src/test/training.test.ts`:
```ts
import type { TrainingItem } from "../api/types";
import { groupTraining, whenLine } from "../lib/training";

const item = (name: string, status: TrainingItem["status"], expires_on: string | null = null): TrainingItem =>
  ({ key: name.toLowerCase().replace(/ /g, "-"), name, kind: "ticket", status, granted_on: null, expires_on });

describe("My training", () => {
  it("puts lapsed and missing in Overdue, expiring in Due soon and current in Done", () => {
    const g = groupTraining([
      item("WHS policy", "missing"),
      item("First aid", "lapsed", "2026-09-30"),
      item("Site induction", "expiring", "2026-11-01"),
      item("Forklift licence", "current", "2031-03-01"),
      item("Fire warden", "lapsed", "2026-01-15"),
      item("Manual handling", "expiring", "2026-10-20"),
      item("Chemical handling", "missing"),
      item("Code of conduct", "current"),
    ]);
    expect(g.overdue.map((i) => i.name)).toEqual(["Fire warden", "First aid", "Chemical handling", "WHS policy"]);
    expect(g.dueSoon.map((i) => i.name)).toEqual(["Manual handling", "Site induction"]);
    expect(g.done.map((i) => i.name)).toEqual(["Code of conduct", "Forklift licence"]);
  });

  it("is empty in every part when there is nothing to do", () => {
    expect(groupTraining([])).toEqual({ overdue: [], dueSoon: [], done: [] });
  });

  it("says when, the Australian way", () => {
    expect(whenLine(item("A", "lapsed", "2026-09-30"))).toBe("Ran out after 30 Sep 2026");
    expect(whenLine(item("A", "missing"))).toBe("Not done yet");
    expect(whenLine(item("A", "expiring", "2026-11-01"))).toBe("Due by 1 Nov 2026");
    expect(whenLine(item("A", "current", "2031-03-01"))).toBe("Done · good until 1 Mar 2031");
    expect(whenLine(item("A", "current"))).toBe("Done · doesn't run out");
  });
});
```

**Step 3: Run it to see it fail**

Run: `cd apps/learner && npm test`
Expected: FAIL, `Failed to resolve import "../lib/training"`.

**Step 4: Minimal implementation**

`apps/learner/src/api/types.ts`:
```ts
/** What the API answers: docs/api.md. */

export type Status = "current" | "expiring" | "lapsed" | "missing";

export interface Me {
  id: number;
  code: string;
  name: string;
  email: string | null;
  permission: string;
  method: "password" | "pin";
  scopes: string[];
  idle_seconds: number;
}

export interface SessionOut { token: string; person: Me }

export interface TrainingItem {
  key: string;
  name: string;
  kind: "module" | "practical" | "ticket" | "policy";
  status: Status;
  granted_on: string | null;
  expires_on: string | null;
}

export interface Training {
  person: { code: string; name: string };
  today: string;
  items: TrainingItem[];
}
```

`apps/learner/src/api/client.ts`:
```ts
/** The learner app is an ordinary API client with a session token, however
 * the person signed in. Nothing here a partner could not do (rule 4). */

export class ApiError extends Error {
  status: number;
  /** The API's reason when it gives one: wrong_pin, wrong_password, locked, ... */
  code: string | null;
  constructor(status: number, body: unknown) {
    const detail = (body as { detail?: unknown })?.detail;
    super(typeof detail === "string" ? detail : `Simple LMS answered ${status}`);
    this.status = status;
    const code = (body as { code?: unknown })?.code;
    this.code = typeof code === "string" ? code : null;
  }
}

/** No signal, or no proper answer. */
export class Unreachable extends Error {
  constructor() {
    super("No signal: Simple LMS can't be reached right now.");
  }
}

type Fetcher = (url: string, init: RequestInit) => Promise<Response>;
const SIGN_INS = new Set(["/v1/auth/login", "/v1/auth/pin-login"]);

export class LearnerApi {
  token: string | null = null;
  /** The API no longer takes the token: idle too long, or the PIN changed. */
  onSignedOut: (() => void) | null = null;
  private fetcher: Fetcher;

  constructor(fetcher?: Fetcher) {
    this.fetcher = fetcher ?? ((url, init) => fetch(url, init));
  }

  async request<T>(method: string, path: string, body?: unknown): Promise<T> {
    const headers: Record<string, string> = { Accept: "application/json" };
    if (body !== undefined) headers["Content-Type"] = "application/json";
    if (this.token) headers.Authorization = `Bearer ${this.token}`;
    let res: Response;
    try {
      res = await this.fetcher(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
    } catch {
      throw new Unreachable();
    }
    if (res.status === 401 && !SIGN_INS.has(path)) this.onSignedOut?.();
    if (res.status === 204) return undefined as T;
    let parsed: unknown;
    try {
      const text = await res.text();
      parsed = text ? JSON.parse(text) : null;
    } catch {
      throw new Unreachable();
    }
    if (!res.ok) throw new ApiError(res.status, parsed);
    return parsed as T;
  }

  get<T>(path: string) { return this.request<T>("GET", path); }
  post<T>(path: string, body: unknown = {}) { return this.request<T>("POST", path, body); }
}

export const api = new LearnerApi();
```

`apps/learner/src/lib/training.ts`:
```ts
/** My training in three parts, the way the learner reads it. */
import type { TrainingItem } from "../api/types";

export interface Groups {
  /** lapsed or never done: oldest lapse first, then the missing by name */
  overdue: TrainingItem[];
  /** expiring within 30 days: soonest first */
  dueSoon: TrainingItem[];
  /** current: by name */
  done: TrainingItem[];
}

const byName = (a: TrainingItem, b: TrainingItem) => a.name.localeCompare(b.name);
const byExpiry = (a: TrainingItem, b: TrainingItem) =>
  (a.expires_on ?? "").localeCompare(b.expires_on ?? "") || byName(a, b);

export function groupTraining(items: TrainingItem[]): Groups {
  const lapsed = items.filter((i) => i.status === "lapsed").sort(byExpiry);
  const missing = items.filter((i) => i.status === "missing").sort(byName);
  return {
    overdue: [...lapsed, ...missing],
    dueSoon: items.filter((i) => i.status === "expiring").sort(byExpiry),
    done: items.filter((i) => i.status === "current").sort(byName),
  };
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export function formatDate(iso: string | null): string {
  if (!iso) return "";
  const [y, m, d] = iso.split("-").map(Number);
  return `${d} ${MONTHS[m - 1]} ${y}`;
}

/** The line under each item's name. */
export function whenLine(item: TrainingItem): string {
  switch (item.status) {
    case "lapsed":
      return `Ran out after ${formatDate(item.expires_on)}`;
    case "missing":
      return "Not done yet";
    case "expiring":
      return `Due by ${formatDate(item.expires_on)}`;
    case "current":
      return item.expires_on ? `Done · good until ${formatDate(item.expires_on)}` : "Done · doesn't run out";
  }
}
```

**Step 5: Run it to see it pass**

Run: `cd apps/learner && npm test`
Expected: `Tests  3 passed (3)`.

**Step 6: Commit**

```
git add apps/learner
git commit -m "Start the learner app: its client, and My training as Overdue, Due soon and Done" \
  -m "Lapsed first by how long ago, then what was never done; due soon by date; done by name."
```

---

### Task 19: Sign in on the phone or a shared tablet, and My training

**Files:**
- Create: `apps/learner/src/main.tsx`, `apps/learner/src/App.tsx`, `apps/learner/src/ui.tsx`
- Create: `apps/learner/src/auth/Session.tsx`
- Create: `apps/learner/src/pages/SignIn.tsx`, `apps/learner/src/pages/MyTraining.tsx`
- Test: `apps/learner/src/test/harness.tsx`, `apps/learner/src/test/learner.test.tsx`

**Step 1: Write the failing tests**

`apps/learner/src/test/harness.tsx`:
```tsx
import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { AppRoutes } from "../App";
import { SessionProvider } from "../auth/Session";
import type { Me } from "../api/types";

export function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

export const KIM: Me = {
  id: 4, code: "LL042", name: "Kim Lee", email: null, permission: "learner", method: "pin",
  scopes: ["training:read"], idle_seconds: 900,
};

export interface Call { method: string; url: string; body: unknown }
type Handler = (method: string, url: string, body: unknown) => Response | null;

export function stubApi(more: Handler) {
  const calls: Call[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit = {}) => {
    const method = init.method ?? "GET";
    const body = init.body ? JSON.parse(init.body as string) : undefined;
    calls.push({ method, url, body });
    return more(method, url, body) ?? json(404, { detail: `no stub for ${method} ${url}` });
  }));
  return calls;
}

/** Signed in already when `who` is given, as if the app had been opened again. */
export function renderApp(who: Me | null = null, activeAt = Date.now()) {
  if (who) window.localStorage.setItem("lms.learner.session", JSON.stringify({ token: "lms_s.kim", person: who, active_at: activeAt }));
  return render(
    <MemoryRouter>
      <SessionProvider>
        <AppRoutes />
      </SessionProvider>
    </MemoryRouter>,
  );
}
```

`apps/learner/src/test/learner.test.tsx`:
```tsx
import { act, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { json, KIM, renderApp, stubApi } from "./harness";

const TRAINING = {
  person: { code: "LL042", name: "Kim Lee" },
  today: "2026-10-12",
  items: [
    { key: "first-aid", name: "First aid", kind: "ticket", status: "lapsed", granted_on: "2023-09-30", expires_on: "2026-09-30" },
    { key: "forklift-licence", name: "Forklift licence", kind: "ticket", status: "current", granted_on: "2026-03-01", expires_on: "2031-03-01" },
    { key: "site-induction", name: "Site induction", kind: "module", status: "expiring", granted_on: "2024-11-01", expires_on: "2026-11-01" },
    { key: "whs-policy", name: "WHS policy", kind: "policy", status: "missing", granted_on: null, expires_on: null },
  ],
};

function answers(_method: string, url: string) {
  if (url === "/v1/auth/pin-login") return json(200, { token: "lms_s.kim", person: KIM });
  if (url === "/v1/people/LL042/training") return json(200, TRAINING);
  if (url === "/v1/auth/logout") return new Response(null, { status: 204 });
  return null;
}

describe("the learner app", () => {
  it("signs in with a code and PIN and shows My training in three parts", async () => {
    const calls = stubApi(answers);
    renderApp();
    await userEvent.type(await screen.findByLabelText("Your code"), "ll042");
    await userEvent.type(screen.getByLabelText("PIN"), "2468");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("heading", { name: "My training" })).toBeInTheDocument();
    expect(calls[0].body).toEqual({ code: "ll042", pin: "2468" });

    const overdue = await screen.findByRole("region", { name: "Overdue" });
    expect(within(overdue).getAllByText(/First aid|WHS policy/).map((e) => e.textContent)).toEqual(["First aid", "WHS policy"]);
    expect(within(overdue).getByText("Ran out after 30 Sep 2026")).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "Due soon" })).getByText("Due by 1 Nov 2026")).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "Done" })).getByText("Forklift licence")).toBeInTheDocument();
  });

  it("can sign in with an email and password instead", async () => {
    const calls = stubApi((method, url) => url === "/v1/auth/login"
      ? json(200, { token: "lms_s.kim", person: { ...KIM, method: "password", idle_seconds: 43200 } })
      : answers(method, url));
    renderApp();
    await userEvent.click(await screen.findByRole("button", { name: "Sign in with email and password" }));
    await userEvent.type(screen.getByLabelText("Email"), "kim@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "correct horse battery");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("heading", { name: "My training" })).toBeInTheDocument();
    expect(calls[0]).toMatchObject({ url: "/v1/auth/login", body: { email: "kim@example.com" } });
  });

  it("says when the PIN is wrong or locked", async () => {
    let code = "wrong_pin";
    stubApi((_m, url) => url === "/v1/auth/pin-login"
      ? json(401, { detail: "this PIN is locked after too many wrong tries; ask your manager to reset it", code }) : null);
    renderApp();
    await userEvent.type(await screen.findByLabelText("Your code"), "LL042");
    await userEvent.type(screen.getByLabelText("PIN"), "0000");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Wrong code or PIN.");
    code = "locked";
    await userEvent.type(screen.getByLabelText("PIN"), "0000");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("This PIN is locked after too many wrong tries; ask your manager to reset it.");
  });

  it("goes back to sign-in when the API ends the session", async () => {
    stubApi((_m, url) => url === "/v1/people/LL042/training" ? json(401, { detail: "session expired or invalid" }) : null);
    renderApp(KIM);
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    expect(window.localStorage.getItem("lms.learner.session")).toBeNull();
  });

  it("forgets whoever left the tablet alone for 15 minutes", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      stubApi(answers);
      renderApp(KIM);
      expect(await screen.findByRole("heading", { name: "My training" })).toBeInTheDocument();
      await act(async () => { vi.advanceTimersByTime(14 * 60_000); });
      expect(screen.getByRole("heading", { name: "My training" })).toBeInTheDocument();
      await act(async () => { vi.advanceTimersByTime(2 * 60_000); });
      expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("does not pick up a session left idle too long", async () => {
    stubApi(answers);
    renderApp(KIM, Date.now() - 16 * 60_000);
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
  });
});
```

**Step 2: Run them to see them fail**

Run: `cd apps/learner && npm test`
Expected: FAIL, `Failed to resolve import "../App"` (and `"../auth/Session"`) in `harness.tsx`.

**Step 3: Minimal implementation**

`apps/learner/src/main.tsx` (Task 20 registers the service worker):
```tsx
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "@fontsource/manrope/latin-400.css";
import "@fontsource/manrope/latin-600.css";
import "@fontsource/manrope/latin-700.css";
import "@fontsource/manrope/latin-800.css";
import "./index.css";
import { App } from "./App";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
```

`apps/learner/src/App.tsx`:
```tsx
import { BrowserRouter, Navigate, Outlet, Route, Routes } from "react-router-dom";
import { SessionProvider, useSession } from "./auth/Session";
import { MyTraining } from "./pages/MyTraining";
import { SignIn } from "./pages/SignIn";

function RequirePerson() {
  const { person } = useSession();
  return person ? <Outlet /> : <Navigate to="/sign-in" replace />;
}

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/sign-in" element={<SignIn />} />
      <Route element={<RequirePerson />}>
        <Route index element={<MyTraining />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export function App() {
  return (
    <BrowserRouter basename="/learn">
      <SessionProvider>
        <AppRoutes />
      </SessionProvider>
    </BrowserRouter>
  );
}
```

`apps/learner/src/ui.tsx`:
```tsx
export function Logo({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
      <path d="M3 7 15 10V28L3 25Z" fill="#5B93D6" />
      <path d="M29 7 17 10V28L29 25Z" fill="#2F6FB8" />
      <path d="M19.5 17.5 22 20l4.5-6" fill="none" stroke="#E8F0FA" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
```

`apps/learner/src/auth/Session.tsx`:
```tsx
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api } from "../api/client";
import type { Me, SessionOut } from "../api/types";

interface Stored { token: string; person: Me; active_at: number }

interface State {
  person: Me | null;
  signInWithPin: (code: string, pin: string) => Promise<void>;
  signInWithPassword: (email: string, password: string) => Promise<void>;
  signOut: () => void;
}

const Ctx = createContext<State | null>(null);
const KEY = "lms.learner.session";
// how often the app checks whether it has been left alone too long
const CHECK_EVERY_MS = 15_000;

function idleTooLong(s: Stored, now = Date.now()): boolean {
  return now - s.active_at > s.person.idle_seconds * 1000;
}

function read(): Stored | null {
  try {
    const s = JSON.parse(window.localStorage.getItem(KEY) ?? "null") as Stored | null;
    return s && !idleTooLong(s) ? s : null;
  } catch {
    return null;
  }
}

function write(s: Stored | null) {
  try {
    if (s) window.localStorage.setItem(KEY, JSON.stringify(s));
    else window.localStorage.removeItem(KEY);
  } catch { /* private mode: signed in for this page only */ }
}

/** Who is signed in on this device. On a shared tablet the app forgets them
 * after the session's idle time (15 minutes for a PIN), as the API does, so
 * the next person never sees the last one's training. */
export function SessionProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Stored | null>(() => {
    const s = read();
    api.token = s?.token ?? null;
    return s;
  });

  const signOut = useCallback(() => {
    const token = api.token;
    api.token = null;
    write(null);
    setSession(null);
    // tell the API too; signed out here whatever it says
    if (token) void fetch("/v1/auth/logout", { method: "POST", headers: { Authorization: `Bearer ${token}` } }).catch(() => undefined);
  }, []);

  useEffect(() => {
    api.onSignedOut = signOut;
  }, [signOut]);

  useEffect(() => {
    if (!session) return;
    const touch = () => {
      const s = { ...session, active_at: Date.now() };
      write(s);
      session.active_at = s.active_at;
    };
    const check = setInterval(() => { if (idleTooLong(session)) signOut(); }, CHECK_EVERY_MS);
    window.addEventListener("pointerdown", touch);
    window.addEventListener("keydown", touch);
    return () => {
      clearInterval(check);
      window.removeEventListener("pointerdown", touch);
      window.removeEventListener("keydown", touch);
    };
  }, [session, signOut]);

  const signedIn = useCallback((out: SessionOut) => {
    const s = { token: out.token, person: out.person, active_at: Date.now() };
    api.token = s.token;
    write(s);
    setSession(s);
  }, []);

  const signInWithPin = useCallback(async (code: string, pin: string) => {
    signedIn(await api.post<SessionOut>("/v1/auth/pin-login", { code, pin }));
  }, [signedIn]);

  const signInWithPassword = useCallback(async (email: string, password: string) => {
    signedIn(await api.post<SessionOut>("/v1/auth/login", { email, password }));
  }, [signedIn]);

  const value = useMemo<State>(() => ({ person: session?.person ?? null, signInWithPin, signInWithPassword, signOut }),
                               [session, signInWithPin, signInWithPassword, signOut]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useSession(): State {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useSession outside SessionProvider");
  return ctx;
}
```

`apps/learner/src/pages/SignIn.tsx`:
```tsx
import { useState, type FormEvent } from "react";
import { Navigate } from "react-router-dom";
import { ApiError } from "../api/client";
import { useSession } from "../auth/Session";
import { Logo } from "../ui";

function refusal(e: unknown): string {
  if (!(e instanceof ApiError)) return (e as Error).message;
  if (e.code === "wrong_pin") return "Wrong code or PIN.";
  if (e.code === "wrong_password") return "Wrong email or password.";
  if (e.code === "locked") return e.message.charAt(0).toUpperCase() + e.message.slice(1) + ".";
  return e.message;
}

/** Code and PIN first (a shared tablet, a phone); email and password for those who have one. */
export function SignIn() {
  const { person, signInWithPin, signInWithPassword } = useSession();
  const [withPassword, setWithPassword] = useState(false);
  const [who, setWho] = useState("");
  const [secret, setSecret] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (person) return <Navigate to="/" replace />;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (withPassword) await signInWithPassword(who.trim(), secret);
      else await signInWithPin(who.trim(), secret);
    } catch (err) {
      setError(refusal(err));
      setSecret("");
    } finally {
      setBusy(false);
    }
  }

  function switchWay() {
    setWithPassword(!withPassword);
    setWho("");
    setSecret("");
    setError(null);
  }

  return (
    <main className="screen">
      <div className="top"><Logo />Simple LMS<span className="chip">My training</span></div>
      <h1 style={{ margin: "8px 0 0", fontSize: 28, fontWeight: 800 }}>Sign in</h1>
      <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        {withPassword ? (
          <>
            <label className="label">Email
              <input className="input" type="email" autoComplete="username" value={who} onChange={(e) => setWho(e.target.value)} required />
            </label>
            <label className="label">Password
              <input className="input" type="password" autoComplete="current-password" value={secret}
                     onChange={(e) => setSecret(e.target.value)} required />
            </label>
          </>
        ) : (
          <>
            <label className="label">Your code
              <input className="input" autoComplete="username" autoCapitalize="characters" autoCorrect="off" spellCheck={false}
                     placeholder="e.g. LL042" value={who} onChange={(e) => setWho(e.target.value)} required />
            </label>
            <label className="label">PIN
              <input className="input" type="password" inputMode="numeric" autoComplete="current-password" maxLength={8}
                     value={secret} onChange={(e) => setSecret(e.target.value.replace(/\D/g, ""))} required />
            </label>
          </>
        )}
        {error && <div className="msg r" role="alert">{error}</div>}
        <button type="submit" className="big primary" disabled={busy || !who.trim() || (!withPassword && secret.length < 4)}>
          Sign in</button>
      </form>
      <button type="button" className="link" onClick={switchWay}>
        {withPassword ? "Sign in with your code and PIN" : "Sign in with email and password"}</button>
      <p className="small" style={{ textAlign: "center", color: "var(--color-muted)", fontSize: 13, marginTop: "auto" }}>
        On a shared tablet you're signed out after 15 minutes without a tap. Forgotten your PIN? Ask your manager.
      </p>
    </main>
  );
}
```

`apps/learner/src/pages/MyTraining.tsx`:
```tsx
import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import type { Training, TrainingItem } from "../api/types";
import { useSession } from "../auth/Session";
import { groupTraining, whenLine } from "../lib/training";
import { Logo } from "../ui";

function Group({ title, tone, items, empty }: { title: string; tone: string; items: TrainingItem[]; empty: string }) {
  return (
    <section className="group" aria-label={title}>
      <h2>{title}<span className={`count ${tone}`}>{items.length}</span></h2>
      {items.length === 0 && <div className="small" style={{ color: "var(--color-muted)" }}>{empty}</div>}
      {items.map((i) => (
        <div key={i.key} className="item"><b>{i.name}</b><span>{whenLine(i)}</span></div>
      ))}
    </section>
  );
}

/** Read only in step 1: what is overdue, what is due soon and what is done. */
export function MyTraining() {
  const { person, signOut } = useSession();
  const [training, setTraining] = useState<Training | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setTraining(await api.get<Training>(`/v1/people/${encodeURIComponent(person!.code)}/training`));
    } catch (e) {
      setError((e as Error).message);
    }
  }, [person]);

  useEffect(() => { void load(); }, [load]);

  const g = training ? groupTraining(training.items) : null;
  return (
    <main className="screen">
      <div className="top"><Logo />{person?.name}
        <button type="button" className="chip" style={{ border: 0, cursor: "pointer" }} onClick={signOut}>Sign out</button>
      </div>
      <h1 style={{ margin: 0, fontSize: 26, fontWeight: 800 }}>My training</h1>
      {error && (
        <>
          <div className="msg r" role="alert">{error}</div>
          <button type="button" className="big primary" onClick={() => void load()}>Try again</button>
        </>
      )}
      {!g && !error && <div style={{ color: "var(--color-muted)" }}>Loading…</div>}
      {g && training!.items.length === 0 && (
        <div className="item"><b>Nothing to do</b><span>Nothing is asked of you yet. Check with your supervisor.</span></div>
      )}
      {g && training!.items.length > 0 && (
        <>
          <Group title="Overdue" tone="t-red" items={g.overdue} empty="Nothing overdue." />
          <Group title="Due soon" tone="t-amber" items={g.dueSoon} empty="Nothing due in the next 30 days." />
          <Group title="Done" tone="t-green" items={g.done} empty="Nothing done yet." />
        </>
      )}
    </main>
  );
}
```

**Step 4: Run them to see them pass**

Run: `cd apps/learner && npm test && npm run typecheck`
Expected: `Tests  9 passed (9)`, and the typecheck prints nothing.

**Step 5: Commit**

```
git add apps/learner/src
git commit -m "Sign in with a code and PIN or an email and password, and see My training" \
  -m "Read only in step 1. The device forgets whoever left it alone for the session's idle time, so a shared tablet never shows the last person's training."
```

---

### Task 20: The service worker and the icons: the learner app installs and opens fast

**Files:**
- Create: `apps/learner/public/sw.js`
- Create: `apps/learner/scripts/make_icons.py`, `apps/learner/public/icon-192.png`, `apps/learner/public/icon-512.png`
- Modify: `apps/learner/src/main.tsx`

**Step 1: Write them**

`apps/learner/public/sw.js` (Simple TMS's driver app's, at `/learn/`; it never keeps an API answer):
```js
/* The learner app's service worker: keeps the app shell on the phone or
 * tablet, as the Simple TMS driver app does, so the app opens quickly and
 * says plainly when there is no signal. API calls (/v1) always go to the
 * network: My training is never kept. The page is fetched fresh whenever
 * there is signal, so a new build arrives the next time the app is opened. */
const CACHE = "lms-learner-v1";
const BASE = "/learn/";
const SHELL = [BASE, `${BASE}manifest.webmanifest`, `${BASE}favicon.svg`, `${BASE}icon-192.png`, `${BASE}icon-512.png`];
const ASSET = /\/learn\/assets\/[^"'()\s]+/g;
const PAGE_WAIT_MS = 4000;

async function assetsOf(response) {
  if (!response) return [];
  return [...new Set((await response.clone().text()).match(ASSET) ?? [])];
}

/** The page's scripts and styles, and the fonts its styles name; and none of
 * an older build's. */
async function keepAssets(page) {
  const cache = await caches.open(CACHE);
  const wanted = new Set(await assetsOf(page));
  for (const css of [...wanted].filter((a) => a.endsWith(".css"))) {
    let res = await cache.match(css);
    if (!res) {
      res = await fetch(css);
      if (res.ok) await cache.put(css, res.clone());
    }
    for (const a of await assetsOf(res)) wanted.add(a);
  }
  for (const a of wanted) {
    if (!(await cache.match(a))) {
      const res = await fetch(a);
      if (res.ok) await cache.put(a, res);
    }
  }
  for (const req of await cache.keys()) {
    const path = new URL(req.url).pathname;
    if (path.startsWith(`${BASE}assets/`) && !wanted.has(path)) await cache.delete(req);
  }
}

self.addEventListener("install", (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE);
    // past the browser's own cache, so a new worker never keeps an old page
    await cache.addAll(SHELL.map((u) => new Request(u, { cache: "no-cache" })));
    await keepAssets(await cache.match(BASE));
    await self.skipWaiting();
  })());
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    for (const key of await caches.keys()) if (key !== CACHE) await caches.delete(key);
    await self.clients.claim();
  })());
});

function timeout(ms) {
  return new Promise((_, reject) => setTimeout(() => reject(new Error("slow")), ms));
}

self.addEventListener("fetch", (event) => {
  const req = event.request;
  const url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== self.location.origin || !url.pathname.startsWith(BASE)) return;

  if (req.mode === "navigate") {
    // the page: fresh when there is signal (and quickly), the kept one when not
    event.respondWith((async () => {
      try {
        // asked of the server every time (the browser's cache may only
        // answer once the server says it is unchanged); every route is the page
        const res = await Promise.race([fetch(req.url, { cache: "no-cache", credentials: "same-origin" }),
                                        timeout(PAGE_WAIT_MS)]);
        if (res.ok) {
          const cache = await caches.open(CACHE);
          await cache.put(BASE, res.clone());
          event.waitUntil(keepAssets(res.clone()).catch(() => undefined));
        }
        return res;
      } catch {
        return (await caches.match(BASE)) ?? Response.error();
      }
    })());
    return;
  }

  // a build's files never change under their name: the kept copy, else fetch and keep it
  event.respondWith((async () => {
    const hit = await caches.match(req);
    if (hit) return hit;
    const res = await fetch(req);
    if (res.ok && url.pathname.startsWith(`${BASE}assets/`)) {
      const cache = await caches.open(CACHE);
      await cache.put(req, res.clone());
    }
    return res;
  })());
});
```

`apps/learner/scripts/make_icons.py`:
```python
"""Draws public/icon-192.png and public/icon-512.png: the Simple LMS open book
from favicon.svg on the page colour, inside the middle 60 % so a maskable
crop keeps it whole. Standard library only. Run from apps/learner:
    python3 scripts/make_icons.py
"""
import struct
import zlib
from pathlib import Path

PAGE = (0xF3, 0xF5, 0xF8)
# the book's two pages in favicon.svg's 32 x 32 box, with their colours
FACES = [
    ([(3, 7), (15, 10), (15, 28), (3, 25)], (0x5B, 0x93, 0xD6)),
    ([(29, 7), (17, 10), (17, 28), (29, 25)], (0x2F, 0x6F, 0xB8)),
]
LEFT, TOP, WIDE, TALL = 3, 7, 26, 21  # the book's box in favicon units
SAMPLES = 4  # per side, per pixel: smooth edges


def inside(x: float, y: float, poly: list[tuple[float, float]]) -> bool:
    hit = False
    for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            hit = not hit
    return hit


def draw(size: int) -> bytes:
    scale = size * 0.6 / WIDE
    left = (size - WIDE * scale) / 2 - LEFT * scale
    top = (size - TALL * scale) / 2 - TOP * scale
    rows = []
    for py in range(size):
        row = bytearray([0])  # filter: none
        for px in range(size):
            totals = [0, 0, 0]
            for sy in range(SAMPLES):
                for sx in range(SAMPLES):
                    x = ((px + (sx + 0.5) / SAMPLES) - left) / scale
                    y = ((py + (sy + 0.5) / SAMPLES) - top) / scale
                    colour = next((c for poly, c in FACES if inside(x, y, poly)), PAGE)
                    for i in range(3):
                        totals[i] += colour[i]
            row += bytes(t // (SAMPLES * SAMPLES) for t in totals)
        rows.append(bytes(row))
    raw = zlib.compress(b"".join(rows), 9)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))

    header = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", raw)
            + chunk(b"IEND", b""))


if __name__ == "__main__":
    public = Path(__file__).resolve().parent.parent / "public"
    for size in (192, 512):
        (public / f"icon-{size}.png").write_bytes(draw(size))
        print(f"public/icon-{size}.png")
```

Append to `apps/learner/src/main.tsx`:
```tsx

// the app shell is kept on the device, so it opens fast (public/sw.js)
if ("serviceWorker" in navigator && import.meta.env.PROD) {
  void navigator.serviceWorker.register("/learn/sw.js", { scope: "/learn/" });
}
```

**Step 2: Draw the icons and check the build carries everything**

```
cd apps/learner && python3 scripts/make_icons.py && npm test && npm run build
ls dist/sw.js dist/manifest.webmanifest dist/icon-192.png dist/icon-512.png
grep -o '/learn/assets/index-[^"]*\.js' dist/index.html
```
Expected: `public/icon-192.png`, `public/icon-512.png`, `Tests  9 passed (9)`, `✓ built in …`, the four files listed, and one `/learn/assets/index-….js` (the service worker's `ASSET` pattern finds the build's files by that prefix).

**Step 3: Commit**

```
git add apps/learner/public apps/learner/scripts apps/learner/src/main.tsx
git commit -m "Keep the learner app's shell on the device, fetching the page fresh" \
  -m "As the Simple TMS driver app does. Answers from the API are never kept. Icons drawn with the standard library."
```

---

### Task 21: Serve both apps through Caddy, and test and build them in CI

**Files:**
- Modify: `deploy/Caddyfile` (replace)
- Modify: `docker-compose.yml` (the `caddy` volumes)
- Create: `.github/workflows/ci.yml`

**Step 1: The check that fails**

```
(cd apps/desktop && npm run build) && (cd apps/learner && npm run build)
curl -sk -o /dev/null -w '%{http_code}\n' https://localhost:8643/
curl -sk -o /dev/null -w '%{http_code}\n' https://localhost:8643/learn/
```
Expected: `404` twice (Task 13's Caddy serves only the API).

**Step 2: Implementation**

`deploy/Caddyfile`:
```
{
	# Listen on the host's ports (LMS_HTTP_PORT, LMS_HTTPS_PORT), so Simple LMS
	# can run beside a sibling's Caddy, which may already have 80 and 443.
	http_port {$LMS_HTTP_PORT:80}
	https_port {$LMS_HTTPS_PORT:443}
	# Caddy's own redirect leaves the port out, so the one below names it.
	auto_https disable_redirects
}

http://{$LMS_DOMAIN} {
	redir https://{host}:{$LMS_HTTPS_PORT:443}{uri} 308
}

{$LMS_DOMAIN} {
	encode gzip
	header {
		X-Content-Type-Options nosniff
		Referrer-Policy same-origin
	}

	# The API is the only door.
	handle /v1/* {
		reverse_proxy api:8000
	}
	handle /docs* {
		reverse_proxy api:8000
	}
	handle /openapi.json {
		reverse_proxy api:8000
	}

	# The learner app: a PWA under /learn/.
	@learnbare path /learn
	redir @learnbare /learn/ 308
	handle_path /learn/* {
		header Content-Security-Policy "default-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
		# checked on every launch, so a new build reaches the phones
		header /sw.js Cache-Control "no-cache"
		# the page names the build's files: asked after every time, never
		# taken from the browser's cache unchecked (any route is the page)
		@learnpage not path /assets/* /sw.js /manifest.webmanifest /favicon.svg /icon-192.png /icon-512.png
		header @learnpage Cache-Control "no-cache"
		root * /srv/learner
		try_files {path} /index.html
		file_server
	}

	# The desktop: everything else.
	handle {
		# Only the desktop: the API's /docs page loads its scripts from a CDN.
		header Content-Security-Policy "default-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
		@desktoppage not path /assets/* /favicon.svg
		header @desktoppage Cache-Control "no-cache"
		root * /srv/desktop
		try_files {path} /index.html
		file_server
	}
}
```

In `docker-compose.yml`, the `caddy` service's `volumes` become:
```yaml
    volumes:
      - ./deploy/Caddyfile:/etc/caddy/Caddyfile:ro
      # the desktop, built on the host: cd apps/desktop && npm run build
      - ./apps/desktop/dist:/srv/desktop:ro
      # the learner app, built on the host: cd apps/learner && npm run build
      - ./apps/learner/dist:/srv/learner:ro
      - caddy_data:/data
      - caddy_config:/config
```

`.github/workflows/ci.yml`:
```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:

# One run per branch: a new push cancels the one before it.
concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  api:
    name: API
    runs-on: ubuntu-latest
    services:
      db:
        image: postgres:16
        env:
          POSTGRES_DB: lms
          POSTGRES_USER: lms
          POSTGRES_PASSWORD: lms
        ports: ["5432:5432"]
        options: >-
          --health-cmd "pg_isready -U lms"
          --health-interval 5s
          --health-timeout 3s
          --health-retries 20
    env:
      # the suite makes and drops its own databases on this server
      TEST_DATABASE_URL: postgresql+psycopg://lms:lms@127.0.0.1:5432/lms_test
    defaults:
      run:
        working-directory: api
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
        with:
          enable-cache: true
      - name: Install
        run: uv venv -p 3.12 && uv pip install -e ".[dev]"
      - name: Tests
        run: .venv/bin/pytest -q

  desktop:
    name: Desktop app
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: apps/desktop
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 22
          cache: npm
          cache-dependency-path: apps/desktop/package-lock.json
      - run: npm ci
      - name: Tests
        run: npm test
      - name: Build
        run: npm run build

  learner:
    name: Learner app
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: apps/learner
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 22
          cache: npm
          cache-dependency-path: apps/learner/package-lock.json
      - run: npm ci
      - name: Tests
        run: npm test
      - name: Build
        run: npm run build

  compose:
    name: Docker Compose comes up
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Settings a real install needs
        run: |
          cp .env.example .env
          sed -i 's/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=ci-only-password/' .env
      - name: Up
        run: docker compose up -d --build db api
      - name: The API answers and the migrations ran
        run: |
          for i in $(seq 1 30); do
            if curl -fsS http://127.0.0.1:8033/v1/health 2>/dev/null; then ok=1; break; fi
            sleep 2
          done
          test "${ok:-0}" = 1 || (docker compose logs api; exit 1)
          # both append-only triggers are there on a real install
          docker compose exec -T db psql -U lms -d lms -tAc \
            "select count(*) from pg_trigger where tgname like '%_append_only'" | grep -qx 2
      - name: Logs on failure
        if: failure()
        run: docker compose logs
```

**Step 3: Run the check to see it pass**

```
docker compose up -d caddy --force-recreate
curl -sk -o /dev/null -w '%{http_code}\n' https://localhost:8643/
curl -sk -o /dev/null -w '%{http_code}\n' https://localhost:8643/learn/
curl -sk -o /dev/null -w '%{http_code} %{redirect_url}\n' https://localhost:8643/learn
curl -sk -I https://localhost:8643/learn/sw.js | grep -i cache-control
curl -sk https://localhost:8643/v1/health; echo
cd api && .venv/bin/python -c "import yaml" 2>/dev/null || uv pip install pyyaml
.venv/bin/python -c "import yaml; print(list(yaml.safe_load(open('../.github/workflows/ci.yml'))['jobs']))"
```
Expected: `200`, `200`, `308 https://localhost:8643/learn/`, `Cache-Control: no-cache`, `{"status":"ok"}`, then `['api', 'desktop', 'learner', 'compose']`. (PyYAML is only for this check; it is not added to `pyproject.toml`.)

**Step 4: Commit**

```
git add deploy/Caddyfile docker-compose.yml .github/workflows/ci.yml
git commit -m "Serve the desktop and the learner app at /learn/, and test and build both in CI" \
  -m "The pages are asked for afresh and sw.js is checked on every launch, so a new build arrives. CI also brings up Compose and checks both append-only triggers."
```

---

### Task 22: The README

**Files:**
- Create: `README.md`

**Step 1: Write it**

`README.md`:
````markdown
# Simple LMS

An open source, self-hosted learning management system for workplace
training: inductions, online modules, practical sign-offs, outside tickets
and licences, and signed policies. It answers one question for a business and
its auditors: is each person current for everything their job needs? It sits
beside Simple WMS, Simple TMS and Platen and works without any of them.

Status: **build step 1, the skeleton.** People with a code and PIN or an
email and password, roles and the competencies each requires, extras and
waivers, completions recorded by hand on the desktop, the matrix (with a CSV
export), and a learner app that shows each person's training. Policies,
tickets, modules, practicals, Entra sign-in and the outward links come with
the next steps in `docs/plans/2026-10-12-simple-lms-design.md`.

## What is in this repo

```
CLAUDE.md            rules for Claude Code when working here
docs/plans/          the design and the implementation plans
docs/api.md          every endpoint
.github/workflows/   CI: the tests, both apps' builds, and a Compose start
api/                 FastAPI app, migrations, tests
apps/desktop/        the desktop app (Vite + React)
apps/learner/        the learner app, a PWA at /learn/ (Vite + React)
deploy/Caddyfile     the only door in
docker-compose.yml   api, db, caddy
```

## Getting started

```
git clone https://github.com/q7-technology/simple-lms
cd simple-lms
cp .env.example .env            # set POSTGRES_PASSWORD
(cd apps/desktop && npm ci && npm run build)
(cd apps/learner && npm ci && npm run build)
docker compose up -d
docker compose exec api lms create-user --code AD001 --name "Your Name" --email you@example.com
```

The desktop is at `https://<LMS_DOMAIN>/` (default `https://localhost/`,
self-signed): sign in with that email and password and it opens on the
matrix. Add competencies, then roles and what each requires, then people.
Click a cell to see that person's history for it and record a completion.

The learner app is at `https://<LMS_DOMAIN>/learn/`. A person signs in with
their code and PIN (set when they are added, or reset by a manager under
**People**), or their email and password, and sees **My training**: Overdue,
Due soon and Done. A PIN session ends after 15 minutes without a tap, so a
shared tablet is safe. Five wrong PINs lock the PIN until a manager sets a
new one.

The API runs its migrations each time it starts; it is at `/v1`, its
interactive docs at `/docs`, and it is also published on `127.0.0.1:8033`
(`LMS_API_PORT`) for local work. Rebuild an app (`npm run build`) after
pulling changes to it; Caddy serves each `dist` as it is.

On a machine that already runs Simple WMS or Simple TMS, their Caddy has
ports 80 and 443: set `LMS_HTTP_PORT` and `LMS_HTTPS_PORT` in `.env` (say
8280 and 8643) for local work. For a real domain beside a sibling, put the
LMS site on the Caddy that holds 80 and 443 and start only
`docker compose up -d db api`, as Simple TMS's README describes.

## Who may do what

| | Learner | Supervisor | Manager | Admin |
| --- | --- | --- | --- | --- |
| See their own training | ✓ | ✓ | ✓ | ✓ |
| See the matrix | | own team | everyone | everyone |
| Add and change people, roles, competencies, extras and waivers | | | ✓ | ✓ |
| Record or revoke a completion (never their own) | | | ✓ | ✓ |
| Add or change a manager or an admin | | | | ✓ |

A supervisor's team is the people whose supervisor they are. Signing in with
a PIN only ever shows your own training, whoever you are.

## Run the API outside Docker

```
docker compose up -d db         # Postgres on 127.0.0.1:5435
cd api
uv venv -p 3.12 && uv pip install -e ".[dev]"
export LMS_DATABASE_URL=postgresql+psycopg://lms:<POSTGRES_PASSWORD>@127.0.0.1:5435/lms
.venv/bin/alembic upgrade head
.venv/bin/lms create-user --code AD001 --name "Your Name" --email you@example.com
.venv/bin/uvicorn lms.api.app:app --reload --port 8033
```

Then `npm run dev` in `apps/desktop` (http://localhost:5176) or `apps/learner`
(http://localhost:5177/learn/); both send `/v1` to `127.0.0.1:8033`.

## Tests

pytest against a real PostgreSQL, so the append-only triggers are exercised
for real. The suite creates and resets an `lms_test` database on the compose
`db` service, expecting `POSTGRES_PASSWORD=lms-dev` locally; point
`TEST_DATABASE_URL` elsewhere to use another server.

```
docker compose up -d db
cd api && .venv/bin/pytest
cd apps/desktop && npm test
cd apps/learner && npm test
```

## Stack

Python 3.12 + FastAPI · PostgreSQL 16 · Vite + React + TypeScript + Tailwind
· Docker Compose · Caddy. The same choices as Simple WMS and Simple TMS, so
one person can look after all of them.
````

**Step 2: Commit**

```
git add README.md
git commit -m "Add the README"
```

---

### Task 23: Every suite, and a clean Compose start

**Step 1: Every suite**

```
cd api && .venv/bin/pytest -q
cd ../apps/desktop && npm test && npm run build
cd ../learner && npm test && npm run build
```
Expected: `133 passed` with no warnings (they are errors in this suite), `Tests  17 passed (17)` and a build, `Tests  9 passed (9)` and a build.

**Step 2: Compose from nothing**

```
docker compose down -v
docker compose up -d --build
for i in $(seq 1 30); do curl -fsS http://127.0.0.1:8033/v1/health && break; sleep 2; done; echo
docker compose exec -T db psql -U lms -d lms -tAc \
  "select count(*) from pg_trigger where tgname like '%_append_only'"
docker compose exec api lms create-user --code AD001 --name "Leighton Lauton" \
  --email leighton@example.com.au --password 'a long enough password'
curl -sk -o /dev/null -w '%{http_code}\n' https://localhost:8643/
curl -sk -o /dev/null -w '%{http_code}\n' https://localhost:8643/learn/
```
Expected: `{"status":"ok"}`, `2`, `AD001 Leighton Lauton <leighton@example.com.au> created as admin`, `200`, `200`. Open `http://127.0.0.1:8033/docs` and check every endpoint in `docs/api.md` is listed.

`docker compose down -v` deletes the LMS database volume: on a machine with data worth keeping, use `docker compose down` and skip the user step.

Nothing to commit unless a step failed and something was fixed.

---

### Task 24: Manual walkthrough: from an empty install to a matrix that goes green, then amber and red

The stack from Task 23 is up, with the admin `AD001` (password `a long enough password`). Caddy is on `https://localhost:8643` (accept the self-signed certificate once in the browser).

**Step 1: Competencies and a role**

Open `https://localhost:8643/` and sign in as `leighton@example.com.au`. The matrix shows only you, with no columns. Under **Competencies** add:
- `site-induction`, "Site induction", Online module, refresher 24
- `forklift-licence`, "Forklift licence", Ticket or licence, no refresher

Under **Roles** add `forklift-operator`, "Forklift operator", open it, tick both competencies and **Save**. Expected: the row says "Forklift licence, Site induction".

**Step 2: A manager, a supervisor and a learner with a PIN**

Under **People**, **Add person**:
- `MG001`, "Mel Grant", `mel@example.com.au`, permission manager, password `correct horse battery`
- `SV001`, "Sam Vu", `sam@example.com.au`, permission supervisor, password `correct horse battery`
- `LL042`, "Kim Lee", supervisor Sam Vu, PIN `2468`, role Forklift operator

Expected: each opens in its drawer once added; Kim's row says "PIN" under Sign-in. Back on **Matrix**: Kim has two red cells ("Missing"); the others are grey.

**Step 3: A completion goes green, and nobody records their own**

Sign out and sign in as Mel. Click **Kim Lee × Site induction**: the drawer says "Nothing recorded yet." Record a completion on `2025-06-01` with the note "Inducted with the June group". Expected: the history shows it, marked "Counts now", and the cell turns green: "Current until 1 Jun 2027".

Click **Kim Lee × Forklift licence** and record `2026-03-01`, good until `2031-03-01`, note "LF 0012345, sighted". Expected: green, "Current until 1 Mar 2031".

For rule 3: sign in as Leighton, open **People → Mel Grant**, tick Forklift operator and **Save roles** (only an admin can change a manager). Sign in as Mel again and click **Mel Grant × Site induction**: "Nobody records their own competency: ask another manager.", and no **Record completion** form. The API says the same: `POST /v1/people/MG001/records` with Mel's token is `403 {"code": "own_record"}`.

**Step 4: The learner sees it**

Open `https://localhost:8643/learn/` (a phone on the same network works with `LMS_DOMAIN` set to the machine's name). Sign in with code `ll042` and PIN `2468`. Expected: **My training**: Overdue 0, Due soon 0, Done 2: "Forklift licence · Done · good until 1 Mar 2031" and "Site induction · Done · good until 1 Jun 2027".

Try a wrong PIN five times on a fresh sign-in: the fifth says the PIN is locked until your manager resets it. As Mel, **People → Kim Lee** shows "PIN locked"; set a new PIN `97531`. Kim signs in with it.

**Step 5: Move a date back: amber, then red**

As Mel, click **Kim Lee × Site induction** and record it again on `2024-10-25` with the note "Date was wrong: inducted October 2024". Expected: the newer row counts (the history shows both, the new one marked "Counts now"), and the cell turns amber: "Expiring: good until 25 Oct 2026". Kim's **My training** (reload the page) moves Site induction to **Due soon**, "Due by 25 Oct 2026".

Record it again on `2024-01-10`, note "Checked the sign-in sheet: January 2024". Expected: red, "Lapsed: was good until 10 Jan 2026", and Kim's list shows it under **Overdue**, "Ran out after 10 Jan 2026".

Now **Revoke** Kim's Forklift licence with the note "Card belongs to another Kim". Expected: red, "Missing"; Kim sees "Not done yet" under Overdue.

**Step 6: Filters, a supervisor, and the spreadsheet**

As Mel, set **Status** to Lapsed: only Kim. **Export CSV** downloads `matrix-<today>.csv`; open it: Kim's row reads `lapsed` and `2026-01-10` under Site induction. Sign in as Sam (the supervisor): the matrix shows only Kim, Sam's team, with no **Record completion** form in the drawer. Sign in to `/learn/` as Sam with a PIN set by Mel: My training only, and `GET /v1/matrix` with that PIN session's token is `403`.

**Step 7: Waive and tidy**

As Mel, **People → Kim Lee → Extras and waivers**: Waive Site induction with the note "Inducted at head office"; the cell goes grey "Waived" and Kim's list drops it. Clear it again ("Back to the role") and it is red once more.

Leave the stack up, or `docker compose down` (keep the volume) when done.

Nothing to commit.
