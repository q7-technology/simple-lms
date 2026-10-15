# Simple LMS step 6: Outward links — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build step 6 of `docs/plans/2026-10-12-simple-lms-design.md`: the outward links. Other systems hear what happens in Simple LMS through HMAC-signed webhooks, each event with its own id, sent through the queue and retried after 1 minute, 5, 30 and 2 hours: `competency.granted`, `competency.revoked`, `competency.expiring` (once, at 30 days), `competency.lapsed` (once) and `person.updated`. They read who is current with an API key: `GET /v1/people/{code}/competencies` and `/{key}` answer `{status, expires_on}`. A manager prints a certificate of completion or a skills card, which goes to Platen as a template name and JSON through the queue; Simple LMS never renders a document. An admin looks after the webhooks (and sees how each delivery went), the API keys and Platen's address on the existing **Settings** screen. Usable end to end: an admin adds Simple TMS's webhook and a key; Kim's forklift licence is recorded and Simple TMS hears `competency.granted`, signed; it asks `GET /v1/people/LL042/competencies/forklift-licence` and is told `expiring` until 11 Nov 2026; the daily job tells it `competency.expiring` once, then `competency.lapsed` once; Mel prints Kim's skills card on the office printer. Nothing in Simple WMS or Simple TMS changes.

**Architecture:** The same FastAPI app (`api/`, package `lms`) and the same worker. Migration `0006` adds `webhook` (where events go, the secret they are signed with, which ones), `api_key` (only a hash kept), `event_seen` (what the daily job has fired, so it fires once), and lets the `outbox` carry `webhook` and `print` rows beside its emails, a delivery naming its webhook. `lms/services/events.py` queues an event for each webhook that wants it, in the same transaction as the change that caused it; every grant and revoke calls it, and so does every change to a person. The worker signs each event as Simple WMS signs its own (`X-LMS-Signature: sha256=…`), posts it with `httpx`, and drains emails, events and print jobs a row of each in turn, as Simple TMS drains its ship calls and print jobs. The competency API takes an API key or a session; a key opens nothing else. Printing queues Platen's intake job (`template`, `version`, `printer`, `copies`, `reference`, `data`), the shape Simple WMS and Simple TMS already send, to the address in `lms/services/settings.py` (four new settings: `platen_url`, `platen_key`, write-only like the email password, `certificate_printer`, `skills_card_printer`). Status still comes only from `lms/services/status.py`. The desktop's Settings screen gains *Printing*, *Webhooks* and *API keys*; a cell's history gains **Print certificate** and a person's drawer **Print skills card**. No new screen: everything is on screens that already open as drawers over the classroom, and as pages with Game Mode off. The learner app does not change.

**Tech Stack:** as before: Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, psycopg 3, pytest against a real PostgreSQL 16; Vite 6, React 19, TypeScript 5, Tailwind 4, Vitest 3 with Testing Library; Docker Compose, Caddy 2, GitHub Actions. One new dependency, `httpx` (Simple WMS and Simple TMS use it for the same job), so the worker can post; its tests use `httpx.MockTransport`, so nothing leaves the machine.

---

## Context

The design is settled; this plan does not change any of its decisions. The decisions in the earlier plans' Contexts still hold (ports, sessions and scopes, the latest row counts, `expires_on` is the last good day, today in the Settings time zone, the person's row locked while a record is made, the outbox's backoff and keys, everyday settings read only through `settings.current()`, every screen a drawer over the classroom in Game Mode and a page without it), and the code on `main` is the truth where it went further than those plans.

**Where this sits.** This plan was written against `main` at `c193b0c` (step 3, the step 1 to 3 follow-ups, the quiz wait, Settings and Game Mode merged) and checked there. Steps 4 (practicals) and 5 (Entra) are built before it, so:

- The migration is `api/alembic/versions/0006_outward_links.py` with `revision = "0006"` and `down_revision = "0005"` (step 5's). It was validated with `down_revision = "0003b"` (the settings migration, `main`'s head); nothing in it touches what steps 4 and 5 add.
- **Step 4's sign-off grants must fire `competency.granted` too.** Wherever step 4 adds the `CompetencyRecord` for a practical signed off, Task 5 has it call `events.granted(db, r)` after `db.add(r)` and before the commit, exactly as for the other four ways in, and adds a test for it.
- Step 5 adds Entra's settings and sign-in method to the Settings screen and service. This plan adds its own keys and sections beside them; nothing here depends on Entra.
- Steps 4 and 5 add tables, scopes, settings and tests. Where a replace block below anchors on a line an earlier step has changed (the `TABLES` set in `test_migrations.py`, the manager's scopes in `sessions.py` and in the desktop's test harness, the `Settings` type and the settings fixtures, the README's status paragraph), make the same change to the line as it now stands: add to it, don't put `main`'s version back.
- The test counts are given as what this plan adds: note the counts before you start (below) as **A** (API), **D** (desktop) and **L** (learner). On `c193b0c`, where this plan was checked, they are 446, 110 and 72, and each expected count gives that figure too.

### Decisions this plan makes that the design leaves open

- **The envelope and the signature are Simple WMS's,** so a receiver written for Simple WMS's events works for these with only the header names changed. The body is `{"event_id", "event_type", "occurred_at", "data"}` (Simple WMS's warehouse, owner and external reference have nothing to say here), sent as compact JSON; `X-LMS-Signature` is `sha256=` and the hex HMAC-SHA256 of the exact bytes of the body, keyed with the webhook's secret; `X-LMS-Event-Id` and `X-LMS-Event-Type` say what it is before the body is read; `User-Agent: simple-lms/0.1`. As with Simple WMS there is no timestamp in the signature: delivery is at least once, and a receiver keeps the `event_id`s it has had. `lms/services/webhooks.py` has `verify()` (Simple TMS's, for Simple WMS's events) for the tests and for `docs/api.md`.
- **One outbox row per webhook per event, in the outbox already there.** It has the backoff, the unique key, `done_at` and the worker; a second queue would be a second copy of all of it. A delivery is `kind = 'webhook'` with `webhook_id` set (a check says only a delivery has one), its `payload` the envelope as sent and its key `event:<event id>:<webhook id>`. It is queued by `events.emit()` in the transaction that made the change, so a change that is rolled back tells nobody. The worker reads the webhook's address and secret when it sends, so a fixed address or a new secret applies to what is still waiting; a webhook turned off has what is waiting for it given up on (`failed`, "the webhook was turned off"), not tried four more times.
- **The worker drains each kind in turn.** `worker.send_due()` takes the next due row of each kind (`email`, `webhook`, `print`) in turn, up to 50 of each per pass, as Simple TMS's worker drains its ship calls and print jobs, so a Monday's 200 reminders don't hold up an event Simple TMS is waiting on. Emails still wait, untried, until an email server is set, and print jobs until Platen's address is (both read through `settings.current()`, so setting either on the Settings screen starts them within seconds); events always go. Each row is still its own transaction, and a row that fails (a refusal, a timeout, an exception) only waits for its next try. `worker.send_emails()` stays, for emails alone.
- **What each event says, and when.** `person` is `{code, name}`, `competency` is `{key, name, kind}`, `status` is what `status.py` says now (it may be `not_required` or `waived`), and `expires_on` is the last good day, worked out as `status.py` does. `competency.granted` (`record_id`, `granted_on`, `expires_on`, `status`, `recorded_by`) is fired by every way a grant is made: by hand, a ticket approved, a policy signed, a module passed, and (step 4) a practical signed off. `competency.revoked` (`record_id`, `note`, `status`, `recorded_by`) by a revoke. `person.updated` carries the person as another system keeps them (`code`, `name`, `email`, `permission`, `active`, `supervisor`, `roles`) and is fired when a person is added, their details or roles change, or they are deactivated or come back; never for a PIN or a password, which no other system should know changed. Waivers, extras and a role's requirements change what is asked of people without an event of their own: the design names five events, and the competency API says how things stand.
- **"Each once", with the design's `event_seen` table.** The daily job fires `competency.expiring` the first day it finds something within 30 days of its last good day, and `competency.lapsed` the first day it finds it past it; `events.once()` inserts `<type>:<person id>:<competency id>:<last good day>` into `event_seen` and fires only if the row is new. The key is written whether or not anyone is listening, so a webhook added later isn't sent every lapse there has ever been; a renewal has a new last good day, so it is told afresh when it comes round. Something the job first sees already past its day is told as lapsed only. The first daily run after this step tells the webhooks what is expiring or lapsed then, once. `expiring` carries `days_left`. The reminder days in Settings don't move it: "expiring" is `status.py`'s 30 days, as the design says.
- **Webhooks and API keys are on the Settings screen, an admin's (`settings:write`, which only `*` carries),** as the design's Settings lists them. They are rows of their own (`webhook`, `api_key`), not key-value settings, so they have their own routes (`/v1/webhooks`, `/v1/api-keys`) and their own sections below the everyday ones. Their secrets are treated as the email password is: a webhook's secret is made by Simple LMS (`whsec_` and 256 random bits), shown once when the webhook is made and once more each time a new one is asked for, and never returned otherwise (it is kept as it is, since the worker signs with it); an API key is shown once and only its hash kept. An address is `http://` or `https://` (a receiver on the local network may have no certificate); it is trusted admin configuration, as Platen says of its callbacks. Webhooks are turned off, never deleted, since their deliveries name them. Each shows how many deliveries are waiting and how many failed; its drawer lists the latest 50 and sends a failed one again from the start of the backoff, the same event with the same id.
- **API keys** are Simple TMS's: `lms_k.` and 256 random bits, shown once, only the SHA-256 kept, with the first ten characters kept to tell keys apart, a list of scopes, revoked (never deleted), and `last_used_at` written at most once a minute as a session's is. A key may be given one scope, `competencies:read`, and opens the competency API and nothing else: anywhere else it is `403 key_not_allowed` (and an unknown or revoked one `401`), so a leaked key can't read a module, a photo or the matrix. Keys are not sessions: `get_principal` still takes only a session, and the competency API's own dependency, `require_reader()`, takes either.
- **The competency API** is `GET /v1/people/{code}/competencies` (everything their roles and extras ask of them, waived or not, by name) and `GET /v1/people/{code}/competencies/{key}` (one, asked of them or not), each with `status`, `granted_on` and `expires_on` from `status.py`, the person's `code`, `name` and `active`, and `today`. A competency not asked of them, or deactivated, is `not_required`; someone deactivated still has their status worked out, with `active: false`, for the caller to decide. A key with `competencies:read` reads anyone; a session with `competencies:read` reads whom it may see, as the matrix does (a supervisor their team); a learner's own is `GET /v1/people/{code}/training`, as now.
- **Printing is asked for, never automatic.** Nobody wants a page out of the printer for every grant, nor for the ones recorded by hand from old paperwork. A manager (a new scope, `printing:write`, which managers and admins carry) prints a **certificate of completion** from the history of the completion that counts now (one recorded again since, or revoked, is `409 not_current`) and a **skills card**, of everything the person is current for today (`current` or `expiring`, asked of them or not, so a first aid certificate they hold is on it), from their drawer. Each is queued as Platen's intake job, the shape Simple WMS and Simple TMS send: `template` (`lms-certificate` or `lms-skills-card`, page templates made and published in Platen with those ids), `version` (`v1`), `printer`, `copies` (1), `reference` and `data`, every value text and never null so every binding has something, dates as "1 Jan 2025", a skills card's competencies in `lines` (Platen gives a page template a row for each). The worker posts it to Platen's address with `Authorization: Bearer <key>` and `X-LMS-Job-Id`; Platen's `2xx` is the end of it here (Platen's own screens say whether it printed, so the key made in Platen for Simple LMS has no callback).
- **Platen's address, key and printers are everyday settings,** in `lms/services/settings.py` with the rest: `platen_url` (Platen's intake, a web address), `platen_key` (write-only, in `SECRET` beside `smtp_password`: the screen says only whether one is set), `certificate_printer` (`office` unless changed) and `skills_card_printer` (empty: the certificates' printer), each with its `LMS_PLATEN_*` / `LMS_*_PRINTER` fallback in `.env`. Until the address is set, a print is `409 printing_not_set_up` and queued jobs wait. The webhook timeout (`LMS_WORKER_HTTP_TIMEOUT_SECONDS`, 10 seconds) is not an everyday setting and stays in `.env` only.
- **The worker can reach the machine it runs on.** Compose gives the worker `host.docker.internal` (`host-gateway`), so a webhook receiver or a Platen running on the same host, outside Compose, is `http://host.docker.internal:<port>/…` on Linux as on a Mac.
- **Desktop:** the Settings screen gains three sections after *Web address*: **Printing** (Platen's address, the key, set or not with a way to clear it, and the two printers, saved like every other section), **Webhooks** (name, address, events, failed and waiting counts, a form to add one choosing the events or *Everything*; the secret shows once with Copy and Done; a webhook's drawer changes its name, address, events and whether it is on, makes a new secret, shown once, and lists its latest deliveries with **Send again** on a failed one) and **API keys** (who each is for, its first characters, what it may do, when it was last used, and **Revoke**, which asks once: "Anything using it stops working, for good."; a new key shows once). **Print certificate** sits on the completion that counts now in a cell's history; **Print skills card** in a person's drawer; each says "Sent to Platen, for the printer office." or why not. Nothing new goes in `ui/screens.ts`: Settings, the matrix and People already open as drawers over the classroom, and as pages with Game Mode off, and a test checks the webhooks with Game Mode off.
- **Left out (YAGNI):** Platen's printed-or-failed callback; a test ping for a webhook; filtering a webhook's events by role or person; a timestamp in the signature; clearing old outbox rows; more key scopes; printing by itself on a grant; anything in the classroom for these (an admin's plumbing has no desk). Nothing in Simple WMS, Simple TMS or Platen changes.

---

## Before you start

```
cd "/Users/leightonlauton/Q7 Technology/Software/q7/simple-lms"
git switch main && git pull --ff-only
git switch -c step-6-outward-links
docker compose up -d db
(cd api && uv pip install -e ".[dev]")
(cd apps/desktop && npm ci)
(cd apps/learner && npm ci)
```

As before: `pytest` runs from `api/` against the compose `db` on 127.0.0.1:5435 (`TEST_DATABASE_URL` points it elsewhere), and `npm` commands run from the app's folder. Every test still runs on 12 October 2026, a Monday. Run the three suites and note their counts:
```
(cd api && .venv/bin/pytest -q | tail -1)
(cd apps/desktop && npm test 2>&1 | grep "Tests ")
(cd apps/learner && npm test 2>&1 | grep "Tests ")
```
Call them **A**, **D** and **L**. On `c193b0c`, where this plan was checked, they are `446 passed`, `Tests  110 passed (110)` and `Tests  72 passed (72)`; with steps 4 and 5 merged they are higher, and every count below is given as A, D or L plus what this step adds.

---

### Task 1: Webhooks, API keys and the events seen, and an outbox for all three kinds

**Files:**
- Create: `api/lms/models/links.py`, `api/alembic/versions/0006_outward_links.py`
- Modify: `api/lms/models/outbox.py`, `api/lms/models/__init__.py`
- Test: `api/tests/test_migrations.py`; create `api/tests/test_link_rows.py`

**Step 1: Write the failing tests**

In `api/tests/test_migrations.py`, replace:
```python
          "quiz_attempt", "module_progress", "setting", "alembic_version"}
```
with:
```python
          "quiz_attempt", "module_progress", "setting", "webhook", "api_key", "event_seen",
          "alembic_version"}
```
(With steps 4 and 5's tables in `TABLES` too: add the three names, keep theirs.)

`api/tests/test_link_rows.py`:
```python
"""Webhooks, their deliveries, API keys and the events the daily job has
fired: what the database itself holds to."""
import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from conftest import make_person
from lms.models import ApiKey, EventSeen, Outbox, Webhook


def hook(**more) -> Webhook:
    return Webhook(**{"name": "Simple TMS", "url": "https://tms.example.com.au/lms-events",
                      "secret": "whsec_x", "events": ["*"], **more})


@pytest.mark.parametrize("row, constraint", [
    ({"url": "ftp://tms.example.com.au"}, "ck_webhook_url"),
    ({"url": "tms.example.com.au/lms-events"}, "ck_webhook_url"),
    ({"events": []}, "ck_webhook_events"),
])
def test_a_webhook_has_a_web_address_and_wants_something(db, row, constraint):
    db.add(hook(**row))
    with pytest.raises(IntegrityError, match=constraint):
        db.commit()


def test_two_webhooks_have_two_names(db):
    db.add(hook())
    db.commit()
    db.add(hook(url="https://other.example.com.au"))
    with pytest.raises(IntegrityError, match="uq_webhook_name"):
        db.commit()


def test_a_delivery_names_its_webhook_and_an_email_names_none(db):
    w = hook()
    db.add(w)
    db.commit()
    db.add(Outbox(kind="webhook", key="event:1", payload={}))
    with pytest.raises(IntegrityError, match="ck_outbox_webhook"):
        db.commit()
    db.rollback()
    db.add(Outbox(kind="email", key="email:1", payload={}, webhook_id=w.id))
    with pytest.raises(IntegrityError, match="ck_outbox_webhook"):
        db.commit()
    db.rollback()
    db.add_all([Outbox(kind="webhook", key="event:2", payload={}, webhook_id=w.id),
                Outbox(kind="print", key="print:1", payload={})])
    db.commit()


def test_the_outbox_holds_emails_deliveries_and_print_jobs_only(db):
    db.add(Outbox(kind="sms", key="sms:1", payload={}))
    with pytest.raises(IntegrityError, match="ck_outbox_kind"):
        db.commit()


def test_an_event_is_seen_once(db):
    db.add(EventSeen(key="competency.lapsed:4:2:2026-10-11", event_id=uuid.uuid4()))
    db.commit()
    db.add(EventSeen(key="competency.lapsed:4:2:2026-10-11", event_id=uuid.uuid4()))
    with pytest.raises(IntegrityError, match="pk_event_seen"):
        db.commit()


def test_an_api_key_is_given_a_scope(db):
    admin = make_person(db, "AD001", "Leighton Lauton", "admin")
    db.add(ApiKey(name="Simple TMS", key_hash="0" * 64, prefix="lms_k.abcd", scopes=[],
                  created_by_id=admin.id))
    with pytest.raises(IntegrityError, match="ck_api_key_scopes"):
        db.commit()
```

**Step 2: Run them to see them fail**

Run: `cd api && .venv/bin/pytest tests/test_migrations.py tests/test_link_rows.py -q`
Expected: FAIL: `ImportError: cannot import name 'ApiKey' from 'lms.models'`, so the run stops while collecting the tests.

**Step 3: Minimal implementation**

`api/lms/models/links.py`:
```python
"""Simple LMS's outward links: the webhooks that hear its events, the API
keys other systems read it with, and the events the daily job has fired."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, String, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from lms.models.base import Base, created_at_column
from lms.models.people import Person


class Webhook(Base):
    """Somewhere Simple LMS sends its events: a web address, the secret each
    body is signed with, and the events it wants (`*` for all). Turned off,
    never deleted: its deliveries name it."""

    __tablename__ = "webhook"
    __table_args__ = (
        CheckConstraint("url ~ '^https?://[^[:space:]]+$'", name="url"),
        CheckConstraint("jsonb_typeof(events) = 'array' and jsonb_array_length(events) > 0",
                        name="events"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    url: Mapped[str] = mapped_column(String(500))
    # kept as it is, since the worker signs with it; shown once, when it is made
    secret: Mapped[str] = mapped_column(String(100))
    # event types, e.g. ["competency.granted", "competency.revoked"], or ["*"]
    events: Mapped[list] = mapped_column(JSONB)
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = created_at_column()


class ApiKey(Base):
    """A key for a system, not a person: Simple TMS reading who is current,
    say. Only its SHA-256 is kept; the key is shown once, when it is made.
    Revoked, never deleted."""

    __tablename__ = "api_key"
    __table_args__ = (
        CheckConstraint("jsonb_typeof(scopes) = 'array' and jsonb_array_length(scopes) > 0",
                        name="scopes"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    # the key's first characters, so a person can tell which one it is
    prefix: Mapped[str] = mapped_column(String(16))
    scopes: Mapped[list] = mapped_column(JSONB)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("person.id"))
    created_at: Mapped[datetime] = created_at_column()
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_by: Mapped[Person] = relationship()


class EventSeen(Base):
    """An event the daily job has fired, by what it was about: the expiring
    or lapsed of one person's competency, to one last good day. It fires
    once (rule 2), whoever was listening then."""

    __tablename__ = "event_seen"

    # e.g. competency.expiring:4:2:2026-11-11 (person, competency, last good day)
    key: Mapped[str] = mapped_column(String(200), primary_key=True)
    event_id: Mapped[uuid.UUID] = mapped_column(Uuid, unique=True)
    created_at: Mapped[datetime] = created_at_column()
```

In `api/lms/models/outbox.py`, replace:
```python
from sqlalchemy import CheckConstraint, DateTime, Index, Integer, String, func
```
with:
```python
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, func
```

In `api/lms/models/outbox.py`, replace:
```python
from sqlalchemy.orm import Mapped, mapped_column

from lms.models.base import Base, created_at_column


class Outbox(Base):
    """The queue the worker drains: today, emails. A failed try is tried
    again after 1 min, 5, 30 and 2 h. `key` is unique, so something queued
    twice (a reminder the daily job finds again) is queued once."""
```
with:
```python
from sqlalchemy.orm import Mapped, mapped_column, relationship

from lms.models.base import Base, created_at_column
from lms.models.links import Webhook


class Outbox(Base):
    """The queue the worker drains: emails, an event for each webhook that
    wants it, and print jobs for Platen. A failed try is tried again after
    1 min, 5, 30 and 2 h. `key` is unique, so something queued twice (a
    reminder the daily job finds again) is queued once."""
```

In `api/lms/models/outbox.py`, replace:
```python
        CheckConstraint("kind in ('email')", name="kind"),
```
with:
```python
        CheckConstraint("kind in ('email', 'webhook', 'print')", name="kind"),
        # an event goes to one webhook, and only an event goes to one
        CheckConstraint("(kind = 'webhook') = (webhook_id is not null)", name="webhook"),
```

In `api/lms/models/outbox.py`, replace:
```python
    # e.g. reminder:4:2:2026-11-11:30 or digest:2:2026-10-12
    key: Mapped[str] = mapped_column(String(200), unique=True)
    # an email: {"to", "subject", "text"}
    payload: Mapped[dict] = mapped_column(JSONB)
```
with:
```python
    # e.g. reminder:4:2:2026-11-11:30, digest:2:2026-10-12,
    # event:<event id>:<webhook id> or print:<job id>
    key: Mapped[str] = mapped_column(String(200), unique=True)
    # an email: {"to", "subject", "text"}; an event: its envelope, as sent;
    # a print job: what Platen is sent
    payload: Mapped[dict] = mapped_column(JSONB)
    # an event: the webhook it goes to (its address and secret as they are
    # when it is sent)
    webhook_id: Mapped[int | None] = mapped_column(ForeignKey("webhook.id"), index=True)
```

In `api/lms/models/outbox.py`, replace:
```python
    created_at: Mapped[datetime] = created_at_column()
```
with:
```python
    created_at: Mapped[datetime] = created_at_column()

    webhook: Mapped[Webhook | None] = relationship()
```

In `api/lms/models/__init__.py`, replace:
```python
from lms.models.outbox import Outbox
```
with:
```python
from lms.models.links import ApiKey, EventSeen, Webhook
from lms.models.outbox import Outbox
```

In `api/lms/models/__init__.py`, replace:
```python
    "QuizQuestion", "QuizAttempt", "ModuleProgress", "Setting",
]
```
with:
```python
    "QuizQuestion", "QuizAttempt", "ModuleProgress", "Setting", "Webhook", "ApiKey",
    "EventSeen",
]
```
(Keep any names steps 4 and 5 added to the list.)

`api/alembic/versions/0006_outward_links.py`:
```python
"""outward links: webhooks and their deliveries, API keys, print jobs, events seen

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-16
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _created_at() -> sa.Column:
    return sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
                     nullable=False)


def upgrade() -> None:
    op.create_table(
        "webhook",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("url", sa.String(length=500), nullable=False),
        sa.Column("secret", sa.String(length=100), nullable=False),
        sa.Column("events", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("active", sa.Boolean(), server_default="true", nullable=False),
        _created_at(),
        sa.CheckConstraint("url ~ '^https?://[^[:space:]]+$'", name=op.f("ck_webhook_url")),
        sa.CheckConstraint("jsonb_typeof(events) = 'array' and jsonb_array_length(events) > 0",
                           name=op.f("ck_webhook_events")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_webhook")),
        sa.UniqueConstraint("name", name=op.f("uq_webhook_name")),
    )
    op.create_table(
        "api_key",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("prefix", sa.String(length=16), nullable=False),
        sa.Column("scopes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_by_id", sa.Integer(), nullable=False),
        _created_at(),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("jsonb_typeof(scopes) = 'array' and jsonb_array_length(scopes) > 0",
                           name=op.f("ck_api_key_scopes")),
        sa.ForeignKeyConstraint(["created_by_id"], ["person.id"],
                                name=op.f("fk_api_key_created_by_id_person")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_api_key")),
        sa.UniqueConstraint("key_hash", name=op.f("uq_api_key_key_hash")),
        sa.UniqueConstraint("name", name=op.f("uq_api_key_name")),
    )
    op.create_table(
        "event_seen",
        sa.Column("key", sa.String(length=200), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        _created_at(),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_event_seen")),
        sa.UniqueConstraint("event_id", name=op.f("uq_event_seen_event_id")),
    )

    # the outbox carries events for webhooks and print jobs for Platen too
    op.add_column("outbox", sa.Column("webhook_id", sa.Integer(), nullable=True))
    op.create_foreign_key(op.f("fk_outbox_webhook_id_webhook"), "outbox", "webhook",
                          ["webhook_id"], ["id"])
    op.create_index(op.f("ix_outbox_webhook_id"), "outbox", ["webhook_id"])
    op.drop_constraint(op.f("ck_outbox_kind"), "outbox", type_="check")
    op.create_check_constraint(op.f("ck_outbox_kind"), "outbox",
                               "kind in ('email', 'webhook', 'print')")
    op.create_check_constraint(op.f("ck_outbox_webhook"), "outbox",
                               "(kind = 'webhook') = (webhook_id is not null)")


def downgrade() -> None:
    # the outbox is a queue, not the training record: events and print jobs
    # in it go with the webhooks they were for
    op.execute("delete from outbox where kind <> 'email'")
    op.drop_constraint(op.f("ck_outbox_webhook"), "outbox", type_="check")
    op.drop_constraint(op.f("ck_outbox_kind"), "outbox", type_="check")
    op.create_check_constraint(op.f("ck_outbox_kind"), "outbox", "kind in ('email')")
    op.drop_index(op.f("ix_outbox_webhook_id"), table_name="outbox")
    op.drop_constraint(op.f("fk_outbox_webhook_id_webhook"), "outbox", type_="foreignkey")
    op.drop_column("outbox", "webhook_id")
    op.drop_table("event_seen")
    op.drop_table("api_key")
    op.drop_table("webhook")
```

**Step 4: Run them, and the whole suite, to see them pass**

Run: `cd api && .venv/bin/pytest tests/test_migrations.py tests/test_link_rows.py -q`
Expected: `10 passed` (the migrations' 2 and the 8 new ones).

Run: `cd api && .venv/bin/pytest -q`
Expected: A + 8 passed (`454 passed` on `c193b0c`).

**Step 5: Commit**

```
git add api/lms/models api/alembic/versions/0006_outward_links.py api/tests/test_migrations.py api/tests/test_link_rows.py
git commit -m "Keep webhooks, API keys and the events seen, and let the outbox carry events and print jobs" \
  -m "A delivery names its webhook and nothing else does. Webhooks and keys are turned off or revoked, never deleted."
```

---

### Task 2: An event queued for each webhook that wants it, and fired once when asked

**Files:**
- Create: `api/lms/services/events.py`
- Test: create `api/tests/test_events.py`

**Step 1: Write the failing tests**

`api/tests/test_events.py`:
```python
"""Events out: one envelope per event, queued for each webhook that wants
it, in the same transaction as what made it happen."""
import uuid
from datetime import UTC, datetime

from lms.models import EventSeen, Outbox, Webhook
from lms.services import events

AT = datetime(2026, 10, 12, 1, 30, tzinfo=UTC)


def hooks(db, *wanted: list[str], active=True) -> list[Webhook]:
    rows = [Webhook(name=f"Hook {i}", url=f"https://h{i}.example.com.au/in", secret=f"whsec_{i}",
                    events=w, active=active) for i, w in enumerate(wanted)]
    db.add_all(rows)
    db.commit()
    return rows


def deliveries(db) -> list[Outbox]:
    db.expire_all()
    return db.query(Outbox).filter_by(kind="webhook").order_by(Outbox.id).all()


def test_one_envelope_for_each_webhook_that_wants_it(db):
    tms, wms, other = hooks(db, ["*"], ["competency.granted"], ["person.updated"])
    event_id = events.emit(db, "competency.granted", {"person": {"code": "LL042"}}, now=AT)
    db.commit()
    rows = deliveries(db)
    assert [r.webhook_id for r in rows] == [tms.id, wms.id]
    assert rows[0].payload == rows[1].payload == {
        "event_id": str(event_id), "event_type": "competency.granted",
        "occurred_at": "2026-10-12T01:30:00Z", "data": {"person": {"code": "LL042"}}}
    assert [r.key for r in rows] == [f"event:{event_id}:{tms.id}", f"event:{event_id}:{wms.id}"]
    assert all(r.status == "pending" and r.next_attempt_at == AT for r in rows)


def test_a_webhook_turned_off_hears_nothing(db):
    hooks(db, ["*"], active=False)
    events.emit(db, "person.updated", {}, now=AT)
    db.commit()
    assert deliveries(db) == []


def test_nothing_is_queued_unless_what_caused_it_is_kept(db):
    hooks(db, ["*"])
    events.emit(db, "person.updated", {}, now=AT)
    db.rollback()
    assert deliveries(db) == []


def test_once_fires_once_whoever_is_listening(db):
    assert events.once(db, "competency.lapsed:4:2:2026-10-11", "competency.lapsed", {}, now=AT)
    db.commit()
    hooks(db, ["*"])
    # a webhook added since isn't told of what was fired before it
    assert not events.once(db, "competency.lapsed:4:2:2026-10-11", "competency.lapsed", {})
    db.commit()
    assert deliveries(db) == []
    seen = db.query(EventSeen).one()
    assert isinstance(seen.event_id, uuid.UUID)


def test_once_names_the_event_it_fired(db):
    hooks(db, ["competency.expiring"])
    events.once(db, "competency.expiring:4:2:2026-11-11", "competency.expiring", {"x": 1}, now=AT)
    db.commit()
    [row] = deliveries(db)
    assert row.payload["event_id"] == str(db.query(EventSeen).one().event_id)


def test_the_catalogue():
    assert events.EVENT_TYPES == ("competency.granted", "competency.revoked",
                                  "competency.expiring", "competency.lapsed", "person.updated")
```

**Step 2: Run them to see them fail**

Run: `cd api && .venv/bin/pytest tests/test_events.py -q`
Expected: FAIL: `ImportError: cannot import name 'events' from 'lms.services'` while collecting.

**Step 3: Minimal implementation**

`api/lms/services/events.py`:
```python
"""Events out, as Simple WMS sends its own: one envelope per event, queued
for each webhook that wants it, in the transaction that made it happen (so
nothing is told of a change that was never kept), and signed by the worker
on the way out. Nothing is sent here."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session as Db

from lms.models import EventSeen, Outbox, Webhook

EVENT_TYPES = ("competency.granted", "competency.revoked", "competency.expiring",
               "competency.lapsed", "person.updated")


def iso_utc(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def wants(hook: Webhook, event_type: str) -> bool:
    return "*" in hook.events or event_type in hook.events


def emit(db: Db, event_type: str, data: dict, now: datetime | None = None,
         event_id: uuid.UUID | None = None) -> uuid.UUID:
    """Queue the event for every webhook switched on that wants it. Returns
    its id, the same for every webhook, so a receiver told twice knows."""
    now = now or datetime.now(UTC)
    event_id = event_id or uuid.uuid4()
    envelope = {"event_id": str(event_id), "event_type": event_type,
                "occurred_at": iso_utc(now), "data": data}
    hooks = db.execute(select(Webhook).where(Webhook.active.is_(True))
                       .order_by(Webhook.id)).scalars()
    for hook in hooks:
        if wants(hook, event_type):
            db.add(Outbox(kind="webhook", key=f"event:{event_id}:{hook.id}", webhook_id=hook.id,
                          payload=envelope, status="pending", attempts=0, next_attempt_at=now))
    db.flush()
    return event_id


def once(db: Db, key: str, event_type: str, data: dict, now: datetime | None = None) -> bool:
    """Fire it unless it has been fired already, whoever was listening then:
    the daily job's expiring and lapsed, each once (rule 2). True when it
    fired now."""
    event_id = uuid.uuid4()
    seen = db.execute(insert(EventSeen).values(key=key, event_id=event_id)
                      .on_conflict_do_nothing(index_elements=["key"])
                      .returning(EventSeen.key)).scalar()
    if seen is None:
        return False
    emit(db, event_type, data, now, event_id)
    return True
```

**Step 4: Run them, and the whole suite, to see them pass**

Run: `cd api && .venv/bin/pytest tests/test_events.py -q`
Expected: `6 passed`

Run: `cd api && .venv/bin/pytest -q`
Expected: A + 14 passed (`460 passed`).

**Step 5: Commit**

```
git add api/lms/services/events.py api/tests/test_events.py
git commit -m "Queue an event for each webhook that wants it, with the change that caused it" \
  -m "One envelope, as Simple WMS sends: event_id, event_type, occurred_at and data. once() fires an event the first time only, whoever is listening."
```

---
### Task 3: The worker posts each event, signed, and drains emails and events in turn

**Files:**
- Create: `api/lms/services/webhooks.py`
- Modify: `api/lms/worker.py` (in full below), `api/lms/services/outbox.py`, `api/lms/config.py`, `api/pyproject.toml`
- Test: create `api/tests/test_webhook_delivery.py`

**Step 1: Write the failing tests**

`api/tests/test_webhook_delivery.py`:
```python
"""The worker delivers each event to its webhook, signed with the webhook's
secret, retried after 1 min, 5, 30 and 2 h; and it drains emails and
deliveries in turn, so neither holds the other up."""
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from lms import worker
from lms.models import Outbox, Webhook
from lms.services import events, outbox, webhooks

T0 = datetime(2026, 10, 12, 0, 0, tzinfo=UTC)


class Receiver:
    """Somewhere to send events: keeps each request, answers `status`, or
    fails to connect when `down` is set."""

    def __init__(self):
        self.got: list[httpx.Request] = []
        self.status = 200
        self.down = False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("Connection refused", request=request)
        self.got.append(request)
        return httpx.Response(self.status, text="thanks" if self.status < 300 else "not now")


@pytest.fixture
def receiver():
    r = Receiver()
    with httpx.Client(transport=httpx.MockTransport(r)) as http:
        r.http = http
        yield r


@pytest.fixture
def hook(db):
    h = Webhook(name="Simple TMS", url="https://tms.example.com.au/lms-events",
                secret="whsec_test", events=["*"])
    db.add(h)
    db.commit()
    return h


def fired(db, data=None) -> Outbox:
    events.emit(db, "competency.granted", data or {"person": {"code": "LL042"}}, now=T0)
    db.commit()
    return db.query(Outbox).filter_by(kind="webhook").order_by(Outbox.id.desc()).first()


def row(db, r: Outbox) -> Outbox:
    db.expire_all()
    return db.get(Outbox, r.id)


def test_an_event_is_posted_signed_with_its_id_and_type(db, hook, receiver):
    r = fired(db)
    assert worker.send_due(db, receiver.http, now=T0) == 1
    [req] = receiver.got
    assert str(req.url) == "https://tms.example.com.au/lms-events"
    assert req.headers["content-type"] == "application/json"
    assert req.headers["x-lms-event-id"] == r.payload["event_id"]
    assert req.headers["x-lms-event-type"] == "competency.granted"
    assert req.headers["user-agent"] == "simple-lms/0.1"
    expected = hmac.new(b"whsec_test", req.content, hashlib.sha256).hexdigest()
    assert req.headers["x-lms-signature"] == f"sha256={expected}"
    assert json.loads(req.content) == r.payload
    assert (row(db, r).status, row(db, r).attempts) == ("done", 1)


def test_a_receiver_checks_the_signature_like_this():
    body = b'{"event_id":"e1"}'
    good = webhooks.sign("whsec_test", body)
    assert webhooks.verify("whsec_test", body, good)
    assert not webhooks.verify("whsec_test", body + b" ", good)
    assert not webhooks.verify("whsec_other", body, good)
    assert not webhooks.verify("whsec_test", body, None)


def test_a_refusal_is_tried_again_after_1_5_30_and_120_minutes(db, hook, receiver):
    r = fired(db)
    receiver.status = 503
    now = T0
    for wait in (60, 300, 1800, 7200):
        assert worker.send_due(db, receiver.http, now=now) == 1
        assert row(db, r).next_attempt_at == now + timedelta(seconds=wait)
        assert row(db, r).last_error == "HTTP 503: not now"
        assert worker.send_due(db, receiver.http, now=now + timedelta(seconds=wait - 1)) == 0
        now += timedelta(seconds=wait)
    worker.send_due(db, receiver.http, now=now)
    assert (row(db, r).status, row(db, r).attempts) == ("failed", 5)
    assert len(receiver.got) == 5


def test_a_receiver_that_cannot_be_reached_is_a_failure_not_a_crash(db, hook, receiver):
    r = fired(db)
    receiver.down = True
    worker.send_due(db, receiver.http, now=T0)
    assert row(db, r).last_error == "ConnectError: Connection refused"
    assert row(db, r).status == "pending"


def test_one_that_fails_does_not_hold_up_the_next(db, hook, receiver):
    first, second = fired(db), fired(db)
    statuses = iter([500, 200])
    receiver.status = 500

    def answer(request):
        receiver.got.append(request)
        return httpx.Response(next(statuses))

    with httpx.Client(transport=httpx.MockTransport(answer)) as http:
        assert worker.send_due(db, http, now=T0) == 2
    assert (row(db, first).status, row(db, second).status) == ("pending", "done")


def test_the_secret_and_address_are_read_when_it_is_sent(db, hook, receiver):
    fired(db)
    hook.url = "https://tms.example.com.au/new-address"
    hook.secret = "whsec_new"
    db.commit()
    worker.send_due(db, receiver.http, now=T0)
    [req] = receiver.got
    assert str(req.url) == "https://tms.example.com.au/new-address"
    assert webhooks.verify("whsec_new", req.content, req.headers["x-lms-signature"])


def test_a_webhook_turned_off_gets_nothing_more(db, hook, receiver):
    r = fired(db)
    hook.active = False
    db.commit()
    worker.send_due(db, receiver.http, now=T0)
    assert receiver.got == []
    assert (row(db, r).status, row(db, r).last_error) == ("failed", "the webhook was turned off")


def test_emails_and_events_take_turns(db, hook, mailbox, monkeypatch):
    order = []
    monkeypatch.setattr(worker.mail, "send", lambda payload: order.append(payload["subject"]))
    for n in range(3):
        outbox.queue_email(db, f"mail{n}", "kim@example.com.au", f"email {n}", "t", now=T0)
        fired(db, {"n": n})

    def answer(request):
        order.append(f"event {json.loads(request.content)['data']['n']}")
        return httpx.Response(200)

    with httpx.Client(transport=httpx.MockTransport(answer)) as http:
        assert worker.send_due(db, http, now=T0) == 6
    assert order == ["email 0", "event 0", "email 1", "event 1", "email 2", "event 2"]


def test_each_kind_has_its_own_limit_per_pass(db, hook, receiver, mailbox):
    for n in range(3):
        outbox.queue_email(db, f"mail{n}", "kim@example.com.au", "s", "t", now=T0)
        fired(db)
    assert worker.send_due(db, receiver.http, now=T0, limit=2) == 4
    assert len(receiver.got) == 2 and len(mailbox.sent) == 2


def test_events_go_while_emails_wait_for_smtp(db, hook, receiver):
    outbox.queue_email(db, "mail", "kim@example.com.au", "s", "t", now=T0)
    fired(db)
    assert worker.send_due(db, receiver.http, now=T0) == 1
    assert len(receiver.got) == 1
```

**Step 2: Run them to see them fail**

Run: `cd api && .venv/bin/pytest tests/test_webhook_delivery.py -q`
Expected: FAIL: `ModuleNotFoundError: No module named 'httpx'` while collecting (the dev install has only `httpx2`, for Starlette's test client). Once httpx is installed (Step 3's first part), `ImportError: cannot import name 'webhooks' from 'lms.services'`.

**Step 3: Minimal implementation**

In `api/pyproject.toml`, replace:
```toml
  # the time zone's rules, so "today" is right in a slim image too
  "tzdata>=2024.1",
]
```
with:
```toml
  # the time zone's rules, so "today" is right in a slim image too
  "tzdata>=2024.1",
  # the worker posts events to webhooks and print jobs to Platen
  "httpx>=0.27",
]
```
and install it: `cd api && uv pip install -e ".[dev]"`.

The timeout is how the worker behaves, not an everyday setting, so it stays in `.env` only. In `api/lms/config.py`, replace:
```python
    daily_hour: int = Field(default=6, ge=0, le=23)
```
with:
```python
    daily_hour: int = Field(default=6, ge=0, le=23)
    # How long the worker waits for a webhook (or Platen) to answer.
    worker_http_timeout_seconds: float = Field(default=10.0, gt=0)
```

In `api/lms/services/outbox.py`, replace:
```python
from lms.models import Outbox

```
with:
```python
from lms.models import Outbox


class GiveUp(Exception):
    """Not worth another try: the row is failed now, with this as its error."""

```

`api/lms/services/webhooks.py`:
```python
"""Delivering an event to a webhook, signed as Simple WMS signs its own:
X-LMS-Signature is `sha256=` and the hex HMAC-SHA256 of the exact body,
keyed with the webhook's secret. X-LMS-Event-Id and X-LMS-Event-Type say
what it is before the body is read. The address and secret are the
webhook's as they are when it is sent, so a fixed address or a new secret
applies to what is still waiting."""
from __future__ import annotations

import hashlib
import hmac
import json

import httpx

from lms.config import get_settings
from lms.models import Outbox
from lms.services.outbox import GiveUp

USER_AGENT = "simple-lms/0.1"


def sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def verify(secret: str, body: bytes, header: str | None) -> bool:
    """What a receiver does: True only if the header is the signature of
    exactly these bytes, compared in constant time."""
    if not secret or not header:
        return False
    return hmac.compare_digest(sign(secret, body).encode(), header.strip().encode())


def deliver(http: httpx.Client, row: Outbox) -> str | None:
    """Post one event to its webhook: None when it answered 2xx, else what
    went wrong. A webhook turned off since is given up on."""
    hook = row.webhook
    if not hook.active:
        raise GiveUp("the webhook was turned off")
    body = json.dumps(row.payload, separators=(",", ":")).encode()
    headers = {
        "Content-Type": "application/json",
        "X-LMS-Signature": sign(hook.secret, body),
        "X-LMS-Event-Id": row.payload["event_id"],
        "X-LMS-Event-Type": row.payload["event_type"],
        "User-Agent": USER_AGENT,
    }
    try:
        resp = http.post(hook.url, content=body, headers=headers,
                         timeout=get_settings().worker_http_timeout_seconds)
    except httpx.HTTPError as e:
        return f"{type(e).__name__}: {e}"
    if 200 <= resp.status_code < 300:
        return None
    return f"HTTP {resp.status_code}: {resp.text[:200]}"
```

`api/lms/worker.py` (the daily job, `Daily` and the settings it reads are as they were; the sending is now by kind, in turn):
```python
"""Drains the outbox (emails, and events for the webhooks) and runs the
daily job. Run as `python -m lms.worker`.

A failed try is tried again after 1 min, 5, 30 and 2 h. The try after the
2 h wait is the last: if it fails too, the row is `failed` and stays, with
its last error, for someone to look at.

Each kind takes its turn, a row at a time, so a Monday's pile of reminders
doesn't hold up an event another system is waiting on, nor the other way
round; and a row that fails waits for its next try without holding up the
rows after it.

The daily job runs once a day from the daily hour in the time zone (both
in Settings, or .env), and again whenever the worker starts after that
hour: each email it queues has its own key, and each event it fires is
fired once, so running it twice sends nothing twice.
"""
from __future__ import annotations

import logging
import time
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from lms.config import get_settings
from lms.db import get_sessionmaker
from lms.models import Outbox
from lms.services import daily, mail, settings, webhooks
from lms.services.outbox import GiveUp

log = logging.getLogger("lms.worker")

BACKOFF = (60, 300, 1800, 7200)
# after the daily job fails, how long before it is tried again
DAILY_RETRY = timedelta(minutes=5)
# what the outbox holds, in the order each takes its turn
KINDS = ("email", "webhook")


def clock() -> datetime:
    return datetime.now(UTC)


def retry_later(row: Outbox, now: datetime, error: str) -> None:
    """After a failed try: wait the next step of the backoff, or give up once
    the try after the last wait has failed. attempts has counted this try."""
    row.last_error = error[:500]
    if row.attempts > len(BACKOFF):
        row.status = "failed"
    else:
        row.next_attempt_at = now + timedelta(seconds=BACKOFF[row.attempts - 1])


def _claim(session: Session, kind: str, now: datetime) -> Outbox | None:
    """The next row of this kind that is due, locked so a second worker
    passes it by. One row per transaction, so a slow mail server or
    receiver holds up only that row."""
    return session.execute(
        select(Outbox)
        .where(Outbox.kind == kind, Outbox.status == "pending", Outbox.next_attempt_at <= now)
        .order_by(Outbox.next_attempt_at, Outbox.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    ).scalar_one_or_none()


def _ready(kind: str) -> bool:
    """Emails wait, untried, until SMTP is set up; events always go."""
    return mail.set_up() if kind == "email" else True


def _send(kind: str, http: httpx.Client | None, row: Outbox) -> str | None:
    if kind == "email":
        return mail.send(row.payload)
    return webhooks.deliver(http, row)


def _send_one(session: Session, kind: str, http: httpx.Client | None,
              now: datetime | None) -> bool:
    """Send the next row of this kind that is due, if there is one."""
    row = _claim(session, kind, now or clock())
    if row is None:
        return False
    give_up = False
    try:
        error = _send(kind, http, row)
    except GiveUp as e:
        error, give_up = str(e), True
    except Exception as e:  # a bad row (or password) must not stop the rows after it
        error = f"{type(e).__name__}: {e}"
    # after the answer, not before: a slow server would date it in the past
    answered = now or clock()
    row.attempts += 1
    if error is None:
        # At least once: a crash between the send and the commit sends it
        # again next time. Reminders don't mind; a receiver goes by event_id.
        row.status = "done"
        row.done_at = answered
        row.last_error = None
        log.info("%s %s sent", kind, row.key)
    elif give_up:
        row.status = "failed"
        row.last_error = error[:500]
        log.warning("%s %s given up: %s", kind, row.key, error)
    else:
        retry_later(row, answered, error)
        log.warning("%s %s try %d failed%s: %s", kind, row.key, row.attempts,
                    "; given up" if row.status == "failed" else "", error)
    session.commit()
    return True


def _drain(session: Session, http: httpx.Client | None, now: datetime | None, limit: int,
           kinds: list[str]) -> int:
    tried = dict.fromkeys(kinds, 0)
    while kinds:
        for kind in list(kinds):
            if tried[kind] < limit and _send_one(session, kind, http, now):
                tried[kind] += 1
            else:
                kinds.remove(kind)
    return sum(tried.values())


def send_due(session: Session, http: httpx.Client | None = None, now: datetime | None = None,
             limit: int = 50, kinds: tuple[str, ...] = KINDS) -> int:
    """Send what is due, a row of each kind in turn, up to `limit` of each.
    Returns how many were tried."""
    ready = [k for k in kinds if _ready(k)]
    if http is None and any(k != "email" for k in ready):
        with httpx.Client() as client:
            return _drain(session, client, now, limit, ready)
    return _drain(session, http, now, limit, ready)


def send_emails(session: Session, now: datetime | None = None, limit: int = 50) -> int:
    """Send every email that is due, and nothing else. Returns how many were tried."""
    return send_due(session, None, now, limit, kinds=("email",))


class Daily:
    """Remembers the last day the daily job ran in this worker."""

    def __init__(self) -> None:
        self.last: date | None = None
        self.not_before: datetime | None = None   # set when it last failed

    def due(self, now: datetime) -> date | None:
        """Today in the time zone, if the job is due: past the daily hour,
        not yet run today, and not failed in the last few minutes. Both are
        read each time, so a change in Settings needs no restart."""
        s = settings.current()
        local = now.astimezone(ZoneInfo(s.timezone))
        if local.hour < s.daily_hour or local.date() == self.last:
            return None
        if self.not_before is not None and now < self.not_before:
            return None
        return local.date()


def run_once(session: Session, today: Daily, now: datetime | None = None,
             http: httpx.Client | None = None) -> int:
    """The daily job if it is due, then whatever is due in the outbox.
    Returns how many rows were tried."""
    day = today.due(now or clock())
    if day is not None:
        try:
            queued = daily.run(session, day, now)
        except Exception:  # the emails already queued still go
            log.exception("daily job for %s failed; trying again in %s", day, DAILY_RETRY)
            # set first: a dead connection can make the rollback raise as well
            today.not_before = (now or clock()) + DAILY_RETRY
            session.rollback()
        else:
            today.last = day
            today.not_before = None
            log.info("daily job for %s: %d reminders, %d digests queued", day,
                     queued["reminders"], queued["digests"])
    return send_due(session, http, now)


def wait_for_schema(session: Session, timeout: float = 120, poll: float = 2) -> None:
    """Block until the api container has run the migrations."""
    from sqlalchemy.exc import ProgrammingError

    deadline = time.monotonic() + timeout
    while True:
        try:
            session.execute(select(Outbox.id).limit(1))
            return
        except ProgrammingError:
            session.rollback()
            if time.monotonic() >= deadline:
                raise TimeoutError("outbox never appeared; did the migrations run?")
            log.info("waiting for migrations")
            time.sleep(poll)


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    poll = get_settings().worker_poll_seconds
    make_session = get_sessionmaker()
    with make_session() as session:
        wait_for_schema(session)
    if not mail.set_up():
        log.warning("no email server (Settings, or LMS_SMTP_HOST and LMS_SMTP_FROM): emails "
                    "wait in the outbox until one is set")
    s = settings.current()
    log.info("worker started, polling every %ss; daily job from %02d:00 %s", poll,
             s.daily_hour, s.timezone)
    today = Daily()
    with httpx.Client() as http:
        while True:
            try:
                with make_session() as session:
                    done = run_once(session, today, http=http)
            except Exception:  # keep the loop alive; log and back off
                log.exception("worker loop error")
                done = 0
            if done == 0:
                time.sleep(poll)


if __name__ == "__main__":
    main()
```

**Step 4: Run them, and the whole suite, to see them pass**

Run: `cd api && .venv/bin/pytest tests/test_webhook_delivery.py tests/test_worker.py -q`
Expected: `30 passed` (10 new; the worker's 20 as they were: `send_emails` and `run_once` keep their shape).

Run: `cd api && .venv/bin/pytest -q`
Expected: A + 24 passed (`470 passed`).

**Step 5: Commit**

```
git add api/pyproject.toml api/lms/config.py api/lms/services/outbox.py api/lms/services/webhooks.py api/lms/worker.py api/tests/test_webhook_delivery.py
git commit -m "Post each event to its webhook, signed as Simple WMS signs, and take emails and events in turn" \
  -m "X-LMS-Signature is sha256= and the HMAC of the exact body. A refusal is tried again after 1 min, 5, 30 and 2 h; a webhook turned off is given up on. Neither kind holds the other up."
```

---

### Task 4: Webhooks for an admin: added, changed, turned off, a new secret, and a failed delivery sent again

**Files:**
- Create: `api/lms/api/routes/webhooks.py`
- Modify: `api/lms/services/webhooks.py`, `api/lms/api/app.py`
- Test: create `api/tests/test_webhooks.py`

**Step 1: Write the failing tests**

`api/tests/test_webhooks.py`:
```python
"""Webhooks: an admin adds where the events go, chooses which, sees how
each delivery went, and sends a failed one again. The secret is shown
once."""
from datetime import UTC, datetime

import pytest

from lms.models import Outbox
from lms.services import events

TMS = {"name": "Simple TMS", "url": "https://tms.example.com.au/lms-events",
       "events": ["competency.granted", "competency.revoked"]}


def add(client, headers, **more):
    return client.post("/v1/webhooks", headers=headers, json={**TMS, **more})


@pytest.fixture
def tms(client, admin_headers):
    r = add(client, admin_headers)
    assert r.status_code == 201, r.text
    return r.json()


def test_an_admin_adds_one_and_sees_its_secret_once(client, admin_headers, tms):
    assert tms["secret"].startswith("whsec_") and len(tms["secret"]) > 40
    assert (tms["name"], tms["url"], tms["events"], tms["active"]) == (
        TMS["name"], TMS["url"], TMS["events"], True)
    assert (tms["waiting"], tms["failed"]) == (0, 0)
    listed = client.get("/v1/webhooks", headers=admin_headers).json()
    assert [w["name"] for w in listed] == ["Simple TMS"]
    assert "secret" not in listed[0]
    assert "secret" not in client.get(f"/v1/webhooks/{tms['id']}", headers=admin_headers).json()


@pytest.mark.parametrize("body, field", [
    ({"events": ["competency.renamed"]}, "events.0"),
    ({"events": []}, "events"),
    ({"url": "tms.example.com.au"}, "url"),
    ({"url": "ftp://tms.example.com.au"}, "url"),
    ({"name": "  "}, "name"),
])
def test_what_is_wrong_is_said(client, admin_headers, body, field):
    r = add(client, admin_headers, **body)
    assert r.status_code == 422
    assert r.json()["errors"][0]["field"] == field


def test_everything_is_a_star_and_the_same_event_is_named_once(client, admin_headers):
    r = add(client, admin_headers, events=["person.updated", "*"])
    assert r.json()["events"] == ["*"]
    r = add(client, admin_headers, name="Twice",
            events=["person.updated", "competency.lapsed", "person.updated"])
    assert r.json()["events"] == ["person.updated", "competency.lapsed"]


def test_two_cannot_share_a_name(client, admin_headers, tms):
    r = add(client, admin_headers)
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "name"


def test_only_an_admin(client, manager_headers, admin_headers, tms):
    assert client.get("/v1/webhooks", headers=manager_headers).status_code == 403
    assert add(client, manager_headers, name="Mine").status_code == 403


def test_changed_and_turned_off(client, admin_headers, tms):
    r = client.patch(f"/v1/webhooks/{tms['id']}", headers=admin_headers,
                     json={"url": "https://tms.example.com.au/v2/lms", "events": ["*"],
                           "active": False})
    assert r.status_code == 200, r.text
    assert (r.json()["url"], r.json()["events"], r.json()["active"]) == (
        "https://tms.example.com.au/v2/lms", ["*"], False)
    assert client.patch("/v1/webhooks/999", headers=admin_headers,
                        json={"active": True}).status_code == 404


def test_a_new_secret_replaces_the_old(client, db, admin_headers, tms):
    r = client.post(f"/v1/webhooks/{tms['id']}/secret", headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["secret"].startswith("whsec_") and r.json()["secret"] != tms["secret"]


def queued(db, at: datetime, event_type="competency.granted"):
    events.emit(db, event_type, {}, now=at)
    db.commit()


def test_its_deliveries_newest_first_and_a_failed_one_sent_again(client, db, admin_headers, tms):
    queued(db, datetime(2026, 10, 12, 1, tzinfo=UTC))
    queued(db, datetime(2026, 10, 12, 2, tzinfo=UTC), "competency.revoked")
    first, second = db.query(Outbox).order_by(Outbox.id).all()
    first.status, first.attempts, first.last_error = "failed", 5, "HTTP 503: not now"
    db.commit()

    out = client.get(f"/v1/webhooks/{tms['id']}/deliveries", headers=admin_headers).json()
    assert [(d["event_type"], d["status"]) for d in out] == [
        ("competency.revoked", "pending"), ("competency.granted", "failed")]
    assert out[1]["event_id"] == first.payload["event_id"]
    assert out[1]["last_error"] == "HTTP 503: not now"
    failed = client.get(f"/v1/webhooks/{tms['id']}/deliveries?status=failed",
                        headers=admin_headers).json()
    assert [d["id"] for d in failed] == [first.id]
    counts = client.get(f"/v1/webhooks/{tms['id']}", headers=admin_headers).json()
    assert (counts["waiting"], counts["failed"]) == (1, 1)

    r = client.post(f"/v1/webhooks/{tms['id']}/deliveries/{first.id}/retry",
                    headers=admin_headers)
    assert r.status_code == 200, r.text
    assert (r.json()["status"], r.json()["attempts"]) == ("pending", 0)
    db.expire_all()
    assert db.get(Outbox, first.id).next_attempt_at <= datetime.now(UTC)

    r = client.post(f"/v1/webhooks/{tms['id']}/deliveries/{second.id}/retry",
                    headers=admin_headers)
    assert r.status_code == 409 and r.json()["code"] == "not_failed"


def test_nothing_is_sent_again_to_a_webhook_turned_off(client, db, admin_headers, tms):
    queued(db, datetime(2026, 10, 12, 1, tzinfo=UTC))
    row = db.query(Outbox).one()
    row.status, row.attempts = "failed", 5
    db.commit()
    client.patch(f"/v1/webhooks/{tms['id']}", headers=admin_headers, json={"active": False})
    r = client.post(f"/v1/webhooks/{tms['id']}/deliveries/{row.id}/retry", headers=admin_headers)
    assert r.status_code == 409 and r.json()["code"] == "inactive"


def test_another_webhooks_delivery_is_not_found(client, db, admin_headers, tms):
    other = add(client, admin_headers, name="Simple WMS").json()
    queued(db, datetime(2026, 10, 12, 1, tzinfo=UTC))
    row = db.query(Outbox).filter_by(webhook_id=tms["id"]).one()
    r = client.post(f"/v1/webhooks/{other['id']}/deliveries/{row.id}/retry",
                    headers=admin_headers)
    assert r.status_code == 404
```

**Step 2: Run them to see them fail**

Run: `cd api && .venv/bin/pytest tests/test_webhooks.py -q`
Expected: FAIL: `6 failed, 8 errors`: there is no `/v1/webhooks` yet (`404` where `201` was wanted).

**Step 3: Minimal implementation**

In `api/lms/services/webhooks.py`, replace:
```python
import json
```
with:
```python
import json
import secrets
```

Append to `api/lms/services/webhooks.py`:
```python


def new_secret() -> str:
    """What a webhook's bodies are signed with: 256 random bits."""
    return "whsec_" + secrets.token_urlsafe(32)
```

`api/lms/api/routes/webhooks.py` (they are part of Settings, so `settings:write`, as `/v1/settings` is):
```python
"""Webhooks: where Simple LMS sends its events, which ones, and how each
delivery went. An admin's to add, change and turn off, on the Settings
screen; never deleted, since their deliveries name them. The secret is shown
once, when it is made, and is never sent back, as the email password isn't."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select

from lms.api.deps import DB, Principal, require
from lms.api.errors import Conflict, FieldError, NotFound, commit_unique
from lms.models import Outbox, Webhook
from lms.services import webhooks

router = APIRouter(tags=["webhooks"])

# an admin's, as the rest of Settings is
SCOPE = "settings:write"

URL = r"^https?://\S+$"
EventName = Literal["*", "competency.granted", "competency.revoked", "competency.expiring",
                    "competency.lapsed", "person.updated"]


def _events(value: list[str] | None) -> list[str] | None:
    """Each once, in the order given; `*` is everything, so it is all there is."""
    if value is None:
        return None
    return ["*"] if "*" in value else list(dict.fromkeys(value))


class WebhookIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=120)
    url: str = Field(max_length=500, pattern=URL)
    events: list[EventName] = Field(min_length=1, max_length=20)

    @field_validator("events")
    @classmethod
    def _each_once(cls, v):
        return _events(v)


class WebhookPatch(BaseModel):
    """Leave a field out to keep it."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    url: str | None = Field(default=None, max_length=500, pattern=URL)
    events: list[EventName] | None = Field(default=None, min_length=1, max_length=20)
    active: bool | None = None

    @field_validator("events")
    @classmethod
    def _each_once(cls, v):
        return _events(v)


class WebhookOut(BaseModel):
    id: int
    name: str
    url: str
    events: list[str]
    active: bool
    # deliveries still to go, and those given up on
    waiting: int
    failed: int
    created_at: datetime


class WebhookMade(WebhookOut):
    # shown this once: keep it where the receiver can check signatures with it
    secret: str


class SecretOut(BaseModel):
    secret: str


class DeliveryOut(BaseModel):
    id: int
    event_id: uuid.UUID
    event_type: str
    status: str
    attempts: int
    next_attempt_at: datetime
    last_error: str | None
    done_at: datetime | None
    created_at: datetime


def _counts(db, hook_ids: list[int]) -> dict[tuple[int, str], int]:
    rows = db.execute(select(Outbox.webhook_id, Outbox.status, func.count())
                      .where(Outbox.webhook_id.in_(hook_ids), Outbox.status != "done")
                      .group_by(Outbox.webhook_id, Outbox.status)).all()
    return {(w, s): n for w, s, n in rows}


def webhook_out(db, w: Webhook, counts: dict | None = None) -> WebhookOut:
    counts = _counts(db, [w.id]) if counts is None else counts
    return WebhookOut(id=w.id, name=w.name, url=w.url, events=w.events, active=w.active,
                      waiting=counts.get((w.id, "pending"), 0),
                      failed=counts.get((w.id, "failed"), 0), created_at=w.created_at)


def delivery_out(r: Outbox) -> DeliveryOut:
    return DeliveryOut(id=r.id, event_id=r.payload["event_id"], event_type=r.payload["event_type"],
                       status=r.status, attempts=r.attempts, next_attempt_at=r.next_attempt_at,
                       last_error=r.last_error, done_at=r.done_at, created_at=r.created_at)


def get_webhook(db, webhook_id: int) -> Webhook:
    w = db.get(Webhook, webhook_id)
    if w is None:
        raise NotFound(f"no webhook {webhook_id}")
    return w


def _name_taken(name: str | None) -> FieldError:
    return FieldError("name", f"there is already a webhook called {name}")


@router.get("/webhooks", response_model=list[WebhookOut])
def list_webhooks(db: DB, who: Principal = require(SCOPE)):
    """By name, turned off or not."""
    rows = db.execute(select(Webhook).order_by(Webhook.name)).scalars().all()
    counts = _counts(db, [w.id for w in rows])
    return [webhook_out(db, w, counts) for w in rows]


@router.post("/webhooks", status_code=201, response_model=WebhookMade)
def add_webhook(body: WebhookIn, db: DB, who: Principal = require(SCOPE)):
    if db.execute(select(Webhook.id).where(Webhook.name == body.name)).first():
        raise _name_taken(body.name)
    w = Webhook(name=body.name, url=body.url, events=body.events, secret=webhooks.new_secret(),
                active=True)
    db.add(w)
    commit_unique(db, {"uq_webhook_name": _name_taken(body.name)})
    out = WebhookMade(**webhook_out(db, w, {}).model_dump(), secret=w.secret)
    return JSONResponse(status_code=201, content=out.model_dump(mode="json"))


@router.get("/webhooks/{webhook_id}", response_model=WebhookOut)
def read_webhook(webhook_id: int, db: DB, who: Principal = require(SCOPE)):
    return webhook_out(db, get_webhook(db, webhook_id))


@router.patch("/webhooks/{webhook_id}", response_model=WebhookOut)
def change_webhook(webhook_id: int, body: WebhookPatch, db: DB,
                   who: Principal = require(SCOPE)):
    """What is still waiting goes to the new address. Turned off, it is sent
    nothing more, and what is waiting for it is given up on."""
    w = get_webhook(db, webhook_id)
    if body.name is not None and body.name != w.name:
        if db.execute(select(Webhook.id).where(Webhook.name == body.name)).first():
            raise _name_taken(body.name)
        w.name = body.name
    if body.url is not None:
        w.url = body.url
    if body.events is not None:
        w.events = body.events
    if body.active is not None:
        w.active = body.active
    commit_unique(db, {"uq_webhook_name": _name_taken(body.name)})
    return webhook_out(db, w)


@router.post("/webhooks/{webhook_id}/secret", response_model=SecretOut)
def new_secret(webhook_id: int, db: DB, who: Principal = require(SCOPE)):
    """A new secret, shown this once. Everything sent from now on is signed
    with it, what was waiting included; the old one stops at once."""
    w = get_webhook(db, webhook_id)
    w.secret = webhooks.new_secret()
    db.commit()
    return SecretOut(secret=w.secret)


@router.get("/webhooks/{webhook_id}/deliveries", response_model=list[DeliveryOut])
def list_deliveries(webhook_id: int, db: DB,
                    status: Literal["pending", "done", "failed"] | None = None,
                    who: Principal = require(SCOPE)):
    """The latest 50, newest first."""
    w = get_webhook(db, webhook_id)
    q = select(Outbox).where(Outbox.webhook_id == w.id)
    if status:
        q = q.where(Outbox.status == status)
    rows = db.execute(q.order_by(Outbox.id.desc()).limit(50)).scalars().all()
    return [delivery_out(r) for r in rows]


@router.post("/webhooks/{webhook_id}/deliveries/{delivery_id}/retry", response_model=DeliveryOut)
def retry_delivery(webhook_id: int, delivery_id: int, db: DB,
                   who: Principal = require(SCOPE)):
    """A delivery given up on, sent again from the start of the backoff:
    the same event, with the same id."""
    w = get_webhook(db, webhook_id)
    r = db.get(Outbox, delivery_id, with_for_update=True)
    if r is None or r.webhook_id != w.id:
        raise NotFound(f"no delivery {delivery_id} for this webhook")
    if not w.active:
        raise Conflict("inactive", f"{w.name} is turned off: turn it on first")
    if r.status != "failed":
        raise Conflict("not_failed",
                       f"this delivery is {r.status}: only a failed one is sent again")
    r.status, r.attempts, r.next_attempt_at = "pending", 0, datetime.now(UTC)
    db.commit()
    return delivery_out(r)
```

In `api/lms/api/app.py`, replace:
```python
    auth, competencies, learning, matrix, media, modules, overrides, people, policies, records,
    roles, settings, tickets, uploads,
)
```
with:
```python
    auth, competencies, learning, matrix, media, modules, overrides, people, policies, records,
    roles, settings, tickets, uploads, webhooks,
)
```
(Keep step 4's and 5's routers in the list.)

In `api/lms/api/app.py`, replace:
```python
v1.include_router(settings.router)
```
with:
```python
v1.include_router(settings.router)
v1.include_router(webhooks.router)
```

**Step 4: Run them, and the whole suite, to see them pass**

Run: `cd api && .venv/bin/pytest tests/test_webhooks.py -q`
Expected: `14 passed`

Run: `cd api && .venv/bin/pytest -q`
Expected: A + 38 passed (`484 passed`).

**Step 5: Commit**

```
git add api/lms/services/webhooks.py api/lms/api/routes/webhooks.py api/lms/api/app.py api/tests/test_webhooks.py
git commit -m "Let an admin add webhooks, choose their events, see each delivery and send a failed one again" \
  -m "The secret is made here and shown once, and again only as a new one. Turned off, never deleted. settings:write, as the rest of Settings."
```

---

### Task 5: competency.granted and competency.revoked, from every way a grant or a revoke is made

**Files:**
- Modify: `api/lms/services/events.py`, `api/lms/api/routes/records.py`, `api/lms/api/routes/tickets.py`, `api/lms/api/routes/policies.py`, `api/lms/api/routes/learning.py`, and step 4's sign-off route
- Test: create `api/tests/test_competency_events.py`

**Step 1: Write the failing tests**

`api/tests/test_competency_events.py`:
```python
"""competency.granted and competency.revoked: fired by every way a grant
or a revoke is made, in the same transaction, with the status it leaves."""
import pytest

import yard
from conftest import make_person
from course import INDUCTION, RIGHT, published
from files import PNG, sent
from lms.models import Outbox, Webhook

KIM = {"code": "LL042", "name": "Kim Lee"}
MEL = {"code": "MG001", "name": "Mel Grant"}


@pytest.fixture
def kim(client, db, manager_headers, learner):
    """Kim is a forklift operator; a webhook hears every grant and revoke."""
    db.add(Webhook(name="Simple TMS", url="https://tms.example.com.au/in", secret="whsec_x",
                   events=["competency.granted", "competency.revoked"]))
    db.commit()
    yard.build(client, manager_headers)
    yard.give_roles(client, manager_headers, "LL042", "forklift-operator")
    return learner


def fired(db, event_type=None) -> list[dict]:
    db.expire_all()
    rows = db.query(Outbox).filter_by(kind="webhook").order_by(Outbox.id).all()
    return [r.payload for r in rows if event_type is None or r.payload["event_type"] == event_type]


def test_a_grant_by_hand(client, db, manager_headers, kim):
    record = yard.grant(client, manager_headers, "LL042", "forklift-licence", "2026-03-01",
                        expires_on="2031-03-01")
    [event] = fired(db)
    assert event["event_type"] == "competency.granted"
    assert event["data"] == {
        "person": KIM,
        "competency": {"key": "forklift-licence", "name": "Forklift licence", "kind": "ticket"},
        "record_id": record["id"], "granted_on": "2026-03-01", "expires_on": "2031-03-01",
        "status": "current", "recorded_by": MEL}


def test_the_last_good_day_is_worked_out_from_the_refresher(client, db, manager_headers, kim):
    yard.grant(client, manager_headers, "LL042", "site-induction", "2024-11-01")
    [event] = fired(db)
    # 24 months on: good until then, and within 30 days of it
    assert (event["data"]["expires_on"], event["data"]["status"]) == ("2026-11-01", "expiring")


def test_a_grant_not_asked_of_them_says_so(client, db, manager_headers, kim):
    yard.grant(client, manager_headers, "LL042", "first-aid", "2026-10-01")
    assert fired(db)[0]["data"]["status"] == "not_required"


def test_a_revoke(client, db, manager_headers, kim):
    yard.grant(client, manager_headers, "LL042", "forklift-licence", "2026-03-01")
    r = client.post("/v1/people/LL042/records/revoke", headers=manager_headers,
                    json={"competency": "forklift-licence", "note": "ticked for the wrong person"})
    [event] = fired(db, "competency.revoked")
    assert event["data"] == {
        "person": KIM,
        "competency": {"key": "forklift-licence", "name": "Forklift licence", "kind": "ticket"},
        "record_id": r.json()["id"], "note": "ticked for the wrong person", "status": "missing",
        "recorded_by": MEL}


def test_nothing_is_fired_for_what_is_refused(client, db, manager_headers, manager, kim):
    r = client.post("/v1/people/MG001/records", headers=manager_headers,
                    json={"competency": "forklift-licence", "granted_on": "2026-03-01"})
    assert r.status_code == 403
    r = client.post("/v1/people/LL042/records/revoke", headers=manager_headers,
                    json={"competency": "forklift-licence", "note": "nothing there"})
    assert r.status_code == 409
    assert fired(db) == []


def test_a_ticket_checked(client, db, manager_headers, learner_headers, kim):
    body = {"competency": "forklift-licence", "number": "LF0012345", "expires_on": "2031-03-01",
            "front": sent(client, learner_headers)}
    ticket = client.post("/v1/tickets", headers=learner_headers, json=body).json()
    assert fired(db) == []   # sent in, not yet checked
    client.post(f"/v1/tickets/{ticket['id']}/approve", headers=manager_headers)
    [event] = fired(db)
    assert (event["data"]["granted_on"], event["data"]["expires_on"], event["data"]["status"],
            event["data"]["recorded_by"]) == ("2026-10-12", "2031-03-01", "current", MEL)


def test_a_policy_signed(client, db, manager_headers, learner_headers, kim):
    client.put("/v1/roles/forklift-operator/requirements", headers=manager_headers,
               json={"competencies": ["site-induction", "forklift-licence", "whs-policy"]})
    client.post("/v1/policies/whs-policy/versions", headers=manager_headers,
                json={"body": "Wear your PPE."})
    signature = sent(client, learner_headers, "signature", PNG, "image/png")
    r = client.post("/v1/policies/whs-policy/sign", headers=learner_headers,
                    json={"version": 1, "signed_name": "Kim Lee", "signature": signature})
    assert r.status_code == 201, r.text
    [event] = fired(db)
    assert (event["data"]["competency"]["key"], event["data"]["status"],
            event["data"]["expires_on"], event["data"]["recorded_by"]) == (
        "whs-policy", "current", None, KIM)


def test_a_module_passed_and_not_a_fail(client, db, manager_headers, learner_headers, kim):
    published(client, manager_headers)
    client.post(f"{INDUCTION}/attempts", headers=learner_headers,
                json={"version": 1, "answers": [1, 0]})
    assert fired(db) == []
    client.post(f"{INDUCTION}/attempts", headers=learner_headers,
                json={"version": 1, "answers": RIGHT})
    [event] = fired(db)
    assert (event["data"]["competency"]["key"], event["data"]["expires_on"],
            event["data"]["recorded_by"]) == ("site-induction", "2028-10-12", KIM)


def test_each_event_has_its_own_id(client, db, manager_headers, kim):
    make_person(db, "LL043", "Ash Patel")
    yard.grant(client, manager_headers, "LL042", "forklift-licence", "2026-03-01")
    yard.grant(client, manager_headers, "LL043", "forklift-licence", "2026-03-01")
    ids = [e["event_id"] for e in fired(db)]
    assert len(set(ids)) == 2
```

Add a test for step 4's way in to the same file, using step 4's own test helpers to have Sam sign off one of Kim's practicals (the same steps as step 4's own test that a sign-off makes it current), then:
```python
    [event] = fired(db)
    assert (event["data"]["competency"]["kind"], event["data"]["status"],
            event["data"]["recorded_by"]) == ("practical", "current",
                                              {"code": "SV001", "name": "Sam Vu"})
```
with `recorded_by` being whoever step 4 records as having signed it off.

**Step 2: Run them to see them fail**

Run: `cd api && .venv/bin/pytest tests/test_competency_events.py -q`
Expected: FAIL: `8 failed, 1 passed` (9 failed, 1 passed with the practical's): nothing is fired yet. `test_nothing_is_fired_for_what_is_refused` passes already, and must go on passing.

**Step 3: Minimal implementation**

In `api/lms/services/events.py`, replace:
```python
from lms.models import EventSeen, Outbox, Webhook
```
with:
```python
from lms.models import Competency, CompetencyRecord, EventSeen, Outbox, Person, Webhook
from lms.services import clock, standing
from lms.services.status import Status, expiry
```

Append to `api/lms/services/events.py`:
```python


# --- what each event says ----------------------------------------------------

def person_ref(p: Person) -> dict:
    return {"code": p.code, "name": p.name}


def competency_ref(c: Competency) -> dict:
    return {"key": c.key, "name": c.name, "kind": c.kind}


def _iso(d) -> str | None:
    return d.isoformat() if d is not None else None


def status_now(db: Db, person_id: int, competency_id: int) -> Status:
    """status.py's word on it as it stands in this transaction, as the
    competency API would answer."""
    st = standing.load(db, [person_id], clock.today())
    if competency_id not in st.competencies:
        return Status("not_required")
    return st.status(person_id, competency_id)


def granted(db: Db, r: CompetencyRecord) -> uuid.UUID:
    """competency.granted, for a grant just added: by hand, a ticket checked,
    a policy signed, a module passed or a practical signed off."""
    db.flush()
    c = db.get(Competency, r.competency_id)
    return emit(db, "competency.granted", {
        "person": person_ref(db.get(Person, r.person_id)), "competency": competency_ref(c),
        "record_id": r.id, "granted_on": _iso(r.granted_on),
        # its last good day, worked out as status.py does: the card's date,
        # or the refresher after the grant, or none
        "expires_on": _iso(expiry(r.granted_on, r.expires_on, c.refresher_months)),
        "status": status_now(db, r.person_id, r.competency_id).status,
        "recorded_by": person_ref(db.get(Person, r.recorded_by_id)),
    })


def revoked(db: Db, r: CompetencyRecord) -> uuid.UUID:
    """competency.revoked, for a revoke just added, with why."""
    db.flush()
    return emit(db, "competency.revoked", {
        "person": person_ref(db.get(Person, r.person_id)),
        "competency": competency_ref(db.get(Competency, r.competency_id)),
        "record_id": r.id, "note": r.note,
        "status": status_now(db, r.person_id, r.competency_id).status,
        "recorded_by": person_ref(db.get(Person, r.recorded_by_id)),
    })
```

In `api/lms/api/routes/records.py`, replace:
```python
from lms.services import clock, policies
```
with:
```python
from lms.services import clock, events, policies
```

In `api/lms/api/routes/records.py`, replace:
```python
                         note=body.note or None, recorded_by=who.person, policy_version=version)
    db.add(r)
    db.commit()
```
with:
```python
                         note=body.note or None, recorded_by=who.person, policy_version=version)
    db.add(r)
    events.granted(db, r)
    db.commit()
```

In `api/lms/api/routes/records.py`, replace:
```python
    r = CompetencyRecord(person_id=p.id, competency=c, kind="revoked", note=body.note,
                         recorded_by=who.person)
    db.add(r)
    db.commit()
```
with:
```python
    r = CompetencyRecord(person_id=p.id, competency=c, kind="revoked", note=body.note,
                         recorded_by=who.person)
    db.add(r)
    events.revoked(db, r)
    db.commit()
```

In `api/lms/api/routes/tickets.py`, replace:
```python
from lms.services import clock, uploads
```
with:
```python
from lms.services import clock, events, uploads
```

In `api/lms/api/routes/tickets.py`, replace:
```python
    db.add(CompetencyRecord(person_id=t.person_id, competency_id=t.competency_id, kind="granted",
                            granted_on=today, expires_on=t.expires_on,
                            note=f"Ticket {t.number}, checked", recorded_by=who.person,
                            ticket_submission_id=t.id))
```
with:
```python
    r = CompetencyRecord(person_id=t.person_id, competency_id=t.competency_id, kind="granted",
                         granted_on=today, expires_on=t.expires_on,
                         note=f"Ticket {t.number}, checked", recorded_by=who.person,
                         ticket_submission_id=t.id)
    db.add(r)
    events.granted(db, r)
```

In `api/lms/api/routes/policies.py`, replace:
```python
from lms.services import clock, policies, uploads
```
with:
```python
from lms.services import clock, events, policies, uploads
```

In `api/lms/api/routes/policies.py`, replace:
```python
                         signature_upload_id=signature.id)
    db.add(r)
    db.commit()
```
with:
```python
                         signature_upload_id=signature.id)
    db.add(r)
    events.granted(db, r)
    db.commit()
```

In `api/lms/api/routes/learning.py`, replace:
```python
from lms.services import clock, modules
```
with:
```python
from lms.services import clock, events, modules
```

In `api/lms/api/routes/learning.py`, replace:
```python
        db.add(CompetencyRecord(person_id=p.id, competency=c, kind="granted",
                                granted_on=clock.today(), recorded_by=p, quiz_attempt=attempt))
```
with:
```python
        r = CompetencyRecord(person_id=p.id, competency=c, kind="granted",
                             granted_on=clock.today(), recorded_by=p, quiz_attempt=attempt)
        db.add(r)
        events.granted(db, r)
```

In step 4's sign-off route, the same: where it adds the `CompetencyRecord` for the practical signed off, name it `r` if it isn't already, and call `events.granted(db, r)` after `db.add(r)` and before `db.commit()`, importing `events` from `lms.services` beside what it imports from there. `grep -rn -A5 "CompetencyRecord(person_id" api/lms/api` must then show every grant and revoke followed by an `events.` call (five of them on `c193b0c`, six with step 4's).

**Step 4: Run them, and the whole suite, to see them pass**

Run: `cd api && .venv/bin/pytest tests/test_competency_events.py tests/test_records.py tests/test_tickets.py tests/test_policies.py tests/test_quiz.py -q`
Expected: all pass (9 new; those files' tests as they were).

Run: `cd api && .venv/bin/pytest -q`
Expected: A + 47 passed (`493 passed`; one more with the practical's test).

**Step 5: Commit**

```
git add api/lms/services/events.py api/lms/api/routes api/tests/test_competency_events.py
git commit -m "Fire competency.granted and competency.revoked from every grant and revoke" \
  -m "By hand, a ticket approved, a policy signed, a module passed, a practical signed off: each says the status it leaves and the last good day."
```

---

### Task 6: person.updated, whenever what another system keeps about a person changes

**Files:**
- Modify: `api/lms/services/events.py`, `api/lms/api/errors.py`, `api/lms/api/routes/people.py`
- Test: create `api/tests/test_person_events.py`

**Step 1: Write the failing tests**

`api/tests/test_person_events.py`:
```python
"""person.updated: fired whenever what another system keeps about a person
changes: added, details, roles, deactivated or back. Never a PIN or a
password."""
import pytest

import yard
from conftest import make_person
from lms.models import Outbox, Webhook


@pytest.fixture
def hook(db):
    db.add(Webhook(name="Simple TMS", url="https://tms.example.com.au/in", secret="whsec_x",
                   events=["person.updated"]))
    db.commit()


def fired(db) -> list[dict]:
    db.expire_all()
    return [r.payload["data"]["person"] for r in
            db.query(Outbox).filter_by(kind="webhook").order_by(Outbox.id)]


def test_added(client, db, manager_headers, supervisor, hook):
    yard.build(client, manager_headers)
    r = client.post("/v1/people", headers=manager_headers,
                    json={"code": "ll042", "name": "Kim Lee", "email": "Kim@Example.com.au",
                          "supervisor": "SV001", "roles": ["picker"], "pin": "2468"})
    assert r.status_code == 201
    assert fired(db) == [{"code": "LL042", "name": "Kim Lee", "email": "kim@example.com.au",
                          "permission": "learner", "active": True,
                          "supervisor": {"code": "SV001", "name": "Sam Vu"},
                          "roles": [{"key": "picker", "name": "Picker"}]}]


def test_details_and_roles_changed(client, db, manager_headers, learner, hook):
    yard.build(client, manager_headers)
    client.patch("/v1/people/LL042", headers=manager_headers,
                 json={"name": "Kim Lee-Park", "supervisor": None})
    yard.give_roles(client, manager_headers, "LL042", "forklift-operator", "picker")
    first, second = fired(db)
    assert (first["name"], first["supervisor"], first["roles"]) == ("Kim Lee-Park", None, [])
    assert [r["key"] for r in second["roles"]] == ["forklift-operator", "picker"]


def test_deactivated_and_back(client, db, manager_headers, learner, hook):
    client.post("/v1/people/LL042/deactivate", headers=manager_headers)
    client.post("/v1/people/LL042/reactivate", headers=manager_headers)
    assert [p["active"] for p in fired(db)] == [False, True]


def test_not_for_a_pin_or_a_password(client, db, manager_headers, learner, hook):
    client.post("/v1/people/LL042/pin", headers=manager_headers, json={"pin": "1357"})
    client.post("/v1/people/LL042/password", headers=manager_headers,
                json={"password": "a long new password"})
    assert fired(db) == []


def test_not_for_what_is_refused(client, db, manager_headers, hook):
    make_person(db, "AD002", "Ada Admin", "admin")
    r = client.patch("/v1/people/AD002", headers=manager_headers, json={"name": "Ada"})
    assert r.status_code == 403
    r = client.post("/v1/people", headers=manager_headers,
                    json={"code": "AD002", "name": "Someone else"})
    assert r.status_code == 422
    assert fired(db) == []
```

**Step 2: Run them to see them fail**

Run: `cd api && .venv/bin/pytest tests/test_person_events.py -q`
Expected: FAIL: `3 failed, 2 passed`: nothing is fired yet (the PIN and refusal tests pass already, and must go on passing).

**Step 3: Minimal implementation**

Append to `api/lms/services/events.py`:
```python


def person_updated(db: Db, p: Person) -> uuid.UUID:
    """person.updated: what another system keeps about a person, as it is
    now. Added, details changed, roles changed, deactivated or back; never
    a PIN or password."""
    return emit(db, "person.updated", {"person": {
        "code": p.code, "name": p.name, "email": p.email, "permission": p.permission,
        "active": p.active,
        "supervisor": person_ref(p.supervisor) if p.supervisor else None,
        "roles": [{"key": r.key, "name": r.name} for r in p.roles],
    }})
```

Adding a person or changing their email can lose a race to a unique constraint, and `commit_unique` turns that into the field's `422`. Queuing the event flushes the person, which is where that race is lost, so it has to happen inside the same guard. In `api/lms/api/errors.py`, replace:
```python
def commit_unique(db, taken: dict[str, FieldError]) -> None:
    """Commit, as the check before it said was fine. Two requests at once can
    both pass that check; the one that loses to a unique constraint named in
    `taken` gets that constraint's field error, as if the check had caught it."""
    try:
        db.commit()
```
with:
```python
def commit_unique(db, taken: dict[str, FieldError], before=None) -> None:
    """Commit, as the check before it said was fine. Two requests at once can
    both pass that check; the one that loses to a unique constraint named in
    `taken` gets that constraint's field error, as if the check had caught it.
    `before` runs first, inside the same guard: something that flushes, such
    as queuing an event about the change."""
    try:
        if before is not None:
            before()
        db.commit()
```

In `api/lms/api/routes/people.py`, replace:
```python
from lms.services import access, sessions
```
with:
```python
from lms.services import access, events, sessions
```

In `api/lms/api/routes/people.py`, replace:
```python
    db.add(p)
    commit_unique(db, {"uq_person_code": code_taken,
                       "uq_person_email": _email_taken(body.email)})
```
with:
```python
    db.add(p)
    commit_unique(db, {"uq_person_code": code_taken,
                       "uq_person_email": _email_taken(body.email)},
                  before=lambda: events.person_updated(db, p))
```

In `api/lms/api/routes/people.py`, replace:
```python
    commit_unique(db, {"uq_person_email": _email_taken(body.email)})
    return person_out(p)
```
with:
```python
    commit_unique(db, {"uq_person_email": _email_taken(body.email)},
                  before=lambda: events.person_updated(db, p))
    return person_out(p)
```

In `api/lms/api/routes/people.py`, replace:
```python
    p.roles = _roles(db, body.roles)
    db.commit()
    db.refresh(p)
```
with:
```python
    p.roles = _roles(db, body.roles)
    events.person_updated(db, p)
    db.commit()
    db.refresh(p)
```

In `api/lms/api/routes/people.py`, replace:
```python
    p.active = False
    sessions.end_all(db, p)
    db.commit()
```
with:
```python
    p.active = False
    sessions.end_all(db, p)
    events.person_updated(db, p)
    db.commit()
```

In `api/lms/api/routes/people.py`, replace:
```python
    p.active = True
    db.commit()
```
with:
```python
    p.active = True
    events.person_updated(db, p)
    db.commit()
```

If step 5 added a way to change what is in `person.updated` (it links an Entra id, which isn't in it, so most likely not), it calls `events.person_updated` the same way.

**Step 4: Run them, and the whole suite, to see them pass**

Run: `cd api && .venv/bin/pytest tests/test_person_events.py tests/test_people.py tests/test_people_access.py -q`
Expected: all pass (5 new); `test_people.py`'s race test still gets its `422`s.

Run: `cd api && .venv/bin/pytest -q`
Expected: A + 52 passed (`498 passed`).

**Step 5: Commit**

```
git add api/lms/services/events.py api/lms/api/errors.py api/lms/api/routes/people.py api/tests/test_person_events.py
git commit -m "Fire person.updated when a person is added, changed, given roles, deactivated or back" \
  -m "Never for a PIN or a password. Queued inside commit_unique's guard, so a lost race is still a 422."
```

---

### Task 7: competency.expiring and competency.lapsed from the daily job, each once

**Files:**
- Modify: `api/lms/services/daily.py`, `api/lms/cli.py`, `api/lms/worker.py`
- Test: `api/tests/test_daily.py`, `api/tests/test_cli.py`, `api/tests/test_worker.py`

**Step 1: Write the failing tests**

In `api/tests/test_daily.py`, replace:
```python
from lms.models import Outbox
```
with:
```python
from lms.models import EventSeen, Outbox, Webhook
```

Append to `api/tests/test_daily.py`:
```python


# --- competency.expiring and competency.lapsed -------------------------------

@pytest.fixture
def hook(db):
    db.add(Webhook(name="Simple TMS", url="https://tms.example.com.au/in", secret="whsec_x",
                   events=["competency.expiring", "competency.lapsed"]))
    db.commit()


def told(db) -> list[tuple[str, str, str]]:
    db.expire_all()
    rows = db.query(Outbox).filter_by(kind="webhook").order_by(Outbox.id).all()
    return [(r.payload["event_type"], r.payload["data"]["competency"]["key"],
             r.payload["data"]["expires_on"]) for r in rows]


def test_expiring_then_lapsed_each_once(db, kim, hook):
    on(db, MONDAY, MONDAY, date(2026, 10, 28), date(2026, 11, 11))
    assert told(db) == [("competency.expiring", "forklift-licence", "2026-11-11")]
    on(db, date(2026, 11, 12), date(2026, 11, 13), date(2026, 12, 25))
    assert told(db)[1:] == [("competency.lapsed", "forklift-licence", "2026-11-11")]


def test_what_expiring_says(db, kim, hook):
    on(db, MONDAY)
    [row] = db.query(Outbox).filter_by(kind="webhook").all()
    assert row.payload["data"] == {
        "person": {"code": "LL042", "name": "Kim Lee"},
        "competency": {"key": "forklift-licence", "name": "Forklift licence", "kind": "ticket"},
        "status": "expiring", "granted_on": "2025-01-01", "expires_on": "2026-11-11",
        "days_left": 30}
    assert row.payload["event_id"] == str(db.query(EventSeen).one().event_id)


def test_a_renewal_is_told_afresh(client, db, manager_headers, kim, hook):
    on(db, MONDAY)
    yard.grant(client, manager_headers, "LL042", "forklift-licence", "2026-10-12",
               expires_on="2026-11-30")
    on(db, date(2026, 11, 1))
    assert told(db) == [("competency.expiring", "forklift-licence", "2026-11-11"),
                        ("competency.expiring", "forklift-licence", "2026-11-30")]


def test_a_lapse_the_job_first_sees_late_is_told_as_lapsed_only(db, kim, hook):
    on(db, date(2026, 11, 20))
    assert told(db) == [("competency.lapsed", "forklift-licence", "2026-11-11")]


def test_fired_once_whoever_was_listening(db, kim):
    on(db, MONDAY)
    assert db.query(EventSeen).count() == 1
    db.add(Webhook(name="Late", url="https://late.example.com.au", secret="s", events=["*"]))
    db.commit()
    on(db, MONDAY)
    assert told(db) == []


def test_not_for_a_waiver_nor_someone_deactivated(client, db, manager_headers, kim, hook):
    client.post("/v1/people/LL042/overrides", headers=manager_headers,
                json={"competency": "forklift-licence", "kind": "waive", "note": "office only now"})
    make_person(db, "LL043", "Ash Patel")
    yard.give_roles(client, manager_headers, "LL043", "picker")
    yard.grant(client, manager_headers, "LL043", "site-induction", "2024-09-01")   # lapsed
    client.post("/v1/people/LL043/deactivate", headers=manager_headers)
    on(db, MONDAY)
    assert told(db) == []


def test_it_says_how_many_it_fired(db, kim, hook):
    assert daily.run(db, MONDAY)["events"] == 1
    assert daily.run(db, MONDAY)["events"] == 0
```

In `api/tests/test_cli.py`, replace:
```python
        "2026-10-13: 1 reminders and 0 digests queued; the worker sends them")
```
with:
```python
        "2026-10-13: 1 reminders, 0 digests and 1 events queued; the worker sends them")
```

In `api/tests/test_worker.py`, replace:
```python
                        {"reminders": 0, "digests": 0})
```
with:
```python
                        {"reminders": 0, "digests": 0, "events": 0})
```

**Step 2: Run them to see them fail**

Run: `cd api && .venv/bin/pytest tests/test_daily.py tests/test_cli.py -q`
Expected: FAIL: `7 failed, 23 passed`: nothing is fired, there is no `events` count, and the command line says it the old way. `test_not_for_a_waiver_nor_someone_deactivated` passes already, and must go on passing.

**Step 3: Minimal implementation**

In `api/lms/services/daily.py`, replace:
```python
"""The daily job, run by the worker each morning: a reminder to each
learner with an email when something of theirs reaches a reminder day
(Settings; 30, 14 and 0 days left unless changed),
and on Mondays a digest of what is expiring and lapsed for each manager.
Status comes from status.py, as everywhere (rule 2). Each email has its
own key in the outbox, so running the job again sends nothing twice."""
```
with:
```python
"""The daily job, run by the worker each morning: a reminder to each
learner with an email when something of theirs reaches a reminder day
(Settings; 30, 14 and 0 days left unless changed), on Mondays a digest of
what is expiring and lapsed for each manager, and competency.expiring and
competency.lapsed for the webhooks. Status comes from status.py, as
everywhere (rule 2). Each email has its own key in the outbox and each
event is fired once, so running the job again sends nothing twice."""
```

In `api/lms/services/daily.py`, replace:
```python
from lms.models import Person
from lms.services import outbox, settings, standing
```
with:
```python
from lms.models import Competency, Person
from lms.services import events, outbox, settings, standing
from lms.services.status import Status
```

In `api/lms/services/daily.py`, replace:
```python
def run(db: Db, today: date, now: datetime | None = None) -> dict[str, int]:
    """Queue today's reminders and (on a Monday) the digests. Returns how
    many were queued now; anything an earlier run queued is not queued again."""
    queued = {"reminders": 0, "digests": 0}
```
with:
```python
def fire(db: Db, p: Person, c: Competency, s: Status, today: date,
         now: datetime | None) -> bool:
    """competency.expiring or competency.lapsed, once for each last good day:
    the first day the job finds it so. A renewal has a new last good day, so
    it is told afresh when it comes round. True when it fired now."""
    data = {"person": events.person_ref(p), "competency": events.competency_ref(c),
            "status": s.status, "granted_on": s.granted_on.isoformat(),
            "expires_on": s.expires_on.isoformat()}
    if s.status == "expiring":
        data["days_left"] = (s.expires_on - today).days
    event_type = f"competency.{s.status}"
    key = f"{event_type}:{p.id}:{c.id}:{s.expires_on.isoformat()}"
    return events.once(db, key, event_type, data, now)


def run(db: Db, today: date, now: datetime | None = None) -> dict[str, int]:
    """Queue today's reminders, (on a Monday) the digests, and the expiring
    and lapsed events. Returns how many were queued now; anything an earlier
    run queued is not queued again."""
    queued = {"reminders": 0, "digests": 0, "events": 0}
```

In `api/lms/services/daily.py`, replace:
```python
            if s.status in ("expiring", "lapsed"):
                items.append(Item(p, name, s.status, s.expires_on))
```
with:
```python
            if s.status in ("expiring", "lapsed"):
                items.append(Item(p, name, s.status, s.expires_on))
                queued["events"] += fire(db, p, st.competencies[c], s, today, now)
```

In `api/lms/cli.py`, replace:
```python
    print(f"{day.isoformat()}: {queued['reminders']} reminders and {queued['digests']} digests "
          "queued; the worker sends them")
```
with:
```python
    print(f"{day.isoformat()}: {queued['reminders']} reminders, {queued['digests']} digests "
          f"and {queued['events']} events queued; the worker sends them")
```

In `api/lms/cli.py`, replace:
```python
    p = sub.add_parser("daily-job", help="queue the reminders (and on a Monday the digests) now")
```
with:
```python
    p = sub.add_parser("daily-job", help="queue the reminders, the expiring and lapsed events "
                                         "(and on a Monday the digests) now")
```

In `api/lms/worker.py`, replace:
```python
            log.info("daily job for %s: %d reminders, %d digests queued", day,
                     queued["reminders"], queued["digests"])
```
with:
```python
            log.info("daily job for %s: %d reminders, %d digests, %d events queued", day,
                     queued["reminders"], queued["digests"], queued["events"])
```

**Step 4: Run them, and the whole suite, to see them pass**

Run: `cd api && .venv/bin/pytest tests/test_daily.py tests/test_cli.py tests/test_worker.py -q`
Expected: `50 passed` (7 new)

Run: `cd api && .venv/bin/pytest -q`
Expected: A + 59 passed (`505 passed`).

**Step 5: Commit**

```
git add api/lms/services/daily.py api/lms/cli.py api/lms/worker.py api/tests/test_daily.py api/tests/test_cli.py api/tests/test_worker.py
git commit -m "Fire competency.expiring and competency.lapsed from the daily job, each once" \
  -m "Once for each last good day, whoever was listening, so a renewal is told afresh and a webhook added later isn't sent every lapse there has been."
```

---
### Task 8: API keys: made by an admin, shown once, revoked, and refused everywhere a person goes

**Files:**
- Create: `api/lms/services/api_keys.py`, `api/lms/api/routes/api_keys.py`
- Modify: `api/lms/api/deps.py`, `api/lms/services/sessions.py`, `api/lms/api/app.py`
- Test: create `api/tests/test_api_keys.py`

**Step 1: Write the failing tests**

`api/tests/test_api_keys.py`:
```python
"""API keys: for other systems, not people. An admin makes one with the
scopes it needs, sees it once, and revokes it; only its hash is kept."""
import hashlib
from datetime import UTC, datetime, timedelta

import pytest

from conftest import bearer
from lms.models import ApiKey
from lms.services import api_keys

TMS = {"name": "Simple TMS", "scopes": ["competencies:read"]}


@pytest.fixture
def made(client, admin_headers):
    r = client.post("/v1/api-keys", headers=admin_headers, json=TMS)
    assert r.status_code == 201, r.text
    return r.json()


def test_made_and_shown_once_and_only_its_hash_kept(client, db, admin_headers, made):
    assert made["key"].startswith("lms_k.") and len(made["key"]) > 40
    assert made["prefix"] == made["key"][:10]
    assert (made["name"], made["scopes"], made["revoked_at"], made["last_used_at"]) == (
        "Simple TMS", ["competencies:read"], None, None)
    assert made["created_by"] == {"code": "AD001", "name": "Leighton Lauton"}
    row = db.query(ApiKey).one()
    assert row.key_hash == hashlib.sha256(made["key"].encode()).hexdigest()
    listed = client.get("/v1/api-keys", headers=admin_headers).json()
    assert [k["name"] for k in listed] == ["Simple TMS"] and "key" not in listed[0]


@pytest.mark.parametrize("body, field", [
    ({"scopes": ["people:write"]}, "scopes.0"),
    ({"scopes": []}, "scopes"),
    ({"name": ""}, "name"),
])
def test_what_is_wrong_is_said(client, admin_headers, body, field):
    r = client.post("/v1/api-keys", headers=admin_headers, json={**TMS, **body})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == field


def test_two_cannot_share_a_name(client, admin_headers, made):
    r = client.post("/v1/api-keys", headers=admin_headers, json=TMS)
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "name"


def test_only_an_admin(client, manager_headers):
    assert client.get("/v1/api-keys", headers=manager_headers).status_code == 403
    assert client.post("/v1/api-keys", headers=manager_headers, json=TMS).status_code == 403


def test_a_key_opens_nothing_a_person_does(client, made):
    for path in ("/v1/auth/me", "/v1/people", "/v1/matrix", "/v1/webhooks"):
        r = client.get(path, headers=bearer(made["key"]))
        assert r.status_code == 403 and r.json()["code"] == "key_not_allowed", path


def test_a_key_that_is_not_ours_is_refused(client):
    r = client.get("/v1/people", headers=bearer("lms_k.not-a-real-one"))
    assert r.status_code == 401


def test_revoked_once_and_it_stops_working(client, db, admin_headers, made):
    r = client.post(f"/v1/api-keys/{made['id']}/revoke", headers=admin_headers)
    assert r.status_code == 200 and r.json()["revoked_at"] is not None
    assert api_keys.find(db, made["key"]) is None
    r = client.post(f"/v1/api-keys/{made['id']}/revoke", headers=admin_headers)
    assert r.status_code == 409 and r.json()["code"] == "revoked"
    assert client.post("/v1/api-keys/999/revoke", headers=admin_headers).status_code == 404


def test_when_it_was_last_used_is_noted_once_a_minute(db, made):
    t0 = datetime(2026, 10, 12, 1, 0, tzinfo=UTC)
    assert api_keys.find(db, made["key"], now=t0).last_used_at == t0
    assert api_keys.find(db, made["key"], now=t0 + timedelta(seconds=30)).last_used_at == t0
    later = t0 + timedelta(minutes=1)
    assert api_keys.find(db, made["key"], now=later).last_used_at == later
```

**Step 2: Run them to see them fail**

Run: `cd api && .venv/bin/pytest tests/test_api_keys.py -q`
Expected: FAIL: `ImportError: cannot import name 'api_keys' from 'lms.services'` while collecting.

**Step 3: Minimal implementation**

`api/lms/services/api_keys.py`:
```python
"""Keys for other systems, not people: Simple TMS reading who is current,
say. The key is shown once; only its SHA-256 is kept, which is enough for
256 random bits: there is nothing to guess back. A key opens only what its
scopes say, and nothing a person's session does."""
from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session as Db

from lms.models import ApiKey, Person

PREFIX = "lms_k."
# what a key may be given: reading people's status, with the competency API
SCOPES = ("competencies:read",)
# last_used_at is written at most once a minute, as a session's last_seen_at is
TOUCH_EVERY = timedelta(minutes=1)


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def create(db: Db, name: str, scopes: list[str], by: Person) -> tuple[ApiKey, str]:
    """A new key; the raw key is returned once and never stored."""
    raw = PREFIX + secrets.token_urlsafe(32)
    key = ApiKey(name=name, key_hash=_hash(raw), prefix=raw[:len(PREFIX) + 4],
                 scopes=list(scopes), created_by=by)
    db.add(key)
    return key, raw


def find(db: Db, raw: str, now: datetime | None = None) -> ApiKey | None:
    """The key this is, if it is ours and not revoked, marked as just used."""
    now = now or datetime.now(UTC)
    key = db.execute(select(ApiKey).where(ApiKey.key_hash == _hash(raw))).scalar_one_or_none()
    if key is None or key.revoked_at is not None:
        return None
    if key.last_used_at is None or now - key.last_used_at >= TOUCH_EVERY:
        key.last_used_at = now
        db.commit()
    return key
```

`api/lms/api/routes/api_keys.py`:
```python
"""API keys: made by an admin on the Settings screen for another system,
with the scopes it needs, shown once, and revoked when it is done with.
Never deleted."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select

from lms.api.deps import DB, Principal, require
from lms.api.errors import Conflict, FieldError, NotFound, commit_unique
from lms.api.schemas import PersonRef, person_ref
from lms.models import ApiKey
from lms.services import api_keys

router = APIRouter(tags=["api keys"])

# an admin's, on the Settings screen
SCOPE = "settings:write"

KeyScope = Literal["competencies:read"]


class ApiKeyIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    # who it is for, e.g. Simple TMS
    name: str = Field(min_length=1, max_length=120)
    scopes: list[KeyScope] = Field(min_length=1, max_length=len(api_keys.SCOPES))

    @field_validator("scopes")
    @classmethod
    def _each_once(cls, v):
        return list(dict.fromkeys(v))


class ApiKeyOut(BaseModel):
    id: int
    name: str
    # its first characters, to tell which key is which
    prefix: str
    scopes: list[str]
    created_by: PersonRef
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None


class ApiKeyMade(ApiKeyOut):
    # shown this once: Simple LMS keeps only its hash
    key: str


def key_out(k: ApiKey) -> ApiKeyOut:
    return ApiKeyOut(id=k.id, name=k.name, prefix=k.prefix, scopes=k.scopes,
                     created_by=person_ref(k.created_by), created_at=k.created_at,
                     last_used_at=k.last_used_at, revoked_at=k.revoked_at)


def _name_taken(name: str) -> FieldError:
    return FieldError("name", f"there is already a key called {name}")


@router.get("/api-keys", response_model=list[ApiKeyOut])
def list_keys(db: DB, who: Principal = require(SCOPE)):
    """By name, revoked or not."""
    rows = db.execute(select(ApiKey).order_by(ApiKey.name)).scalars().all()
    return [key_out(k) for k in rows]


@router.post("/api-keys", status_code=201, response_model=ApiKeyMade)
def make_key(body: ApiKeyIn, db: DB, who: Principal = require(SCOPE)):
    if db.execute(select(ApiKey.id).where(ApiKey.name == body.name)).first():
        raise _name_taken(body.name)
    key, raw = api_keys.create(db, body.name, body.scopes, who.person)
    commit_unique(db, {"uq_api_key_name": _name_taken(body.name)})
    out = ApiKeyMade(**key_out(key).model_dump(), key=raw)
    return JSONResponse(status_code=201, content=out.model_dump(mode="json"))


@router.post("/api-keys/{key_id}/revoke", response_model=ApiKeyOut)
def revoke_key(key_id: int, db: DB, who: Principal = require(SCOPE)):
    """It stops working at once, for good."""
    k = db.get(ApiKey, key_id, with_for_update=True)
    if k is None:
        raise NotFound(f"no API key {key_id}")
    if k.revoked_at is not None:
        raise Conflict("revoked", f"the key {k.name} was revoked already")
    k.revoked_at = datetime.now(UTC)
    db.commit()
    return key_out(k)
```

A key is not a session: `get_principal` refuses one plainly, so every route a person uses stays closed to keys. In `api/lms/api/deps.py`, replace:
```python
from lms.services import sessions
```
with:
```python
from lms.services import api_keys, sessions
```

In `api/lms/api/deps.py`, replace:
```python
def get_principal(db: DB, authorization: Annotated[str | None, Header()] = None) -> Principal:
    raw = bearer_token(authorization)
    if raw is None:
        raise Unauthorised("missing bearer token")
    row = sessions.find(db, raw)
```
with:
```python
def get_principal(db: DB, authorization: Annotated[str | None, Header()] = None) -> Principal:
    raw = bearer_token(authorization)
    if raw is None:
        raise Unauthorised("missing bearer token")
    if raw.startswith(api_keys.PREFIX):
        if api_keys.find(db, raw) is None:
            raise Unauthorised("API key unknown or revoked")
        raise Forbidden("an API key opens the competency API only", "key_not_allowed")
    row = sessions.find(db, raw)
```

In `api/lms/services/sessions.py`, replace:
```python
# are the admin's "*" alone: settings:write (Settings, sign-in methods among
# them) now, webhooks and API keys with their step.
```
with:
```python
# are the admin's "*" alone: settings:write (Settings: sign-in methods,
# email, printing, webhooks and API keys).
```

In `api/lms/api/app.py`, replace:
```python
    auth, competencies, learning, matrix, media, modules, overrides, people, policies, records,
    roles, settings, tickets, uploads, webhooks,
)
```
with:
```python
    api_keys, auth, competencies, learning, matrix, media, modules, overrides, people, policies,
    records, roles, settings, tickets, uploads, webhooks,
)
```

In `api/lms/api/app.py`, replace:
```python
v1.include_router(webhooks.router)
```
with:
```python
v1.include_router(webhooks.router)
v1.include_router(api_keys.router)
```

**Step 4: Run them, and the whole suite, to see them pass**

Run: `cd api && .venv/bin/pytest tests/test_api_keys.py -q`
Expected: `10 passed`

Run: `cd api && .venv/bin/pytest -q`
Expected: A + 69 passed (`515 passed`).

**Step 5: Commit**

```
git add api/lms/services/api_keys.py api/lms/api/routes/api_keys.py api/lms/api/deps.py api/lms/services/sessions.py api/lms/api/app.py api/tests/test_api_keys.py
git commit -m "Let an admin make API keys for other systems, shown once and kept as a hash, and revoke them" \
  -m "A key is not a session: anywhere a person goes it is 403 key_not_allowed."
```

---

### Task 9: The competency API, read with a key or a session

**Files:**
- Create: `api/lms/api/routes/statuses.py`
- Modify: `api/lms/api/deps.py`, `api/lms/api/app.py`
- Test: create `api/tests/test_competency_api.py`

**Step 1: Write the failing tests**

`api/tests/test_competency_api.py`:
```python
"""The competency API: is this person current for what they need, or for
this one competency? For another system with an API key, and for the
people who may see the person."""
import pytest

import yard
from conftest import bearer, make_person
from lms.models import ApiKey


@pytest.fixture
def key(client, admin_headers) -> dict:
    r = client.post("/v1/api-keys", headers=admin_headers,
                    json={"name": "Simple TMS", "scopes": ["competencies:read"]})
    return bearer(r.json()["key"])


@pytest.fixture
def kim(client, manager_headers, learner):
    """Kim is a forklift operator: the induction current, the licence
    expiring, and first aid (not asked of her) done anyway."""
    yard.build(client, manager_headers)
    yard.give_roles(client, manager_headers, "LL042", "forklift-operator")
    yard.grant(client, manager_headers, "LL042", "site-induction", "2026-01-01")
    yard.grant(client, manager_headers, "LL042", "forklift-licence", "2025-01-01",
               expires_on="2026-11-11")
    yard.grant(client, manager_headers, "LL042", "first-aid", "2026-01-01")
    return learner


def test_everything_they_are_asked_for(client, key, kim):
    r = client.get("/v1/people/ll042/competencies", headers=key)
    assert r.status_code == 200, r.text
    assert r.json() == {
        "person": {"code": "LL042", "name": "Kim Lee", "active": True},
        "today": "2026-10-12",
        "competencies": [
            {"key": "forklift-licence", "name": "Forklift licence", "kind": "ticket",
             "status": "expiring", "granted_on": "2025-01-01", "expires_on": "2026-11-11"},
            {"key": "site-induction", "name": "Site induction", "kind": "module",
             "status": "current", "granted_on": "2026-01-01", "expires_on": "2028-01-01"},
        ]}


def test_one_competency(client, key, kim):
    r = client.get("/v1/people/LL042/competencies/Forklift-Licence", headers=key)
    assert r.status_code == 200
    assert r.json() == {"person": {"code": "LL042", "name": "Kim Lee", "active": True},
                        "today": "2026-10-12", "key": "forklift-licence",
                        "name": "Forklift licence", "kind": "ticket", "status": "expiring",
                        "granted_on": "2025-01-01", "expires_on": "2026-11-11"}


def test_one_not_asked_of_them_or_deactivated_is_not_required(client, manager_headers, key, kim):
    r = client.get("/v1/people/LL042/competencies/first-aid", headers=key).json()
    assert (r["status"], r["expires_on"]) == ("not_required", None)
    client.post("/v1/competencies/forklift-licence/deactivate", headers=manager_headers)
    r = client.get("/v1/people/LL042/competencies/forklift-licence", headers=key).json()
    assert r["status"] == "not_required"


def test_someone_who_has_left_says_so(client, manager_headers, key, kim):
    client.post("/v1/people/LL042/deactivate", headers=manager_headers)
    r = client.get("/v1/people/LL042/competencies/site-induction", headers=key).json()
    assert (r["person"]["active"], r["status"]) == (False, "current")


def test_who_or_what_is_not_there(client, key, kim):
    assert client.get("/v1/people/ZZ999/competencies", headers=key).status_code == 404
    assert client.get("/v1/people/LL042/competencies/juggling", headers=key).status_code == 404


def test_a_revoked_key_is_refused(client, db, admin_headers, key, kim):
    k = db.query(ApiKey).one()
    client.post(f"/v1/api-keys/{k.id}/revoke", headers=admin_headers)
    assert client.get("/v1/people/LL042/competencies", headers=key).status_code == 401


def test_a_person_sees_it_for_whom_they_may_see(client, db, manager_headers, supervisor_headers,
                                                learner_headers, kim):
    make_person(db, "LL043", "Ash Patel")
    assert client.get("/v1/people/LL043/competencies", headers=manager_headers).status_code == 200
    # Sam supervises Kim, not Ash
    assert client.get("/v1/people/LL042/competencies",
                      headers=supervisor_headers).status_code == 200
    assert client.get("/v1/people/LL043/competencies",
                      headers=supervisor_headers).status_code == 404
    # a learner's own is My training: /v1/people/{code}/training
    r = client.get("/v1/people/LL042/competencies", headers=learner_headers)
    assert r.status_code == 403
```

**Step 2: Run them to see them fail**

Run: `cd api && .venv/bin/pytest tests/test_competency_api.py -q`
Expected: FAIL: `6 failed, 1 passed`: there is no such route (so `test_who_or_what_is_not_there`'s `404`s pass already, and must go on passing).

**Step 3: Minimal implementation**

In `api/lms/api/deps.py`, replace:
```python
from lms.models import Person, Session
```
with:
```python
from lms.models import ApiKey, Person, Session
```

Append to `api/lms/api/deps.py`:
```python


@dataclass(slots=True)
class KeyCaller:
    """Another system, calling with an API key: no person, only the key's
    scopes, and anyone those let it read."""

    key: ApiKey

    def has_scope(self, scope: str) -> bool:
        return scope in self.key.scopes

    def sees(self, other: Person) -> bool:
        return True


def require_reader(scope: str):
    """Dependency: a person's session or an API key, carrying this scope.
    Only the competency API takes a key."""

    def _check(db: DB, authorization: Annotated[str | None, Header()] = None
               ) -> Principal | KeyCaller:
        raw = bearer_token(authorization)
        if raw is not None and raw.startswith(api_keys.PREFIX):
            key = api_keys.find(db, raw)
            if key is None:
                raise Unauthorised("API key unknown or revoked")
            caller: Principal | KeyCaller = KeyCaller(key)
        else:
            caller = get_principal(db, authorization)
        if not caller.has_scope(scope):
            raise Forbidden(f"you do not have the {scope} scope")
        return caller

    return Depends(_check)
```

`api/lms/api/routes/statuses.py`:
```python
"""The competency API: a person's status for everything they are asked
for, or for one competency, worked out today by status.py (rule 2). For
another system with an API key (Simple TMS checking a driver's licence and
induction before a run) and for the people who may see the person."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter
from pydantic import BaseModel

from lms.api.deps import DB, KeyCaller, Principal, require_reader
from lms.api.errors import NotFound
from lms.api.routes.competencies import get_competency
from lms.api.routes.people import get_person
from lms.models import Competency, Person
from lms.services import clock, standing
from lms.services.status import Status

router = APIRouter(tags=["competency API"])


class PersonStatusOut(BaseModel):
    code: str
    name: str
    # someone deactivated has left: their records stay, and so does their status
    active: bool


class StatusOut(BaseModel):
    key: str
    name: str
    kind: str
    # current, expiring, lapsed, missing, waived or not_required
    status: str
    granted_on: date | None
    # the last good day; null when it doesn't run out, or there is no grant
    expires_on: date | None


class CompetenciesOut(BaseModel):
    person: PersonStatusOut
    today: date
    competencies: list[StatusOut]


class CompetencyOut(StatusOut):
    person: PersonStatusOut
    today: date


def _person(db, code: str, who: Principal | KeyCaller) -> Person:
    p = get_person(db, code)
    if not who.sees(p):
        raise NotFound(f"no person {code}")
    return p


def _out(c: Competency, s: Status) -> dict:
    return {"key": c.key, "name": c.name, "kind": c.kind, "status": s.status,
            "granted_on": s.granted_on, "expires_on": s.expires_on}


def _person_out(p: Person) -> PersonStatusOut:
    return PersonStatusOut(code=p.code, name=p.name, active=p.active)


@router.get("/people/{code}/competencies", response_model=CompetenciesOut)
def competencies(code: str, db: DB,
                 who: Principal | KeyCaller = require_reader("competencies:read")):
    """Everything their roles and extras ask of them, waived or not, by name."""
    p = _person(db, code, who)
    st = standing.load(db, [p.id], clock.today())
    asked = sorted((st.competencies[c] for c in st.asked_for(p.id)),
                   key=lambda c: (c.name, c.key))
    return CompetenciesOut(person=_person_out(p), today=st.today,
                           competencies=[StatusOut(**_out(c, st.status(p.id, c.id)))
                                         for c in asked])


@router.get("/people/{code}/competencies/{key}", response_model=CompetencyOut)
def one_competency(code: str, key: str, db: DB,
                   who: Principal | KeyCaller = require_reader("competencies:read")):
    """Their status for this one: `not_required` when it isn't asked of
    them (or has been deactivated)."""
    p = _person(db, code, who)
    c = get_competency(db, key)
    st = standing.load(db, [p.id], clock.today())
    s = st.status(p.id, c.id) if c.id in st.competencies else Status("not_required")
    return CompetencyOut(person=_person_out(p), today=st.today, **_out(c, s))
```

In `api/lms/api/app.py`, replace:
```python
    records, roles, settings, tickets, uploads, webhooks,
)
```
with:
```python
    records, roles, settings, statuses, tickets, uploads, webhooks,
)
```

In `api/lms/api/app.py`, replace:
```python
v1.include_router(api_keys.router)
```
with:
```python
v1.include_router(api_keys.router)
v1.include_router(statuses.router)
```

**Step 4: Run them, and the whole suite, to see them pass**

Run: `cd api && .venv/bin/pytest tests/test_competency_api.py -q`
Expected: `7 passed`

Run: `cd api && .venv/bin/pytest -q`
Expected: A + 76 passed (`522 passed`).

**Step 5: Commit**

```
git add api/lms/api/deps.py api/lms/api/routes/statuses.py api/lms/api/app.py api/tests/test_competency_api.py
git commit -m "Answer whether a person is current, for everything they need or one competency" \
  -m "GET /v1/people/{code}/competencies and /{key}: status and the last good day, for a key with competencies:read or anyone who may see the person."
```

---

### Task 10: Certificates and skills cards, queued for Platen at the address in Settings, sent by the worker

**Files:**
- Create: `api/lms/services/printing.py`, `api/lms/api/routes/printing.py`
- Modify: `api/lms/services/settings.py`, `api/lms/config.py`, `api/lms/services/standing.py`, `api/lms/services/sessions.py`, `api/lms/worker.py`, `api/lms/api/app.py`
- Test: create `api/tests/test_printing.py`

**Step 1: Write the failing tests**

`api/tests/test_printing.py`:
```python
"""Certificates of completion and skills cards: Simple LMS renders
nothing. It queues a template's name and the JSON it binds to, and the
worker hands the job to Platen."""
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

import yard
from lms import worker
from lms.config import get_settings
from lms.models import Outbox

PLATEN = "https://platen.example.com.au/intake/jobs"


@pytest.fixture
def platen(monkeypatch):
    """Platen is set up, as LMS_PLATEN_URL and LMS_PLATEN_KEY in .env would."""
    monkeypatch.setattr(get_settings(), "platen_url", PLATEN)
    monkeypatch.setattr(get_settings(), "platen_key", "platen-key")


@pytest.fixture
def kim(client, manager_headers, learner):
    """Kim, a forklift operator: her induction current, her licence
    expiring, her first aid (asked of nobody) lapsed."""
    yard.build(client, manager_headers)
    yard.give_roles(client, manager_headers, "LL042", "forklift-operator")
    yard.grant(client, manager_headers, "LL042", "site-induction", "2026-01-01")
    yard.grant(client, manager_headers, "LL042", "first-aid", "2023-01-01")
    return yard.grant(client, manager_headers, "LL042", "forklift-licence", "2025-01-01",
                      expires_on="2026-11-11", note="LF0012345")


def jobs(db) -> list[dict]:
    db.expire_all()
    return [r.payload for r in db.query(Outbox).filter_by(kind="print").order_by(Outbox.id)]


def test_a_certificate_for_the_completion_that_counts(client, db, manager_headers, platen, kim):
    r = client.post(f"/v1/people/LL042/records/{kim['id']}/certificate", headers=manager_headers)
    assert r.status_code == 202, r.text
    [job] = jobs(db)
    assert r.json() == {"job_id": job["job_id"], "template": "lms-certificate",
                        "printer": "office"}
    assert {k: v for k, v in job.items() if k != "job_id"} == {
        "template": "lms-certificate", "version": "v1", "printer": "office", "copies": 1,
        "reference": {"type": "record", "ref": str(kim["id"])},
        "data": {"certificate_no": str(kim["id"]), "person_name": "Kim Lee",
                 "person_code": "LL042", "competency": "Forklift licence",
                 "kind": "Ticket or licence", "completed_on": "1 Jan 2025",
                 "good_until": "11 Nov 2026", "recorded_by": "Mel Grant",
                 "issued_on": "12 Oct 2026"}}


def test_a_refresher_says_when_it_is_good_until_and_none_says_nothing(client, db, manager_headers,
                                                                      platen, kim):
    records = client.get("/v1/people/LL042/records", headers=manager_headers).json()
    induction = next(r for r in records if r["competency"]["key"] == "site-induction")
    client.post(f"/v1/people/LL042/records/{induction['id']}/certificate",
                headers=manager_headers)
    yard.grant(client, manager_headers, "LL042", "whs-policy", "2026-10-01")
    whs = client.get("/v1/people/LL042/records?competency=whs-policy",
                     headers=manager_headers).json()[0]
    client.post(f"/v1/people/LL042/records/{whs['id']}/certificate", headers=manager_headers)
    assert [j["data"]["good_until"] for j in jobs(db)] == ["1 Jan 2028", ""]


def test_only_for_the_completion_that_counts_now(client, db, manager_headers, platen, kim):
    newer = yard.grant(client, manager_headers, "LL042", "forklift-licence", "2026-10-01",
                       expires_on="2031-10-01")
    r = client.post(f"/v1/people/LL042/records/{kim['id']}/certificate", headers=manager_headers)
    assert r.status_code == 409 and r.json()["code"] == "not_current"
    revoke = client.post("/v1/people/LL042/records/revoke", headers=manager_headers,
                         json={"competency": "forklift-licence", "note": "wrong person"}).json()
    for record in (newer, revoke):
        r = client.post(f"/v1/people/LL042/records/{record['id']}/certificate",
                        headers=manager_headers)
        assert r.status_code == 409 and r.json()["code"] == "not_current"
    assert jobs(db) == []


def test_someone_elses_record_is_not_found(client, manager_headers, platen, kim):
    r = client.post(f"/v1/people/SV001/records/{kim['id']}/certificate", headers=manager_headers)
    assert r.status_code == 404


def test_platen_is_set_up_on_the_settings_screen(client, db, admin_headers, manager_headers,
                                                 kim):
    r = client.put("/v1/settings", headers=admin_headers,
                   json={"platen_url": PLATEN, "platen_key": "platen-key",
                         "certificate_printer": "front office"})
    assert r.status_code == 200, r.text
    # the key is never sent back, as the email password isn't
    assert r.json()["platen_key"] == {"set": True, "source": "here"}
    assert r.json()["platen_url"] == {"value": PLATEN, "source": "here"}
    r = client.post(f"/v1/people/LL042/records/{kim['id']}/certificate", headers=manager_headers)
    assert r.status_code == 202 and r.json()["printer"] == "front office"


def test_platens_address_is_a_web_address(client, admin_headers):
    r = client.put("/v1/settings", headers=admin_headers, json={"platen_url": "platen:8000/jobs"})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "platen_url"


def test_not_until_platen_is_set_up(client, db, manager_headers, kim):
    r = client.post(f"/v1/people/LL042/records/{kim['id']}/certificate", headers=manager_headers)
    assert r.status_code == 409 and r.json()["code"] == "printing_not_set_up"
    r = client.post("/v1/people/LL042/skills-card", headers=manager_headers)
    assert r.status_code == 409 and r.json()["code"] == "printing_not_set_up"


def test_a_manager_prints_and_a_supervisor_does_not(client, supervisor_headers, learner_headers,
                                                    platen, kim):
    for headers in (supervisor_headers, learner_headers):
        assert client.post("/v1/people/LL042/skills-card", headers=headers).status_code == 403


def test_a_skills_card_lists_what_they_are_current_for(client, db, manager_headers, platen, kim,
                                                      monkeypatch):
    monkeypatch.setattr(get_settings(), "skills_card_printer", "card printer")
    yard.grant(client, manager_headers, "LL042", "whs-policy", "2026-10-01")
    r = client.post("/v1/people/ll042/skills-card", headers=manager_headers)
    assert r.status_code == 202, r.text
    [job] = jobs(db)
    assert (job["template"], job["version"], job["printer"], job["reference"]) == (
        "lms-skills-card", "v1", "card printer", {"type": "person", "ref": "LL042"})
    # first aid ran out, so it is not on it; the policy isn't asked of her, and is
    assert job["data"] == {
        "person_name": "Kim Lee", "person_code": "LL042", "roles": "Forklift operator",
        "issued_on": "12 Oct 2026", "count": 3,
        "lines": [
            {"competency": "Forklift licence", "kind": "Ticket or licence",
             "completed_on": "1 Jan 2025", "good_until": "11 Nov 2026"},
            {"competency": "Site induction", "kind": "Online module",
             "completed_on": "1 Jan 2026", "good_until": "1 Jan 2028"},
            {"competency": "WHS policy", "kind": "Policy", "completed_on": "1 Oct 2026",
             "good_until": ""},
        ]}


def test_a_skills_card_with_nothing_on_it_is_not_printed(client, manager_headers, platen,
                                                         learner):
    r = client.post("/v1/people/LL042/skills-card", headers=manager_headers)
    assert r.status_code == 409 and r.json()["code"] == "nothing_current"


# --- the worker hands it to Platen --------------------------------------------

def test_the_worker_hands_it_to_platen(client, db, manager_headers, platen, kim):
    client.post("/v1/people/LL042/skills-card", headers=manager_headers)
    got = []

    def intake(request):
        got.append(request)
        return httpx.Response(202, json={"id": "run-1", "duplicate": False})

    with httpx.Client(transport=httpx.MockTransport(intake)) as http:
        assert worker.send_due(db, http) == 1
    [req] = got
    [job] = jobs(db)
    assert str(req.url) == PLATEN
    assert req.headers["authorization"] == "Bearer platen-key"
    assert req.headers["x-lms-job-id"] == job["job_id"]
    assert json.loads(req.content) == job
    assert db.query(Outbox).filter_by(kind="print").one().status == "done"


def test_platen_saying_no_is_tried_again_in_its_own_words(client, db, manager_headers, platen,
                                                          kim):
    client.post("/v1/people/LL042/skills-card", headers=manager_headers)

    def intake(request):
        return httpx.Response(422, json={"detail": "template: Platen has no template "
                                                   "'lms-skills-card'; make one with that id"})

    with httpx.Client(transport=httpx.MockTransport(intake)) as http:
        worker.send_due(db, http)
    db.expire_all()
    row = db.query(Outbox).filter_by(kind="print").one()
    assert row.last_error == ("Platen answered 422: template: Platen has no template "
                              "'lms-skills-card'; make one with that id")
    assert (row.status, row.attempts) == ("pending", 1)
    assert row.next_attempt_at > datetime.now(UTC) + timedelta(seconds=50)


def test_jobs_wait_untried_while_platen_is_not_set_up(client, db, manager_headers, platen, kim,
                                                      monkeypatch):
    client.post("/v1/people/LL042/skills-card", headers=manager_headers)
    monkeypatch.setattr(get_settings(), "platen_url", "")
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500))) as http:
        assert worker.send_due(db, http) == 0
```

**Step 2: Run them to see them fail**

Run: `cd api && .venv/bin/pytest tests/test_printing.py -q`
Expected: FAIL: `2 failed, 1 passed, 10 errors`: the `.env` settings have no `platen_url` for the `platen` fixture to set (`AttributeError: Settings(…) has no attribute 'platen_url'`), `PUT /v1/settings` refuses the new keys (`Extra inputs are not permitted`), and without the fixture there is no route to refuse a print (`404`, not `409`). `test_platens_address_is_a_web_address` passes already (an unknown key is a `422` on that key too), and must go on passing.

**Step 3: Minimal implementation**

Platen's address, key and printers are everyday settings, read through `settings.current()` like the email server's, with `.env` as the fallback. In `api/lms/config.py`, replace:
```python
    smtp_security: Literal["starttls", "ssl", "none"] = "starttls"

```
with:
```python
    smtp_security: Literal["starttls", "ssl", "none"] = "starttls"

    # Printing, through Platen (or any print service that takes the same job):
    # its intake address (https://<platen>/intake/jobs), a Platen key, and the
    # printers (a Platen printer's id or name) certificates and skills cards
    # go to. Without the address nothing can be printed. Settings wins.
    platen_url: str = ""
    platen_key: str = ""
    certificate_printer: str = "office"
    # empty: the certificates' printer
    skills_card_printer: str = ""

```

In `api/lms/services/settings.py`, replace:
```python
    # where people open Simple LMS, for the links in emails
    public_url: str = ""
```
with:
```python
    # where people open Simple LMS, for the links in emails
    public_url: str = ""
    # printing: Platen's intake address and key, and the printers (a Platen
    # printer's id or name) certificates and skills cards go to; an empty
    # skills card printer is the certificates' one
    platen_url: str = ""
    platen_key: str = ""
    certificate_printer: str = "office"
    skills_card_printer: str = ""

    @property
    def skills_card_printer_or_default(self) -> str:
        return self.skills_card_printer.strip() or self.certificate_printer
```

In `api/lms/services/settings.py`, replace:
```python
FROM_ENV = ("quiz_cooldown_minutes", "timezone", "daily_hour", "smtp_host", "smtp_port",
            "smtp_user", "smtp_password", "smtp_from", "smtp_security", "public_url")
# never sent back: only whether there is one
SECRET = ("smtp_password",)
```
with:
```python
FROM_ENV = ("quiz_cooldown_minutes", "timezone", "daily_hour", "smtp_host", "smtp_port",
            "smtp_user", "smtp_password", "smtp_from", "smtp_security", "public_url",
            "platen_url", "platen_key", "certificate_printer", "skills_card_printer")
# never sent back: only whether there is one
SECRET = ("smtp_password", "platen_key")
```
(Keep step 5's Entra keys in each.)

In `api/lms/services/settings.py`, replace:
```python
    public_url: Annotated[str, Field(max_length=2000)] | None = None

    @field_validator("timezone", "smtp_host", "smtp_user", "smtp_password", "smtp_from",
                     "public_url")
```
with:
```python
    public_url: Annotated[str, Field(max_length=2000)] | None = None
    platen_url: Annotated[str, Field(max_length=2000)] | None = None
    platen_key: Annotated[str, Field(max_length=500)] | None = None
    certificate_printer: Annotated[str, Field(max_length=64)] | None = None
    skills_card_printer: Annotated[str, Field(max_length=64)] | None = None

    @field_validator("timezone", "smtp_host", "smtp_user", "smtp_password", "smtp_from",
                     "public_url", "platen_url", "platen_key", "certificate_printer",
                     "skills_card_printer")
```

In `api/lms/services/settings.py`, replace:
```python
            raise ValueError("a web address starting https://, e.g. https://lms.example.com.au")
        return value
```
with:
```python
            raise ValueError("a web address starting https://, e.g. https://lms.example.com.au")
        return value

    @field_validator("platen_url")
    @classmethod
    def _intake(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if value and not re.fullmatch(r"https?://[^\s/?#]+(/[^\s?#]*)?", value):
            raise ValueError("Platen's intake address, "
                             "e.g. https://platen.example.com.au/intake/jobs")
        return value
```

A skills card lists what someone holds, asked of them or not; `status.py` still says what that is. In `api/lms/services/standing.py`, replace:
```python
    def status(self, person_id: int, competency_id: int) -> Status:
        record = self.records.get((person_id, competency_id))
        latest = None if record is None else Latest(record.kind, record.granted_on,
                                                    record.expires_on, record.policy_version_id)
        override = self.overrides.get((person_id, competency_id))
        return work_out(
            by_role=(person_id, competency_id) in self.by_role,
            override=None if override == "clear" else override,
            latest=latest,
            refresher_months=self.competencies[competency_id].refresher_months,
            today=self.today,
            current_version=self.versions.get(competency_id),
        )
```
with:
```python
    def _latest(self, person_id: int, competency_id: int) -> Latest | None:
        record = self.records.get((person_id, competency_id))
        return None if record is None else Latest(record.kind, record.granted_on,
                                                  record.expires_on, record.policy_version_id)

    def status(self, person_id: int, competency_id: int) -> Status:
        override = self.overrides.get((person_id, competency_id))
        return work_out(
            by_role=(person_id, competency_id) in self.by_role,
            override=None if override == "clear" else override,
            latest=self._latest(person_id, competency_id),
            refresher_months=self.competencies[competency_id].refresher_months,
            today=self.today,
            current_version=self.versions.get(competency_id),
        )

    def held(self, person_id: int) -> dict[int, Status]:
        """What they are current for now, asked of them or not: each active
        competency their latest record makes current or expiring, as
        status.py works it out for one that is asked of them."""
        held = {}
        for (p, c) in self.records:
            if p != person_id or c not in self.competencies:
                continue
            s = work_out(by_role=True, override=None, latest=self._latest(p, c),
                         refresher_months=self.competencies[c].refresher_months,
                         today=self.today, current_version=self.versions.get(c))
            if s.status in ("current", "expiring"):
                held[c] = s
        return held
```
(If step 4 changed `status()`, keep its change and take only `_latest` and `held` from here.)

In `api/lms/services/sessions.py`, replace:
```python
# ticket. tickets:verify is checking someone else's ticket.
SCOPES: dict[str, list[str]] = {
```
with:
```python
# ticket. tickets:verify is checking someone else's ticket. printing:write
# is sending a certificate or a skills card to Platen.
SCOPES: dict[str, list[str]] = {
```

In `api/lms/services/sessions.py`, add `"printing:write"` to the end of the manager's list; on `c193b0c`, replace:
```python
                "competencies:write", "records:write", "tickets:verify"],
```
with:
```python
                "competencies:write", "records:write", "tickets:verify", "printing:write"],
```

`api/lms/services/printing.py`:
```python
"""Certificates of completion and skills cards, printed by Platen (or any
print service that takes the same job). Simple LMS never renders a
document: it queues a template's name and the JSON it binds to, the worker
sends it, and Platen prints it, as Simple TMS sends its run sheets."""
from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import httpx
from sqlalchemy.orm import Session as Db

from lms.config import get_settings
from lms.models import CompetencyRecord, Outbox, Person
from lms.services import settings, standing
from lms.services.daily import formatted
from lms.services.status import expiry
from lms.services.webhooks import USER_AGENT

# The Platen page templates that print them: make each with this id and publish it.
CERTIFICATE, CERTIFICATE_VERSION = "lms-certificate", "v1"
SKILLS_CARD, SKILLS_CARD_VERSION = "lms-skills-card", "v1"
KIND_WORDS = {"module": "Online module", "practical": "Practical", "ticket": "Ticket or licence",
              "policy": "Policy"}


def set_up() -> bool:
    return bool(settings.current().platen_url)


def _day(d: date | None) -> str:
    """Text only, never null, so every binding in the template has something."""
    return formatted(d) if d is not None else ""


def certificate_data(r: CompetencyRecord, p: Person, today: date) -> dict:
    """What the certificate template binds to: one completion."""
    c = r.competency
    return {
        "certificate_no": str(r.id), "person_name": p.name, "person_code": p.code,
        "competency": c.name, "kind": KIND_WORDS[c.kind], "completed_on": _day(r.granted_on),
        "good_until": _day(expiry(r.granted_on, r.expires_on, c.refresher_months)),
        "recorded_by": r.recorded_by.name, "issued_on": _day(today),
    }


def skills_card_data(db: Db, p: Person, today: date) -> dict:
    """What the skills card template binds to: the person at the top, a line
    for each competency they are current for, asked of them or not, by name
    (Platen gives a page template a row per entry in `lines`)."""
    st = standing.load(db, [p.id], today)
    held = sorted(st.held(p.id).items(), key=lambda h: st.competencies[h[0]].name)
    lines = [{"competency": st.competencies[c].name, "kind": KIND_WORDS[st.competencies[c].kind],
              "completed_on": _day(s.granted_on), "good_until": _day(s.expires_on)}
             for c, s in held]
    return {"person_name": p.name, "person_code": p.code,
            "roles": ", ".join(r.name for r in p.roles), "issued_on": _day(today),
            "count": len(lines), "lines": lines}


def queue(db: Db, template: str, version: str, printer: str, reference: dict,
          data: dict) -> dict:
    """A print job on the queue, as Platen's intake takes it."""
    job_id = uuid.uuid4()
    job = {"job_id": str(job_id), "template": template, "version": version, "printer": printer,
           "copies": 1, "reference": reference, "data": data}
    db.add(Outbox(kind="print", key=f"print:{job_id}", payload=job, status="pending",
                  attempts=0, next_attempt_at=datetime.now(UTC)))
    db.flush()
    return job


def send(http: httpx.Client, row: Outbox) -> str | None:
    """Hand one job to Platen's intake: None when it took it, otherwise why
    not, in Platen's own words where it gave some. Never the key."""
    s = settings.current()
    headers = {"X-LMS-Job-Id": row.payload["job_id"], "User-Agent": USER_AGENT}
    if s.platen_key:
        headers["Authorization"] = f"Bearer {s.platen_key}"
    try:
        resp = http.post(s.platen_url, json=row.payload, headers=headers,
                         timeout=get_settings().worker_http_timeout_seconds)
    except httpx.HTTPError as e:
        return f"{type(e).__name__}: {e}"
    if 200 <= resp.status_code < 300:
        return None
    try:
        detail = resp.json().get("detail")
    except (ValueError, AttributeError):
        detail = None
    said = detail if isinstance(detail, str) else resp.text[:200]
    return f"Platen answered {resp.status_code}: {said}"
```

`api/lms/api/routes/printing.py`:
```python
"""Printing a certificate of completion or a skills card: queued here,
sent to Platen by the worker. Asked for from the desktop, never printed by
itself: nobody wants a page for every grant."""
from __future__ import annotations

import uuid

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from lms.api.deps import DB, Principal, require
from lms.api.errors import Conflict, NotFound
from lms.api.routes.people import get_person
from lms.api.routes.records import latest_record
from lms.models import CompetencyRecord, Person
from lms.services import clock, printing, settings

router = APIRouter(tags=["printing"])


class PrintOut(BaseModel):
    job_id: uuid.UUID
    template: str
    printer: str


def _set_up() -> None:
    if not printing.set_up():
        raise Conflict("printing_not_set_up",
                       "Printing is not set up: give Platen's address in Settings, under "
                       "Printing.")


def _person(db, code: str, who: Principal) -> Person:
    p = get_person(db, code)
    if not who.sees(p):
        raise NotFound(f"no person {code}")
    return p


def _queued(job: dict) -> JSONResponse:
    out = PrintOut(job_id=job["job_id"], template=job["template"], printer=job["printer"])
    return JSONResponse(status_code=202, content=out.model_dump(mode="json"))


@router.post("/people/{code}/records/{record_id}/certificate", status_code=202,
             response_model=PrintOut)
def print_certificate(code: str, record_id: int, db: DB,
                      who: Principal = require("printing:write")):
    """A certificate for the completion that counts now: not one that has
    been recorded again since, nor revoked."""
    _set_up()
    p = _person(db, code, who)
    r = db.get(CompetencyRecord, record_id)
    if r is None or r.person_id != p.id:
        raise NotFound(f"no record {record_id} for {p.code}")
    latest = latest_record(db, p.id, r.competency_id)
    if r.kind != "granted" or latest.id != r.id:
        raise Conflict("not_current", "only the completion that counts now gets a certificate")
    job = printing.queue(db, printing.CERTIFICATE, printing.CERTIFICATE_VERSION,
                         settings.current().certificate_printer,
                         {"type": "record", "ref": str(r.id)},
                         printing.certificate_data(r, p, clock.today()))
    db.commit()
    return _queued(job)


@router.post("/people/{code}/skills-card", status_code=202, response_model=PrintOut)
def print_skills_card(code: str, db: DB, who: Principal = require("printing:write")):
    """A card listing what they are current for today."""
    _set_up()
    p = _person(db, code, who)
    data = printing.skills_card_data(db, p, clock.today())
    if not data["lines"]:
        raise Conflict("nothing_current", f"{p.name} is current for nothing yet")
    job = printing.queue(db, printing.SKILLS_CARD, printing.SKILLS_CARD_VERSION,
                         settings.current().skills_card_printer_or_default,
                         {"type": "person", "ref": p.code}, data)
    db.commit()
    return _queued(job)
```

In `api/lms/api/app.py`, replace:
```python
    records, roles, settings, statuses, tickets, uploads, webhooks,
)
```
with:
```python
    printing, records, roles, settings, statuses, tickets, uploads, webhooks,
)
```

In `api/lms/api/app.py`, replace:
```python
v1.include_router(statuses.router)
```
with:
```python
v1.include_router(statuses.router)
v1.include_router(printing.router)
```

The worker takes print jobs as its third kind. In `api/lms/worker.py`, replace:
```python
"""Drains the outbox (emails, and events for the webhooks) and runs the
daily job. Run as `python -m lms.worker`.
```
with:
```python
"""Drains the outbox (emails, events for the webhooks, and print jobs for
Platen) and runs the daily job. Run as `python -m lms.worker`.
```

In `api/lms/worker.py`, replace:
```python
from lms.services import daily, mail, settings, webhooks
```
with:
```python
from lms.services import daily, mail, printing, settings, webhooks
```

In `api/lms/worker.py`, replace:
```python
KINDS = ("email", "webhook")
```
with:
```python
KINDS = ("email", "webhook", "print")
```

In `api/lms/worker.py`, replace:
```python
def _ready(kind: str) -> bool:
    """Emails wait, untried, until SMTP is set up; events always go."""
    return mail.set_up() if kind == "email" else True


def _send(kind: str, http: httpx.Client | None, row: Outbox) -> str | None:
    if kind == "email":
        return mail.send(row.payload)
    return webhooks.deliver(http, row)
```
with:
```python
def _ready(kind: str) -> bool:
    """Emails wait, untried, until SMTP is set up, and print jobs until
    Platen is; events always go."""
    if kind == "email":
        return mail.set_up()
    if kind == "print":
        return printing.set_up()
    return True


def _send(kind: str, http: httpx.Client | None, row: Outbox) -> str | None:
    if kind == "email":
        return mail.send(row.payload)
    if kind == "print":
        return printing.send(http, row)
    return webhooks.deliver(http, row)
```

**Step 4: Run them, and the whole suite, to see them pass**

Run: `cd api && .venv/bin/pytest tests/test_printing.py tests/test_settings_api.py tests/test_settings_service.py tests/test_worker.py -q`
Expected: all pass (13 new; the settings and worker tests as they were).

Run: `cd api && .venv/bin/pytest -q`
Expected: A + 89 passed (`535 passed`).

**Step 5: Commit**

```
git add api/lms/config.py api/lms/services/settings.py api/lms/services/standing.py api/lms/services/sessions.py api/lms/services/printing.py api/lms/api/routes/printing.py api/lms/api/app.py api/lms/worker.py api/tests/test_printing.py
git commit -m "Print a certificate or a skills card through Platen: a template name and JSON, sent by the worker" \
  -m "Asked for by a manager, never by itself. Platen's address, key and printers are settings, the key write-only like the email password."
```

---

### Task 11: Compose and CI: Platen's fallback settings, the worker reaching the host, the new tables checked

**Files:**
- Modify: `docker-compose.yml`, `.env.example`, `.github/workflows/ci.yml`

**Step 1: The check that fails**

```
cd "/Users/leightonlauton/Q7 Technology/Software/q7/simple-lms"
docker compose up -d --build db api worker
docker compose exec -T worker python -c "import socket; print(socket.gethostbyname('host.docker.internal'))"
docker compose exec -T worker env | grep -c LMS_PLATEN
```
Expected: on Docker Desktop the first prints an address, on Linux it fails (`socket.gaierror`); the second prints `0`: `.env`'s Platen settings don't reach the api or the worker.

**Step 2: Implementation**

In `docker-compose.yml`, replace:
```yaml
  LMS_SMTP_SECURITY: ${LMS_SMTP_SECURITY:-starttls}

services:
```
with:
```yaml
  LMS_SMTP_SECURITY: ${LMS_SMTP_SECURITY:-starttls}
  LMS_PLATEN_URL: ${LMS_PLATEN_URL:-}
  LMS_PLATEN_KEY: ${LMS_PLATEN_KEY:-}
  LMS_CERTIFICATE_PRINTER: ${LMS_CERTIFICATE_PRINTER:-office}
  LMS_SKILLS_CARD_PRINTER: ${LMS_SKILLS_CARD_PRINTER:-}

services:
```

In `docker-compose.yml`, replace:
```yaml
  # Sends the emails in the outbox with backoff, and runs the daily job
  # (reminders, and the managers' Monday digest). Waits for the api's
  # migrations. Later steps give it the webhooks and print jobs.
  worker:
```
with:
```yaml
  # Sends what is in the outbox with backoff: emails, events to the
  # webhooks and print jobs to Platen. Runs the daily job (reminders, the
  # managers' Monday digest, the expiring and lapsed events). Waits for the
  # api's migrations.
  worker:
```

In `docker-compose.yml`, replace:
```yaml
      LMS_DATABASE_URL: postgresql+psycopg://${POSTGRES_USER:-lms}:${POSTGRES_PASSWORD}@db:5432/${POSTGRES_DB:-lms}
    depends_on:
      db:
        condition: service_healthy

  caddy:
```
with:
```yaml
      LMS_DATABASE_URL: postgresql+psycopg://${POSTGRES_USER:-lms}:${POSTGRES_PASSWORD}@db:5432/${POSTGRES_DB:-lms}
    # a webhook or Platen on this machine, outside Compose, is
    # http://host.docker.internal:<port>/… from in here (Linux too)
    extra_hosts:
      - "host.docker.internal:host-gateway"
    depends_on:
      db:
        condition: service_healthy

  caddy:
```

In `.env.example`, replace:
```text
LMS_QUIZ_COOLDOWN_MINUTES=60
```
with:
```text
LMS_QUIZ_COOLDOWN_MINUTES=60

# Printing: certificates and skills cards go to Platen as a template name and
# JSON. LMS_PLATEN_URL is its intake, e.g. https://platen.example.com.au/intake/jobs
# (on this machine, outside Compose: http://host.docker.internal:<port>/intake/jobs).
# LMS_PLATEN_KEY is a key made in Platen for Simple LMS. The printers are a
# Platen printer's id or name; the skills cards' is the certificates' unless
# it says otherwise. Without an address nothing can be printed. All Settings.
LMS_PLATEN_URL=
LMS_PLATEN_KEY=
LMS_CERTIFICATE_PRINTER=office
LMS_SKILLS_CARD_PRINTER=
```

In `.github/workflows/ci.yml`, after the check for the `setting` table, replace:
```yaml
            "select count(*) from information_schema.tables where table_name = 'setting'" | grep -qx 1
```
with:
```yaml
            "select count(*) from information_schema.tables where table_name = 'setting'" | grep -qx 1
          # the outward links: webhooks, API keys, and the events fired once
          docker compose exec -T db psql -U lms -d lms -tAc \
            "select count(*) from information_schema.tables where table_name in ('webhook', 'api_key', 'event_seen')" | grep -qx 3
```

**Step 3: Run the check to see it pass**

```
docker compose up -d --build db api worker
docker compose exec -T worker python -c "import socket; print(socket.gethostbyname('host.docker.internal'))"
docker compose exec -T worker env | grep -c LMS_PLATEN
docker compose exec -T db psql -U lms -d lms -tAc "select count(*) from information_schema.tables where table_name in ('webhook', 'api_key', 'event_seen')"
docker compose exec -T db psql -U lms -d lms -tAc "select version_num from alembic_version"
```
Expected: an address, `2`, `3` and `0006` (the API ran the migration as it started).

**Step 4: Commit**

```
git add docker-compose.yml .env.example .github/workflows/ci.yml
git commit -m "Pass Platen's fallback settings, give the worker a way to the host, and check the new tables in CI"
```

---

### Task 12: `docs/api.md`

**Files:**
- Modify: `docs/api.md`

**Step 1: Write it**

In `docs/api.md`, replace:
````markdown
  (code and PIN). The desktop and the learner app use these endpoints and
  nothing else: the API is the only door.
````
with:
````markdown
  (code and PIN). The desktop and the learner app use these endpoints and
  nothing else: the API is the only door. Another system calls with an
  **API key** (`lms_k.…`) as its bearer token instead: a key opens the
  competency API and nothing else (below).
````
(If step 5 reworded this bullet for Entra, add the two sentences to the end of it as it stands.)

In `docs/api.md`, replace:
````markdown
| `manager` | the supervisor's, plus `people:read`, `people:write`, `roles:write`, `competencies:write`, `records:write`, `tickets:verify` |
| `admin` | `*` (everything, `settings:write` among it) |
````
with:
````markdown
| `manager` | the supervisor's, plus `people:read`, `people:write`, `roles:write`, `competencies:write`, `records:write`, `tickets:verify`, `printing:write` |
| `admin` | `*` (everything, `settings:write` among it: Settings, webhooks and API keys) |
````
(Keep any scopes step 4 added to these rows.)

In `docs/api.md`, replace:
````markdown
The learner app shows it as Overdue (`lapsed`, `missing`), Due soon
(`expiring`) and Done (`current`).
````
with:
````markdown
The learner app shows it as Overdue (`lapsed`, `missing`), Due soon
(`expiring`) and Done (`current`).

## The competency API

For other systems (Simple TMS checking a driver before a run, say) with an
API key carrying `competencies:read`, and for anyone signed in with
`competencies:read` who may see the person (a supervisor their team, a
manager or admin everyone; anyone else is `404`). A learner's own is
`GET /v1/people/{code}/training`. Status is worked out today, as for the
matrix.

### GET /v1/people/{code}/competencies
Everything their roles and extras ask of them, waived or not, by name:
```json
{
  "person": { "code": "LL042", "name": "Kim Lee", "active": true },
  "today": "2026-10-12",
  "competencies": [
    { "key": "forklift-licence", "name": "Forklift licence", "kind": "ticket",
      "status": "expiring", "granted_on": "2025-01-01", "expires_on": "2026-11-11" }
  ]
}
```

### GET /v1/people/{code}/competencies/{key}
One competency, whether it is asked of them or not:
`{ "person": { "code", "name", "active" }, "today", "key", "name", "kind", "status", "granted_on", "expires_on" }`.
`status` is `not_required` when it isn't asked of them, or the competency
is deactivated. An unknown code or key is `404`.

`expires_on` is the last good day (`null` when it doesn't run out, or there
is no grant). Someone deactivated has left: `active` is `false` and their
status is still worked out from their records. A revoked or unknown key is
`401`; a key used anywhere else is `403 { "code": "key_not_allowed" }`.
````

In `docs/api.md`, replace:
````markdown
## Emails and the daily job
````
with:
````markdown
## Printing

Certificates of completion and skills cards go to Platen (or any print
service that takes the same job): Simple LMS renders nothing. It queues a
template's name and the JSON it binds to, and the worker hands the job to
Platen's `/intake/jobs` with `Authorization: Bearer
<platen_key>` and `X-LMS-Job-Id`, retried after 1 minute, 5, 30 and 2
hours. Platen's address, key and printers are Settings (`platen_url`,
`platen_key`, `certificate_printer`, `skills_card_printer`, below), or
`LMS_PLATEN_*` in `.env`. Platen's answer that it has the job is the end of
it here; Platen's own screens say whether it printed. Both are
`printing:write`, for someone who may see the person, and answer
`202 { "job_id", "template", "printer" }` once queued. Until Platen's
address is set both are `409 { "code": "printing_not_set_up" }`.

- `POST /v1/people/{code}/records/{id}/certificate` — for the completion
  that counts now: one recorded again since, or revoked, is
  `409 { "code": "not_current" }`; another person's record is `404`.
  Printed on `certificate_printer`.
- `POST /v1/people/{code}/skills-card` — what they are current for today
  (`current` or `expiring`, asked of them or not), by name; nothing is
  `409 { "code": "nothing_current" }`. Printed on `skills_card_printer`,
  or the certificates' printer.

What Platen is sent (make a page template in Platen with each id and
publish it; every value is text, never null, and `good_until` is empty for
what doesn't run out):
```json
{ "job_id": "…", "template": "lms-certificate", "version": "v1", "printer": "office", "copies": 1,
  "reference": { "type": "record", "ref": "12" },
  "data": { "certificate_no": "12", "person_name": "Kim Lee", "person_code": "LL042",
            "competency": "Forklift licence", "kind": "Ticket or licence",
            "completed_on": "1 Jan 2025", "good_until": "11 Nov 2026",
            "recorded_by": "Mel Grant", "issued_on": "12 Oct 2026" } }
```
```json
{ "job_id": "…", "template": "lms-skills-card", "version": "v1", "printer": "office", "copies": 1,
  "reference": { "type": "person", "ref": "LL042" },
  "data": { "person_name": "Kim Lee", "person_code": "LL042", "roles": "Forklift operator",
            "issued_on": "12 Oct 2026", "count": 2,
            "lines": [{ "competency": "Forklift licence", "kind": "Ticket or licence",
                        "completed_on": "1 Jan 2025", "good_until": "11 Nov 2026" },
                      { "competency": "Site induction", "kind": "Online module",
                        "completed_on": "1 Jan 2026", "good_until": "1 Jan 2028" }] } }
```
Platen gives a page template a row for each entry in `lines`, with the
rest beside it.

## Emails and the daily job
````

In `docs/api.md`, replace:
````markdown
- on Mondays, a digest for each active manager and admin with an email of
  what is lapsed and what is expiring, for everyone (none when nothing is).

`lms daily-job [--on YYYY-MM-DD]` queues them now (as if today were that
date); nothing is queued twice. A date it can't read is refused with exit
code 2.
````
with:
````markdown
- on Mondays, a digest for each active manager and admin with an email of
  what is lapsed and what is expiring, for everyone (none when nothing is);
- `competency.expiring` and `competency.lapsed` for the webhooks (below),
  each once.

`lms daily-job [--on YYYY-MM-DD]` queues them now (as if today were that
date) and says how many reminders, digests and events it queued; nothing
is queued twice. A date it can't read is refused with exit code 2.
````

In `docs/api.md`, replace:
````markdown
| `public_url` | `https://…` (or `http://`), no trailing slash, or `""` | `LMS_PUBLIC_URL` | `""` |
````
with:
````markdown
| `public_url` | `https://…` (or `http://`), no trailing slash, or `""` | `LMS_PUBLIC_URL` | `""` |
| `platen_url` | Platen's intake, `https://…/intake/jobs` (or `http://`), or `""`: nothing prints | `LMS_PLATEN_URL` | `""` |
| `platen_key` | write-only: a key made in Platen for Simple LMS | `LMS_PLATEN_KEY` | `""` |
| `certificate_printer` | a Platen printer's id or name | `LMS_CERTIFICATE_PRINTER` | `"office"` |
| `skills_card_printer` | the same, or `""` for the certificates' printer | `LMS_SKILLS_CARD_PRINTER` | `""` |
````

In `docs/api.md`, replace:
````markdown
`env` (`.env` gives a value other than the default) or `default`. The password is never sent: `"smtp_password": { "set":
````
with:
````markdown
`env` (`.env` gives a value other than the default) or `default`. The password and Platen's key are never sent: `"smtp_password": { "set":
````

In `docs/api.md`, replace:
````markdown
## System
````
with:
````markdown
## Webhooks and events

Simple LMS tells other systems what happens by posting an event to each
webhook that wants it, as Simple WMS does: the same envelope and the same
signature, with `X-LMS-` headers where Simple WMS has `X-WMS-`. Events are
queued in the same transaction as the change (nothing is told of a change
that wasn't kept), sent by the worker, and a refusal (anything but `2xx`)
or no answer within 10 seconds is tried again after 1 minute, 5, 30 and 2
hours, then left `failed` for an admin to send again. At least once: a
receiver keeps the `event_id`s it has had and ignores one it has seen.

### What is sent
`POST <the webhook's url>` with the envelope as the body:
```json
{ "event_id": "1b4e28ba-2fa1-41d2-883f-0016d3cca427", "event_type": "competency.granted",
  "occurred_at": "2026-10-12T01:30:00Z", "data": { … } }
```
and the headers `Content-Type: application/json`, `User-Agent:
simple-lms/0.1`, `X-LMS-Event-Id`, `X-LMS-Event-Type` and
`X-LMS-Signature: sha256=<hex>`, the HMAC-SHA256 of the exact bytes of the
body, keyed with the webhook's secret.

### Checking the signature
Check it against the raw body, before parsing it, in constant time:
```python
import hashlib, hmac

def verify(secret: str, body: bytes, header: str | None) -> bool:
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return header is not None and hmac.compare_digest(expected, header.strip())
```

### The events
`person` is `{ "code", "name" }` and `competency` is `{ "key", "name",
"kind" }`. `status` is the person's status for it as the change leaves it
(it may be `not_required`, or `waived`), and `expires_on` the last good day
(`null` when it doesn't run out).

| Event | When | `data` |
| --- | --- | --- |
| `competency.granted` | a grant by hand, a ticket checked, a policy signed, a module passed, a practical signed off | `person`, `competency`, `record_id`, `granted_on`, `expires_on`, `status`, `recorded_by` |
| `competency.revoked` | a grant revoked | `person`, `competency`, `record_id`, `note`, `status`, `recorded_by` |
| `competency.expiring` | the daily job first finds it within 30 days of its last good day: once for each last good day, so a renewal is told afresh | `person`, `competency`, `status` (`expiring`), `granted_on`, `expires_on`, `days_left` |
| `competency.lapsed` | the daily job first finds its last good day has passed: once for each last good day | `person`, `competency`, `status` (`lapsed`), `granted_on`, `expires_on` |
| `person.updated` | a person added, their details or roles changed, deactivated or back; never a PIN or password | `person`: `{ "code", "name", "email", "permission", "active", "supervisor": { "code", "name" } \| null, "roles": [{ "key", "name" }] }` |

Expiring and lapsed are fired once whoever was listening: a webhook added
later isn't told of what went before (the competency API says how things
stand now). Waivers, extras and role requirements change what is asked of
people without an event of their own.

### Managing them
`settings:write` (admins), on the desktop's Settings screen:

- `GET /v1/webhooks` — by name: `[{ "id", "name", "url", "events", "active",
  "waiting", "failed", "created_at" }]`, where `waiting` and `failed` count
  its deliveries still to go and given up on. `GET /v1/webhooks/{id}`.
- `POST /v1/webhooks` — `{ "name", "url" (http:// or https://), "events":
  ["competency.granted", …] or ["*"] }` → `201`, the webhook with its
  `secret` (`whsec_…`), **shown this once**. A name already taken is `422`.
- `PATCH /v1/webhooks/{id}` — any of `name`, `url`, `events`, `active`.
  Deliveries still waiting go to the new address; turned off, it gets
  nothing more and what was waiting for it is given up on.
- `POST /v1/webhooks/{id}/secret` — a new secret, shown this once: everything
  sent from now on (what is waiting included) is signed with it.
- `GET /v1/webhooks/{id}/deliveries?status=pending|done|failed` — the latest
  50, newest first: `[{ "id", "event_id", "event_type", "status", "attempts",
  "next_attempt_at", "last_error", "done_at", "created_at" }]`.
- `POST /v1/webhooks/{id}/deliveries/{delivery_id}/retry` — a failed
  delivery sent again from the start of the backoff, the same event with
  the same id. One that hasn't failed is `409 { "code": "not_failed" }`; a
  webhook turned off is `409 { "code": "inactive" }`.

A webhook's address is trusted admin configuration: the worker posts to
whatever it says.

## API keys

For other systems, not people. `settings:write` (admins), on the desktop's
Settings screen:

- `GET /v1/api-keys` — by name: `[{ "id", "name", "prefix", "scopes",
  "created_by": { "code", "name" }, "created_at", "last_used_at",
  "revoked_at" }]`. `prefix` is the key's first ten characters, to tell
  which is which; `last_used_at` is to the minute.
- `POST /v1/api-keys` — `{ "name", "scopes": ["competencies:read"] }` →
  `201`, the key with `key` (`lms_k.…`), **shown this once**: only its
  SHA-256 is kept. `competencies:read` is the one scope a key can have.
- `POST /v1/api-keys/{id}/revoke` — it stops working at once, for good
  (`409 { "code": "revoked" }` the second time). Keys are never deleted.

## System
````

**Step 2: Commit**

```
git add docs/api.md
git commit -m "Document the webhooks and their events, checking a signature, API keys, the competency API, printing and Platen's settings in docs/api.md"
```

---
### Task 13: Webhooks on the Settings screen: added, changed, their deliveries seen and sent again

**Files:**
- Create: `apps/desktop/src/pages/Webhooks.tsx`, `apps/desktop/src/ui/ShownOnce.tsx`
- Modify: `apps/desktop/src/api/types.ts`, `apps/desktop/src/pages/Settings.tsx`
- Test: `apps/desktop/src/test/harness.tsx`; create `apps/desktop/src/test/Webhooks.test.tsx`

No new screen and nothing in `ui/screens.ts`: the webhooks are a section of Settings, which already opens as a drawer over the classroom (and as a page with Game Mode off); a webhook's own drawer opens over that.

**Step 1: Write the failing tests**

In `apps/desktop/src/test/harness.tsx`, replace:
```tsx
import type { Me } from "../api/types";
```
with:
```tsx
import type { Me, Settings } from "../api/types";
```

In `apps/desktop/src/test/harness.tsx`, replace:
```tsx
  idle_seconds: 43200,
};
```
with:
```tsx
  idle_seconds: 43200,
};

/** An admin: everything, Settings with its webhooks and API keys too. */
export const ADA: Me = { ...MEL, id: 1, code: "AD001", name: "Ada Admin", email: "ada@example.com.au",
                         permission: "admin", scopes: ["*"] };

/** GET /v1/settings as a fresh install answers it. */
export const ALL_SETTINGS: Settings = {
  sign_in_pin: { value: true, source: "default" },
  sign_in_password: { value: true, source: "default" },
  quiz_cooldown_tries: { value: 3, source: "default" },
  quiz_cooldown_minutes: { value: 60, source: "default" },
  reminder_days: { value: [30, 14, 0], source: "default" },
  timezone: { value: "Australia/Melbourne", source: "default" },
  daily_hour: { value: 6, source: "default" },
  smtp_host: { value: "", source: "default" },
  smtp_port: { value: 587, source: "default" },
  smtp_user: { value: "", source: "default" },
  smtp_password: { set: false, source: "default" },
  smtp_from: { value: "", source: "default" },
  smtp_security: { value: "starttls", source: "default" },
  public_url: { value: "", source: "default" },
};
```
(the first `idle_seconds: 43200,` and `};` in the file: the end of `MEL`. With step 5's settings in the `Settings` type, give them their defaults here too.)

`apps/desktop/src/test/Webhooks.test.tsx`:
```tsx
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Delivery, Webhook } from "../api/types";
import { GAME_PREFS_KEY } from "../lib/gamePrefs";
import { ADA, ALL_SETTINGS, json, renderApp, stubApi } from "./harness";

const TMS: Webhook = {
  id: 1, name: "Simple TMS", url: "https://tms.example.com.au/lms-events",
  events: ["competency.granted", "competency.revoked"], active: true, waiting: 0, failed: 1,
  created_at: "2026-10-12T01:00:00Z",
};
const FAILED: Delivery = {
  id: 9, event_id: "1b4e28ba-2fa1-41d2-883f-0016d3cca427", event_type: "competency.granted", status: "failed",
  attempts: 5, next_attempt_at: "2026-10-12T05:00:00Z", last_error: "HTTP 503: not now", done_at: null,
  created_at: "2026-10-12T01:30:00Z",
};

/** Settings with these webhooks, and no API keys yet. */
function hooks(list: Webhook[], more: (method: string, url: string, body: unknown) => Response | null = () => null) {
  return stubApi((method, url, body) => {
    if (method === "GET" && url === "/v1/settings") return json(200, ALL_SETTINGS);
    if (method === "GET" && url === "/v1/webhooks") return json(200, list);
    if (method === "GET" && url === "/v1/api-keys") return json(200, []);
    return more(method, url, body);
  }, ADA);
}

describe("webhooks", () => {
  it("adds one and shows its secret once", async () => {
    let list: Webhook[] = [];
    const { calls } = hooks(list, (method, url) => {
      if (method === "POST" && url === "/v1/webhooks") {
        list = [TMS];
        return json(201, { ...TMS, failed: 0, secret: "whsec_s3cret" });
      }
      return null;
    });
    renderApp("/settings");
    const form = await screen.findByRole("form", { name: "Add a webhook" });
    await userEvent.type(within(form).getByLabelText("Name"), "Simple TMS");
    await userEvent.type(within(form).getByLabelText("Address"), "https://tms.example.com.au/lms-events");
    await userEvent.click(within(form).getByLabelText("Granted"));
    await userEvent.click(within(form).getByLabelText("Revoked"));
    await userEvent.click(within(form).getByRole("button", { name: "Add webhook" }));

    expect(calls.find((c) => c.method === "POST")?.body).toEqual({
      name: "Simple TMS", url: "https://tms.example.com.au/lms-events",
      events: ["competency.granted", "competency.revoked"],
    });
    expect(await screen.findByLabelText("Simple TMS's secret")).toHaveValue("whsec_s3cret");
    expect(screen.getByText(/Simple LMS won't show it again/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(screen.queryByLabelText("Simple TMS's secret")).not.toBeInTheDocument();
  });

  it("sends everything as a star", async () => {
    const { calls } = hooks([], (method, url) =>
      method === "POST" && url === "/v1/webhooks" ? json(201, { ...TMS, events: ["*"], secret: "whsec_x" }) : null);
    renderApp("/settings");
    const form = await screen.findByRole("form", { name: "Add a webhook" });
    await userEvent.type(within(form).getByLabelText("Name"), "Everything");
    await userEvent.type(within(form).getByLabelText("Address"), "https://hooks.example.com.au/lms");
    await userEvent.click(within(form).getByLabelText("Everything, and whatever is added later"));
    expect(within(form).getByLabelText("Granted")).toBeDisabled();
    await userEvent.click(within(form).getByRole("button", { name: "Add webhook" }));
    await waitFor(() => expect(calls.find((c) => c.method === "POST")?.body).toMatchObject({ events: ["*"] }));
  });

  it("changes one's events and turns it off", async () => {
    const { calls } = hooks([TMS], (method, url, body) => {
      if (url === "/v1/webhooks/1/deliveries") return json(200, []);
      if (method === "PATCH" && url === "/v1/webhooks/1") return json(200, { ...TMS, ...(body as object) });
      return null;
    });
    renderApp("/settings");
    await userEvent.click(await screen.findByRole("button", { name: "Simple TMS" }));
    const drawer = await screen.findByRole("dialog", { name: "Simple TMS" });
    await userEvent.click(within(drawer).getByLabelText("Lapsed"));
    await userEvent.click(within(drawer).getByLabelText("On: events are sent to it"));
    await userEvent.click(within(drawer).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({
      name: "Simple TMS", url: TMS.url, events: ["competency.granted", "competency.revoked", "competency.lapsed"],
      active: false,
    }));
    expect(await within(drawer).findByText("Saved.")).toBeInTheDocument();
  });

  it("lists how its deliveries went and sends a failed one again", async () => {
    let deliveries = [FAILED];
    const { calls } = hooks([TMS], (method, url) => {
      if (url === "/v1/webhooks/1/deliveries") return json(200, deliveries);
      if (method === "POST" && url === "/v1/webhooks/1/deliveries/9/retry") {
        deliveries = [{ ...FAILED, status: "pending", attempts: 0 }];
        return json(200, deliveries[0]);
      }
      return null;
    });
    renderApp("/settings");
    expect(await screen.findByText("1 failed")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Simple TMS" }));
    const drawer = await screen.findByRole("dialog", { name: "Simple TMS" });
    const row = (await within(drawer).findByText("competency.granted")).closest("li")!;
    expect(within(row).getByText("Failed")).toBeInTheDocument();
    expect(within(row).getByText(/HTTP 503: not now/)).toBeInTheDocument();
    await userEvent.click(within(row).getByRole("button", { name: "Send again" }));
    expect(calls.some((c) => c.method === "POST" && c.url === "/v1/webhooks/1/deliveries/9/retry")).toBe(true);
    expect(await within(drawer).findByText("Waiting")).toBeInTheDocument();
  });

  it("makes a new secret and shows it once", async () => {
    hooks([TMS], (method, url) => {
      if (url === "/v1/webhooks/1/deliveries") return json(200, []);
      if (method === "POST" && url === "/v1/webhooks/1/secret") return json(200, { secret: "whsec_new" });
      return null;
    });
    renderApp("/settings");
    await userEvent.click(await screen.findByRole("button", { name: "Simple TMS" }));
    const drawer = await screen.findByRole("dialog", { name: "Simple TMS" });
    await userEvent.click(within(drawer).getByRole("button", { name: "New secret" }));
    expect(await within(drawer).findByLabelText("Simple TMS's secret")).toHaveValue("whsec_new");
  });

  it("is on the Settings page with Game Mode off too", async () => {
    window.localStorage.setItem(GAME_PREFS_KEY, '{"classroom":false}');
    hooks([TMS], (_m, url) => (url === "/v1/webhooks/1/deliveries" ? json(200, []) : null));
    renderApp("/settings");
    expect(await screen.findByRole("heading", { name: "Settings" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Back to the classroom" })).not.toBeInTheDocument();
    await userEvent.click(await screen.findByRole("button", { name: "Simple TMS" }));
    expect(await screen.findByRole("dialog", { name: "Simple TMS" })).toBeInTheDocument();
  });
});
```

**Step 2: Run them to see them fail**

Run: `cd apps/desktop && npx vitest run src/test/Webhooks.test.tsx`
Expected: FAIL: `Tests  6 failed (6)`: Settings has no "Add a webhook" form and lists no webhooks.

**Step 3: Minimal implementation**

Append to `apps/desktop/src/api/types.ts`:
```ts


export type EventType = "competency.granted" | "competency.revoked" | "competency.expiring"
  | "competency.lapsed" | "person.updated";

export interface Webhook {
  id: number;
  name: string;
  url: string;
  /** event types, or ["*"] for everything */
  events: string[];
  active: boolean;
  /** deliveries still to go, and those given up on */
  waiting: number;
  failed: number;
  created_at: string;
}

/** Shown once, when it is made: what its bodies are signed with. */
export interface WebhookMade extends Webhook { secret: string }

export interface Delivery {
  id: number;
  event_id: string;
  event_type: EventType;
  status: "pending" | "done" | "failed";
  attempts: number;
  next_attempt_at: string;
  last_error: string | null;
  done_at: string | null;
  created_at: string;
}
```

`apps/desktop/src/ui/ShownOnce.tsx`:
```tsx
import { useState } from "react";

/** A secret or a key Simple LMS shows this once and keeps no copy of (or,
 * for a webhook's secret, never shows again). `onDone` puts it away. */
export function ShownOnce({ label, value, why, onDone }: {
  label: string; value: string; why: string; onDone: () => void;
}) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
    } catch { /* no clipboard here: it can still be selected and copied */ }
  }
  return (
    <div className="card flex flex-col gap-2" role="status">
      <label className="label">{label}
        <input className="field font-mono" value={value} readOnly onFocus={(e) => e.target.select()} />
      </label>
      <div className="small">{why} Copy it now: Simple LMS won't show it again.</div>
      <div className="flex gap-2">
        <button type="button" className="btn" onClick={() => void copy()}>{copied ? "Copied" : "Copy"}</button>
        <button type="button" className="btn primary" onClick={onDone}>Done</button>
      </div>
    </div>
  );
}
```

`apps/desktop/src/pages/Webhooks.tsx`:
```tsx
import { useState, type FormEvent } from "react";
import { api } from "../api/client";
import type { Delivery, EventType, Webhook, WebhookMade } from "../api/types";
import { formatDate } from "../lib/status";
import { useAction, useLoad } from "../lib/useLoad";
import { Drawer, Problem } from "../ui/Drawer";
import { ShownOnce } from "../ui/ShownOnce";

const EVENTS: { type: EventType; label: string }[] = [
  { type: "competency.granted", label: "Granted" },
  { type: "competency.revoked", label: "Revoked" },
  { type: "competency.expiring", label: "Expiring" },
  { type: "competency.lapsed", label: "Lapsed" },
  { type: "person.updated", label: "Person updated" },
];

const DELIVERY: Record<Delivery["status"], { label: string; tone: string }> = {
  pending: { label: "Waiting", tone: "t-amber" },
  done: { label: "Sent", tone: "t-green" },
  failed: { label: "Failed", tone: "t-red" },
};

function wants(events: string[]): string {
  if (events.includes("*")) return "Everything";
  return EVENTS.filter((e) => events.includes(e.type)).map((e) => e.label).join(", ");
}

/** "2026-10-12T01:30:00Z" → "12 Oct 2026 12:30", in this browser's time. */
function when(iso: string): string {
  const d = new Date(iso);
  const day = formatDate(`${d.getFullYear()}-${d.getMonth() + 1}-${d.getDate()}`);
  return `${day} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

/** Which events: each of the five, or everything (and whatever comes later). */
function EventPicker({ value, onChange }: { value: string[]; onChange: (v: string[]) => void }) {
  const all = value.includes("*");
  return (
    <fieldset className="flex flex-col gap-1">
      <legend className="label mb-1">Events</legend>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={all} onChange={(e) => onChange(e.target.checked ? ["*"] : [])} />
        Everything, and whatever is added later
      </label>
      {EVENTS.map((e) => (
        <label key={e.type} className="flex items-center gap-2 text-sm" title={e.type}>
          <input type="checkbox" disabled={all} checked={all || value.includes(e.type)}
                 onChange={(x) => onChange(x.target.checked ? [...value, e.type] : value.filter((t) => t !== e.type))} />
          {e.label}
        </label>
      ))}
    </fieldset>
  );
}

/** Where the events go. */
export function Webhooks() {
  const hooks = useLoad(() => api.get<Webhook[]>("/v1/webhooks"), []);
  const [open, setOpen] = useState<number | null>(null);
  const [made, setMade] = useState<WebhookMade | null>(null);
  const [f, setF] = useState({ name: "", url: "", events: [] as string[] });
  const action = useAction();
  const hook = hooks.data?.find((w) => w.id === open);

  async function add(e: FormEvent) {
    e.preventDefault();
    let out: WebhookMade | null = null;
    const ok = await action.run(async () => { out = await api.post<WebhookMade>("/v1/webhooks", f); });
    if (ok) {
      setMade(out);
      setF({ name: "", url: "", events: [] });
      hooks.reload();
    }
  }

  return (
    <section className="card flex flex-col gap-3" aria-label="Webhooks">
      <div>
        <h2 className="m-0 text-lg font-extrabold">Webhooks</h2>
        <div className="small">Other systems hear what happens here: a competency granted, revoked, expiring or lapsed, a person changed. docs/api.md says what each is sent and how to check its signature.</div>
      </div>
      <Problem error={hooks.error} />
      {hooks.data?.length === 0 && <div className="card small">None yet. Add one for each system that should hear when someone is granted a competency, loses one, or changes.</div>}
      {hooks.data && hooks.data.length > 0 && (
        <table className="tbl">
          <thead><tr><th>Name</th><th>Address</th><th>Events</th><th>Deliveries</th></tr></thead>
          <tbody>
            {hooks.data.map((w) => (
              <tr key={w.id} className="click" onClick={() => setOpen(w.id)}>
                <td><button type="button" className="rowbtn" onClick={() => setOpen(w.id)}><b>{w.name}</b></button>
                  {!w.active && <span className="pill t-grey ml-2">Off</span>}</td>
                <td className="small">{w.url}</td>
                <td className="small">{wants(w.events)}</td>
                <td>
                  {w.failed > 0 && <span className="pill t-red">{w.failed} failed</span>}
                  {w.waiting > 0 && <span className="pill t-amber ml-1">{w.waiting} waiting</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {made && <ShownOnce label={`${made.name}'s secret`} value={made.secret} onDone={() => setMade(null)}
                         why="Give it to whoever looks after the receiver: it checks each event's X-LMS-Signature with it." />}
      <form className="card flex flex-col gap-3" aria-label="Add a webhook" onSubmit={add}>
        <div className="eyebrow">Add a webhook</div>
        <div className="grid grid-cols-2 gap-3">
          <label className="label">Name<input className="field" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder="e.g. Simple TMS" required /></label>
          <label className="label">Address<input className="field" type="url" value={f.url} onChange={(e) => setF({ ...f, url: e.target.value })} placeholder="https://…" required /></label>
        </div>
        <EventPicker value={f.events} onChange={(events) => setF({ ...f, events })} />
        <Problem error={action.error} />
        <div><button type="submit" className="btn primary" disabled={action.busy || f.events.length === 0}>Add webhook</button></div>
      </form>
      {hook && <WebhookDrawer key={hook.id} hook={hook} onClose={() => setOpen(null)} onChanged={hooks.reload} />}
    </section>
  );
}

function WebhookDrawer({ hook, onClose, onChanged }: { hook: Webhook; onClose: () => void; onChanged: () => void }) {
  const path = `/v1/webhooks/${hook.id}`;
  const deliveries = useLoad(() => api.get<Delivery[]>(`${path}/deliveries`), [path]);
  const [f, setF] = useState({ name: hook.name, url: hook.url, events: hook.events, active: hook.active });
  const [said, setSaid] = useState<string | null>(null);
  const [secret, setSecret] = useState<string | null>(null);
  const action = useAction();

  async function change(what: string, fn: () => Promise<unknown>) {
    setSaid(null);
    if (await action.run(fn)) {
      setSaid(what);
      deliveries.reload();
      onChanged();
    }
  }

  function save(e: FormEvent) {
    e.preventDefault();
    void change("Saved.", () => api.patch(path, f));
  }

  return (
    <Drawer title={hook.name} sub={hook.url} onClose={onClose}>
      <Problem error={action.error} />
      {said && <div className="msg g" role="status">{said}</div>}
      <form className="card flex flex-col gap-3" onSubmit={save}>
        <label className="label">Name<input className="field" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} required /></label>
        <label className="label">Address<input className="field" type="url" value={f.url} onChange={(e) => setF({ ...f, url: e.target.value })} required /></label>
        <EventPicker value={f.events} onChange={(events) => setF({ ...f, events })} />
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={f.active} onChange={(e) => setF({ ...f, active: e.target.checked })} />
          On: events are sent to it
        </label>
        <div><button type="submit" className="btn primary" disabled={action.busy || f.events.length === 0}>Save</button></div>
      </form>
      <div className="card flex flex-col gap-2">
        <div className="eyebrow">Secret</div>
        <div className="small">A new one signs everything sent from now on, what is waiting too; the old one stops at once.</div>
        {secret
          ? <ShownOnce label={`${hook.name}'s secret`} value={secret} onDone={() => setSecret(null)}
                       why="Give it to whoever looks after the receiver." />
          : <div><button type="button" className="btn" disabled={action.busy}
                         onClick={() => void action.run(async () => {
                           setSecret((await api.post<{ secret: string }>(`${path}/secret`)).secret);
                         })}>New secret</button></div>}
      </div>
      <section className="flex flex-col gap-2" aria-label="Deliveries">
        <div className="eyebrow">Latest deliveries</div>
        <Problem error={deliveries.error} />
        {deliveries.data?.length === 0 && <div className="small">Nothing sent yet.</div>}
        <ul className="flex flex-col gap-2">
          {deliveries.data?.map((d) => (
            <li key={d.id} className="card flex flex-col gap-1">
              <div className="flex items-center gap-2">
                <span className={`pill ${DELIVERY[d.status].tone}`}>{DELIVERY[d.status].label}</span>
                <span className="text-sm">{d.event_type}</span>
                <span className="small ml-auto">{when(d.created_at)}</span>
              </div>
              {d.last_error && <div className="small">After {d.attempts} {d.attempts === 1 ? "try" : "tries"}: {d.last_error}</div>}
              {d.status === "failed" && (
                <div><button type="button" className="btn" disabled={action.busy}
                             onClick={() => void change("Sending it again.", () => api.post(`${path}/deliveries/${d.id}/retry`))}>
                  Send again</button></div>
              )}
            </li>
          ))}
        </ul>
      </section>
    </Drawer>
  );
}
```

In `apps/desktop/src/pages/Settings.tsx`, replace:
```tsx
import { Problem } from "../ui/Drawer";
```
with:
```tsx
import { Problem } from "../ui/Drawer";
import { Webhooks } from "./Webhooks";
```

In `apps/desktop/src/pages/Settings.tsx`, replace:
```tsx
          <WebAddress all={all} onSaved={setAll} />
        </>
```
with:
```tsx
          <WebAddress all={all} onSaved={setAll} />
          <Webhooks />
        </>
```
(After whatever section step 5 added for Entra, if it comes last.)

**Step 4: Run them, and every desktop test, to see them pass**

Run: `cd apps/desktop && npx vitest run src/test/Webhooks.test.tsx`
Expected: `Tests  6 passed (6)`

Run: `cd apps/desktop && npm test && npm run typecheck`
Expected: D + 6 (`Tests  116 passed (116)` on `c193b0c`), and no type errors.

**Step 5: Commit**

```
git add apps/desktop/src
git commit -m "Add webhooks to Settings: added and changed, the secret shown once, a failed delivery sent again"
```

---

### Task 14: API keys on the Settings screen: made, shown once, revoked after asking

**Files:**
- Create: `apps/desktop/src/pages/ApiKeys.tsx`
- Modify: `apps/desktop/src/api/types.ts`, `apps/desktop/src/pages/Settings.tsx`
- Test: create `apps/desktop/src/test/ApiKeys.test.tsx`

**Step 1: Write the failing tests**

`apps/desktop/src/test/ApiKeys.test.tsx`:
```tsx
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ApiKey } from "../api/types";
import { ADA, ALL_SETTINGS, json, renderApp, stubApi } from "./harness";

const TMS: ApiKey = {
  id: 3, name: "Simple TMS", prefix: "lms_k.Ab3d", scopes: ["competencies:read"],
  created_by: { code: "AD001", name: "Ada Admin" }, created_at: "2026-10-12T01:00:00Z",
  last_used_at: "2026-10-12T03:15:00Z", revoked_at: null,
};

/** Settings with these keys, and no webhooks yet. */
function keys(list: () => ApiKey[], more: (method: string, url: string) => Response | null = () => null) {
  return stubApi((method, url) => {
    if (method === "GET" && url === "/v1/settings") return json(200, ALL_SETTINGS);
    if (method === "GET" && url === "/v1/webhooks") return json(200, []);
    if (method === "GET" && url === "/v1/api-keys") return json(200, list());
    return more(method, url);
  }, ADA);
}

describe("API keys", () => {
  it("makes one for another system and shows it once", async () => {
    let list: ApiKey[] = [];
    const { calls } = keys(() => list, (method, url) => {
      if (method === "POST" && url === "/v1/api-keys") {
        list = [TMS];
        return json(201, { ...TMS, key: "lms_k.Ab3dEfGh" });
      }
      return null;
    });
    renderApp("/settings");
    const form = await screen.findByRole("form", { name: "Make an API key" });
    expect(within(form).getByLabelText("Read who is current (the competency API)")).toBeChecked();
    await userEvent.type(within(form).getByLabelText("Who it is for"), "Simple TMS");
    await userEvent.click(within(form).getByRole("button", { name: "Make key" }));
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({ name: "Simple TMS", scopes: ["competencies:read"] });
    expect(await screen.findByLabelText("Simple TMS's key")).toHaveValue("lms_k.Ab3dEfGh");
    const row = await screen.findByRole("row", { name: /Simple TMS/ });
    expect(within(row).getByText("lms_k.Ab3d…")).toBeInTheDocument();
  });

  it("asks once before revoking one", async () => {
    let list = [TMS];
    const { calls } = keys(() => list, (method, url) => {
      if (method === "POST" && url === "/v1/api-keys/3/revoke") {
        list = [{ ...TMS, revoked_at: "2026-10-12T04:00:00Z" }];
        return json(200, list[0]);
      }
      return null;
    });
    renderApp("/settings");
    const row = await screen.findByRole("row", { name: /Simple TMS/ });
    await userEvent.click(within(row).getByRole("button", { name: "Revoke" }));
    expect(screen.getByText("Revoke Simple TMS's key? Anything using it stops working, for good.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Keep it" }));
    expect(calls.some((c) => c.method === "POST")).toBe(false);
    await userEvent.click(within(row).getByRole("button", { name: "Revoke" }));
    await userEvent.click(screen.getByRole("button", { name: "Revoke it" }));
    await waitFor(() => expect(calls.some((c) => c.url === "/v1/api-keys/3/revoke")).toBe(true));
    expect(await within(await screen.findByRole("row", { name: /Simple TMS/ })).findByText("Revoked")).toBeInTheDocument();
  });
});
```

**Step 2: Run them to see them fail**

Run: `cd apps/desktop && npx vitest run src/test/ApiKeys.test.tsx`
Expected: FAIL: `Tests  2 failed (2)`: no "Make an API key" form, no keys listed.

**Step 3: Minimal implementation**

Append to `apps/desktop/src/api/types.ts`:
```ts


export interface ApiKey {
  id: number;
  name: string;
  /** its first characters, to tell which is which */
  prefix: string;
  scopes: string[];
  created_by: PersonRef;
  created_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
}

/** Shown once, when it is made: Simple LMS keeps only its hash. */
export interface ApiKeyMade extends ApiKey { key: string }
```

`apps/desktop/src/pages/ApiKeys.tsx`:
```tsx
import { useState, type FormEvent } from "react";
import { api } from "../api/client";
import type { ApiKey, ApiKeyMade } from "../api/types";
import { formatDate } from "../lib/status";
import { useAction, useLoad } from "../lib/useLoad";
import { Problem } from "../ui/Drawer";
import { ShownOnce } from "../ui/ShownOnce";

const SCOPES = [{ scope: "competencies:read", label: "Read who is current (the competency API)" }];

/** Keys for other systems: made, shown once, revoked. */
export function ApiKeys() {
  const keys = useLoad(() => api.get<ApiKey[]>("/v1/api-keys"), []);
  const [name, setName] = useState("");
  const [scopes, setScopes] = useState(["competencies:read"]);
  const [made, setMade] = useState<ApiKeyMade | null>(null);
  const [asking, setAsking] = useState<ApiKey | null>(null);
  const action = useAction();

  async function make(e: FormEvent) {
    e.preventDefault();
    let out: ApiKeyMade | null = null;
    if (await action.run(async () => { out = await api.post<ApiKeyMade>("/v1/api-keys", { name, scopes }); })) {
      setMade(out);
      setName("");
      keys.reload();
    }
  }

  async function revoke(k: ApiKey) {
    setAsking(null);
    if (await action.run(() => api.post(`/v1/api-keys/${k.id}/revoke`))) keys.reload();
  }

  return (
    <section className="card flex flex-col gap-3" aria-label="API keys">
      <div>
        <h2 className="m-0 text-lg font-extrabold">API keys</h2>
        <div className="small">Other systems read who is current with a key: <code>GET /v1/people/&#123;code&#125;/competencies</code>, and nothing else.</div>
      </div>
      <Problem error={action.error ?? keys.error} />
      {keys.data?.length === 0 && <div className="card small">None yet. Make one for each system that reads who is current, such as Simple TMS.</div>}
      {keys.data && keys.data.length > 0 && (
        <table className="tbl">
          <thead><tr><th>For</th><th>Key</th><th>May</th><th>Last used</th><th /></tr></thead>
          <tbody>
            {keys.data.map((k) => (
              <tr key={k.id}>
                <td><b>{k.name}</b><span className="small block">by {k.created_by.name} · {formatDate(k.created_at.slice(0, 10))}</span></td>
                <td className="font-mono small">{k.prefix}…</td>
                <td className="small">{k.scopes.join(", ")}</td>
                <td className="small">{k.last_used_at ? formatDate(k.last_used_at.slice(0, 10)) : "Never"}</td>
                <td>{k.revoked_at
                  ? <span className="pill t-grey">Revoked</span>
                  : <button type="button" className="btn danger" disabled={action.busy} onClick={() => setAsking(k)}>Revoke</button>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {asking && (
        <div className="card flex flex-wrap items-center gap-3" role="alertdialog" aria-label="Revoke a key">
          <span className="text-sm"><b>Revoke {asking.name}'s key? Anything using it stops working, for good.</b></span>
          <button type="button" className="btn danger" onClick={() => void revoke(asking)}>Revoke it</button>
          <button type="button" className="btn" autoFocus onClick={() => setAsking(null)}>Keep it</button>
        </div>
      )}
      {made && <ShownOnce label={`${made.name}'s key`} value={made.key} onDone={() => setMade(null)}
                         why={`Put it in ${made.name}'s settings: it sends it as its bearer token.`} />}
      <form className="card flex flex-col gap-3" aria-label="Make an API key" onSubmit={make}>
        <div className="eyebrow">Make an API key</div>
        <label className="label">Who it is for<input className="field" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Simple TMS" required /></label>
        <fieldset className="flex flex-col gap-1">
          <legend className="label mb-1">It may</legend>
          {SCOPES.map((s) => (
            <label key={s.scope} className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={scopes.includes(s.scope)}
                     onChange={(e) => setScopes(e.target.checked ? [...scopes, s.scope] : scopes.filter((x) => x !== s.scope))} />
              {s.label}
            </label>
          ))}
        </fieldset>
        <div><button type="submit" className="btn primary" disabled={action.busy || scopes.length === 0}>Make key</button></div>
      </form>
    </section>
  );
}
```

In `apps/desktop/src/pages/Settings.tsx`, replace:
```tsx
import { Webhooks } from "./Webhooks";
```
with:
```tsx
import { ApiKeys } from "./ApiKeys";
import { Webhooks } from "./Webhooks";
```

In `apps/desktop/src/pages/Settings.tsx`, replace:
```tsx
          <Webhooks />
```
with:
```tsx
          <Webhooks />
          <ApiKeys />
```

**Step 4: Run them, and every desktop test, to see them pass**

Run: `cd apps/desktop && npx vitest run src/test/ApiKeys.test.tsx src/test/Webhooks.test.tsx`
Expected: `Tests  8 passed (8)`

Run: `cd apps/desktop && npm test && npm run typecheck`
Expected: D + 8 (`Tests  118 passed (118)`), and no type errors.

**Step 5: Commit**

```
git add apps/desktop/src
git commit -m "Make and revoke API keys on the Settings screen, each shown once"
```

---

### Task 15: Printing: Platen in Settings, a certificate from a cell's history, a skills card from a person's drawer

**Files:**
- Modify: `apps/desktop/src/api/types.ts`, `apps/desktop/src/pages/Settings.tsx`, `apps/desktop/src/pages/HistoryDrawer.tsx`, `apps/desktop/src/pages/People.tsx`
- Test: `apps/desktop/src/test/harness.tsx`, `apps/desktop/src/test/Settings.test.tsx`; create `apps/desktop/src/test/Printing.test.tsx`

**Step 1: Write the failing tests**

A manager now carries `printing:write`. In `apps/desktop/src/test/harness.tsx`, add it to the end of `MEL`'s scopes; on `c193b0c`, replace:
```tsx
           "people:write", "roles:write", "competencies:write", "records:write", "tickets:verify"],
```
with:
```tsx
           "people:write", "roles:write", "competencies:write", "records:write", "tickets:verify", "printing:write"],
```

In `apps/desktop/src/test/harness.tsx`, replace:
```tsx
  public_url: { value: "", source: "default" },
};
```
with:
```tsx
  public_url: { value: "", source: "default" },
  platen_url: { value: "", source: "default" },
  platen_key: { set: false, source: "default" },
  certificate_printer: { value: "office", source: "default" },
  skills_card_printer: { value: "", source: "default" },
};
```

In `apps/desktop/src/test/Settings.test.tsx`, the same four in its `SETTINGS`; replace:
```tsx
  public_url: { value: "", source: "default" },
};
```
with:
```tsx
  public_url: { value: "", source: "default" },
  platen_url: { value: "", source: "default" },
  platen_key: { set: false, source: "default" },
  certificate_printer: { value: "office", source: "default" },
  skills_card_printer: { value: "", source: "default" },
};
```

In `apps/desktop/src/test/Settings.test.tsx`, so its stand-in API keeps the key write-only, replace:
```tsx
        if (k === "smtp_password") now.smtp_password = { set: v !== "", source: "here" };
```
with:
```tsx
        if (k === "smtp_password") now.smtp_password = { set: v !== "", source: "here" };
        else if (k === "platen_key") now.platen_key = { set: v !== "", source: "here" };
```

In `apps/desktop/src/test/Settings.test.tsx`, replace:
```tsx
  it("puts a value back to .env or the default", async () => {
```
with:
```tsx
  it("sets where certificates and skills cards print, the key never shown", async () => {
    const { calls } = stubSettings();
    renderApp("/settings");
    const printing = await section("Printing");
    await userEvent.type(within(printing).getByLabelText(/Platen's address/), "https://platen.example.com.au/intake/jobs");
    await userEvent.type(within(printing).getByLabelText(/Platen key/), "pk_s3cret");
    await userEvent.clear(within(printing).getByLabelText(/Certificates print on/));
    await userEvent.type(within(printing).getByLabelText(/Certificates print on/), "front office");
    await userEvent.click(within(printing).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(puts(calls)).toEqual([{
      platen_url: "https://platen.example.com.au/intake/jobs", platen_key: "pk_s3cret", certificate_printer: "front office",
    }]));
    expect(await within(printing).findByText("A key is set. Leave this empty to keep it.")).toBeInTheDocument();
    expect(within(printing).getByLabelText(/Platen key/)).toHaveValue("");
  });

  it("puts a value back to .env or the default", async () => {
```

`apps/desktop/src/test/Printing.test.tsx`:
```tsx
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { CompetencyRecord, Matrix, Person } from "../api/types";
import { MEL, json, renderApp, stubApi } from "./harness";

const FORKLIFT = { key: "forklift-licence", name: "Forklift licence", kind: "ticket" as const };
const MATRIX: Matrix = {
  today: "2026-10-12",
  competencies: [FORKLIFT],
  people: [{ code: "LL042", name: "Kim Lee", roles: [], supervisor: null,
             cells: { "forklift-licence": { status: "current", granted_on: "2026-03-01", expires_on: "2031-03-01" } } }],
};
const record = (id: number, granted_on: string): CompetencyRecord => ({
  id, competency: FORKLIFT, kind: "granted", granted_on, expires_on: "2031-03-01", note: null,
  recorded_by: { code: "MG001", name: "Mel Grant" }, policy_version: null, signed_name: null, signature: null,
  ticket: null, quiz: null, created_at: `${granted_on}T01:00:00Z`,
});
const KIM: Person = {
  id: 4, code: "LL042", name: "Kim Lee", email: null, permission: "learner", supervisor: null, roles: [],
  active: true, has_pin: true, pin_locked: false, has_password: false,
};

function history(more: (method: string, url: string) => Response | null) {
  return stubApi((method, url) => {
    if (url.startsWith("/v1/matrix")) return json(200, MATRIX);
    if (url === "/v1/roles") return json(200, { items: [], total: 0 });
    if (method === "GET" && url.startsWith("/v1/people/LL042/records")) {
      return json(200, [record(12, "2026-03-01"), record(5, "2021-03-01")]);
    }
    return more(method, url);
  });
}

async function openKimsForklift() {
  renderApp("/matrix");
  await userEvent.click(await screen.findByRole("button", { name: /Kim Lee, Forklift licence/ }));
  return screen.findByRole("dialog", { name: "Forklift licence" });
}

describe("printing", () => {
  it("prints a certificate for the completion that counts", async () => {
    const { calls } = history((method, url) => method === "POST" && url === "/v1/people/LL042/records/12/certificate"
      ? json(202, { job_id: "j-1", template: "lms-certificate", printer: "office" }) : null);
    const drawer = await openKimsForklift();
    const print = await within(drawer).findAllByRole("button", { name: "Print certificate" });
    expect(print).toHaveLength(1);
    await userEvent.click(print[0]);
    expect(await within(drawer).findByText("Sent to Platen, for the printer office.")).toBeInTheDocument();
    expect(calls.filter((c) => c.method === "POST").map((c) => c.url)).toEqual(["/v1/people/LL042/records/12/certificate"]);
  });

  it("says so when printing isn't set up", async () => {
    history((method) => method === "POST"
      ? json(409, { detail: "Printing is not set up: give Platen's address in Settings, under Printing.", code: "printing_not_set_up" })
      : null);
    const drawer = await openKimsForklift();
    await userEvent.click(await within(drawer).findByRole("button", { name: "Print certificate" }));
    expect(await within(drawer).findByRole("alert")).toHaveTextContent("Printing is not set up");
  });

  it("isn't offered to a supervisor", async () => {
    stubApi((_method, url) => {
      if (url.startsWith("/v1/matrix")) return json(200, MATRIX);
      if (url === "/v1/roles") return json(200, { items: [], total: 0 });
      if (url.startsWith("/v1/people/LL042/records")) return json(200, [record(12, "2026-03-01")]);
      return null;
    }, { ...MEL, permission: "supervisor", scopes: ["training:read", "training:write", "matrix:read", "roles:read", "competencies:read"] });
    const drawer = await openKimsForklift();
    expect(await within(drawer).findByText("Counts now")).toBeInTheDocument();
    expect(within(drawer).queryByRole("button", { name: "Print certificate" })).not.toBeInTheDocument();
  });

  it("prints a person's skills card", async () => {
    const { calls } = stubApi((method, url) => {
      if (url.startsWith("/v1/people?")) return json(200, { items: [KIM], total: 1 });
      if (url === "/v1/people/LL042") return json(200, KIM);
      if (url === "/v1/people/LL042/overrides") return json(200, []);
      if (url === "/v1/roles" || url.startsWith("/v1/competencies")) return json(200, { items: [], total: 0 });
      if (method === "POST" && url === "/v1/people/LL042/skills-card") {
        return json(202, { job_id: "j-2", template: "lms-skills-card", printer: "card printer" });
      }
      return null;
    });
    renderApp("/people");
    await userEvent.click(await screen.findByRole("button", { name: "Kim Lee" }));
    const drawer = await screen.findByRole("dialog", { name: "Kim Lee" });
    await userEvent.click(await within(drawer).findByRole("button", { name: "Print skills card" }));
    expect(await within(drawer).findByText("Sent to Platen, for the printer card printer.")).toBeInTheDocument();
    expect(calls.some((c) => c.method === "POST" && c.url === "/v1/people/LL042/skills-card")).toBe(true);
  });
});
```

**Step 2: Run them to see them fail**

Run: `cd apps/desktop && npx vitest run src/test/Printing.test.tsx src/test/Settings.test.tsx`
Expected: FAIL: `Tests  4 failed | 11 passed (15)`: no *Printing* section, no "Print certificate" or "Print skills card" button ("isn't offered to a supervisor" passes already, and must go on passing).

**Step 3: Minimal implementation**

In `apps/desktop/src/api/types.ts`, replace:
```ts
  smtp_security: SettingValue<"starttls" | "ssl" | "none">;
  public_url: SettingValue<string>;
}
```
with:
```ts
  smtp_security: SettingValue<"starttls" | "ssl" | "none">;
  public_url: SettingValue<string>;
  platen_url: SettingValue<string>;
  /** never sent back: only whether there is one */
  platen_key: { set: boolean; source: SettingSource };
  certificate_printer: SettingValue<string>;
  skills_card_printer: SettingValue<string>;
}
```

Append to `apps/desktop/src/api/types.ts`:
```ts

/** A certificate or skills card queued for Platen. */
export interface PrintJob { job_id: string; template: string; printer: string }
```

In `apps/desktop/src/pages/Settings.tsx`, replace:
```tsx
  smtp_from: "text", smtp_security: "text", public_url: "text",
};
```
with:
```tsx
  smtp_from: "text", smtp_security: "text", public_url: "text",
  platen_url: "text", platen_key: "secret", certificate_printer: "text", skills_card_printer: "text",
};
```

In `apps/desktop/src/pages/Settings.tsx`, replace:
```tsx
          <WebAddress all={all} onSaved={setAll} />
```
with:
```tsx
          <WebAddress all={all} onSaved={setAll} />
          <Printing all={all} onSaved={setAll} />
```

Append to `apps/desktop/src/pages/Settings.tsx` (the key is kept as the email password is: a password field, never filled in, with whether one is set and a way to clear it):
```tsx

function Printing({ all, onSaved }: Props) {
  const s = useSection(all, ["platen_url", "platen_key", "certificate_printer", "skills_card_printer"], onSaved);
  const text = (key: Key, label: string, hint?: string, type = "text") => (
    <Field label={label} hint={hint} source={all[key].source} error={s.errors[key]} onReset={() => void s.reset(key)}>
      {(id) => <input id={id} className="field" type={type} value={String(s.draft[key] ?? "")}
                      onChange={(e) => s.set(key)(e.target.value)} />}
    </Field>
  );
  return (
    <Section title="Printing" sub="Certificates and skills cards print through Platen: Simple LMS sends the template's name and the data, never a page. Until Platen's address is set, nothing prints."
             onSubmit={s.save} busy={s.action.busy} error={s.action.error} said={s.said}>
      {text("platen_url", "Platen's address", "Its intake, e.g. https://platen.example.com.au/intake/jobs", "url")}
      <Field label="Platen key" source={all.platen_key.source} error={s.errors.platen_key}
             onReset={() => void s.reset("platen_key")}
             hint={<>{all.platen_key.set ? "A key is set. Leave this empty to keep it." : "No key set: make one in Platen for Simple LMS."}{" "}
               {all.platen_key.set && (
                 <button type="button" className="rowbtn underline" onClick={() => void s.send({ platen_key: "" }, "Key cleared.")}>
                   Clear the key</button>
               )}</>}>
        {(id) => <input id={id} className="field" type="password" autoComplete="new-password" value={String(s.draft.platen_key ?? "")}
                        onChange={(e) => s.set("platen_key")(e.target.value)} />}
      </Field>
      <div className="grid grid-cols-2 gap-3">
        {text("certificate_printer", "Certificates print on", "A Platen printer's id or name")}
        {text("skills_card_printer", "Skills cards print on", "Leave empty for the certificates' printer")}
      </div>
    </Section>
  );
}
```

In `apps/desktop/src/pages/HistoryDrawer.tsx`, replace:
```tsx
import type { Cell, CompetencyRecord, CompetencyRef, PersonRef } from "../api/types";
```
with:
```tsx
import type { Cell, CompetencyRecord, CompetencyRef, PersonRef, PrintJob } from "../api/types";
```

In `apps/desktop/src/pages/HistoryDrawer.tsx`, replace:
```tsx
/** One person's history for one competency, newest first: the first row is
 * the one that counts. A manager records a completion or revokes one here. */
```
with:
```tsx
/** One person's history for one competency, newest first: the first row is
 * the one that counts. A manager records a completion or revokes one here,
 * and prints a certificate of the one that counts. */
```

In `apps/desktop/src/pages/HistoryDrawer.tsx`, replace:
```tsx
  const [why, setWhy] = useState("");
  const action = useAction();
```
with:
```tsx
  const [why, setWhy] = useState("");
  const [printed, setPrinted] = useState<string | null>(null);
  const action = useAction();
```

In `apps/desktop/src/pages/HistoryDrawer.tsx`, replace:
```tsx
  async function changed(fn: () => Promise<unknown>) {
    if (await action.run(fn)) {
```
with:
```tsx
  async function changed(fn: () => Promise<unknown>) {
    setPrinted(null);
    if (await action.run(fn)) {
```

In `apps/desktop/src/pages/HistoryDrawer.tsx`, replace:
```tsx
  function revoke(e: FormEvent) {
```
with:
```tsx
  function printCertificate(id: number) {
    setPrinted(null);
    void action.run(async () => {
      const job = await api.post<PrintJob>(`${path}/${id}/certificate`);
      setPrinted(`Sent to Platen, for the printer ${job.printer}.`);
    });
  }

  function revoke(e: FormEvent) {
```

In `apps/desktop/src/pages/HistoryDrawer.tsx`, replace:
```tsx
      <Problem error={action.error ?? history.error} />
      {can("records:write") && own && (
```
with:
```tsx
      <Problem error={action.error ?? history.error} />
      {printed && <div className="msg g" role="status">{printed}</div>}
      {can("records:write") && own && (
```

In `apps/desktop/src/pages/HistoryDrawer.tsx`, replace:
```tsx
            {r.note && <div className="text-sm">{r.note}</div>}
            <div className="small">by {r.recorded_by.name} · {formatDate(r.created_at.slice(0, 10))}</div>
```
with:
```tsx
            {r.note && <div className="text-sm">{r.note}</div>}
            <div className="small">by {r.recorded_by.name} · {formatDate(r.created_at.slice(0, 10))}</div>
            {i === 0 && r.kind === "granted" && can("printing:write") && (
              <div><button type="button" className="btn" disabled={action.busy}
                           onClick={() => printCertificate(r.id)}>Print certificate</button></div>
            )}
```
(Step 4 may have added a practical's sign-off details above the note; the button still goes at the end of the card.)

In `apps/desktop/src/pages/People.tsx`, replace:
```tsx
import type { Competency, Override, Page, Permission, Person, Role } from "../api/types";
```
with:
```tsx
import type { Competency, Override, Page, Permission, Person, PrintJob, Role } from "../api/types";
```

In `apps/desktop/src/pages/People.tsx`, replace:
```tsx
  const { me, signOut } = useAuth();
  const path = `/v1/people/${encodeURIComponent(code)}`;
```
with:
```tsx
  const { me, signOut, can } = useAuth();
  const path = `/v1/people/${encodeURIComponent(code)}`;
```

In `apps/desktop/src/pages/People.tsx`, replace:
```tsx
      {said && <div className="msg g" role="status">{said}</div>}
      {!mine && <div className="msg r">Only an admin can change a manager or an admin.</div>}
```
with:
```tsx
      {said && <div className="msg g" role="status">{said}</div>}
      {can("printing:write") && (
        <div><button type="button" className="btn" disabled={action.busy} onClick={() => {
          setSaid(null);
          void action.run(async () => {
            const job = await api.post<PrintJob>(`${path}/skills-card`);
            setSaid(`Sent to Platen, for the printer ${job.printer}.`);
          });
        }}>Print skills card</button></div>
      )}
      {!mine && <div className="msg r">Only an admin can change a manager or an admin.</div>}
```

**Step 4: Run them, and every desktop test, to see them pass**

Run: `cd apps/desktop && npx vitest run src/test/Printing.test.tsx src/test/Settings.test.tsx`
Expected: `Tests  15 passed (15)`

Run: `cd apps/desktop && npm test && npm run typecheck && npm run build`
Expected: D + 13 (`Tests  123 passed (123)`), no type errors, and a build.

**Step 5: Commit**

```
git add apps/desktop/src
git commit -m "Set Platen in Settings, and print a certificate from the completion that counts and a skills card from a person's drawer"
```

---

### Task 16: The README and CLAUDE.md

**Files:**
- Modify: `README.md`, `CLAUDE.md`

**Step 1: Write it**

In `README.md`, replace the status paragraph (the one that starts `Status: **`, whatever step 5 left it saying) with:
````markdown
Status: **all seven build steps are done.** People with a code and PIN,
an email and password or a Microsoft account, roles and the competencies
each requires, extras and waivers, completions recorded by hand on the
desktop, the matrix (with a CSV export), and a learner app that shows each
person's training. People take online modules, sign policies, send in their
tickets and have their practicals signed off; a manager checks each ticket
in the desktop's Inbox; the worker emails reminders and a Monday digest.
Other systems hear what happens through signed webhooks and read who is
current with an API key, and certificates and skills cards print through
Platen. The desktop opens on a classroom, a desk for each role with its
people sitting at it in green, amber or red, and every screen in a drawer
over it; the learner app shows a ring for how much is done and says Ding!
out loud. `docs/plans/2026-10-12-simple-lms-design.md` is the design.
````

In `README.md`, replace:
````markdown
(with **Send a test email**), and the web address for links in emails.
````
with:
````markdown
(with **Send a test email**), the web address for links in emails, and
printing through Platen; below them, the webhooks and API keys.
````

In `README.md`, replace:
````markdown
`docker compose exec worker lms daily-job` (add `--on YYYY-MM-DD` to run it
as if today were that date, to try it out).
````
with:
````markdown
`docker compose exec worker lms daily-job` (add `--on YYYY-MM-DD` to run it
as if today were that date, to try it out).

**Webhooks.** An admin adds one under **Settings** for each system that
should hear what happens: its address, and which of `competency.granted`,
`competency.revoked`, `competency.expiring`, `competency.lapsed` and
`person.updated` it wants (or everything). Its secret is shown once: the
receiver checks each event's `X-LMS-Signature` with it, as it would Simple
WMS's `X-WMS-Signature`, and keeps the `event_id`s it has had. The worker
sends each event with the change that caused it, and tries a refusal again
after 1 minute, 5, 30 and 2 hours; the webhook's drawer shows how each went
and sends a failed one again. Expiring and lapsed come from the daily job,
each once. `docs/api.md` has the catalogue and how to check a signature. A
webhook on this machine but outside Compose is
`http://host.docker.internal:<port>/…` to the worker.

**API keys.** Under **Settings** an admin makes a key for a system that
reads who is current (Simple TMS, say), shown once, and revokes it when it
is done with. A key reads `GET /v1/people/{code}/competencies` and
`/{key}` (status and last good day) and nothing else.

**Printing.** Under **Settings**, *Printing*, an admin gives Platen's
intake address (`https://<platen>/intake/jobs`), a key made in Platen for
Simple LMS (kept, never shown again) and the printers certificates and
skills cards go to (or `LMS_PLATEN_*` in `.env`). In Platen, make and
publish page templates with the ids `lms-certificate` and
`lms-skills-card`; the fields each binds to are in `docs/api.md`. A manager
prints a certificate from the history of the completion that counts now
(click a cell on the matrix) and a skills card, of everything the person is
current for, from their drawer under **People**. Simple LMS sends the
template name and the data, and never draws a page itself.
````

In `README.md`, replace:
````markdown
| Add or change a manager or an admin | | | | ✓ |
````
with:
````markdown
| Print a certificate or a skills card | | | ✓ | ✓ |
| Add or change a manager or an admin | | | | ✓ |
| Settings, webhooks and API keys | | | | ✓ |
````

In `README.md`, replace:
````markdown
.venv/bin/python -m lms.worker   # in another terminal, for email and the daily job
````
with:
````markdown
.venv/bin/python -m lms.worker   # in another terminal: email, webhooks, printing, the daily job
````

In `CLAUDE.md`, replace:
````markdown
- Sister apps: nothing in Simple WMS or Simple TMS changes for Simple LMS. It
  publishes signed events and a competency API (build step 6).
````
with:
````markdown
- Sister apps: nothing in Simple WMS or Simple TMS changes for Simple LMS. It
  publishes signed events and a competency API.
- Events: queued by `lms/services/events.py` in the same transaction as the
  change, one outbox row per webhook, signed by the worker with
  `X-LMS-Signature` exactly as Simple WMS signs its own. Anything new that
  grants or revokes a competency calls `events.granted` or `events.revoked`;
  anything that changes what another system keeps about a person calls
  `events.person_updated`. The daily job's expiring and lapsed go through
  `events.once`, so each fires once. The catalogue is in `docs/api.md`.
- API keys: for systems, not people; shown once, only the hash kept. A key
  opens the competency API and nothing else. Webhooks and keys are an
  admin's (`settings:write`), on the Settings screen.
````

**Step 2: Commit**

```
git add README.md CLAUDE.md
git commit -m "Describe webhooks, API keys and printing in the README, and the events' rules in CLAUDE.md"
```

---

### Task 17: Every suite, and a clean Compose start

**Step 1: Every suite**

```
(cd api && .venv/bin/pytest -q)
(cd apps/desktop && npm test && npm run typecheck && npm run build)
(cd apps/learner && npm test && npm run typecheck && npm run build)
```
Expected: A + 89 passed (`535 passed` on `c193b0c`; one more with step 4's practical event test); D + 13 (`Tests  123 passed (123)`) and a build; L, unchanged (`Tests  72 passed (72)`), and a build.

**Step 2: Compose from nothing**

This drops the local database and its uploads: only on a machine with nothing to keep.
```
docker compose down -v
docker compose up -d --build
for i in $(seq 1 30); do curl -fsS http://127.0.0.1:8033/v1/health && break; sleep 2; done; echo
docker compose ps --format '{{.Service}} {{.State}}'
docker compose logs worker | grep "worker started"
docker compose exec -T db psql -U lms -d lms -tAc "select version_num from alembic_version"
docker compose exec -T db psql -U lms -d lms -tAc "select count(*) from information_schema.tables where table_name in ('webhook', 'api_key', 'event_seen')"
```
Expected: `{"status":"ok"}`; `api running`, `caddy running`, `db running`, `worker running`; the worker's `worker started` line; `0006`; and `3`. Fix anything that is not, then commit the fix with a message that says what it fixes.

---

### Task 18: Manual walkthrough: a webhook heard and checked, a key read, a card printed

With the stack from Task 17 (and `LMS_HTTPS_PORT=8643` in `.env`), the first admin made with `docker compose exec api lms create-user --code AD001 --name "…" --email …`, and a manager Mel (`MG001`) added on the desktop. Two stand-ins run on this machine, outside Compose, in a folder of their own (say `/tmp/lms-links`); the worker reaches them at `host.docker.internal`. Do it once with Game Mode on (Settings opens as a drawer over the classroom) and look at Settings once with it off (a page of its own).

`/tmp/lms-links/receiver.py`, a webhook receiver that checks each signature as `docs/api.md` says, prints each event, notes one it has had before, and refuses while a file called `FAIL` is beside it:
```python
"""A webhook receiver for trying Simple LMS out: checks each event's
signature with the secret, prints it, and answers 204 (or 503 with FAIL=1)."""
import hashlib, hmac, json, os, sys
from http.server import BaseHTTPRequestHandler, HTTPServer

SECRET = os.environ["SECRET"]
seen = set()

class Hook(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        expected = "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
        ok = hmac.compare_digest(expected, self.headers.get("X-LMS-Signature", ""))
        event = json.loads(body)
        again = event["event_id"] in seen
        seen.add(event["event_id"])
        print(("signed" if ok else "BAD SIGNATURE"), event["event_type"],
              "(seen before)" if again else "", json.dumps(event["data"]), flush=True)
        failing = os.path.exists("FAIL")
        self.send_response(503 if failing or not ok else 204)
        self.end_headers()

    def log_message(self, *args):
        pass

HTTPServer(("0.0.0.0", int(sys.argv[1])), Hook).serve_forever()
```

`/tmp/lms-links/fake_platen.py`, a stand-in for Platen's intake that prints each job and answers `202`:
```python
"""A stand-in for Platen's intake: prints each job and answers 202."""
import json, sys
from http.server import BaseHTTPRequestHandler, HTTPServer

class Intake(BaseHTTPRequestHandler):
    def do_POST(self):
        job = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        print(self.path, self.headers.get("Authorization"), job["template"], job["printer"],
              json.dumps(job["data"]), flush=True)
        body = json.dumps({"id": "run-1", "duplicate": False}).encode()
        self.send_response(202)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass

HTTPServer(("0.0.0.0", int(sys.argv[1])), Intake).serve_forever()
```

**Step 1: Add the webhook.** On the desktop as the admin, open **Settings**: below *Web address* are *Printing*, *Webhooks* and *API keys* (Mel has no Settings at all). Add a webhook "Local receiver", address `http://host.docker.internal:9461/lms-events`, *Everything, and whatever is added later*. Its secret shows once: copy it, and start the receiver with it: `cd /tmp/lms-links && SECRET='whsec_…' python3 receiver.py 9461`. **Done**: the secret has gone, and the webhook is listed with "Everything". Close Settings with Escape: back to the classroom.

**Step 2: Granted and person.updated.** As Mel, add **Forklift licence** (a ticket), **Site induction** (a module, refresher 24 months), a role **Forklift operator** requiring both, and Kim (`LL042`, PIN `2468`, the role). Within a few seconds the receiver prints `signed person.updated` with Kim's code, name, roles and `"active": true`. On the matrix, record Kim's forklift licence completed 1 Jan 2025, good until 11 Nov 2026: `signed competency.granted … "status": "expiring" … "expires_on": "2026-11-11" … "recorded_by": {"code": "MG001", …}`. To see a wrong signature refused: stop the receiver, start it with `SECRET=wrong`, and change Kim's name: it prints `BAD SIGNATURE person.updated …` and answers `503`; start it again with the right secret, and a minute later the same event arrives, `signed` and `(seen before)`.

**Step 3: A refusal, tried again.** `touch /tmp/lms-links/FAIL`, then revoke Kim's licence with a note: the receiver prints `competency.revoked` and answers `503`. In Settings the webhook shows "1 waiting"; its drawer lists the delivery as Waiting, "After 1 try: HTTP 503: ". `rm /tmp/lms-links/FAIL`: a minute later the receiver prints it again with `(seen before)`, the same `event_id`, and the drawer says Sent. For a delivery that has failed for good (`docker compose exec -T db psql -U lms -d lms -c "update outbox set status = 'failed' where kind = 'webhook' and id = (select max(id) from outbox where kind = 'webhook')"` stands in for two hours of refusals), **Send again** sends it once more, the same event.

**Step 4: Expiring and lapsed, each once.** Record the licence again (1 Jan 2025, good until 11 Nov 2026). `docker compose exec worker lms daily-job --on 2026-10-15` says `… and 1 events queued`, and the receiver prints `competency.expiring … "days_left": 27`; run it again: `0 events`. `docker compose exec worker lms daily-job --on 2026-11-12`: `competency.lapsed`, once. Kim's site induction is missing, not expiring, so nothing is said of it.

**Step 5: An API key.** In Settings, *API keys*, make a key for "Simple TMS" (*Read who is current* ticked): it shows once as `lms_k.…`; the list keeps its first ten characters. Then:
```
curl -s http://127.0.0.1:8033/v1/people/LL042/competencies/forklift-licence -H "Authorization: Bearer lms_k.…"
curl -s http://127.0.0.1:8033/v1/people -H "Authorization: Bearer lms_k.…"
```
The first answers `"status":"expiring","expires_on":"2026-11-11"` with Kim's code, name and `"active":true`; the second `{"detail":"an API key opens the competency API only","code":"key_not_allowed"}`. The key's "Last used" is today. **Revoke** asks "Revoke Simple TMS's key? Anything using it stops working, for good."; **Revoke it**, and the first `curl` is now `401`.

**Step 6: Printing.** As Mel, open Kim's forklift licence on the matrix: **Print certificate** is on the completion that counts, and nowhere else; pressing it says "Printing is not set up: give Platen's address in Settings, under Printing.". Start the stand-in (`cd /tmp/lms-links && python3 fake_platen.py 9462`). As the admin, in Settings, *Printing*: Platen's address `http://host.docker.internal:9462/intake/jobs`, the key `platen-test-key`, **Save**: "A key is set. Leave this empty to keep it.", and the key field is empty again. Within a few seconds (no restart), Mel's **Print certificate** says "Sent to Platen, for the printer office.", and the stand-in prints `/intake/jobs Bearer platen-test-key lms-certificate office` and the data: Kim Lee, Forklift licence, "Ticket or licence", completed "1 Jan 2025", good until "11 Nov 2026". Under **People**, Kim's drawer: **Print skills card** sends `lms-skills-card` with a line for the licence. Change *Skills cards print on* to `cards` and print again: the stand-in shows `cards`. Against a real Platen, make page templates with the ids `lms-certificate` and `lms-skills-card` and publish them, or Platen refuses the job: the worker logs `Platen answered 422: template: Platen has no template 'lms-certificate'; …` and tries again after a minute.

**Step 7: Tidy up.** Turn the webhook off in its drawer (anything still waiting for it is given up on), stop the two stand-ins, and in Settings put Platen's address back to `.env` or the default if this machine has no Platen.
