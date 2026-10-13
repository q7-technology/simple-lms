# Simple LMS step 2: Policies and tickets — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build step 2 of `docs/plans/2026-10-12-simple-lms-design.md`: policies signed in the learner app (read it, then a typed name and a finger signature, again for each new version), tickets and licences sent in from the learner app (photos of the front and back, type, number, expiry) and checked in the desktop's **Inbox** by a manager who is not the learner, expiry from the card's date, and the worker: an outbox drained with backoff, email over SMTP, and a daily job that sends reminders at 30, 14 and 0 days and a Monday digest to managers. Usable end to end: a manager publishes a policy version and a learner signs it on a tablet; the learner sends in their forklift licence, a manager approves it in the Inbox and the matrix goes green; the next morning the learner is emailed that it has 30 days left.

**Architecture:** The same FastAPI app (`api/`, package `lms`). Migration `0002` adds `upload`, `policy_version`, `ticket_submission` and `outbox`, a `card_expires` flag on `competency`, and on `competency_record` the policy version a grant is for, the signed name, the signature and the ticket it came from. `policy_version` is append-only through the existing `block_change()` trigger; `ticket_submission` gets a `decide_once()` trigger that lets a pending ticket be approved or rejected once and refuses every other change and every delete. Status still comes only from `lms/services/status.py`, which learns that a policy counts only for its newest version. Files are sent as the raw request body (no multipart), checked by their first bytes, kept under `LMS_UPLOAD_DIR` by a random id, and served only to whoever may see their owner. A new `lms/worker.py` (as in Simple TMS) drains the outbox with backoff 1 min, 5, 30, 2 h and runs `lms/services/daily.py` each morning; each email has a unique key, so nothing is queued twice. Compose gains the `worker` and an `uploads` volume; Caddy lets both apps show `blob:` images.

**Tech Stack:** as step 1: Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, psycopg 3, pytest against a real PostgreSQL 16; Vite 6, React 19, TypeScript 5, Tailwind 4, Vitest 3 with Testing Library; Docker Compose, Caddy 2, GitHub Actions. Email is the standard library's `smtplib`: no new dependencies.

---

## Context

The design is settled; this plan does not change any of its decisions. The decisions in the step 1 plan's Context still hold (ports, sessions, scopes, the latest row counts, `expires_on` is the last good day, today in `LMS_TIMEZONE`, and the rest). The code on `main` is the truth where it went further than the step 1 plan (`errors.commit_unique`, `409 has_team` and `self` on people, `403 own_override`, the person's row locked while a record is granted or revoked, the learner app's sessions shared across tabs, the desktop drawer's focus trap and row buttons).

### Patterns copied from Simple TMS

Paths relative to `/Users/leightonlauton/Q7 Technology/Software/q7/simple-tms/`, from the code as shipped:

- **The worker:** `api/tms/worker.py`: `BACKOFF = (60, 300, 1800, 7200)`, `retry_later()` (the try after the 2 h wait is the last, then `failed`), `_claim()` with `with_for_update(skip_locked=True)` one row per transaction, the answer's time taken after the call, `wait_for_schema()`, a loop that logs and carries on. Compose runs it as `python -m tms.worker` from the API's image.
- **Queued rows:** `api/tms/models/integration.py` (`OutboundCall`, `PrintJob`): `status`, `attempts`, `next_attempt_at`, `last_error`, an `ix_…_due` index on `(status, next_attempt_at)`.
- **Files:** `api/tms/services/pod_files.py` and `api/tms/api/routes/pod_files.py`: kinds with allowed types and a size each, `sniff()` by magic bytes, `_write()` to a temporary file then `os.replace`, a `Refused` error for `413 too_large` and `415 unsupported_type`, the body read only after the caller is checked and no further than the largest file, and the file served with `Cache-Control: private, no-store`, `Content-Security-Policy: default-src 'none'; sandbox`, `Content-Disposition: inline; filename="<id>.<ext>"` and `nosniff`; a row whose file is missing from disk is a `404` with a warning in the log. Tests point the folder at `tmp_path` with an autouse fixture.
- **Pictures on the phone:** `apps/driver/src/lib/picture.ts` (`shrinkPhoto` to a 1600 px JPEG, `toBlob`) and `apps/driver/src/ui/pictures.tsx` (`PhotoPicker`, `SignaturePad` with pointer events, a device-pixel-ratio canvas and an `aria-label` that says whether it holds a signature).
- **Pictures on the desktop:** `apps/desktop/src/ui/Photo.tsx`: an `<img>` can't send the token, so the bytes are fetched with it and shown from a `blob:` URL; Caddy's CSP has `img-src 'self' blob:`.

### Decisions this plan makes that the design leaves open

- **A ticket type is a competency of kind `ticket`** (e.g. `forklift-licence`), as in step 1. The design's "ticket type and whether it expires" is a new `competency.card_expires` flag (true by default): when true the learner types the card's date and it must be after today; when false the date is left out and only a refresher, if any, makes it run out.
- **A ticket sent in** is a `ticket_submission`: the number, the card's last good day, a photo (or PDF) of the front and optionally the back. One waits at a time for a person and a ticket (a partial unique index, and a `409 already_waiting`). It is **decided once**: a trigger lets `pending` become `approved` or `rejected` (with a reason) and refuses any other change and every delete, so the check is as permanent as the record.
- **Approving a ticket is a grant:** a new `competency_record` from the day it is approved (`granted_on` = today) to the card's date (`expires_on`), recorded by the manager who approved it, with the note `Ticket <number>, checked` and `ticket_submission_id` pointing at what they checked. Nobody approves or rejects their own, admins included (`403 own_ticket`, rule 3). A card that ran out while it waited can't be approved (`409 card_ran_out`): send it back. The person's row is locked first, as for a grant by hand, so two managers approving at once make one record.
- **Policy versions** belong to a competency of kind `policy`: `policy_version` rows numbered 1, 2, 3 …, the text only (a PDF policy can wait for step 3's uploads), with an optional note of what changed. Append-only: what someone signed never changes under them. The newest is the one to sign. Publishing locks the competency's row so two at once get consecutive numbers.
- **Status for a policy** (rule 2, still only in `status.py`): with a version published, a grant counts only if it is for the newest version; otherwise it is `missing`. A grant from before there were versions, or for an older one, needs a new signature. `standing.load` loads each policy's newest version id in one more query.
- **A signature** is the person's own act, like a module pass: it says they have read the policy, so it is recorded as theirs (`recorded_by` is the signer) and rule 3 is untouched. It is a `competency_record` with `policy_version_id`, the `signed_name` they typed (it must be their name as Simple LMS has it, case and spacing aside) and `signature_upload_id`, the PNG drawn with a finger, sent first as an upload. They sign the version they read: if a newer one came out meanwhile it is `409 new_version`, and the learner app shows the new text. Once per version (`409 already_signed`). A policy **signed on paper** and recorded by hand on the desktop counts for the newest version.
- **Scopes:** `training:write` (do your own training: send a file, sign a policy, send in a ticket) for every permission and for **PIN sessions**, which still reach nothing of anyone else's; `tickets:verify` for managers (admins have `*`). Reading a policy to sign is `training:read`; publishing a version is `competencies:write`.
- **Uploads:** `POST /v1/uploads?purpose=ticket|signature` with the file as the body, so no multipart dependency, as Simple TMS does it. A ticket may be a JPEG, PNG or PDF up to 20 MB (the design's limit for anything that is not a video); a signature a PNG up to 1 MB. Named by a `uuid4` under `LMS_UPLOAD_DIR` (`/data/uploads`, a Compose volume). `GET /v1/uploads/{id}` serves it to whoever `sees` its owner (themselves, their supervisor, managers and admins); anyone else gets a `404`. A ticket or signature may only name the caller's own uploads of the right purpose. The learner app makes a photo a 1600 px JPEG on the phone first (dropping its EXIF, location included) and sends a PDF as it is.
- **The outbox** is one table for everything the worker sends; step 2 only has `email`. Each row has a unique `key`, so queuing is `insert … on conflict do nothing`: a reminder is `reminder:<person id>:<competency id>:<last good day>:<days>` and a digest `digest:<manager id>:<date>`. That is all the "each once" bookkeeping reminders need; `event_seen` and the events themselves wait for step 6.
- **Reminders** go to active people with an email for what they are asked for and is `expiring`, counted in days to the last good day: 30, 14 and 0 (the day itself). A day the worker missed still gets the reminder it owed (9 days left sends the 14-day one, once). A renewal has a new last good day, so its reminders start afresh. Lapsed items are not emailed to the learner again: they are in their supervisor's and managers' view and in the digest.
- **The Monday digest** goes to each active manager and admin with an email: everyone's lapsed items, then everyone's expiring ones, soonest first. Nothing due, no digest.
- **The daily job's clock:** it runs once a day from `LMS_DAILY_HOUR` (6 by default) in `LMS_TIMEZONE`, and again whenever the worker starts after that hour (the keys make that harmless). Monday is Monday in that zone. `lms daily-job [--on YYYY-MM-DD]` queues them now, for an operator who wants to, and for the walkthrough.
- **SMTP** comes from `.env` (`LMS_SMTP_HOST`, `_PORT`, `_USER`, `_PASSWORD`, `_FROM`, `_SECURITY` = `starttls`, `ssl` or `none`) and `LMS_PUBLIC_URL` for the links. Without a host and a from address emails wait in the outbox, untried, as Simple TMS's ship calls wait for Simple WMS. The design's Settings screen (with SMTP and reminder days on it) comes with the sign-in switches in step 5; until then the days are 30, 14 and 0.
- **Testing email without a server:** a `mailbox` fixture replaces `mail.connect` with an in-memory server that keeps what was sent and can be told to fail; one test checks `connect` itself chooses `SMTP`, `SMTP_SSL` and `starttls` as told. The manual walkthrough uses Mailpit in a container.
- **Learner app:** My training's items gain their next step: **Read and sign** on a policy that is not current, **Add your ticket** on a ticket that is missing, expiring or lapsed, or "Sent in · waiting for a manager's check" while one waits (the training list gains `waiting` and `card_expires`). Signing opens `/learn/sign/<key>`, a ticket `/learn/ticket/<key>`, which also says why the last one was sent back.
- **Desktop:** an **Inbox** tab for those with `tickets:verify` (photos fetched with the token, a PDF offered to save, approve, or reject with a reason they see); a policy's drawer on **Competencies** lists its versions and publishes the next; a ticket's drawer has the card-expiry switch; the history drawer shows "Signed version 2 as “Kim Lee”" with the signature.

---

## Before you start

```
cd "/Users/leightonlauton/Q7 Technology/Software/q7/simple-lms"
git switch main && git pull --ff-only
git switch -c step-2-policies-and-tickets
docker compose up -d db
(cd api && uv pip install -e ".[dev]")
(cd apps/desktop && npm ci)
(cd apps/learner && npm ci)
```

As in step 1: `pytest` runs from `api/` against the compose `db` on 127.0.0.1:5435 (`TEST_DATABASE_URL` points it elsewhere), and `npm` commands run from the app's folder. There are no new Python or npm dependencies. Every test still runs on 12 October 2026, a Monday.

---

### Task 1: Scopes for your own training and for checking tickets, and step 2's settings

**Files:**
- Modify: `api/lms/config.py` (in full below)
- Modify: `api/lms/services/sessions.py`
- Test: `api/tests/test_config.py`, `api/tests/test_sessions.py`, `api/tests/test_auth.py`

**Step 1: Write the failing tests**

Append to `api/tests/test_config.py`:
```python
def test_email_waits_until_there_is_a_host():
    s = Settings()
    assert (s.smtp_host, s.smtp_port, s.smtp_security) == ("", 587, "starttls")


def test_smtp_security_is_one_of_three():
    with pytest.raises(ValidationError):
        Settings(smtp_security="tls")
    assert Settings(smtp_security="ssl").smtp_security == "ssl"


def test_the_daily_job_runs_from_an_hour_of_the_day():
    assert Settings().daily_hour == 6
    with pytest.raises(ValidationError):
        Settings(daily_hour=24)


def test_the_public_url_loses_its_trailing_slash():
    assert Settings(public_url="https://lms.example.com.au/").public_url == "https://lms.example.com.au"
```

In `api/tests/test_sessions.py`, replace:
```python
def test_a_pin_session_only_reads_training_whoever_has_it():
    assert sessions.scopes_for("admin", "pin") == ["training:read"]
    assert sessions.scopes_for("admin", "password") == ["*"]
    assert sessions.scopes_for("learner", "password") == ["training:read"]
```
with:
```python
def test_a_pin_session_only_does_its_own_training_whoever_has_it():
    assert sessions.scopes_for("admin", "pin") == ["training:read", "training:write"]
    assert sessions.scopes_for("admin", "password") == ["*"]
    assert sessions.scopes_for("learner", "password") == ["training:read", "training:write"]
```

In `api/tests/test_auth.py`, replace:
```python
    assert (me["code"], me["method"], me["scopes"]) == ("LL042", "pin", ["training:read"])
```
with:
```python
    assert (me["code"], me["method"], me["scopes"]) == ("LL042", "pin", ["training:read", "training:write"])
```

In `api/tests/test_auth.py`, replace:
```python
def test_a_supervisor_signed_in_by_pin_only_reads_training(client, supervisor):
    by_pin = pin_login(client, supervisor.code)["person"]
    assert (by_pin["permission"], by_pin["scopes"]) == ("supervisor", ["training:read"])
```
with:
```python
def test_a_supervisor_signed_in_by_pin_only_does_their_own_training(client, supervisor):
    by_pin = pin_login(client, supervisor.code)["person"]
    assert (by_pin["permission"], by_pin["scopes"]) == ("supervisor", ["training:read", "training:write"])
```

**Step 2: Run them to see them fail**

Run: `cd api && .venv/bin/pytest tests/test_config.py tests/test_sessions.py tests/test_auth.py -q`
Expected: FAIL: `AttributeError: 'Settings' object has no attribute 'smtp_host'`, and the scope lists without `training:write`.

**Step 3: Minimal implementation**

`api/lms/config.py`:
```python
from functools import lru_cache
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LMS_", extra="ignore")

    database_url: str = "postgresql+psycopg://lms:lms@127.0.0.1:5432/lms"
    # Whose "today" decides what is current, expiring or lapsed, and when the
    # daily job runs.
    timezone: str = "Australia/Melbourne"

    # Tickets' photos and policy signatures: kept on disk (a volume in
    # Compose), named by a random id. Only the API reads and writes them.
    upload_dir: str = "/data/uploads"

    # Where people open Simple LMS, for the links in emails, e.g.
    # https://lms.example.com.au. Without it the emails carry no link.
    public_url: str = ""

    # Email, sent by the worker. Without a host the emails wait, unsent,
    # until one is set.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    # starttls (port 587), ssl (port 465) or none (a relay on the same network)
    smtp_security: Literal["starttls", "ssl", "none"] = "starttls"

    # The worker: how long it waits when there is nothing to send, and the
    # hour (in LMS_TIMEZONE) from which it runs the daily job each day.
    worker_poll_seconds: float = 5.0
    daily_hour: int = Field(default=6, ge=0, le=23)

    @field_validator("timezone")
    @classmethod
    def _known_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(f"LMS_TIMEZONE {value!r} is not a time zone, e.g. Australia/Melbourne")
        return value

    @field_validator("public_url")
    @classmethod
    def _no_trailing_slash(cls, value: str) -> str:
        return value.strip().rstrip("/")


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

In `api/lms/services/sessions.py`, replace:
```python
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
```
with:
```python
# What each permission level may do (the design's table). Admin-only areas
# (users, sign-in settings, webhooks, API keys) arrive with their steps.
# training:write is doing your own training: signing a policy, adding a
# ticket. tickets:verify is checking someone else's ticket.
SCOPES: dict[str, list[str]] = {
    "learner": ["training:read", "training:write"],
    "supervisor": ["training:read", "training:write", "matrix:read", "roles:read",
                   "competencies:read"],
    "manager": ["training:read", "training:write", "matrix:read", "roles:read",
                "competencies:read", "people:read", "people:write", "roles:write",
                "competencies:write", "records:write", "tickets:verify"],
    "admin": ["*"],
}
# A PIN is short, so a PIN session is for the learner app's own training,
# whoever signs in with it: seeing it, signing a policy, adding a ticket.
PIN_SCOPES = ["training:read", "training:write"]
```

**Step 4: Run them to see them pass**

Run: `cd api && .venv/bin/pytest tests/test_config.py tests/test_sessions.py tests/test_auth.py -q`
Expected: `34 passed`.

**Step 5: Commit**

```
git add api/lms/config.py api/lms/services/sessions.py api/tests/test_config.py api/tests/test_sessions.py api/tests/test_auth.py
git commit -m "Let everyone do their own training and a manager check tickets, and add step 2's settings" \
  -m "A PIN session can sign a policy and send in a ticket, and still reaches nobody else's training. Uploads, email and the worker's settings come from .env."
```

---

### Task 2: Uploads, policy versions, ticket submissions and the outbox, append-only or decided once

**Files:**
- Modify: `api/lms/models/catalogue.py`
- Create: `api/lms/models/evidence.py`, `api/lms/models/outbox.py`
- Modify: `api/lms/models/records.py`, `api/lms/models/__init__.py` (both in full below)
- Create: `api/alembic/versions/0002_policies_and_tickets.py`
- Test: `api/tests/test_migrations.py`, `api/tests/test_append_only.py` (in full below)

**Step 1: Write the failing tests**

In `api/tests/test_migrations.py`, replace:
```python
TABLES = {"person", "session", "role", "person_role", "competency", "role_requirement",
          "person_override", "competency_record", "alembic_version"}
```
with:
```python
TABLES = {"person", "session", "role", "person_role", "competency", "role_requirement",
          "person_override", "competency_record", "upload", "policy_version",
          "ticket_submission", "outbox", "alembic_version"}
TRIGGERS = {"competency_record_append_only", "person_override_append_only",
            "policy_version_append_only", "ticket_submission_decide_once"}
```

In `api/tests/test_migrations.py`, replace:
```python
    assert triggers == {"competency_record_append_only", "person_override_append_only"}
```
with:
```python
    assert triggers == TRIGGERS
```

`api/tests/test_append_only.py`:
```python
"""The training record, the overrides and the policy versions are
append-only, and a ticket is decided once, and the database says so (rule 1)."""
import uuid
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.exc import DBAPIError, IntegrityError

from lms.models import (
    Competency, CompetencyRecord, Person, PersonOverride, PolicyVersion, TicketSubmission, Upload,
)


@pytest.fixture
def setting(db):
    boss = Person(code="MG001", name="Mel Grant", permission="manager")
    kim = Person(code="LL042", name="Kim Lee")
    forklift = Competency(key="forklift-licence", name="Forklift licence", kind="ticket")
    whs = Competency(key="whs-policy", name="WHS policy", kind="policy")
    db.add_all([boss, kim, forklift, whs])
    db.flush()
    db.add(CompetencyRecord(person_id=kim.id, competency_id=forklift.id, kind="granted",
                            granted_on=date(2026, 3, 1), expires_on=date(2031, 3, 1),
                            recorded_by_id=boss.id))
    db.add(PersonOverride(person_id=kim.id, competency_id=forklift.id, kind="extra",
                          note="drives the yard forklift on Saturdays", recorded_by_id=boss.id))
    db.add(PolicyVersion(competency_id=whs.id, version=1, body="Wear your PPE.",
                         published_by_id=boss.id))
    db.commit()
    return boss, kim, forklift


@pytest.mark.parametrize("model", [CompetencyRecord, PersonOverride, PolicyVersion])
def test_rows_cannot_be_updated(db, setting, model):
    with pytest.raises(DBAPIError, match="append-only"):
        db.execute(update(model).values(note="changed afterwards"))
        db.commit()


@pytest.mark.parametrize("model", [CompetencyRecord, PersonOverride, PolicyVersion])
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


@pytest.fixture
def waiting(db, setting):
    boss, kim, forklift = setting
    front = Upload(id=uuid.uuid4(), person_id=kim.id, purpose="ticket", content_type="image/jpeg",
                   size_bytes=3, sha256="0" * 64, path="ab/front.jpg")
    db.add(front)
    db.flush()
    ticket = TicketSubmission(person_id=kim.id, competency_id=forklift.id, number="LF0012345",
                              expires_on=date(2031, 3, 1), front_upload_id=front.id,
                              status="pending")
    db.add(ticket)
    db.commit()
    return boss, ticket


def test_a_ticket_is_decided_once(db, waiting):
    boss, ticket = waiting
    db.execute(update(TicketSubmission).values(status="approved", decided_by_id=boss.id,
                                               decided_at=datetime.now(UTC)))
    db.commit()
    with pytest.raises(DBAPIError, match="decided once"):
        db.execute(update(TicketSubmission).values(status="rejected", reason="changed my mind"))
        db.commit()


def test_a_ticket_cannot_be_changed_while_it_waits(db, waiting):
    with pytest.raises(DBAPIError, match="decided once"):
        db.execute(update(TicketSubmission).values(number="LF0099999"))
        db.commit()


def test_a_ticket_is_never_deleted(db, waiting):
    with pytest.raises(DBAPIError, match="cannot be deleted"):
        db.execute(delete(TicketSubmission))
        db.commit()
```

**Step 2: Run them to see them fail**

Run: `cd api && .venv/bin/pytest tests/test_migrations.py tests/test_append_only.py -q`
Expected: FAIL: `ImportError: cannot import name 'PolicyVersion' from 'lms.models'`, and the tables missing from a fresh database.

**Step 3: Minimal implementation**

In `api/lms/models/catalogue.py`, replace:
```python
from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, String
```
with:
```python
from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, String, true
```

In `api/lms/models/catalogue.py`, replace:
```python
    refresher_months: Mapped[int | None] = mapped_column(Integer)
    active
```
with:
```python
    refresher_months: Mapped[int | None] = mapped_column(Integer)
    # a ticket: whether its card has an expiry date to type in (a forklift
    # licence does; some cards never run out). Other kinds leave it be.
    card_expires: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    active
```

`api/lms/models/evidence.py`:
```python
from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint,
    Uuid, text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from lms.models.base import Base, created_at_column
from lms.models.catalogue import Competency
from lms.models.people import Person


class Upload(Base):
    """A file someone sent: a ticket's photo or PDF, or a policy signature.
    Kept on disk under LMS_UPLOAD_DIR, named by its random id; served only
    through the API to people who may see it."""

    __tablename__ = "upload"
    __table_args__ = (CheckConstraint("purpose in ('ticket', 'signature')", name="purpose"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    # whose it is: the person who sent it
    person_id: Mapped[int] = mapped_column(ForeignKey("person.id"), index=True)
    purpose: Mapped[str] = mapped_column(String(16))
    # worked out from its first bytes, never from what the request said
    content_type: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    # under LMS_UPLOAD_DIR, e.g. 3f/3f2a….jpg
    path: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = created_at_column()


class PolicyVersion(Base):
    """One version of a policy's text. Append-only: what someone signed never
    changes under them. The newest version is the one to sign."""

    __tablename__ = "policy_version"
    __table_args__ = (
        UniqueConstraint("competency_id", "version"),
        CheckConstraint("version >= 1", name="version"),
        CheckConstraint("length(trim(body)) > 0", name="body"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    competency_id: Mapped[int] = mapped_column(ForeignKey("competency.id"), index=True)
    # 1, 2, 3 … for each policy
    version: Mapped[int] = mapped_column(Integer)
    body: Mapped[str] = mapped_column(Text)
    # what changed, for the people asked to sign again
    note: Mapped[str | None] = mapped_column(String(500))
    published_by_id: Mapped[int] = mapped_column(ForeignKey("person.id"))
    created_at: Mapped[datetime] = created_at_column()

    competency: Mapped[Competency] = relationship()
    published_by: Mapped[Person] = relationship()


class TicketSubmission(Base):
    """A ticket or licence a person sent in, waiting for a manager's check.
    Decided once: a trigger lets a pending ticket be approved or rejected and
    refuses every other change, and every delete."""

    __tablename__ = "ticket_submission"
    __table_args__ = (
        CheckConstraint("status in ('pending', 'approved', 'rejected')", name="status"),
        CheckConstraint("status <> 'rejected' or length(trim(reason)) > 0", name="reason"),
        CheckConstraint("(status = 'pending') = (decided_by_id is null)", name="decided"),
        CheckConstraint("length(trim(number)) > 0", name="number"),
        # one waiting at a time for a person and a ticket
        Index("uq_ticket_submission_waiting", "person_id", "competency_id", unique=True,
              postgresql_where=text("status = 'pending'")),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("person.id"), index=True)
    competency_id: Mapped[int] = mapped_column(ForeignKey("competency.id"), index=True)
    # the number on the card
    number: Mapped[str] = mapped_column(String(64))
    # the card's last good day; none for a card that never runs out
    expires_on: Mapped[date | None] = mapped_column(Date)
    front_upload_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("upload.id"))
    back_upload_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("upload.id"))
    # pending, approved, rejected
    status: Mapped[str] = mapped_column(String(16), default="pending")
    reason: Mapped[str | None] = mapped_column(String(500))
    decided_by_id: Mapped[int | None] = mapped_column(ForeignKey("person.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_column()

    person: Mapped[Person] = relationship(foreign_keys=[person_id])
    competency: Mapped[Competency] = relationship()
    decided_by: Mapped[Person | None] = relationship(foreign_keys=[decided_by_id])
```

`api/lms/models/outbox.py`:
```python
from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from lms.models.base import Base, created_at_column


class Outbox(Base):
    """The queue the worker drains: today, emails. A failed try is tried
    again after 1 min, 5, 30 and 2 h. `key` is unique, so something queued
    twice (a reminder the daily job finds again) is queued once."""

    __tablename__ = "outbox"
    __table_args__ = (
        CheckConstraint("kind in ('email')", name="kind"),
        CheckConstraint("status in ('pending', 'done', 'failed')", name="status"),
        Index("ix_outbox_due", "status", "next_attempt_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))
    # e.g. reminder:4:2:2026-11-11:30 or digest:2:2026-10-12
    key: Mapped[str] = mapped_column(String(200), unique=True)
    # an email: {"to", "subject", "text"}
    payload: Mapped[dict] = mapped_column(JSONB)
    # pending, done, failed
    status: Mapped[str] = mapped_column(String(16), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(500))
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_column()
```

`api/lms/models/records.py`:
```python
from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from lms.models.base import Base, created_at_column
from lms.models.catalogue import Competency
from lms.models.evidence import PolicyVersion
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
        CheckConstraint("signature_upload_id is null or "
                        "(policy_version_id is not null and signed_name is not null)",
                        name="signature"),
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
    # a policy: the version this grant is for (signed in the learner app, or
    # on paper and recorded by hand). A newer version needs a new grant.
    policy_version_id: Mapped[int | None] = mapped_column(ForeignKey("policy_version.id"))
    # signed in the learner app: the name they typed and their finger signature
    signed_name: Mapped[str | None] = mapped_column(String(120))
    signature_upload_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("upload.id"))
    # a ticket a manager verified: the submission it came from
    ticket_submission_id: Mapped[int | None] = mapped_column(ForeignKey("ticket_submission.id"),
                                                             unique=True)
    created_at: Mapped[datetime] = created_at_column()

    competency: Mapped[Competency] = relationship()
    recorded_by: Mapped[Person] = relationship(foreign_keys=[recorded_by_id])
    policy_version: Mapped[PolicyVersion | None] = relationship()
```

`api/lms/models/__init__.py`:
```python
from lms.models.base import Base
from lms.models.people import PERMISSIONS, Person, Session
from lms.models.catalogue import KINDS, Competency, PersonRole, Role, RoleRequirement
from lms.models.evidence import PolicyVersion, TicketSubmission, Upload
from lms.models.records import CompetencyRecord, PersonOverride
from lms.models.outbox import Outbox

__all__ = [
    "Base", "PERMISSIONS", "KINDS", "Person", "Session", "Role", "PersonRole", "Competency",
    "RoleRequirement", "PersonOverride", "CompetencyRecord", "Upload", "PolicyVersion",
    "TicketSubmission", "Outbox",
]
```

`api/alembic/versions/0002_policies_and_tickets.py`:
```python
"""policies and tickets: uploads, policy versions, ticket submissions, the outbox

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-13
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _created_at() -> sa.Column:
    return sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
                     nullable=False)


def upgrade() -> None:
    op.add_column("competency", sa.Column("card_expires", sa.Boolean(), nullable=False,
                                          server_default=sa.true()))

    op.create_table(
        "upload",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Integer(), nullable=False),
        sa.Column("purpose", sa.String(length=16), nullable=False),
        sa.Column("content_type", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("path", sa.String(length=200), nullable=False),
        _created_at(),
        sa.CheckConstraint("purpose in ('ticket', 'signature')", name=op.f("ck_upload_purpose")),
        sa.ForeignKeyConstraint(["person_id"], ["person.id"], name=op.f("fk_upload_person_id_person")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_upload")),
    )
    op.create_index(op.f("ix_upload_person_id"), "upload", ["person_id"])

    op.create_table(
        "policy_version",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("competency_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("published_by_id", sa.Integer(), nullable=False),
        _created_at(),
        sa.CheckConstraint("version >= 1", name=op.f("ck_policy_version_version")),
        sa.CheckConstraint("length(trim(body)) > 0", name=op.f("ck_policy_version_body")),
        sa.ForeignKeyConstraint(["competency_id"], ["competency.id"],
                                name=op.f("fk_policy_version_competency_id_competency")),
        sa.ForeignKeyConstraint(["published_by_id"], ["person.id"],
                                name=op.f("fk_policy_version_published_by_id_person")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_policy_version")),
        sa.UniqueConstraint("competency_id", "version",
                            name=op.f("uq_policy_version_competency_id_version")),
    )
    op.create_index(op.f("ix_policy_version_competency_id"), "policy_version", ["competency_id"])

    op.create_table(
        "ticket_submission",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("person_id", sa.Integer(), nullable=False),
        sa.Column("competency_id", sa.Integer(), nullable=False),
        sa.Column("number", sa.String(length=64), nullable=False),
        sa.Column("expires_on", sa.Date(), nullable=True),
        sa.Column("front_upload_id", sa.Uuid(), nullable=False),
        sa.Column("back_upload_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("decided_by_id", sa.Integer(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        _created_at(),
        sa.CheckConstraint("status in ('pending', 'approved', 'rejected')",
                           name=op.f("ck_ticket_submission_status")),
        sa.CheckConstraint("status <> 'rejected' or length(trim(reason)) > 0",
                           name=op.f("ck_ticket_submission_reason")),
        sa.CheckConstraint("(status = 'pending') = (decided_by_id is null)",
                           name=op.f("ck_ticket_submission_decided")),
        sa.CheckConstraint("length(trim(number)) > 0", name=op.f("ck_ticket_submission_number")),
        sa.ForeignKeyConstraint(["person_id"], ["person.id"],
                                name=op.f("fk_ticket_submission_person_id_person")),
        sa.ForeignKeyConstraint(["competency_id"], ["competency.id"],
                                name=op.f("fk_ticket_submission_competency_id_competency")),
        sa.ForeignKeyConstraint(["front_upload_id"], ["upload.id"],
                                name=op.f("fk_ticket_submission_front_upload_id_upload")),
        sa.ForeignKeyConstraint(["back_upload_id"], ["upload.id"],
                                name=op.f("fk_ticket_submission_back_upload_id_upload")),
        sa.ForeignKeyConstraint(["decided_by_id"], ["person.id"],
                                name=op.f("fk_ticket_submission_decided_by_id_person")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ticket_submission")),
    )
    op.create_index(op.f("ix_ticket_submission_person_id"), "ticket_submission", ["person_id"])
    op.create_index(op.f("ix_ticket_submission_competency_id"), "ticket_submission",
                    ["competency_id"])
    op.create_index("uq_ticket_submission_waiting", "ticket_submission",
                    ["person_id", "competency_id"], unique=True,
                    postgresql_where=sa.text("status = 'pending'"))

    op.add_column("competency_record", sa.Column("policy_version_id", sa.Integer(), nullable=True))
    op.add_column("competency_record", sa.Column("signed_name", sa.String(length=120),
                                                 nullable=True))
    op.add_column("competency_record", sa.Column("signature_upload_id", sa.Uuid(), nullable=True))
    op.add_column("competency_record", sa.Column("ticket_submission_id", sa.Integer(),
                                                 nullable=True))
    op.create_foreign_key(op.f("fk_competency_record_policy_version_id_policy_version"),
                          "competency_record", "policy_version", ["policy_version_id"], ["id"])
    op.create_foreign_key(op.f("fk_competency_record_signature_upload_id_upload"),
                          "competency_record", "upload", ["signature_upload_id"], ["id"])
    op.create_foreign_key(op.f("fk_competency_record_ticket_submission_id_ticket_submission"),
                          "competency_record", "ticket_submission", ["ticket_submission_id"],
                          ["id"])
    op.create_unique_constraint(op.f("uq_competency_record_ticket_submission_id"),
                                "competency_record", ["ticket_submission_id"])
    op.create_check_constraint(
        op.f("ck_competency_record_signature"), "competency_record",
        "signature_upload_id is null or (policy_version_id is not null and signed_name is not null)")

    op.create_table(
        "outbox",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("key", sa.String(length=200), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
        _created_at(),
        sa.CheckConstraint("kind in ('email')", name=op.f("ck_outbox_kind")),
        sa.CheckConstraint("status in ('pending', 'done', 'failed')", name=op.f("ck_outbox_status")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_outbox")),
        sa.UniqueConstraint("key", name=op.f("uq_outbox_key")),
    )
    op.create_index("ix_outbox_due", "outbox", ["status", "next_attempt_at"])

    # A policy's text never changes under the people who signed it.
    op.execute("create trigger policy_version_append_only before update or delete "
               "on policy_version for each row execute function block_change()")
    # A ticket is decided once: pending to approved or rejected, and nothing
    # else ever changes. Never deleted.
    op.execute("""
        create or replace function decide_once() returns trigger
        language plpgsql as $$
        begin
            if tg_op = 'DELETE' then
                raise exception '% rows cannot be deleted', tg_table_name
                    using errcode = 'restrict_violation';
            end if;
            if old.status <> 'pending' or new.status = 'pending'
               or (new.id, new.person_id, new.competency_id, new.number, new.expires_on,
                   new.front_upload_id, new.back_upload_id, new.created_at)
                  is distinct from
                  (old.id, old.person_id, old.competency_id, old.number, old.expires_on,
                   old.front_upload_id, old.back_upload_id, old.created_at) then
                raise exception '% is decided once: only a pending ticket is approved or rejected',
                    tg_table_name using errcode = 'restrict_violation';
            end if;
            return new;
        end
        $$
    """)
    op.execute("create trigger ticket_submission_decide_once before update or delete "
               "on ticket_submission for each row execute function decide_once()")


def downgrade() -> None:
    op.execute("drop trigger if exists ticket_submission_decide_once on ticket_submission")
    op.execute("drop function if exists decide_once()")
    op.execute("drop trigger if exists policy_version_append_only on policy_version")
    op.drop_index("ix_outbox_due", table_name="outbox")
    op.drop_table("outbox")
    op.drop_constraint(op.f("ck_competency_record_signature"), "competency_record", type_="check")
    op.drop_constraint(op.f("uq_competency_record_ticket_submission_id"), "competency_record",
                       type_="unique")
    op.drop_constraint(op.f("fk_competency_record_ticket_submission_id_ticket_submission"),
                       "competency_record", type_="foreignkey")
    op.drop_constraint(op.f("fk_competency_record_signature_upload_id_upload"),
                       "competency_record", type_="foreignkey")
    op.drop_constraint(op.f("fk_competency_record_policy_version_id_policy_version"),
                       "competency_record", type_="foreignkey")
    for column in ("ticket_submission_id", "signature_upload_id", "signed_name",
                   "policy_version_id"):
        op.drop_column("competency_record", column)
    op.drop_index("uq_ticket_submission_waiting", table_name="ticket_submission")
    op.drop_index(op.f("ix_ticket_submission_competency_id"), table_name="ticket_submission")
    op.drop_index(op.f("ix_ticket_submission_person_id"), table_name="ticket_submission")
    op.drop_table("ticket_submission")
    op.drop_index(op.f("ix_policy_version_competency_id"), table_name="policy_version")
    op.drop_table("policy_version")
    op.drop_index(op.f("ix_upload_person_id"), table_name="upload")
    op.drop_table("upload")
    op.drop_column("competency", "card_expires")
```

**Step 4: Run them, and the whole suite, to see them pass**

Run: `cd api && .venv/bin/pytest tests/test_migrations.py tests/test_append_only.py -q`
Expected: `13 passed`.

Run: `cd api && .venv/bin/pytest -q`
Expected: `154 passed` (nothing else uses the new tables yet).

**Step 5: Commit**

```
git add api/lms/models api/alembic/versions/0002_policies_and_tickets.py api/tests/test_migrations.py api/tests/test_append_only.py
git commit -m "Add uploads, policy versions, ticket submissions and the outbox" \
  -m "A policy version is append-only, as the record is. A ticket is decided once: a trigger lets a pending one be approved or rejected and refuses any other change, and every delete."
```

---

### Task 3: A new policy version needs a new signature

**Files:**
- Modify: `api/lms/services/status.py`, `api/lms/services/standing.py` (both in full below)
- Test: `api/tests/test_status.py`

**Step 1: Write the failing test**

Append to `api/tests/test_status.py`:
```python
def signed(version: int | None) -> Latest:
    return Latest("granted", D("2026-03-01"), None, version)


@pytest.mark.parametrize("why,latest,current,status", [
    ("no version published yet: any grant counts", signed(None), None, "current"),
    ("signed the version that is current", signed(7), 7, "current"),
    ("signed an older version", signed(3), 7, "missing"),
    ("recorded before there were versions", signed(None), 7, "missing"),
    ("a revoke is still a revoke", REVOKED, 7, "missing"),
])
def test_a_new_policy_version_needs_a_new_signature(why, latest, current, status):
    s = work_out(by_role=True, override=None, latest=latest, refresher_months=None,
                 today=TODAY, current_version=current)
    assert s.status == status, why
```

**Step 2: Run it to see it fail**

Run: `cd api && .venv/bin/pytest tests/test_status.py -q`
Expected: FAIL: `TypeError: Latest.__init__() takes from 2 to 4 positional arguments but 5 were given`.

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
    # a policy: the version it was granted for
    policy_version_id: int | None = None


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
             refresher_months: int | None, today: date,
             current_version: int | None = None) -> Status:
    """Required is roles plus extras, less waivers. `override` is the latest
    override's kind: extra, waive, or None (none, or cleared).
    `current_version` is a policy's newest version: a grant for any other
    version (or for none) is not a signature of what the policy says now."""
    if not (by_role or override == "extra"):
        return Status("not_required")
    if override == "waive":
        return Status("waived")
    if latest is None or latest.kind != "granted" or latest.granted_on is None:
        return Status("missing")
    if current_version is not None and latest.policy_version_id != current_version:
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

`api/lms/services/standing.py`:
```python
"""Where a group of people stand: what each is asked for and their status
for it, loaded in a handful of queries for the matrix and the to-do list."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session as Db

from lms.models import (
    Competency, CompetencyRecord, PersonOverride, PersonRole, PolicyVersion, RoleRequirement,
)
from lms.services.status import Latest, Status, work_out


@dataclass
class Standing:
    today: date
    competencies: dict[int, Competency]  # active ones only
    by_role: set[tuple[int, int]]
    overrides: dict[tuple[int, int], str]
    records: dict[tuple[int, int], CompetencyRecord]
    # each policy's newest version id
    versions: dict[int, int]

    def asked_for(self, person_id: int) -> set[int]:
        """Competencies their roles or an extra ask for, waived or not."""
        keys = {c for (p, c) in self.by_role if p == person_id}
        keys |= {c for (p, c), kind in self.overrides.items() if p == person_id and kind == "extra"}
        return {c for c in keys if c in self.competencies}

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


def latest_rows(db: Db, model, person_ids: list[int]):
    """The newest row per person and competency: the one that counts."""
    newest = (select(func.max(model.id)).where(model.person_id.in_(person_ids))
              .group_by(model.person_id, model.competency_id))
    return db.execute(select(model).where(model.id.in_(newest))).scalars().all()


def load(db: Db, person_ids: list[int], today: date) -> Standing:
    if not person_ids:
        return Standing(today, {}, set(), {}, {}, {})
    competencies = {c.id: c for c in db.execute(
        select(Competency).where(Competency.active.is_(True))).scalars()}
    by_role = {(p, c) for p, c in db.execute(
        select(PersonRole.person_id, RoleRequirement.competency_id)
        .join(RoleRequirement, RoleRequirement.role_id == PersonRole.role_id)
        .where(PersonRole.person_id.in_(person_ids)))}
    overrides = {(o.person_id, o.competency_id): o.kind
                 for o in latest_rows(db, PersonOverride, person_ids)}
    records = {(r.person_id, r.competency_id): r for r in latest_rows(db, CompetencyRecord, person_ids)}
    return Standing(today, competencies, by_role, overrides, records, current_versions(db))


def current_versions(db: Db) -> dict[int, int]:
    """Each policy's newest version: the one to sign."""
    return dict(db.execute(select(PolicyVersion.competency_id, func.max(PolicyVersion.id))
                           .group_by(PolicyVersion.competency_id)).all())
```

**Step 4: Run it, and the matrix, to see them pass**

Run: `cd api && .venv/bin/pytest tests/test_status.py tests/test_matrix.py -q`
Expected: `42 passed`.

**Step 5: Commit**

```
git add api/lms/services/status.py api/lms/services/standing.py api/tests/test_status.py
git commit -m "Count a policy only for its newest version" \
  -m "Worked out in status.py like everything else: a grant for an older version, or from before there were versions, is missing again."
```

---

### Task 4: Files: a ticket's photos and a signature, kept by a random id and shown only to who may see them

**Files:**
- Modify: `api/lms/api/errors.py`, `api/lms/api/app.py`
- Create: `api/lms/services/uploads.py`, `api/lms/api/routes/uploads.py`
- Modify: `api/tests/conftest.py`
- Create: `api/tests/files.py`
- Test: `api/tests/test_uploads.py`

**Step 1: Write the failing test**

In `api/tests/conftest.py`, replace:
```python
@pytest.fixture
def beaten_to_it(engine):
```
with:
```python
@pytest.fixture(autouse=True)
def upload_dir(tmp_path, monkeypatch):
    """Files go to a folder of the test's own, never /data/uploads."""
    from lms.config import get_settings

    folder = tmp_path / "uploads"
    monkeypatch.setattr(get_settings(), "upload_dir", str(folder))
    return folder


@pytest.fixture
def beaten_to_it(engine):
```

`api/tests/files.py`:
```python
"""Small files of each kind, and sending one through the API."""

PNG = b"\x89PNG\r\n\x1a\n" + b"signature" * 20
JPEG = b"\xff\xd8\xff\xe0" + b"photo" * 40
PDF = b"%PDF-1.7\n" + b"card" * 40


def send(client, headers, purpose="ticket", data=JPEG, content_type="image/jpeg"):
    return client.post("/v1/uploads", params={"purpose": purpose}, content=data,
                       headers={**headers, "Content-Type": content_type})


def sent(client, headers, purpose="ticket", data=JPEG, content_type="image/jpeg") -> str:
    """The id of a file just sent."""
    r = send(client, headers, purpose, data, content_type)
    assert r.status_code == 201, r.text
    return r.json()["id"]
```

`api/tests/test_uploads.py`:
```python
"""Tickets' photos and signatures: kept on disk under a random id, checked
for what they are, and shown only to who may see whose they are."""
import hashlib
import uuid

from conftest import bearer, make_person, pin_login
from files import JPEG, PDF, PNG, send, sent
from lms.services import uploads


def test_a_photo_is_kept_on_disk_under_a_random_id(client, learner_headers, upload_dir):
    r = send(client, learner_headers)
    assert r.status_code == 201, r.text
    out = r.json()
    assert (out["purpose"], out["content_type"], out["size_bytes"]) == ("ticket", "image/jpeg",
                                                                      len(JPEG))
    stored = list(upload_dir.rglob("*.jpg"))
    assert [p.name for p in stored] == [f"{out['id']}.jpg"] and stored[0].read_bytes() == JPEG
    # the same bytes again are another file: nothing is shared between uploads
    assert send(client, learner_headers).json()["id"] != out["id"]


def test_a_ticket_may_be_a_photo_or_a_pdf_and_a_signature_a_png(client, learner_headers):
    assert send(client, learner_headers, data=PNG).json()["content_type"] == "image/png"
    assert send(client, learner_headers, data=PDF).json()["content_type"] == "application/pdf"
    assert send(client, learner_headers, "signature", PNG).status_code == 201
    r = send(client, learner_headers, "signature", JPEG)
    assert r.status_code == 415 and r.json() == {
        "detail": "a signature file must be one of: PNG", "code": "unsupported_type"}


def test_what_counts_is_the_bytes_not_what_the_request_says(client, learner_headers, db):
    from lms.models import Upload

    r = send(client, learner_headers, data=b"<html>not a photo</html>", content_type="image/jpeg")
    assert r.status_code == 415
    assert db.query(Upload).count() == 0


def test_a_file_too_big_is_refused(client, learner_headers, monkeypatch):
    monkeypatch.setitem(uploads.PURPOSES, "ticket", ({"image/jpeg"}, 100))
    r = send(client, learner_headers)
    assert r.status_code == 413 and r.json()["code"] == "too_large"
    # past the largest of all, it is refused before the body is read
    monkeypatch.setattr(uploads, "LARGEST", 50)
    assert send(client, learner_headers).status_code == 413


def test_an_unknown_purpose_or_no_session_is_refused(client, learner_headers):
    assert send(client, learner_headers, "selfie").status_code == 422
    assert send(client, {}).status_code == 401


def test_a_file_is_shown_to_its_owner_their_supervisor_and_a_manager(
        client, db, learner_headers, supervisor_headers, manager_headers):
    file_id = sent(client, learner_headers)
    for headers in (learner_headers, supervisor_headers, manager_headers):
        r = client.get(f"/v1/uploads/{file_id}", headers=headers)
        assert r.status_code == 200 and r.content == JPEG
        assert r.headers["content-type"] == "image/jpeg"
        assert r.headers["cache-control"] == "private, no-store"
        assert r.headers["content-security-policy"] == "default-src 'none'; sandbox"
        assert r.headers["content-disposition"] == f'inline; filename="{file_id}.jpg"'
        assert r.headers["x-content-type-options"] == "nosniff"


def test_anyone_else_finds_nothing(client, db, learner_headers):
    file_id = sent(client, learner_headers)
    make_person(db, "LL099", "Pat Other", pin="1357")
    pat = bearer(pin_login(client, "LL099", "1357")["token"])
    assert client.get(f"/v1/uploads/{file_id}", headers=pat).status_code == 404
    assert client.get("/v1/uploads/7d1f6a2e-5b8c-4c1e-9f00-000000000000",
                      headers=learner_headers).status_code == 404
    assert client.get(f"/v1/uploads/{file_id}").status_code == 401


def test_a_file_lost_from_disk_is_not_found(client, learner_headers, upload_dir):
    file_id = sent(client, learner_headers)
    for p in upload_dir.rglob("*.jpg"):
        p.unlink()
    assert client.get(f"/v1/uploads/{file_id}", headers=learner_headers).status_code == 404


def test_the_row_says_what_was_kept(client, db, learner_headers):
    from lms.models import Upload

    file_id = sent(client, learner_headers, data=PDF, content_type="application/pdf")
    row = db.get(Upload, uuid.UUID(file_id))
    assert row.sha256 == hashlib.sha256(PDF).hexdigest() and row.path.endswith(".pdf")
```

**Step 2: Run it to see it fail**

Run: `cd api && .venv/bin/pytest tests/test_uploads.py -q`
Expected: FAIL: `ImportError: cannot import name 'uploads' from 'lms.services'`.

**Step 3: Minimal implementation**

In `api/lms/api/errors.py`, replace:
```python
class Unauthorised(Exception):
```
with:
```python
class Refused(Exception):
    """A request refused with a status of its own: a file too big (413) or of
    a kind we do not keep (415). `code` is for programs, `message` for people."""

    def __init__(self, status_code: int, code: str, message: str):
        self.status_code = status_code
        self.code = code
        self.message = message
        super().__init__(message)


class Unauthorised(Exception):
```

In `api/lms/api/errors.py`, replace:
```python
    @app.exception_handler(Unauthorised)
```
with:
```python
    @app.exception_handler(Refused)
    async def _refused(request: Request, exc: Refused):
        return JSONResponse(status_code=exc.status_code,
                            content={"detail": exc.message, "code": exc.code})

    @app.exception_handler(Unauthorised)
```

`api/lms/services/uploads.py`:
```python
"""Files people send: a ticket's photos (or a PDF of it) and policy
signatures. Kept on disk under LMS_UPLOAD_DIR, one file each, named by a
random id; the row says whose it is and what it is. What a file is comes
from its first bytes, never from what the request says."""
from __future__ import annotations

import hashlib
import os
import tempfile
import uuid
from pathlib import Path

from sqlalchemy.orm import Session as Db

from lms.api.errors import Refused
from lms.config import get_settings
from lms.models import Person, Upload

# what each purpose may be, and how big: 20 MB for a ticket (the design's
# limit for anything that is not a video); a signature is a few kB
PURPOSES = {
    "ticket": ({"image/jpeg", "image/png", "application/pdf"}, 20_000_000),
    "signature": ({"image/png"}, 1_000_000),
}
LARGEST = max(limit for _, limit in PURPOSES.values())
MAGIC = {"image/png": b"\x89PNG\r\n\x1a\n", "image/jpeg": b"\xff\xd8\xff",
         "application/pdf": b"%PDF-"}
EXT = {"image/png": "png", "image/jpeg": "jpg", "application/pdf": "pdf"}


def sniff(data: bytes) -> str | None:
    for content_type, magic in MAGIC.items():
        if data.startswith(magic):
            return content_type
    return None


def full_path(row: Upload) -> Path:
    return Path(get_settings().upload_dir) / row.path


def _write(target: Path, data: bytes) -> None:
    """All of it or none of it: a half-written file never has the real name."""
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=".upload-")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, target)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def store(db: Db, person: Person, purpose: str, data: bytes) -> Upload:
    allowed, limit = PURPOSES[purpose]
    if len(data) > limit:
        raise Refused(413, "too_large", f"a {purpose} file may be {limit // 1_000_000} MB at most")
    content_type = sniff(data)
    if content_type not in allowed:
        wanted = ", ".join(sorted(EXT[t].upper() for t in allowed))
        raise Refused(415, "unsupported_type", f"a {purpose} file must be one of: {wanted}")
    upload_id = uuid.uuid4()
    relative = f"{upload_id.hex[:2]}/{upload_id}.{EXT[content_type]}"
    _write(Path(get_settings().upload_dir) / relative, data)
    row = Upload(id=upload_id, person_id=person.id, purpose=purpose, content_type=content_type,
                 size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest(), path=relative)
    db.add(row)
    db.flush()
    return row


def mine(db: Db, person: Person, upload_id: uuid.UUID | None, purpose: str) -> Upload | None:
    """One of this person's own files for this purpose, or None."""
    if upload_id is None:
        return None
    row = db.get(Upload, upload_id)
    if row is None or row.person_id != person.id or row.purpose != purpose:
        return None
    return row
```

`api/lms/api/routes/uploads.py`:
```python
"""Files: sent by the learner app before the ticket or signature that names
them, and shown only to who may see the person they belong to."""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from lms.api.deps import DB, Principal, Who, require
from lms.api.errors import NotFound, Refused
from lms.models import Person, Upload
from lms.services import uploads

router = APIRouter(tags=["uploads"])
log = logging.getLogger("lms.uploads")


class UploadOut(BaseModel):
    id: uuid.UUID
    purpose: str
    content_type: str
    size_bytes: int
    created_at: datetime


def upload_out(row: Upload) -> UploadOut:
    return UploadOut(id=row.id, purpose=row.purpose, content_type=row.content_type,
                     size_bytes=row.size_bytes, created_at=row.created_at)


@dataclass(frozen=True)
class Sent:
    purpose: str
    data: bytes


async def sent(request: Request, purpose: Literal["ticket", "signature"] = Query()) -> Sent:
    """The purpose, then the body, read no further than the largest file we
    keep. A wrong purpose is refused before a byte of the body is read."""
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > uploads.LARGEST:
        raise Refused(413, "too_large", "that file is too big")
    data = bytearray()
    async for chunk in request.stream():
        data += chunk
        if len(data) > uploads.LARGEST:
            raise Refused(413, "too_large", "that file is too big")
    return Sent(purpose=purpose, data=bytes(data))


@router.post("/uploads", status_code=201, response_model=UploadOut)
def send_file(db: DB, who: Principal = require("training:write"), file: Sent = Depends(sent)):
    """The file as the body (what counts is its first bytes, not its
    Content-Type). The caller is checked before the body is read
    (dependencies run in order)."""
    row = uploads.store(db, who.person, file.purpose, file.data)
    db.commit()
    return JSONResponse(status_code=201, content=upload_out(row).model_dump(mode="json"))


@router.get("/uploads/{upload_id}", response_class=Response)
def get_file(upload_id: uuid.UUID, db: DB, who: Who):
    """For the person it belongs to, their supervisor, and managers and
    admins: whoever may see that person's training."""
    row = db.get(Upload, upload_id)
    if row is None or not who.sees(db.get(Person, row.person_id)):
        raise NotFound(f"no file {upload_id}")
    try:
        content = uploads.full_path(row).read_bytes()
    except FileNotFoundError:
        # the row is there but the file is not: a volume lost or restored
        # without it. Not found to the caller; someone should look.
        log.warning("upload %s is recorded but missing from disk at %s",
                    upload_id, uploads.full_path(row))
        raise NotFound(f"no file {upload_id}") from None
    return Response(content=content, media_type=row.content_type,
                    headers={"Cache-Control": "private, no-store",
                             # opened on its own, it runs nothing and reaches nothing
                             "Content-Security-Policy": "default-src 'none'; sandbox",
                             "Content-Disposition":
                                 f'inline; filename="{row.id}.{uploads.EXT[row.content_type]}"',
                             "X-Content-Type-Options": "nosniff"})
```

In `api/lms/api/app.py`, replace:
```python
from lms.api.routes import auth, competencies, matrix, overrides, people, records, roles
```
with:
```python
from lms.api.routes import (
    auth, competencies, matrix, overrides, people, records, roles, uploads,
)
```

In `api/lms/api/app.py`, replace:
```python
v1.include_router(matrix.router)
```
with:
```python
v1.include_router(matrix.router)
v1.include_router(uploads.router)
```

**Step 4: Run it to see it pass**

Run: `cd api && .venv/bin/pytest tests/test_uploads.py -q`
Expected: `9 passed`.

**Step 5: Commit**

```
git add api/lms/api/errors.py api/lms/api/app.py api/lms/services/uploads.py api/lms/api/routes/uploads.py api/tests/conftest.py api/tests/files.py api/tests/test_uploads.py
git commit -m "Keep a ticket's photos and a signature on disk, and show them only to who may see whose they are" \
  -m "The file is the request body, checked by its first bytes and read no further than the largest we keep. Named by a random id under LMS_UPLOAD_DIR, served sandboxed and never cached."
```

---

### Task 5: A ticket says whether its card runs out

**Files:**
- Modify: `api/lms/api/routes/competencies.py`
- Test: `api/tests/test_competencies.py`

**Step 1: Write the failing test**

Append to `api/tests/test_competencies.py`:
```python
def test_a_ticket_says_whether_its_card_runs_out(client, manager_headers):
    out = make_competency(client, manager_headers,
                          {"key": "forklift-licence", "name": "Forklift licence", "kind": "ticket"})
    assert out["card_expires"] is True
    out = make_competency(client, manager_headers, {"key": "white-card", "name": "White card",
                                                    "kind": "ticket", "card_expires": False})
    assert out["card_expires"] is False
    r = client.patch("/v1/competencies/white-card", headers=manager_headers,
                     json={"card_expires": True})
    assert r.json()["card_expires"] is True
```

**Step 2: Run it to see it fail**

Run: `cd api && .venv/bin/pytest tests/test_competencies.py -q`
Expected: FAIL: `KeyError: 'card_expires'`.

**Step 3: Minimal implementation**

In `api/lms/api/routes/competencies.py`, replace:
```python
    refresher_months: int | None = Field(default=None, ge=1, le=240)

    @field_validator
```
with:
```python
    refresher_months: int | None = Field(default=None, ge=1, le=240)
    # a ticket: whether its card has an expiry date to type in
    card_expires: bool = True

    @field_validator
```

In `api/lms/api/routes/competencies.py`, replace:
```python
    refresher_months: int | None = Field(default=None, ge=1, le=240)


class CompetencyOut
```
with:
```python
    refresher_months: int | None = Field(default=None, ge=1, le=240)
    card_expires: bool | None = None


class CompetencyOut
```

In `api/lms/api/routes/competencies.py`, replace:
```python
    refresher_months: int | None
    active: bool
    created_at: datetime
```
with:
```python
    refresher_months: int | None
    card_expires: bool
    active: bool
    created_at: datetime
```

In `api/lms/api/routes/competencies.py`, replace:
```python
                         refresher_months=c.refresher_months, active=c.active,
```
with:
```python
                         refresher_months=c.refresher_months, card_expires=c.card_expires,
                         active=c.active,
```

In `api/lms/api/routes/competencies.py`, replace:
```python
                   refresher_months=body.refresher_months, active=True)
```
with:
```python
                   refresher_months=body.refresher_months, card_expires=body.card_expires,
                   active=True)
```

In `api/lms/api/routes/competencies.py`, replace:
```python
        c.refresher_months = body.refresher_months
    db.commit()
```
with:
```python
        c.refresher_months = body.refresher_months
    if body.card_expires is not None:
        c.card_expires = body.card_expires
    db.commit()
```

**Step 4: Run it to see it pass**

Run: `cd api && .venv/bin/pytest tests/test_competencies.py -q`
Expected: `13 passed`.

**Step 5: Commit**

```
git add api/lms/api/routes/competencies.py api/tests/test_competencies.py
git commit -m "Say whether a ticket's card has an expiry date"
```

---

### Task 6: Policy versions, read and signed with a typed name and a finger signature

**Files:**
- Create: `api/lms/services/policies.py`, `api/lms/api/routes/policies.py`
- Modify: `api/lms/api/routes/records.py` (in full below), `api/lms/api/app.py`
- Test: `api/tests/test_policies.py`

**Step 1: Write the failing test**

`api/tests/test_policies.py`:
```python
"""Policies: versions published by a manager, read and signed by each
person with their typed name and a finger signature. A new version needs a
new signature."""
import pytest

import yard
from conftest import bearer, login, make_person, pin_login
from files import JPEG, PNG, sent

WHS = "/v1/policies/whs-policy"


@pytest.fixture
def kim(client, manager_headers, learner):
    """Kim is a picker, and pickers are asked to sign the WHS policy."""
    yard.build(client, manager_headers)
    r = client.put("/v1/roles/picker/requirements", headers=manager_headers,
                   json={"competencies": ["site-induction", "whs-policy"]})
    assert r.status_code == 200
    yard.give_roles(client, manager_headers, "LL042", "picker")
    return learner


def publish(client, headers, body="Wear your PPE on the floor.", note=None):
    r = client.post(f"{WHS}/versions", headers=headers, json={"body": body, "note": note})
    assert r.status_code == 201, r.text
    return r.json()


def sign(client, headers, version=1, name="Kim Lee", signature=None):
    signature = signature or sent(client, headers, "signature", PNG, "image/png")
    return client.post(f"{WHS}/sign", headers=headers,
                       json={"version": version, "signed_name": name, "signature": signature})


def whs_status(client, headers, code="LL042"):
    items = client.get(f"/v1/people/{code}/training", headers=headers).json()["items"]
    return next(i["status"] for i in items if i["key"] == "whs-policy")


def test_versions_are_numbered_and_newest_first(client, manager_headers, kim):
    one = publish(client, manager_headers)
    two = publish(client, manager_headers, "Wear your PPE, and hi-vis in the yard.",
                  note="hi-vis in the yard")
    assert (one["version"], two["version"]) == (1, 2)
    assert two["published_by"] == {"code": "MG001", "name": "Mel Grant"}
    r = client.get(f"{WHS}/versions", headers=manager_headers).json()
    assert [v["version"] for v in r] == [2, 1] and r[0]["note"] == "hi-vis in the yard"


def test_only_a_policy_has_versions(client, manager_headers, kim):
    r = client.post("/v1/policies/site-induction/versions", headers=manager_headers,
                    json={"body": "x"})
    assert r.status_code == 404
    r = client.post(f"{WHS}/versions", headers=manager_headers, json={"body": "  "})
    assert r.status_code == 422


def test_a_learner_or_supervisor_cannot_publish(client, learner_headers, supervisor_headers, kim):
    for headers in (learner_headers, supervisor_headers):
        assert client.post(f"{WHS}/versions", headers=headers,
                           json={"body": "x"}).status_code == 403


def test_the_learner_reads_the_version_to_sign(client, manager_headers, learner_headers, kim):
    r = client.get(WHS, headers=learner_headers)
    assert r.status_code == 404 and r.json()["detail"] == "WHS policy has no version to sign yet"
    publish(client, manager_headers)
    out = client.get(WHS, headers=learner_headers).json()
    assert (out["key"], out["name"]) == ("whs-policy", "WHS policy")
    assert out["version"]["version"] == 1 and out["version"]["body"] == "Wear your PPE on the floor."


def test_signing_makes_it_current(client, manager_headers, learner_headers, kim):
    publish(client, manager_headers)
    assert whs_status(client, learner_headers) == "missing"
    r = sign(client, learner_headers)
    assert r.status_code == 201, r.text
    out = r.json()
    assert (out["kind"], out["granted_on"], out["policy_version"]) == ("granted", "2026-10-12", 1)
    assert out["signed_name"] == "Kim Lee" and out["signature"]
    assert out["recorded_by"] == {"code": "LL042", "name": "Kim Lee"}
    assert whs_status(client, learner_headers) == "current"


def test_a_new_version_needs_a_new_signature(client, manager_headers, learner_headers, kim):
    publish(client, manager_headers)
    sign(client, learner_headers)
    publish(client, manager_headers, "Wear your PPE, and hi-vis in the yard.")
    assert whs_status(client, learner_headers) == "missing"
    # read version 1, but version 2 came out meanwhile
    r = sign(client, learner_headers, version=1)
    assert r.status_code == 409 and r.json()["code"] == "new_version"
    assert sign(client, learner_headers, version=2).status_code == 201
    assert whs_status(client, learner_headers) == "current"


def test_once_for_each_version(client, manager_headers, learner_headers, kim):
    publish(client, manager_headers)
    sign(client, learner_headers)
    r = sign(client, learner_headers)
    assert r.status_code == 409 and r.json()["code"] == "already_signed"


def test_the_typed_name_is_theirs(client, manager_headers, learner_headers, kim):
    publish(client, manager_headers)
    r = sign(client, learner_headers, name="Sam Vu")
    assert r.status_code == 422 and r.json()["errors"] == [
        {"field": "signed_name", "message": "type your name as it is on your record: Kim Lee"}]
    assert sign(client, learner_headers, name="  kim   LEE ").status_code == 201


def test_the_signature_is_their_own_and_a_signature(client, db, manager_headers, learner_headers,
                                                    kim):
    publish(client, manager_headers)
    photo = sent(client, learner_headers, "ticket", JPEG)
    r = sign(client, learner_headers, signature=photo)
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "signature"
    make_person(db, "LL099", "Pat Other", pin="1357")
    pat = bearer(pin_login(client, "LL099", "1357")["token"])
    pats = sent(client, pat, "signature", PNG, "image/png")
    assert sign(client, learner_headers, signature=pats).status_code == 422


def test_a_supervisor_signs_their_own_on_a_pin(client, manager_headers, supervisor, kim):
    publish(client, manager_headers)
    sam = bearer(pin_login(client, supervisor.code)["token"])
    assert sign(client, sam, name="Sam Vu").status_code == 201


def test_signed_on_paper_and_recorded_by_hand_counts_for_the_version_now(
        client, manager_headers, learner_headers, kim):
    publish(client, manager_headers)
    out = yard.grant(client, manager_headers, "LL042", "whs-policy", "2026-10-01",
                     note="signed on paper at the toolbox meeting")
    assert out["policy_version"] == 1 and out["signature"] is None
    assert whs_status(client, learner_headers) == "current"
    publish(client, manager_headers, "Version two.")
    assert whs_status(client, learner_headers) == "missing"


def test_a_deactivated_policy_is_not_signed(client, manager_headers, learner_headers, kim):
    publish(client, manager_headers)
    client.post("/v1/competencies/whs-policy/deactivate", headers=manager_headers)
    r = sign(client, learner_headers)
    assert r.status_code == 409 and r.json()["code"] == "inactive"


def test_the_matrix_shows_who_has_signed(client, manager_headers, learner_headers, kim, db):
    make_person(db, "LL043", "Ash Patel")
    yard.give_roles(client, manager_headers, "LL043", "picker")
    publish(client, manager_headers)
    sign(client, learner_headers)
    m = client.get("/v1/matrix", headers=manager_headers).json()
    cells = {p["code"]: p["cells"]["whs-policy"]["status"] for p in m["people"]
             if "whs-policy" in p["cells"] and p["code"].startswith("LL")}
    assert cells == {"LL042": "current", "LL043": "missing"}


def test_a_manager_signs_their_own_too(client, db, manager, manager_headers, admin_headers, kim):
    publish(client, admin_headers)
    mel = bearer(login(client, manager.email)["token"])
    assert sign(client, mel, name="Mel Grant").status_code == 201
```

**Step 2: Run it to see it fail**

Run: `cd api && .venv/bin/pytest tests/test_policies.py -q`
Expected: FAIL: `404` from `POST /v1/policies/whs-policy/versions` and the rest.

**Step 3: Minimal implementation**

`api/lms/services/policies.py`:
```python
"""Policies: the newest version is the one to sign, and a signature names
the person as Simple LMS has them."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session as Db

from lms.models import Competency, PolicyVersion


def newest(db: Db, competency: Competency) -> PolicyVersion | None:
    return db.execute(select(PolicyVersion).where(PolicyVersion.competency_id == competency.id)
                      .order_by(PolicyVersion.id.desc()).limit(1)).scalar_one_or_none()


def same_name(typed: str, name: str) -> bool:
    """'kim  lee' is Kim Lee: case and spacing aside, the name on their record."""
    return " ".join(typed.split()).casefold() == " ".join(name.split()).casefold()
```

The record now says which policy version it is for, how it was signed and which ticket it came from. `one_at_a_time` and `latest_record` lose their underscore: policies and tickets use them too. A policy recorded by hand is for its newest version.

`api/lms/api/routes/records.py`:
```python
"""The training record, entered by hand from the desktop in step 1: a
completion granted, or revoked with a note. Append-only (rule 1); the
latest row counts, so a wrong date is put right by recording it again.
Nobody records their own (rule 3)."""
from __future__ import annotations

import uuid
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
from lms.services import clock, policies

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
    # a policy: the version this grant is for; signed in the learner app, the
    # name they typed and their signature (GET /v1/uploads/{id})
    policy_version: int | None
    signed_name: str | None
    signature: uuid.UUID | None
    # a ticket a manager verified: its submission's id
    ticket: int | None
    created_at: datetime


def record_out(r: CompetencyRecord) -> RecordOut:
    return RecordOut(id=r.id, competency=competency_ref(r.competency), kind=r.kind,
                     granted_on=r.granted_on, expires_on=r.expires_on, note=r.note,
                     recorded_by=person_ref(r.recorded_by),
                     policy_version=r.policy_version.version if r.policy_version else None,
                     signed_name=r.signed_name, signature=r.signature_upload_id,
                     ticket=r.ticket_submission_id, created_at=r.created_at)


def latest_record(db, person_id: int, competency_id: int) -> CompetencyRecord | None:
    return db.execute(
        select(CompetencyRecord)
        .where(CompetencyRecord.person_id == person_id,
               CompetencyRecord.competency_id == competency_id)
        .order_by(CompetencyRecord.id.desc()).limit(1)
    ).scalar_one_or_none()


def one_at_a_time(db, code: str):
    # the person stays locked until this record is in, so a grant and a revoke
    # sent at once are weighed one after the other: a revoke never misses a
    # grant made at the same moment
    p = get_person(db, code)
    db.refresh(p, with_for_update=True)
    return p


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
    p = one_at_a_time(db, code)
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
    # a policy signed on paper: for the version people are asked to sign now
    version = policies.newest(db, c) if c.kind == "policy" else None
    r = CompetencyRecord(person_id=p.id, competency=c, kind="granted",
                         granted_on=body.granted_on, expires_on=body.expires_on,
                         note=body.note or None, recorded_by=who.person, policy_version=version)
    db.add(r)
    db.commit()
    return _created(r)


@router.post("/people/{code}/records/revoke", status_code=201, response_model=RecordOut)
def revoke(code: str, body: RevokeIn, db: DB, who: Principal = require("records:write")):
    """Cancels the grant that counts now, with a note saying why."""
    p = one_at_a_time(db, code)
    c = get_competency(db, body.competency)
    latest = latest_record(db, p.id, c.id)
    if latest is None or latest.kind != "granted":
        raise Conflict("nothing_to_revoke", f"{p.code} has no grant of {c.key} to revoke")
    r = CompetencyRecord(person_id=p.id, competency=c, kind="revoked", note=body.note,
                         recorded_by=who.person)
    db.add(r)
    db.commit()
    return _created(r)
```

`api/lms/api/routes/policies.py`:
```python
"""Policies: versions of the text, published by a manager, and signed by
each person in the learner app with their typed name and a finger
signature. A new version needs a new signature (status.py says so)."""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from lms.api.deps import DB, Principal, require
from lms.api.errors import Conflict, FieldError, NotFound
from lms.api.routes.competencies import get_competency
from lms.api.routes.records import RecordOut, latest_record, one_at_a_time, record_out
from lms.api.schemas import PersonRef, person_ref
from lms.models import Competency, CompetencyRecord, PolicyVersion
from lms.services import clock, policies, uploads

router = APIRouter(tags=["policies"])


class VersionIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    body: str = Field(min_length=1, max_length=50_000)
    note: str | None = Field(default=None, max_length=500)


class VersionOut(BaseModel):
    id: int
    version: int
    body: str
    note: str | None
    published_by: PersonRef
    created_at: datetime


class PolicyOut(BaseModel):
    key: str
    name: str
    version: VersionOut


class SignIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    # the version they read: if a newer one came out meanwhile, they read that
    version: int
    signed_name: str = Field(min_length=1, max_length=120)
    # the finger signature, sent first to POST /v1/uploads?purpose=signature
    signature: uuid.UUID


def version_out(v: PolicyVersion) -> VersionOut:
    return VersionOut(id=v.id, version=v.version, body=v.body, note=v.note,
                      published_by=person_ref(v.published_by), created_at=v.created_at)


def get_policy(db, key: str) -> Competency:
    c = get_competency(db, key)
    if c.kind != "policy":
        raise NotFound(f"no policy {key}")
    return c


@router.get("/policies/{key}/versions", response_model=list[VersionOut])
def list_versions(key: str, db: DB, who: Principal = require("competencies:read")):
    """Newest first: the first is the one to sign."""
    c = get_policy(db, key)
    rows = db.execute(select(PolicyVersion).where(PolicyVersion.competency_id == c.id)
                      .order_by(PolicyVersion.id.desc())).scalars().all()
    return [version_out(v) for v in rows]


@router.post("/policies/{key}/versions", status_code=201, response_model=VersionOut)
def publish_version(key: str, body: VersionIn, db: DB,
                    who: Principal = require("competencies:write")):
    """The next version. Everyone asked for the policy needs to sign it."""
    c = get_policy(db, key)
    # one at a time per policy, so two published at once get 1 and 2
    db.refresh(c, with_for_update=True)
    last = db.execute(select(func.max(PolicyVersion.version))
                      .where(PolicyVersion.competency_id == c.id)).scalar() or 0
    v = PolicyVersion(competency=c, version=last + 1, body=body.body, note=body.note or None,
                      published_by=who.person)
    db.add(v)
    db.commit()
    return JSONResponse(status_code=201, content=version_out(v).model_dump(mode="json"))


@router.get("/policies/{key}", response_model=PolicyOut)
def read_policy(key: str, db: DB, who: Principal = require("training:read")):
    """The version to read and sign now."""
    c = get_policy(db, key)
    v = policies.newest(db, c)
    if v is None:
        raise NotFound(f"{c.name} has no version to sign yet")
    return PolicyOut(key=c.key, name=c.name, version=version_out(v))


@router.post("/policies/{key}/sign", status_code=201, response_model=RecordOut)
def sign(key: str, body: SignIn, db: DB, who: Principal = require("training:write")):
    """Your own signature, for the newest version. Like a module pass, it
    is something you do yourself: it says you have read the policy, and it
    is recorded as yours."""
    p = one_at_a_time(db, who.person.code)
    c = get_policy(db, key)
    if not c.active:
        raise Conflict("inactive", f"{c.key} is deactivated")
    v = policies.newest(db, c)
    if v is None:
        raise NotFound(f"{c.name} has no version to sign yet")
    if body.version != v.version:
        raise Conflict("new_version", f"version {v.version} is the one to sign now: read it first")
    latest = latest_record(db, p.id, c.id)
    if latest is not None and latest.kind == "granted" and latest.policy_version_id == v.id:
        raise Conflict("already_signed", f"you have signed version {v.version} already")
    if not policies.same_name(body.signed_name, p.name):
        raise FieldError("signed_name", f"type your name as it is on your record: {p.name}")
    signature = uploads.mine(db, p, body.signature, "signature")
    if signature is None:
        raise FieldError("signature", "sign with your finger first")
    r = CompetencyRecord(person_id=p.id, competency=c, kind="granted", granted_on=clock.today(),
                         recorded_by=p, policy_version=v, signed_name=body.signed_name,
                         signature_upload_id=signature.id)
    db.add(r)
    db.commit()
    return JSONResponse(status_code=201, content=record_out(r).model_dump(mode="json"))
```

In `api/lms/api/app.py`, replace:
```python
    auth, competencies, matrix, overrides, people, records, roles, uploads,
```
with:
```python
    auth, competencies, matrix, overrides, people, policies, records, roles, uploads,
```

In `api/lms/api/app.py`, replace:
```python
v1.include_router(uploads.router)
```
with:
```python
v1.include_router(uploads.router)
v1.include_router(policies.router)
```

**Step 4: Run it, and the records, to see them pass**

Run: `cd api && .venv/bin/pytest tests/test_policies.py tests/test_records.py -q`
Expected: `23 passed`.

**Step 5: Commit**

```
git add api/lms/services/policies.py api/lms/api/routes/policies.py api/lms/api/routes/records.py api/lms/api/app.py api/tests/test_policies.py
git commit -m "Publish policy versions, and sign the newest with a typed name and a finger signature" \
  -m "A signature is the person's own act, recorded as theirs, for the version they read. A new version asks everyone to sign again; one signed on paper and recorded by hand counts for the newest."
```

---

### Task 7: Tickets sent in, and approved or sent back by a manager who is not the learner

**Files:**
- Create: `api/lms/api/routes/tickets.py`
- Modify: `api/lms/api/routes/matrix.py`, `api/lms/api/app.py`
- Test: `api/tests/test_tickets.py`

**Step 1: Write the failing test**

`api/tests/test_tickets.py`:
```python
"""Tickets: sent in by the person with photos, a number and the card's
expiry; checked by a manager who is not them, and approved (a grant good
until the card's date) or sent back with a reason."""
import pytest

import yard
from conftest import all_at_once, bearer, fresh_client, login, make_person
from files import JPEG, PDF, PNG, sent


@pytest.fixture
def kim(client, manager_headers, learner):
    """Kim is a forklift operator: a site induction and a forklift licence."""
    yard.build(client, manager_headers)
    yard.give_roles(client, manager_headers, "LL042", "forklift-operator")
    return learner


def send_in(client, headers, competency="forklift-licence", number="LF0012345",
            expires_on="2031-03-01", back=True, **more):
    body = {"competency": competency, "number": number, "expires_on": expires_on,
            "front": sent(client, headers), **more}
    if back:
        body["back"] = sent(client, headers, data=PNG, content_type="image/png")
    return client.post("/v1/tickets", headers=headers, json=body)


def forklift(client, headers, code="LL042"):
    items = client.get(f"/v1/people/{code}/training", headers=headers).json()["items"]
    return next(i for i in items if i["key"] == "forklift-licence")


def test_a_learner_sends_in_a_ticket_and_it_waits(client, manager_headers, learner_headers, kim):
    r = send_in(client, learner_headers)
    assert r.status_code == 201, r.text
    out = r.json()
    assert (out["status"], out["number"], out["expires_on"]) == ("pending", "LF0012345",
                                                                 "2031-03-01")
    assert out["person"] == {"code": "LL042", "name": "Kim Lee"} and out["back"]
    item = forklift(client, learner_headers)
    assert (item["status"], item["waiting"], item["card_expires"]) == ("missing", True, True)


def test_one_waiting_at_a_time(client, learner_headers, kim):
    send_in(client, learner_headers)
    r = send_in(client, learner_headers)
    assert r.status_code == 409 and r.json()["code"] == "already_waiting"


def test_the_back_is_optional_and_a_pdf_will_do(client, learner_headers, kim):
    front = sent(client, learner_headers, data=PDF, content_type="application/pdf")
    r = client.post("/v1/tickets", headers=learner_headers,
                    json={"competency": "forklift-licence", "number": "LF1", "front": front,
                          "expires_on": "2031-03-01"})
    assert r.status_code == 201 and r.json()["back"] is None


def test_the_card_date_is_asked_for_when_the_card_has_one(client, manager_headers,
                                                          learner_headers, kim):
    def field(r):
        assert r.status_code == 422, r.text
        return r.json()["errors"][0]

    assert field(send_in(client, learner_headers, expires_on=None)) == {
        "field": "expires_on", "message": "this card has an expiry date: type it in"}
    # the last good day must still be ahead
    assert field(send_in(client, learner_headers, expires_on="2026-10-12"))["message"] == \
        "this card has run out: send the new one"
    client.post("/v1/competencies", headers=manager_headers,
                json={"key": "white-card", "name": "White card", "kind": "ticket",
                      "card_expires": False})
    client.post("/v1/people/LL042/overrides", headers=manager_headers,
                json={"competency": "white-card", "kind": "extra", "note": "on the building site"})
    assert field(send_in(client, learner_headers, "white-card"))["field"] == "expires_on"
    assert send_in(client, learner_headers, "white-card", expires_on=None).status_code == 201


def test_only_a_ticket_and_only_your_own_photos(client, db, learner_headers, kim):
    r = send_in(client, learner_headers, competency="site-induction")
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "competency"
    make_person(db, "LL099", "Pat Other", email="pat@example.com.au", password="correct horse battery")
    pat = bearer(login(client, "pat@example.com.au")["token"])
    r = client.post("/v1/tickets", headers=learner_headers,
                    json={"competency": "forklift-licence", "number": "LF1",
                          "expires_on": "2031-03-01", "front": sent(client, pat)})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "front"
    signature = sent(client, learner_headers, "signature", PNG, "image/png")
    r = client.post("/v1/tickets", headers=learner_headers,
                    json={"competency": "forklift-licence", "number": "LF1",
                          "expires_on": "2031-03-01", "front": signature})
    assert r.status_code == 422


def test_the_inbox_is_for_managers_oldest_first(client, db, manager_headers, learner_headers,
                                                supervisor_headers, kim):
    send_in(client, learner_headers)
    send_in(client, learner_headers, competency="first-aid", number="FA 778",
            expires_on="2029-05-01")
    r = client.get("/v1/tickets", headers=manager_headers)
    assert [t["competency"]["key"] for t in r.json()] == ["forklift-licence", "first-aid"]
    for headers in (learner_headers, supervisor_headers):
        assert client.get("/v1/tickets", headers=headers).status_code == 403


def test_a_manager_approves_and_it_is_current_until_the_card_date(
        client, manager_headers, learner_headers, kim):
    ticket = send_in(client, learner_headers).json()
    r = client.post(f"/v1/tickets/{ticket['id']}/approve", headers=manager_headers)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["status"] == "approved" and out["decided_by"] == {"code": "MG001", "name": "Mel Grant"}
    item = forklift(client, learner_headers)
    assert (item["status"], item["granted_on"], item["expires_on"], item["waiting"]) == (
        "current", "2026-10-12", "2031-03-01", False)
    record = client.get("/v1/people/LL042/records", headers=manager_headers).json()[0]
    assert record["ticket"] == ticket["id"] and record["note"] == "Ticket LF0012345, checked"
    assert record["recorded_by"]["code"] == "MG001"
    assert client.get("/v1/tickets", headers=manager_headers).json() == []


def test_a_ticket_is_decided_once(client, manager_headers, learner_headers, kim):
    ticket = send_in(client, learner_headers).json()
    client.post(f"/v1/tickets/{ticket['id']}/approve", headers=manager_headers)
    for path in ("approve", "reject"):
        r = client.post(f"/v1/tickets/{ticket['id']}/{path}", headers=manager_headers,
                        json={"reason": "x"})
        assert r.status_code == 409 and r.json()["code"] == "decided"


def test_nobody_verifies_their_own(client, manager, manager_headers, admin_headers, kim):
    client.post("/v1/people/MG001/overrides", headers=admin_headers,
                json={"competency": "forklift-licence", "kind": "extra", "note": "drives too"})
    ticket = send_in(client, manager_headers).json()
    for path in ("approve", "reject"):
        r = client.post(f"/v1/tickets/{ticket['id']}/{path}", headers=manager_headers,
                        json={"reason": "x"})
        assert r.status_code == 403 and r.json()["code"] == "own_ticket"
    assert client.post(f"/v1/tickets/{ticket['id']}/approve",
                       headers=admin_headers).status_code == 200


def test_sent_back_with_a_reason_they_see(client, manager_headers, learner_headers, kim):
    ticket = send_in(client, learner_headers).json()
    r = client.post(f"/v1/tickets/{ticket['id']}/reject", headers=manager_headers,
                    json={"reason": " "})
    assert r.status_code == 422
    r = client.post(f"/v1/tickets/{ticket['id']}/reject", headers=manager_headers,
                    json={"reason": "The photo is blurry: take it again in good light."})
    assert r.json()["status"] == "rejected"
    mine = client.get("/v1/people/LL042/tickets", headers=learner_headers).json()
    assert mine[0]["reason"] == "The photo is blurry: take it again in good light."
    assert forklift(client, learner_headers)["waiting"] is False
    # and they can send it again
    assert send_in(client, learner_headers).status_code == 201


def test_a_card_that_ran_out_while_it_waited_is_not_approved(client, manager_headers,
                                                             learner_headers, kim, today):
    ticket = send_in(client, learner_headers, expires_on="2026-10-20").json()
    today.set(today.value.replace(day=20))
    r = client.post(f"/v1/tickets/{ticket['id']}/approve", headers=manager_headers)
    assert r.status_code == 409 and r.json()["code"] == "card_ran_out"


def test_the_photos_are_shown_to_the_manager(client, manager_headers, learner_headers, kim):
    ticket = send_in(client, learner_headers).json()
    r = client.get(f"/v1/uploads/{ticket['front']}", headers=manager_headers)
    assert r.status_code == 200 and r.content == JPEG


def test_whose_tickets_who_may_read(client, db, learner_headers, supervisor_headers, kim):
    make_person(db, "LL099", "Pat Other")
    assert client.get("/v1/people/LL042/tickets", headers=supervisor_headers).status_code == 200
    assert client.get("/v1/people/LL099/tickets", headers=learner_headers).status_code == 404


def test_two_managers_at_once_approve_it_once(client, db, manager_headers, admin_headers,
                                              learner_headers, kim):
    from lms.models import CompetencyRecord

    ticket = send_in(client, learner_headers).json()
    managers = [manager_headers, admin_headers]

    def approve():
        headers = managers.pop()
        return fresh_client().post(f"/v1/tickets/{ticket['id']}/approve",
                                   headers=headers).status_code

    assert sorted(all_at_once(2, approve)) == [200, 409]
    assert db.query(CompetencyRecord).count() == 1
```

**Step 2: Run it to see it fail**

Run: `cd api && .venv/bin/pytest tests/test_tickets.py -q`
Expected: FAIL: `404` from `POST /v1/tickets` and the rest.

**Step 3: Minimal implementation**

`api/lms/api/routes/tickets.py`:
```python
"""Tickets and licences: a person sends in the photos, the number and the
expiry; a manager who is not them checks it, and approves it (a grant
good until the card's date) or rejects it with a reason (rule 3)."""
from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Literal

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from lms.api.deps import DB, Principal, require
from lms.api.errors import Conflict, FieldError, Forbidden, NotFound
from lms.api.routes.competencies import get_competency
from lms.api.routes.people import get_person
from lms.api.routes.records import one_at_a_time
from lms.api.schemas import CompetencyRef, PersonRef, competency_ref, person_ref
from lms.models import CompetencyRecord, TicketSubmission
from lms.services import clock, uploads

router = APIRouter(tags=["tickets"])


class TicketIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    competency: str = Field(max_length=64)
    number: str = Field(min_length=1, max_length=64)
    # the card's last good day; leave it out for a card that never runs out
    expires_on: date | None = None
    # photos (or a PDF) sent first to POST /v1/uploads?purpose=ticket
    front: uuid.UUID
    back: uuid.UUID | None = None


class RejectIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    reason: str = Field(min_length=1, max_length=500)


class TicketOut(BaseModel):
    id: int
    person: PersonRef
    competency: CompetencyRef
    number: str
    expires_on: date | None
    front: uuid.UUID
    back: uuid.UUID | None
    status: str
    reason: str | None
    decided_by: PersonRef | None
    decided_at: datetime | None
    created_at: datetime


def ticket_out(t: TicketSubmission) -> TicketOut:
    return TicketOut(id=t.id, person=person_ref(t.person), competency=competency_ref(t.competency),
                     number=t.number, expires_on=t.expires_on, front=t.front_upload_id,
                     back=t.back_upload_id, status=t.status, reason=t.reason,
                     decided_by=person_ref(t.decided_by), decided_at=t.decided_at,
                     created_at=t.created_at)


def _query():
    return select(TicketSubmission).options(selectinload(TicketSubmission.person),
                                            selectinload(TicketSubmission.competency),
                                            selectinload(TicketSubmission.decided_by))


@router.post("/tickets", status_code=201, response_model=TicketOut)
def send_ticket(body: TicketIn, db: DB, who: Principal = require("training:write")):
    """Your own ticket, for a manager to check."""
    p = one_at_a_time(db, who.person.code)
    c = get_competency(db, body.competency)
    if c.kind != "ticket":
        raise FieldError("competency", f"{c.key} is not a ticket or licence")
    if not c.active:
        raise FieldError("competency", f"{c.key} is deactivated")
    if c.card_expires and body.expires_on is None:
        raise FieldError("expires_on", "this card has an expiry date: type it in")
    if not c.card_expires and body.expires_on is not None:
        raise FieldError("expires_on", "this card doesn't run out: leave the date out")
    if body.expires_on is not None and body.expires_on <= clock.today():
        raise FieldError("expires_on", "this card has run out: send the new one")
    front = uploads.mine(db, p, body.front, "ticket")
    if front is None:
        raise FieldError("front", "add a photo of the front first")
    back = uploads.mine(db, p, body.back, "ticket")
    if body.back is not None and back is None:
        raise FieldError("back", "add the photo of the back again")
    waiting = db.execute(select(TicketSubmission.id).where(
        TicketSubmission.person_id == p.id, TicketSubmission.competency_id == c.id,
        TicketSubmission.status == "pending")).first()
    if waiting is not None:
        raise Conflict("already_waiting", f"your {c.name} is already waiting for a manager's check")
    t = TicketSubmission(person=p, competency=c, number=body.number, expires_on=body.expires_on,
                         front_upload_id=front.id, back_upload_id=back.id if back else None,
                         status="pending")
    db.add(t)
    db.commit()
    return JSONResponse(status_code=201, content=ticket_out(t).model_dump(mode="json"))


@router.get("/tickets", response_model=list[TicketOut])
def list_tickets(db: DB, status: Literal["pending", "approved", "rejected"] = "pending",
                 who: Principal = require("tickets:verify")):
    """The inbox: tickets waiting for a check, oldest first."""
    rows = db.execute(_query().where(TicketSubmission.status == status)
                      .order_by(TicketSubmission.id)).scalars().all()
    return [ticket_out(t) for t in rows]


@router.get("/people/{code}/tickets", response_model=list[TicketOut])
def person_tickets(code: str, db: DB, who: Principal = require("training:read")):
    """What a person has sent in, newest first: waiting, approved or sent back."""
    p = get_person(db, code)
    if not who.sees(p):
        raise NotFound(f"no person {code}")
    rows = db.execute(_query().where(TicketSubmission.person_id == p.id)
                      .order_by(TicketSubmission.id.desc())).scalars().all()
    return [ticket_out(t) for t in rows]


def _to_decide(db, ticket_id: int, who: Principal) -> TicketSubmission:
    """The ticket, still waiting, and not the caller's own; its person locked
    first (as a grant does), then the ticket, so two decisions take turns."""
    t = db.get(TicketSubmission, ticket_id)
    if t is None:
        raise NotFound(f"no ticket {ticket_id}")
    if t.person_id == who.person.id:
        raise Forbidden("nobody verifies their own ticket: ask another manager", "own_ticket")
    one_at_a_time(db, t.person.code)
    db.refresh(t, with_for_update=True)
    if t.status != "pending":
        raise Conflict("decided", f"this ticket was {t.status} already")
    return t


@router.post("/tickets/{ticket_id}/approve", response_model=TicketOut)
def approve(ticket_id: int, db: DB, who: Principal = require("tickets:verify")):
    """Checked and good: a grant from today until the card's date."""
    t = _to_decide(db, ticket_id, who)
    if not t.person.active:
        raise Conflict("inactive", f"{t.person.code} is deactivated")
    today = clock.today()
    if t.expires_on is not None and t.expires_on <= today:
        raise Conflict("card_ran_out", "this card ran out while it waited: send it back and ask "
                                       "for the new one")
    db.add(CompetencyRecord(person_id=t.person_id, competency_id=t.competency_id, kind="granted",
                            granted_on=today, expires_on=t.expires_on,
                            note=f"Ticket {t.number}, checked", recorded_by=who.person,
                            ticket_submission_id=t.id))
    t.status = "approved"
    t.decided_by = who.person
    t.decided_at = datetime.now(UTC)
    db.commit()
    return ticket_out(t)


@router.post("/tickets/{ticket_id}/reject", response_model=TicketOut)
def reject(ticket_id: int, body: RejectIn, db: DB, who: Principal = require("tickets:verify")):
    """Sent back, with a reason the person sees."""
    t = _to_decide(db, ticket_id, who)
    t.status = "rejected"
    t.reason = body.reason
    t.decided_by = who.person
    t.decided_at = datetime.now(UTC)
    db.commit()
    return ticket_out(t)
```

My training says when a ticket waits for its check, and whether its card has a date to type in. In `api/lms/api/routes/matrix.py`, replace:
```python
from lms.models import Person, PersonRole, Role
```
with:
```python
from lms.models import Person, PersonRole, Role, TicketSubmission
```

In `api/lms/api/routes/matrix.py`, replace:
```python
    status: str
    granted_on: date | None
    expires_on: date | None


class TrainingOut
```
with:
```python
    status: str
    granted_on: date | None
    expires_on: date | None
    # a ticket: whether its card has an expiry date to type in
    card_expires: bool
    # a ticket sent in and waiting for a manager's check
    waiting: bool


class TrainingOut
```

In `api/lms/api/routes/matrix.py`, replace:
```python
    st = standing.load(db, [p.id], clock.today())
    items = []
```
with:
```python
    st = standing.load(db, [p.id], clock.today())
    waiting = set(db.execute(select(TicketSubmission.competency_id).where(
        TicketSubmission.person_id == p.id, TicketSubmission.status == "pending")).scalars())
    items = []
```

In `api/lms/api/routes/matrix.py`, replace:
```python
                                      status=s.status, granted_on=s.granted_on,
                                      expires_on=s.expires_on))
```
with:
```python
                                      status=s.status, granted_on=s.granted_on,
                                      expires_on=s.expires_on, card_expires=comp.card_expires,
                                      waiting=c in waiting))
```

In `api/lms/api/app.py`, replace:
```python
    auth, competencies, matrix, overrides, people, policies, records, roles, uploads,
```
with:
```python
    auth, competencies, matrix, overrides, people, policies, records, roles, tickets, uploads,
```

In `api/lms/api/app.py`, replace:
```python
v1.include_router(policies.router)
```
with:
```python
v1.include_router(policies.router)
v1.include_router(tickets.router)
```

**Step 4: Run it, and the matrix, to see them pass**

Run: `cd api && .venv/bin/pytest tests/test_tickets.py tests/test_matrix.py -q`
Expected: `26 passed`.

**Step 5: Commit**

```
git add api/lms/api/routes/tickets.py api/lms/api/routes/matrix.py api/lms/api/app.py api/tests/test_tickets.py
git commit -m "Send in a ticket with its photos, and approve it or send it back, never your own" \
  -m "Approving is a grant from today to the card's date, recorded by the manager who checked it. A card that ran out while it waited is sent back, not approved. My training says which tickets wait for a check."
```

---

### Task 8: The daily job: reminders at 30, 14 and 0 days, and the Monday digest

**Files:**
- Create: `api/lms/services/outbox.py`, `api/lms/services/daily.py`
- Test: `api/tests/test_daily.py`

**Step 1: Write the failing test**

`api/tests/test_daily.py`:
```python
"""The daily job: reminders at 30, 14 and 0 days to learners with an email,
and a digest of what is expiring and lapsed for each manager on Mondays.
Each is queued once, however often the job runs."""
from datetime import date

import pytest

import yard
from conftest import make_person
from lms.config import get_settings
from lms.models import Outbox
from lms.services import daily

MONDAY = date(2026, 10, 12)


@pytest.fixture
def kim(client, db, manager_headers, learner):
    """Kim has an email; her forklift licence is good until 11 Nov 2026,
    30 days after the Monday the tests start on."""
    yard.build(client, manager_headers)
    learner.email = "kim@example.com.au"
    db.commit()
    yard.give_roles(client, manager_headers, "LL042", "forklift-operator")
    yard.grant(client, manager_headers, "LL042", "forklift-licence", "2025-01-01",
               expires_on="2026-11-11")
    yard.grant(client, manager_headers, "LL042", "site-induction", "2026-01-01")
    return learner


def emails(db, prefix="reminder"):
    db.expire_all()
    rows = db.query(Outbox).filter(Outbox.key.startswith(prefix)).order_by(Outbox.id).all()
    return [(r.payload["to"], r.payload["subject"]) for r in rows]


def on(db, *days):
    for d in days:
        daily.run(db, d)


def test_reminders_at_30_14_and_0_days_each_once(db, kim):
    on(db, date(2026, 10, 12), date(2026, 10, 12), date(2026, 10, 20))
    assert emails(db) == [("kim@example.com.au", "Forklift licence: 30 days left")]
    on(db, date(2026, 10, 28), date(2026, 11, 5))
    assert emails(db)[1:] == [("kim@example.com.au", "Forklift licence: 14 days left")]
    on(db, date(2026, 11, 11), date(2026, 11, 12), date(2026, 12, 1))
    assert emails(db)[2:] == [("kim@example.com.au", "Forklift licence: today is its last day")]


def test_a_day_the_worker_missed_still_gets_the_reminder_it_owed(db, kim):
    on(db, date(2026, 11, 2))   # 9 days left: the 14-day one, not the 30
    assert emails(db) == [("kim@example.com.au", "Forklift licence: 14 days left")]


def test_what_the_reminder_says(db, kim, monkeypatch):
    monkeypatch.setattr(get_settings(), "public_url", "https://lms.example.com.au")
    on(db, MONDAY)
    text = db.query(Outbox).filter(Outbox.key.startswith("reminder")).one().payload["text"]
    assert text.startswith("Hi Kim Lee,\n\nYour Forklift licence is good until 11 Nov 2026, "
                           "30 days from now.")
    assert "Open Simple LMS: https://lms.example.com.au/learn/" in text


def test_no_email_no_reminder(db, kim):
    kim.email = None
    db.commit()
    on(db, MONDAY)
    assert emails(db) == []


def test_a_renewed_ticket_is_reminded_afresh(client, db, manager_headers, kim):
    on(db, MONDAY)
    yard.grant(client, manager_headers, "LL042", "forklift-licence", "2026-10-12",
               expires_on="2026-11-30")
    on(db, date(2026, 11, 1))
    assert [s for _, s in emails(db)] == ["Forklift licence: 30 days left",
                                          "Forklift licence: 30 days left"]


def test_a_waived_one_is_not_reminded(client, db, manager_headers, kim):
    client.post("/v1/people/LL042/overrides", headers=manager_headers,
                json={"competency": "forklift-licence", "kind": "waive", "note": "office only now"})
    on(db, MONDAY)
    assert emails(db) == []


def test_managers_get_a_digest_on_mondays(client, db, manager_headers, kim):
    make_person(db, "LL043", "Ash Patel", email="ash@example.com.au")
    yard.give_roles(client, manager_headers, "LL043", "picker")
    yard.grant(client, manager_headers, "LL043", "site-induction", "2024-09-01")   # lapsed
    on(db, MONDAY, MONDAY)
    assert emails(db, "digest") == [("mel@example.com.au", "Training this week: 1 lapsed, 1 expiring")]
    text = db.query(Outbox).filter(Outbox.key.startswith("digest")).one().payload["text"]
    assert "Lapsed:\n- Ash Patel (LL043): Site induction, ran out after 1 Sep 2026" in text
    assert ("Expiring in the next 30 days:\n- Kim Lee (LL042): Forklift licence, good until "
            "11 Nov 2026") in text
    on(db, date(2026, 10, 13))   # a Tuesday
    assert len(emails(db, "digest")) == 1
    on(db, date(2026, 10, 19))   # the next Monday
    assert len(emails(db, "digest")) == 2


def test_no_digest_when_nothing_is_due(db, manager):
    on(db, MONDAY)
    assert emails(db, "digest") == []


def test_reminder_days():
    assert [daily.reminder_for(d) for d in (30, 29, 15, 14, 1, 0)] == [30, 30, 30, 14, 14, 0]
```

**Step 2: Run it to see it fail**

Run: `cd api && .venv/bin/pytest tests/test_daily.py -q`
Expected: FAIL: `ImportError: cannot import name 'daily' from 'lms.services'`.

**Step 3: Minimal implementation**

`api/lms/services/outbox.py`:
```python
"""Putting something on the queue the worker drains."""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session as Db

from lms.models import Outbox


def queue_email(db: Db, key: str, to: str, subject: str, text: str,
                now: datetime | None = None) -> bool:
    """Queue an email once: a second time with the same key does nothing.
    True when it was queued now."""
    stmt = insert(Outbox).values(
        kind="email", key=key, payload={"to": to, "subject": subject, "text": text},
        status="pending", attempts=0, next_attempt_at=now or datetime.now(UTC),
    ).on_conflict_do_nothing(index_elements=["key"]).returning(Outbox.id)
    return db.execute(stmt).scalar() is not None
```

`api/lms/services/daily.py`:
```python
"""The daily job, run by the worker each morning: a reminder to each
learner with an email when something of theirs has 30, 14 or 0 days left,
and on Mondays a digest of what is expiring and lapsed for each manager.
Status comes from status.py, as everywhere (rule 2). Each email has its
own key in the outbox, so running the job again sends nothing twice."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session as Db

from lms.config import get_settings
from lms.models import Person
from lms.services import outbox, standing

# days left on the last good day's count: 30, 14, and the day itself
REMINDER_DAYS = (30, 14, 0)
MONDAY = 0
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def formatted(d: date) -> str:
    """1 Nov 2026, day first as Australians write it."""
    return f"{d.day} {MONTHS[d.month - 1]} {d.year}"


def reminder_for(days_left: int) -> int:
    """Which reminder is due: the nearest of 30, 14 and 0 not yet passed, so a
    day the worker missed still gets the one it was owed."""
    return min(t for t in REMINDER_DAYS if t >= days_left)


@dataclass
class Item:
    person: Person
    name: str
    status: str
    expires_on: date


def _where_to(path: str) -> str:
    url = get_settings().public_url
    return f"\n\nOpen Simple LMS: {url}{path}" if url else ""


def reminder(person: Person, name: str, expires_on: date, days: int) -> tuple[str, str]:
    if days == 0:
        subject = f"{name}: today is its last day"
        when = f"Your {name} is good until the end of today, {formatted(expires_on)}."
    else:
        subject = f"{name}: {days} days left"
        when = f"Your {name} is good until {formatted(expires_on)}, {days} days from now."
    text = (f"Hi {person.name},\n\n{when} Renew it before then, and it will show in "
            f"My training.{_where_to('/learn/')}\n\nIf you have already done it, ask your "
            "supervisor to check it is recorded.\n\nSimple LMS")
    return subject, text


def digest(manager: Person, items: list[Item]) -> tuple[str, str]:
    lapsed = [i for i in items if i.status == "lapsed"]
    expiring = [i for i in items if i.status == "expiring"]
    subject = f"Training this week: {len(lapsed)} lapsed, {len(expiring)} expiring"
    lines = [f"Hi {manager.name},", ""]
    if lapsed:
        lines += ["Lapsed:"] + [f"- {i.person.name} ({i.person.code}): {i.name}, ran out after "
                                f"{formatted(i.expires_on)}" for i in lapsed] + [""]
    if expiring:
        lines += ["Expiring in the next 30 days:"] + [
            f"- {i.person.name} ({i.person.code}): {i.name}, good until {formatted(i.expires_on)}"
            for i in expiring] + [""]
    text = "\n".join(lines).rstrip() + _where_to("/") + "\n\nSimple LMS"
    return subject, text


def run(db: Db, today: date, now: datetime | None = None) -> dict[str, int]:
    """Queue today's reminders and (on a Monday) the digests. Returns how
    many were queued now; anything an earlier run queued is not queued again."""
    queued = {"reminders": 0, "digests": 0}
    people = db.execute(select(Person).where(Person.active.is_(True))
                        .order_by(Person.name, Person.code)).scalars().all()
    st = standing.load(db, [p.id for p in people], today)
    items: list[Item] = []
    for p in people:
        for c in sorted(st.asked_for(p.id), key=lambda c: st.competencies[c].name):
            s = st.status(p.id, c)
            if s.status not in ("expiring", "lapsed"):
                continue
            name = st.competencies[c].name
            items.append(Item(p, name, s.status, s.expires_on))
            if s.status == "expiring" and p.email:
                days = reminder_for((s.expires_on - today).days)
                subject, text = reminder(p, name, s.expires_on, days)
                key = f"reminder:{p.id}:{c}:{s.expires_on.isoformat()}:{days}"
                queued["reminders"] += outbox.queue_email(db, key, p.email, subject, text, now)
    if today.weekday() == MONDAY and items:
        items.sort(key=lambda i: (i.expires_on, i.person.name, i.name))
        for m in people:
            if m.permission in ("manager", "admin") and m.email:
                subject, text = digest(m, items)
                key = f"digest:{m.id}:{today.isoformat()}"
                queued["digests"] += outbox.queue_email(db, key, m.email, subject, text, now)
    db.commit()
    return queued
```

**Step 4: Run it to see it pass**

Run: `cd api && .venv/bin/pytest tests/test_daily.py -q`
Expected: `9 passed`.

**Step 5: Commit**

```
git add api/lms/services/outbox.py api/lms/services/daily.py api/tests/test_daily.py
git commit -m "Queue reminders at 30, 14 and 0 days, and a Monday digest for managers" \
  -m "Status comes from status.py, as everywhere. Each email has its own key in the outbox, so running the job again queues nothing twice, and a day missed still gets the reminder it owed."
```

---

### Task 9: The worker: email with backoff, and the daily job each morning

**Files:**
- Create: `api/lms/services/mail.py`, `api/lms/worker.py`
- Modify: `api/tests/conftest.py`
- Test: `api/tests/test_worker.py`

**Step 1: Write the failing test**

In `api/tests/conftest.py`, replace:
```python
@pytest.fixture
def beaten_to_it(engine):
```
with:
```python
@pytest.fixture
def mailbox(monkeypatch):
    """A mail server of the test's own, set up as LMS_SMTP_* would be: what
    the worker sends lands in .sent. Set .refuse to an exception to make the
    next sends fail."""
    from lms.config import get_settings
    from lms.services import mail

    settings = get_settings()
    monkeypatch.setattr(settings, "smtp_host", "mail.example.com.au")
    monkeypatch.setattr(settings, "smtp_from", "Simple LMS <lms@example.com.au>")

    class Mailbox:
        def __init__(self):
            self.sent = []
            self.logins = []
            self.refuse: Exception | None = None

    box = Mailbox()

    class Server:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def login(self, user, password):
            box.logins.append((user, password))

        def send_message(self, msg):
            if box.refuse is not None:
                raise box.refuse
            box.sent.append(msg)

    monkeypatch.setattr(mail, "connect", lambda s: Server())
    return box


@pytest.fixture
def beaten_to_it(engine):
```

`api/tests/test_worker.py`:
```python
"""The worker sends each email in the outbox, retrying after 1 min, 5, 30
and 2 h, and runs the daily job once a day from LMS_DAILY_HOUR."""
import smtplib
from datetime import UTC, date, datetime, timedelta

import pytest

from conftest import all_at_once
from lms import worker
from lms.config import get_settings
from lms.models import Outbox
from lms.services import outbox

T0 = datetime(2026, 10, 12, 0, 0, tzinfo=UTC)


def queued(db, key="hello", to="kim@example.com.au"):
    outbox.queue_email(db, key, to, "Forklift licence: 30 days left", "Hi Kim", now=T0)
    db.commit()


def row(db, key="hello") -> Outbox:
    db.expire_all()
    return db.query(Outbox).filter_by(key=key).one()


def test_an_email_is_sent_once(db, mailbox):
    queued(db)
    assert worker.send_emails(db, now=T0) == 1
    [msg] = mailbox.sent
    assert (msg["To"], msg["From"], msg["Subject"]) == (
        "kim@example.com.au", "Simple LMS <lms@example.com.au>", "Forklift licence: 30 days left")
    assert msg.get_content().strip() == "Hi Kim"
    assert (row(db).status, row(db).attempts) == ("done", 1)
    assert worker.send_emails(db, now=T0 + timedelta(hours=1)) == 0


def test_the_same_key_is_queued_once(db):
    assert outbox.queue_email(db, "k", "a@example.com.au", "s", "t") is True
    assert outbox.queue_email(db, "k", "a@example.com.au", "s", "t") is False
    db.commit()
    assert db.query(Outbox).count() == 1


def test_emails_wait_until_smtp_is_set_up(db):
    queued(db)
    assert worker.send_emails(db, now=T0) == 0
    assert (row(db).status, row(db).attempts) == ("pending", 0)


def test_it_signs_in_to_the_mail_server_when_told_to(db, mailbox, monkeypatch):
    monkeypatch.setattr(get_settings(), "smtp_user", "lms")
    monkeypatch.setattr(get_settings(), "smtp_password", "app password")
    queued(db)
    worker.send_emails(db, now=T0)
    assert mailbox.logins == [("lms", "app password")]


def test_a_failure_is_tried_again_after_1_5_30_and_120_minutes(db, mailbox):
    queued(db)
    mailbox.refuse = smtplib.SMTPServerDisconnected("Connection unexpectedly closed")
    now = T0
    for wait in (60, 300, 1800, 7200):
        assert worker.send_emails(db, now=now) == 1
        r = row(db)
        assert r.status == "pending" and r.next_attempt_at == now + timedelta(seconds=wait)
        assert r.last_error == "SMTPServerDisconnected: Connection unexpectedly closed"
        # not before its time
        assert worker.send_emails(db, now=now + timedelta(seconds=wait - 1)) == 0
        now += timedelta(seconds=wait)
    worker.send_emails(db, now=now)
    assert (row(db).status, row(db).attempts) == ("failed", 5)
    assert worker.send_emails(db, now=now + timedelta(days=1)) == 0


def test_a_mail_server_that_cannot_be_reached_is_a_failure_not_a_crash(db, mailbox):
    queued(db)
    mailbox.refuse = ConnectionRefusedError(61, "Connection refused")
    worker.send_emails(db, now=T0)
    assert row(db).last_error.startswith("ConnectionRefusedError")


def test_it_comes_good_on_a_later_try(db, mailbox):
    queued(db)
    mailbox.refuse = smtplib.SMTPDataError(451, b"try again later")
    worker.send_emails(db, now=T0)
    mailbox.refuse = None
    worker.send_emails(db, now=T0 + timedelta(minutes=1))
    assert (row(db).status, row(db).attempts, row(db).last_error) == ("done", 2, None)
    assert len(mailbox.sent) == 1


def test_two_workers_at_once_send_each_email_once(db, engine, mailbox):
    from sqlalchemy.orm import Session

    for n in range(6):
        queued(db, key=f"k{n}")

    def one_worker():
        with Session(engine) as s:
            return worker.send_emails(s, now=T0)

    assert sum(all_at_once(2, one_worker)) == 6
    assert len(mailbox.sent) == 6


@pytest.mark.parametrize("utc,due", [
    # 6 am in Melbourne (AEDT, UTC+11) is 7 pm UTC the day before
    (datetime(2026, 10, 11, 18, 59, tzinfo=UTC), None),
    (datetime(2026, 10, 11, 19, 0, tzinfo=UTC), date(2026, 10, 12)),
    (datetime(2026, 10, 12, 12, 59, tzinfo=UTC), date(2026, 10, 12)),
    # just past midnight in Melbourne: a new day, but before six
    (datetime(2026, 10, 12, 13, 30, tzinfo=UTC), None),
])
def test_the_daily_job_is_due_from_six_in_the_morning_where_the_business_is(utc, due):
    assert worker.Daily().due(utc) == due


def test_the_daily_job_runs_once_a_day(db, monkeypatch):
    runs = []
    monkeypatch.setattr(worker.daily, "run", lambda s, day, now: runs.append(day) or
                        {"reminders": 0, "digests": 0})
    today = worker.Daily()
    morning = datetime(2026, 10, 11, 20, 0, tzinfo=UTC)
    worker.run_once(db, today, now=morning)
    worker.run_once(db, today, now=morning + timedelta(hours=3))
    worker.run_once(db, today, now=morning + timedelta(days=1))
    assert runs == [date(2026, 10, 12), date(2026, 10, 13)]


def test_run_once_queues_the_days_emails_then_sends_them(client, db, mailbox, manager_headers,
                                                         learner):
    import yard

    yard.build(client, manager_headers)
    learner.email = "kim@example.com.au"
    db.commit()
    yard.give_roles(client, manager_headers, "LL042", "forklift-operator")
    yard.grant(client, manager_headers, "LL042", "forklift-licence", "2025-01-01",
               expires_on="2026-11-11")
    assert worker.run_once(db, worker.Daily(), now=datetime(2026, 10, 11, 20, 0, tzinfo=UTC)) >= 1
    assert "Forklift licence: 30 days left" in [m["Subject"] for m in mailbox.sent]


def test_the_connection_is_encrypted_as_the_settings_say(monkeypatch):
    from lms.config import Settings
    from lms.services import mail

    made = []

    class SMTP:
        def __init__(self, host, port, timeout, context=None):
            made.append((type(self).__name__, host, port))

        def starttls(self, context):
            made.append("starttls")

    class SMTP_SSL(SMTP):
        pass

    monkeypatch.setattr(mail.smtplib, "SMTP", SMTP)
    monkeypatch.setattr(mail.smtplib, "SMTP_SSL", SMTP_SSL)
    mail.connect(Settings(smtp_host="mail.example.com.au"))
    mail.connect(Settings(smtp_host="mail.example.com.au", smtp_port=465, smtp_security="ssl"))
    mail.connect(Settings(smtp_host="relay", smtp_port=25, smtp_security="none"))
    assert made == [("SMTP", "mail.example.com.au", 587), "starttls",
                    ("SMTP_SSL", "mail.example.com.au", 465), ("SMTP", "relay", 25)]
```

**Step 2: Run it to see it fail**

Run: `cd api && .venv/bin/pytest tests/test_worker.py -q`
Expected: FAIL: `ImportError: cannot import name 'worker' from 'lms'`.

**Step 3: Minimal implementation**

`api/lms/services/mail.py`:
```python
"""Email through SMTP, with the settings in .env (LMS_SMTP_*). Only the
worker sends, from the outbox; nothing waits on an email."""
from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage

from lms.config import Settings, get_settings

TIMEOUT_SECONDS = 20


def set_up() -> bool:
    s = get_settings()
    return bool(s.smtp_host and s.smtp_from)


def connect(s: Settings) -> smtplib.SMTP:
    """A connection to the mail server, encrypted as the settings say."""
    if s.smtp_security == "ssl":
        return smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, timeout=TIMEOUT_SECONDS,
                                context=ssl.create_default_context())
    smtp = smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=TIMEOUT_SECONDS)
    if s.smtp_security == "starttls":
        smtp.starttls(context=ssl.create_default_context())
    return smtp


def message(payload: dict) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = get_settings().smtp_from
    msg["To"] = payload["to"]
    msg["Subject"] = payload["subject"]
    msg.set_content(payload["text"])
    return msg


def send(payload: dict) -> str | None:
    """Send one email: None when the server took it, else what went wrong."""
    s = get_settings()
    try:
        with connect(s) as smtp:
            if s.smtp_user:
                smtp.login(s.smtp_user, s.smtp_password)
            smtp.send_message(message(payload))
    except (smtplib.SMTPException, OSError) as e:
        return f"{type(e).__name__}: {e}"
    return None
```

`api/lms/worker.py`:
```python
"""Drains the outbox (emails, for now) and runs the daily job. Run as
`python -m lms.worker`.

A failed try is tried again after 1 min, 5, 30 and 2 h. The try after the
2 h wait is the last: if it fails too, the row is `failed` and stays, with
its last error, for someone to look at.

The daily job runs once a day from LMS_DAILY_HOUR in LMS_TIMEZONE, and
again whenever the worker starts after that hour: each email it queues has
its own key, so running it twice sends nothing twice.
"""
from __future__ import annotations

import logging
import time
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from lms.config import get_settings
from lms.db import get_sessionmaker
from lms.models import Outbox
from lms.services import daily, mail

log = logging.getLogger("lms.worker")

BACKOFF = (60, 300, 1800, 7200)


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


def _claim(session: Session, now: datetime) -> Outbox | None:
    """The next row due, locked so a second worker passes it by. One row per
    transaction, so a slow mail server holds up only that row."""
    return session.execute(
        select(Outbox)
        .where(Outbox.status == "pending", Outbox.next_attempt_at <= now)
        .order_by(Outbox.next_attempt_at, Outbox.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    ).scalar_one_or_none()


def _send_one(session: Session, now: datetime | None) -> bool:
    row = _claim(session, now or clock())
    if row is None:
        return False
    error = mail.send(row.payload)
    # after the answer, not before: a slow server would date it in the past
    answered = now or clock()
    row.attempts += 1
    if error is None:
        row.status = "done"
        row.done_at = answered
        row.last_error = None
        log.info("email %s sent", row.key)
    else:
        retry_later(row, answered, error)
        log.warning("email %s try %d failed%s: %s", row.key, row.attempts,
                    "; given up" if row.status == "failed" else "", error)
    session.commit()
    return True


def send_emails(session: Session, now: datetime | None = None, limit: int = 50) -> int:
    """Send every email that is due. Returns how many were tried."""
    if not mail.set_up():
        return 0    # they wait, untried, until SMTP is set up
    tried = 0
    while tried < limit and _send_one(session, now):
        tried += 1
    return tried


class Daily:
    """Remembers the last day the daily job ran in this worker."""

    def __init__(self) -> None:
        self.last: date | None = None

    def due(self, now: datetime) -> date | None:
        """Today in LMS_TIMEZONE, if the job is due: past LMS_DAILY_HOUR and
        not yet run today."""
        settings = get_settings()
        local = now.astimezone(ZoneInfo(settings.timezone))
        if local.hour < settings.daily_hour or local.date() == self.last:
            return None
        return local.date()


def run_once(session: Session, today: Daily, now: datetime | None = None) -> int:
    """The daily job if it is due, then the emails. Returns how many emails
    were tried."""
    day = today.due(now or clock())
    if day is not None:
        queued = daily.run(session, day, now)
        today.last = day
        log.info("daily job for %s: %d reminders, %d digests queued", day,
                 queued["reminders"], queued["digests"])
    return send_emails(session, now)


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
    settings = get_settings()
    make_session = get_sessionmaker()
    with make_session() as session:
        wait_for_schema(session)
    if not mail.set_up():
        log.warning("no LMS_SMTP_HOST and LMS_SMTP_FROM: emails wait in the outbox until set")
    log.info("worker started, polling every %ss; daily job from %02d:00 %s",
             settings.worker_poll_seconds, settings.daily_hour, settings.timezone)
    today = Daily()
    while True:
        try:
            with make_session() as session:
                done = run_once(session, today)
        except Exception:  # keep the loop alive; log and back off
            log.exception("worker loop error")
            done = 0
        if done == 0:
            time.sleep(settings.worker_poll_seconds)


if __name__ == "__main__":
    main()
```

**Step 4: Run it to see it pass**

Run: `cd api && .venv/bin/pytest tests/test_worker.py -q`
Expected: `15 passed`.

**Step 5: Commit**

```
git add api/lms/services/mail.py api/lms/worker.py api/tests/conftest.py api/tests/test_worker.py
git commit -m "Send the outbox's emails with backoff, and run the daily job each morning" \
  -m "Tried again after 1 min, 5, 30 and 2 h, then failed. Without SMTP set up the emails wait, untried. The daily job runs from LMS_DAILY_HOUR in LMS_TIMEZONE, and again on a restart, harmlessly."
```

---

### Task 10: `lms daily-job`

**Files:**
- Modify: `api/lms/cli.py` (in full below)
- Test: `api/tests/test_cli.py`

**Step 1: Write the failing test**

Append to `api/tests/test_cli.py`:
```python
def test_daily_job_queues_the_reminders_now(client, db, manager_headers, learner, capsys):
    import yard
    from lms.models import Outbox

    yard.build(client, manager_headers)
    learner.email = "kim@example.com.au"
    db.commit()
    yard.give_roles(client, manager_headers, "LL042", "forklift-operator")
    yard.grant(client, manager_headers, "LL042", "forklift-licence", "2025-01-01",
               expires_on="2026-11-11")
    assert main(["daily-job", "--on", "2026-10-13"]) == 0
    assert capsys.readouterr().out.strip() == (
        "2026-10-13: 1 reminders and 0 digests queued; the worker sends them")
    assert main(["daily-job", "--on", "2026-10-13"]) == 0
    assert "0 reminders" in capsys.readouterr().out
    assert db.query(Outbox).count() == 1
```

**Step 2: Run it to see it fail**

Run: `cd api && .venv/bin/pytest tests/test_cli.py -q`
Expected: FAIL: `SystemExit: 2` (`invalid choice: 'daily-job'`).

**Step 3: Minimal implementation**

`api/lms/cli.py`:
```python
"""Command line for what has to happen before anyone can sign in."""
from __future__ import annotations

import argparse
import getpass
import sys
from datetime import date

from sqlalchemy import or_, select

from lms.api.schemas import normal_code
from lms.db import get_sessionmaker
from lms.models import PERMISSIONS, Person
from lms.services import access, clock, daily


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


def cmd_daily_job(args) -> int:
    """What the worker does each morning, now. Safe to run again: nothing
    already queued is queued twice."""
    day = date.fromisoformat(args.on) if args.on else clock.today()
    with get_sessionmaker()() as db:
        queued = daily.run(db, day)
    print(f"{day.isoformat()}: {queued['reminders']} reminders and {queued['digests']} digests "
          "queued; the worker sends them")
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

    p = sub.add_parser("daily-job", help="queue the reminders (and on a Monday the digests) now")
    p.add_argument("--on", help="as if today were this date, YYYY-MM-DD (to try it out)")
    p.set_defaults(func=cmd_daily_job)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
```

**Step 4: Run it, and the whole suite, to see them pass**

Run: `cd api && .venv/bin/pytest tests/test_cli.py -q`
Expected: `4 passed`.

Run: `cd api && .venv/bin/pytest -q`
Expected: `222 passed`.

**Step 5: Commit**

```
git add api/lms/cli.py api/tests/test_cli.py
git commit -m "Add lms daily-job to queue the day's reminders now"
```

---

### Task 11: The worker and the uploads volume in Compose, blob images through Caddy, and CI

**Files:**
- Modify: `docker-compose.yml`, `deploy/Caddyfile`, `.env.example`, `.github/workflows/ci.yml`

**Step 1: The check that fails**

Run: `docker compose up -d --build db api worker`
Expected: `no such service: worker`.

**Step 2: Implementation**

In `docker-compose.yml`, replace:
```yaml
      LMS_TIMEZONE: ${LMS_TIMEZONE:-Australia/Melbourne}
    depends_on:
      db:
        condition: service_healthy
    expose:
```
with:
```yaml
      LMS_TIMEZONE: ${LMS_TIMEZONE:-Australia/Melbourne}
    volumes:
      # tickets' photos and policy signatures (LMS_UPLOAD_DIR)
      - uploads:/data/uploads
    depends_on:
      db:
        condition: service_healthy
    expose:
```

In `docker-compose.yml`, replace:
```yaml
  # The worker arrives with build step 2, with the queue it drains (the
  # daily job, email reminders, and later the webhooks and print jobs).
```
with:
```yaml
  # Sends the emails in the outbox with backoff, and runs the daily job
  # (reminders, and the managers' Monday digest). Waits for the api's
  # migrations. Later steps give it the webhooks and print jobs.
  worker:
    build: ./api
    restart: unless-stopped
    command: python -m lms.worker
    environment:
      LMS_DATABASE_URL: postgresql+psycopg://${POSTGRES_USER:-lms}:${POSTGRES_PASSWORD}@db:5432/${POSTGRES_DB:-lms}
      LMS_TIMEZONE: ${LMS_TIMEZONE:-Australia/Melbourne}
      LMS_PUBLIC_URL: ${LMS_PUBLIC_URL:-}
      LMS_DAILY_HOUR: ${LMS_DAILY_HOUR:-6}
      LMS_SMTP_HOST: ${LMS_SMTP_HOST:-}
      LMS_SMTP_PORT: ${LMS_SMTP_PORT:-587}
      LMS_SMTP_USER: ${LMS_SMTP_USER:-}
      LMS_SMTP_PASSWORD: ${LMS_SMTP_PASSWORD:-}
      LMS_SMTP_FROM: ${LMS_SMTP_FROM:-}
      LMS_SMTP_SECURITY: ${LMS_SMTP_SECURITY:-starttls}
    depends_on:
      db:
        condition: service_healthy
```

In `docker-compose.yml`, replace:
```yaml
volumes:
  pgdata:
```
with:
```yaml
volumes:
  pgdata:
  uploads:
```

In `deploy/Caddyfile`, replace:
```
	# The learner app: a PWA under /learn/.
```
with:
```
	# Photos and signatures are fetched with the session's token and shown
	# from blob: URLs, so both apps allow blob: images and nothing else new.

	# The learner app: a PWA under /learn/.
```

In `deploy/Caddyfile`, replace each of the two (the learner app's and the desktop's):
```
header Content-Security-Policy "default-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
```
with:
```
header Content-Security-Policy "default-src 'self'; img-src 'self' blob:; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
```

In `.env.example`, replace:
```
# Caddy: the public host name.
```
with:
```
# Where people open Simple LMS, for the links in emails, e.g.
# https://lms.example.com.au. Leave empty and the emails carry no link.
LMS_PUBLIC_URL=

# Email (the worker sends reminders and the managers' Monday digest).
# Without LMS_SMTP_HOST and LMS_SMTP_FROM the emails wait in the outbox,
# unsent, until they are set. LMS_SMTP_SECURITY is starttls (port 587),
# ssl (port 465) or none (a relay on your own network).
LMS_SMTP_HOST=
LMS_SMTP_PORT=587
LMS_SMTP_USER=
LMS_SMTP_PASSWORD=
LMS_SMTP_FROM=Simple LMS <lms@example.com.au>
LMS_SMTP_SECURITY=starttls
# The hour (0 to 23, in LMS_TIMEZONE) from which the daily job runs each day.
LMS_DAILY_HOUR=6

# Caddy: the public host name.
```

Add the same settings to your own `.env` (copy the block above under `LMS_TIMEZONE`).

In `.github/workflows/ci.yml`, replace:
```yaml
        run: docker compose up -d --build db api
      - name: The API answers and the migrations ran
```
with:
```yaml
        run: docker compose up -d --build db api worker
      - name: The API answers, the migrations ran and the worker started
```

In `.github/workflows/ci.yml`, replace:
```yaml
          # both append-only triggers are there on a real install
          docker compose exec -T db psql -U lms -d lms -tAc \
            "select count(*) from pg_trigger where tgname like '%_append_only'" | grep -qx 2
```
with:
```yaml
          # the append-only triggers and the ticket's decide-once one are there
          docker compose exec -T db psql -U lms -d lms -tAc \
            "select count(*) from pg_trigger where tgname like '%_append_only'" | grep -qx 3
          docker compose exec -T db psql -U lms -d lms -tAc \
            "select count(*) from pg_trigger where tgname = 'ticket_submission_decide_once'" | grep -qx 1
          for i in $(seq 1 30); do
            if docker compose logs worker | grep -q "worker started"; then up=1; break; fi
            sleep 2
          done
          test "${up:-0}" = 1 || (docker compose logs worker; exit 1)
```

**Step 3: Run the check to see it pass**

```
docker compose up -d --build db api worker
for i in $(seq 1 30); do curl -fsS http://127.0.0.1:8033/v1/health && break; sleep 2; done; echo
docker compose exec -T db psql -U lms -d lms -tAc \
  "select string_agg(tgname, ',' order by tgname) from pg_trigger where not tgisinternal"
docker compose logs worker | tail -3
```
Expected: `{"status":"ok"}`, then
`competency_record_append_only,person_override_append_only,policy_version_append_only,ticket_submission_decide_once`,
then the worker's log ending in lines like:
```
WARNING lms.worker no LMS_SMTP_HOST and LMS_SMTP_FROM: emails wait in the outbox until set
INFO lms.worker worker started, polling every 5.0s; daily job from 06:00 Australia/Melbourne
INFO lms.worker daily job for 2026-10-13: 0 reminders, 0 digests queued
```
(the last only after 6 am in Melbourne).

```
docker compose up -d caddy
curl -skI https://localhost:8643/learn/ | grep -i content-security-policy
```
Expected: `content-security-policy: default-src 'self'; img-src 'self' blob:; object-src 'none'; …` (with `LMS_HTTPS_PORT=8643` in `.env` for local work, as in step 1).

**Step 4: Commit**

```
git add docker-compose.yml deploy/Caddyfile .env.example .github/workflows/ci.yml
git commit -m "Run the worker in Compose, keep uploads on a volume, and let both apps show blob images" \
  -m "SMTP, the public URL and the daily job's hour come from .env. CI starts the worker and checks the new triggers."
```

---

### Task 12: `docs/api.md`

**Files:**
- Modify: `docs/api.md`

**Step 1: Write it**

In `docs/api.md`, replace:
```markdown
| `learner` | `training:read` |
| `supervisor` | `training:read`, `matrix:read`, `roles:read`, `competencies:read` |
| `manager` | the supervisor's, plus `people:read`, `people:write`, `roles:write`, `competencies:write`, `records:write` |
| `admin` | `*` |

A session signed in with a **PIN** carries `training:read` only, whoever it
is: a PIN is short, so it opens the learner app's own training and nothing
more.
```
with:
```markdown
| `learner` | `training:read`, `training:write` |
| `supervisor` | `training:read`, `training:write`, `matrix:read`, `roles:read`, `competencies:read` |
| `manager` | the supervisor's, plus `people:read`, `people:write`, `roles:write`, `competencies:write`, `records:write`, `tickets:verify` |
| `admin` | `*` |

`training:write` is doing your own training: signing a policy, sending in a
ticket. A session signed in with a **PIN** carries `training:read` and
`training:write` only, whoever it is: a PIN is short, so it opens the
learner app's own training and nothing more.
```

In `docs/api.md`, replace:
```markdown
  induction", "kind": "module" | "practical" | "ticket" | "policy",
  "refresher_months"?: 1 to 240 }` → `201`.
```
with:
```markdown
  induction", "kind": "module" | "practical" | "ticket" | "policy",
  "refresher_months"?: 1 to 240, "card_expires"?: true }` → `201`.
  `card_expires` is for a ticket: whether its card has an expiry date that
  people type in (true unless said otherwise).
```

In `docs/api.md`, replace:
```markdown
- `PATCH /v1/competencies/{key}` — `name` and/or `refresher_months` (`null`
  for none). The kind cannot change.
```
with:
```markdown
- `PATCH /v1/competencies/{key}` — `name`, `refresher_months` (`null` for
  none) and/or `card_expires`. The kind cannot change.
```

In `docs/api.md`, replace:
```markdown
Each competency: `{ "id", "key", "name", "kind", "refresher_months", "active", "created_at" }`.
In step 1 every kind is recorded by hand; modules, practicals, tickets and
policies get their own ways in with later build steps.
```
with:
```markdown
Each competency: `{ "id", "key", "name", "kind", "refresher_months", "card_expires", "active", "created_at" }`.
Every kind can still be recorded by hand. Policies are signed in the
learner app and tickets sent in from it (below); modules and practicals get
their own ways in with later build steps.
```

In `docs/api.md`, replace:
```markdown
     "note": "LF 0012345, sighted", "recorded_by": { "code": "MG001", "name": "Mel Grant" },
     "created_at": "…" }]
  ```
```
with:
```markdown
     "note": "LF 0012345, sighted", "recorded_by": { "code": "MG001", "name": "Mel Grant" },
     "policy_version": null, "signed_name": null, "signature": null, "ticket": null,
     "created_at": "…" }]
  ```
  `policy_version` is the policy version a grant is for; `signed_name` and
  `signature` (an upload id) are there when it was signed in the learner
  app; `ticket` is the ticket's id when a manager approved one.
```

In `docs/api.md`, replace:
```markdown
  must be after it. Nobody records their own (`403 { "code": "own_record" }`).
```
with:
```markdown
  must be after it. Nobody records their own (`403 { "code": "own_record" }`).
  A policy recorded by hand (signed on paper) is for its newest version.
```

In `docs/api.md`, replace:
```markdown
The last good day is the record's `expires_on` if it has one, else
`granted_on` plus the competency's refresher months, else never. Today is
the date in `LMS_TIMEZONE` (default `Australia/Melbourne`).
```
with:
```markdown
The last good day is the record's `expires_on` if it has one, else
`granted_on` plus the competency's refresher months, else never. Today is
the date in `LMS_TIMEZONE` (default `Australia/Melbourne`).

A **policy** with a version published counts only for its newest version:
a grant for an older version (or from before there were versions) is
`missing` again until they sign the new one.
```

In `docs/api.md`, replace:
````markdown
`{ "person": { "code", "name" }, "today", "items": [{ "key", "name", "kind", "status", "granted_on", "expires_on" }] }`.
The learner app shows it as Overdue (`lapsed`, `missing`), Due soon
(`expiring`) and Done (`current`).
````
with:
````markdown
`{ "person": { "code", "name" }, "today", "items": [{ "key", "name", "kind", "status", "granted_on", "expires_on", "card_expires", "waiting" }] }`.
`waiting` is true while a ticket they sent in waits for a manager's check.
The learner app shows it as Overdue (`lapsed`, `missing`), Due soon
(`expiring`) and Done (`current`).

## Files

Tickets' photos (or a PDF) and policy signatures. Sent before the ticket or
signature that names them; kept on the host under `LMS_UPLOAD_DIR`
(`/data/uploads`), named by a random id.

- `POST /v1/uploads?purpose=ticket|signature` (`training:write`) — the file
  as the request body (any `Content-Type`: what counts is its first bytes)
  → `201 { "id", "purpose", "content_type", "size_bytes", "created_at" }`.
  A ticket may be a JPEG, PNG or PDF of up to 20 MB; a signature a PNG of
  up to 1 MB. Anything else is `415 { "code": "unsupported_type" }`; too big
  is `413 { "code": "too_large" }`, before the body is read when its length
  says so.
- `GET /v1/uploads/{id}` — the file, for the person it belongs to, their
  supervisor, and managers and admins; anyone else gets `404`. Sent with
  `Cache-Control: private, no-store`, `Content-Security-Policy: default-src
  'none'; sandbox` and `Content-Disposition: inline; filename="<id>.<ext>"`.

## Policies

- `POST /v1/policies/{key}/versions` (`competencies:write`) — `{ "body",
  "note"? }` → `201`, the next version (1, 2, 3 …). Versions are never
  changed or deleted: what someone signed stays as they read it. Everyone
  asked for the policy needs to sign the new one.
- `GET /v1/policies/{key}/versions` (`competencies:read`) — newest first:
  `[{ "id", "version", "body", "note", "published_by": { "code", "name" }, "created_at" }]`.
- `GET /v1/policies/{key}` (`training:read`) — the version to sign now:
  `{ "key", "name", "version": { … } }`; `404` until one is published.
- `POST /v1/policies/{key}/sign` (`training:write`) — your own signature:
  `{ "version", "signed_name", "signature" }` (an upload with purpose
  `signature`, yours) → `201`, the record (above). `version` is the one you
  read: if a newer one came out meanwhile, `409 { "code": "new_version" }`.
  The name is yours as Simple LMS has it, case and spacing aside (`422`).
  Once per version (`409 { "code": "already_signed" }`). A key that is not a
  policy is `404`; a deactivated policy `409 { "code": "inactive" }`.

## Tickets

- `POST /v1/tickets` (`training:write`) — your own: `{ "competency",
  "number", "expires_on"?, "front", "back"? }` (`front` and `back` are your
  uploads with purpose `ticket`) → `201`, waiting. The competency must be a
  ticket. `expires_on` (the card's last good day) is needed when the ticket's
  card expires and must be after today; it is left out when it doesn't.
  One waits at a time for each ticket (`409 { "code": "already_waiting" }`).
- `GET /v1/tickets?status=pending|approved|rejected` (`tickets:verify`) —
  the inbox, oldest first (`pending` unless asked).
- `GET /v1/people/{code}/tickets` (`training:read`; your own, your team's,
  or anyone's for a manager) — newest first.
- `POST /v1/tickets/{id}/approve` (`tickets:verify`) → `200`: a grant from
  today until the card's date, recorded by you, with the note `Ticket
  <number>, checked`. A card that ran out while it waited is `409 { "code":
  "card_ran_out" }`.
- `POST /v1/tickets/{id}/reject` (`tickets:verify`) — `{ "reason" }` →
  `200`. The person sees the reason.

Nobody approves or rejects their own, admins included (`403 { "code":
"own_ticket" }`). A ticket is decided once (`409 { "code": "decided" }`).
Each ticket:
```json
{ "id": 7, "person": { "code": "LL042", "name": "Kim Lee" },
  "competency": { "key": "forklift-licence", "name": "Forklift licence", "kind": "ticket" },
  "number": "LF0012345", "expires_on": "2031-03-01", "front": "…", "back": null,
  "status": "pending", "reason": null, "decided_by": null, "decided_at": null, "created_at": "…" }
```

## Emails and the daily job

The worker sends email through SMTP (`LMS_SMTP_*` in `.env`) from the
outbox, trying a failed one again after 1 minute, 5, 30 and 2 hours, then
leaving it `failed`. Each day from `LMS_DAILY_HOUR` (6 am by default, in
`LMS_TIMEZONE`) it queues:

- a reminder to each person with an email when something they are asked
  for has 30, 14 or 0 days left (the last good day itself), each once;
- on Mondays, a digest for each manager and admin with an email of what is
  lapsed and what is expiring, for everyone.

`lms daily-job [--on YYYY-MM-DD]` queues them now; nothing is queued twice.
````

**Step 2: Check it against the app**

Run: `cd api && .venv/bin/python -c "from lms.api.app import app; print(sorted({r.path for r in app.routes if r.path.startswith('/v1')}))"`
Expected: every path in the list has its section in `docs/api.md`; the new ones are `/v1/uploads`, `/v1/uploads/{upload_id}`, `/v1/policies/{key}`, `/v1/policies/{key}/versions`, `/v1/policies/{key}/sign`, `/v1/tickets`, `/v1/tickets/{ticket_id}/approve`, `/v1/tickets/{ticket_id}/reject` and `/v1/people/{code}/tickets`.

**Step 3: Commit**

```
git add docs/api.md
git commit -m "Document files, policies, tickets and the emails in docs/api.md"
```

---

### Task 13: The desktop's Inbox: check a ticket's photos, approve it or send it back

**Files:**
- Modify: `apps/desktop/src/api/types.ts`, `apps/desktop/src/api/client.ts`
- Create: `apps/desktop/src/ui/Picture.tsx`, `apps/desktop/src/pages/Inbox.tsx`
- Modify: `apps/desktop/src/App.tsx`, `apps/desktop/src/ui/Layout.tsx`
- Modify: `apps/desktop/src/test/harness.tsx`, `apps/desktop/src/test/Rows.test.tsx`
- Test: `apps/desktop/src/test/client.test.ts` (in full below), `apps/desktop/src/test/Inbox.test.tsx`

**Step 1: Write the failing tests**

Mel, the harness's manager, checks tickets now. In `apps/desktop/src/test/harness.tsx`, replace:
```tsx
  scopes: ["training:read", "matrix:read", "roles:read", "competencies:read", "people:read", "people:write",
           "roles:write", "competencies:write", "records:write"],
```
with:
```tsx
  scopes: ["training:read", "training:write", "matrix:read", "roles:read", "competencies:read", "people:read",
           "people:write", "roles:write", "competencies:write", "records:write", "tickets:verify"],
```

A competency says whether its card runs out. In `apps/desktop/src/test/Rows.test.tsx`, replace:
```tsx
const INDUCTION: Competency = { id: 1, key: "site-induction", name: "Site induction", kind: "module", refresher_months: 24, active: true };
```
with:
```tsx
const INDUCTION: Competency = { id: 1, key: "site-induction", name: "Site induction", kind: "module", refresher_months: 24, card_expires: true, active: true };
```

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

  it("fetches a kept file with the token", async () => {
    client.token = "lms_s.abc";
    answers.push(new Response(new Uint8Array([0xff, 0xd8, 0xff]), { status: 200, headers: { "Content-Type": "image/jpeg" } }));
    const b = await client.blob("/v1/uploads/abc");
    expect(b.type).toBe("image/jpeg");
    expect(new Headers(calls[0].init.headers).get("Authorization")).toBe("Bearer lms_s.abc");
    answers.push(json(404, { detail: "no file abc" }));
    await expect(client.blob("/v1/uploads/abc")).rejects.toThrow("no file abc");
  });
});
```

`apps/desktop/src/test/Inbox.test.tsx`:
```tsx
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Ticket } from "../api/types";
import { MEL, json, renderApp, stubApi } from "./harness";

const KIMS: Ticket = {
  id: 7, person: { code: "LL042", name: "Kim Lee" },
  competency: { key: "forklift-licence", name: "Forklift licence", kind: "ticket" },
  number: "LF0012345", expires_on: "2031-03-01", front: "f-1", back: "b-1", status: "pending",
  reason: null, decided_by: null, decided_at: null, created_at: "2026-10-12T01:00:00Z",
};

function photos(url: string) {
  if (url.startsWith("/v1/uploads/")) {
    return new Response(new Uint8Array([0xff, 0xd8, 0xff]), { status: 200, headers: { "Content-Type": "image/jpeg" } });
  }
  return null;
}

describe("the inbox", () => {
  beforeEach(() => {
    URL.createObjectURL = vi.fn(() => "blob:photo");
    URL.revokeObjectURL = vi.fn();
  });

  it("lists the tickets waiting and shows one's photos", async () => {
    stubApi((_m, url) => url === "/v1/tickets" ? json(200, [KIMS]) : photos(url));
    renderApp("/inbox");
    await userEvent.click(await screen.findByRole("button", { name: /Kim Lee/ }));
    const drawer = await screen.findByRole("dialog", { name: "Forklift licence: Kim Lee" });
    expect(within(drawer).getByText("LF0012345")).toBeInTheDocument();
    expect(within(drawer).getByText("1 Mar 2031")).toBeInTheDocument();
    expect(await within(drawer).findByRole("img", { name: "The front" })).toHaveAttribute("src", "blob:photo");
    expect(within(drawer).getByRole("img", { name: "The back" })).toBeInTheDocument();
  });

  it("approves one, and it leaves the inbox", async () => {
    let waiting = [KIMS];
    const { calls } = stubApi((method, url) => {
      if (url === "/v1/tickets") return json(200, waiting);
      if (method === "POST" && url === "/v1/tickets/7/approve") { waiting = []; return json(200, { ...KIMS, status: "approved" }); }
      return photos(url);
    });
    renderApp("/inbox");
    await userEvent.click(await screen.findByRole("button", { name: /Kim Lee/ }));
    await userEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Approve" }));
    expect(await screen.findByText(/Nothing waiting/)).toBeInTheDocument();
    expect(calls.some((c) => c.method === "POST" && c.url === "/v1/tickets/7/approve")).toBe(true);
  });

  it("sends one back with a reason", async () => {
    let waiting = [KIMS];
    const { calls } = stubApi((method, url) => {
      if (url === "/v1/tickets") return json(200, waiting);
      if (method === "POST" && url === "/v1/tickets/7/reject") { waiting = []; return json(200, { ...KIMS, status: "rejected" }); }
      return photos(url);
    });
    renderApp("/inbox");
    await userEvent.click(await screen.findByRole("button", { name: /Kim Lee/ }));
    const drawer = await screen.findByRole("dialog");
    expect(within(drawer).getByRole("button", { name: "Reject" })).toBeDisabled();
    await userEvent.type(within(drawer).getByLabelText("Reason (they see this)"), "The photo is blurry");
    await userEvent.click(within(drawer).getByRole("button", { name: "Reject" }));
    await waitFor(() => expect(calls.find((c) => c.url === "/v1/tickets/7/reject")?.body).toEqual({ reason: "The photo is blurry" }));
  });

  it("doesn't offer a manager their own", async () => {
    const own = { ...KIMS, person: { code: MEL.code, name: MEL.name } };
    stubApi((_m, url) => url === "/v1/tickets" ? json(200, [own]) : photos(url));
    renderApp("/inbox");
    await userEvent.click(await screen.findByRole("button", { name: /Mel Grant/ }));
    const drawer = await screen.findByRole("dialog");
    expect(within(drawer).getByText("Nobody verifies their own ticket: ask another manager.")).toBeInTheDocument();
    expect(within(drawer).queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
  });

  it("is a tab for those who check tickets only", async () => {
    stubApi((_m, url) => url.startsWith("/v1/matrix") ? json(200, { today: "2026-10-12", competencies: [], people: [] })
      : url === "/v1/roles" ? json(200, { items: [], total: 0 }) : null,
    { ...MEL, permission: "supervisor", scopes: ["training:read", "training:write", "matrix:read", "roles:read", "competencies:read"] });
    renderApp("/");
    expect(await screen.findByRole("link", { name: "Matrix" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Inbox" })).not.toBeInTheDocument();
  });
});
```

**Step 2: Run them to see them fail**

Run: `cd apps/desktop && npm test`
Expected: FAIL: `Tests  5 failed | 28 passed (33)`: `client.blob is not a function`, and no Inbox at `/inbox` (the catch-all sends it to the matrix).

**Step 3: Minimal implementation**

In `apps/desktop/src/api/types.ts`, replace:
```ts
  refresher_months: number | null;
  active: boolean;
}
```
with:
```ts
  refresher_months: number | null;
  /** a ticket: whether its card has an expiry date to type in */
  card_expires: boolean;
  active: boolean;
}
```

In `apps/desktop/src/api/types.ts`, replace:
```ts
  note: string | null;
  recorded_by: PersonRef;
  created_at: string;
}
```
with:
```ts
  note: string | null;
  recorded_by: PersonRef;
  /** a policy: the version this grant is for */
  policy_version: number | null;
  /** signed in the learner app: the name typed, and the signature's upload id */
  signed_name: string | null;
  signature: string | null;
  /** a ticket a manager checked: its submission's id */
  ticket: number | null;
  created_at: string;
}

export interface PolicyVersion {
  id: number;
  version: number;
  body: string;
  note: string | null;
  published_by: PersonRef;
  created_at: string;
}

export interface Ticket {
  id: number;
  person: PersonRef;
  competency: CompetencyRef;
  number: string;
  expires_on: string | null;
  /** upload ids: GET /v1/uploads/{id} */
  front: string;
  back: string | null;
  status: "pending" | "approved" | "rejected";
  reason: string | null;
  decided_by: PersonRef | null;
  decided_at: string | null;
  created_at: string;
}
```

In `apps/desktop/src/api/client.ts`, replace:
```ts
  /** A file the API makes (the matrix as CSV), saved by the browser. */
```
with:
```ts
  /** A file kept by the API (a ticket's photo, a signature), fetched with the
   * session's token: an <img> can't send it. */
  async blob(path: string): Promise<Blob> {
    const res = await this.send("GET", path);
    if (!res.ok) throw new ApiError(res.status, await res.json().catch(() => null));
    return res.blob();
  }

  /** A file the API makes (the matrix as CSV), saved by the browser. */
```

`apps/desktop/src/ui/Picture.tsx`:
```tsx
import { useEffect, useState } from "react";
import { api } from "../api/client";

/** A ticket's photo or a signature, kept by the API. An <img> can't send the
 * session's token, so the bytes are fetched with it and shown from a blob:
 * URL, let go when it is gone. A PDF is offered to save instead. */
export function Picture({ upload, label, width = 240 }: { upload: string; label: string; width?: number }) {
  const [file, setFile] = useState<{ url: string; pdf: boolean } | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let live = true;
    let made: string | null = null;
    api.blob(`/v1/uploads/${encodeURIComponent(upload)}`)
      .then((b) => {
        if (!live) return;
        made = URL.createObjectURL(b);
        setFile({ url: made, pdf: b.type === "application/pdf" });
      })
      .catch(() => { if (live) setFailed(true); });
    return () => { live = false; if (made) URL.revokeObjectURL(made); };
  }, [upload]);
  if (failed) return <span className="small">{label} couldn't be loaded.</span>;
  if (!file) return <span className="small">Loading {label.toLowerCase()}…</span>;
  if (file.pdf) return <a className="btn" href={file.url} download={`${label}.pdf`}>Save {label.toLowerCase()} (PDF)</a>;
  return <img src={file.url} alt={label} width={width} style={{ borderRadius: 10, display: "block", border: "1px solid var(--color-line)" }} />;
}
```

`apps/desktop/src/pages/Inbox.tsx`:
```tsx
import { useState, type FormEvent } from "react";
import { api } from "../api/client";
import type { Ticket } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { formatDate } from "../lib/status";
import { useAction, useLoad } from "../lib/useLoad";
import { Drawer, Problem } from "../ui/Drawer";
import { Picture } from "../ui/Picture";

/** Tickets waiting for a manager's check, oldest first. */
export function Inbox() {
  const tickets = useLoad(() => api.get<Ticket[]>("/v1/tickets"), []);
  const [open, setOpen] = useState<number | null>(null);
  const ticket = tickets.data?.find((t) => t.id === open);

  return (
    <main className="page">
      <h1>Inbox</h1>
      <div className="small">Tickets and licences people have sent in. Check each against its photos, then approve it or send it back with a reason.</div>
      <Problem error={tickets.error} />
      {tickets.data?.length === 0 && <div className="card small">Nothing waiting. New tickets show here as people send them in.</div>}
      {tickets.data && tickets.data.length > 0 && (
        <table className="tbl">
          <thead><tr><th>Person</th><th>Ticket</th><th>Number</th><th>Card good until</th><th>Sent</th></tr></thead>
          <tbody>
            {tickets.data.map((t) => (
              <tr key={t.id} className="click" onClick={() => setOpen(t.id)}>
                <td><button type="button" className="rowbtn" onClick={() => setOpen(t.id)}>
                  <b>{t.person.name}</b><span className="small block">{t.person.code}</span></button></td>
                <td>{t.competency.name}</td>
                <td>{t.number}</td>
                <td>{t.expires_on ? formatDate(t.expires_on) : "Doesn't run out"}</td>
                <td className="small">{formatDate(t.created_at.slice(0, 10))}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {ticket && (
        <TicketDrawer key={ticket.id} ticket={ticket} onClose={() => setOpen(null)}
                      onDecided={() => { setOpen(null); tickets.reload(); }} />
      )}
    </main>
  );
}

function TicketDrawer({ ticket, onClose, onDecided }: { ticket: Ticket; onClose: () => void; onDecided: () => void }) {
  const { me } = useAuth();
  const [reason, setReason] = useState("");
  const action = useAction();
  const path = `/v1/tickets/${ticket.id}`;
  const own = me?.code === ticket.person.code;

  async function decide(fn: () => Promise<unknown>) {
    if (await action.run(fn)) onDecided();
  }

  function reject(e: FormEvent) {
    e.preventDefault();
    void decide(() => api.post(`${path}/reject`, { reason: reason.trim() }));
  }

  return (
    <Drawer title={`${ticket.competency.name}: ${ticket.person.name}`} sub={`${ticket.person.code} · sent ${formatDate(ticket.created_at.slice(0, 10))}`} onClose={onClose}>
      <dl className="card grid grid-cols-2 gap-2 text-sm">
        <dt className="small">Number</dt><dd className="m-0"><b>{ticket.number}</b></dd>
        <dt className="small">Card good until</dt><dd className="m-0"><b>{ticket.expires_on ? formatDate(ticket.expires_on) : "Doesn't run out"}</b></dd>
      </dl>
      <section className="flex flex-col gap-2" aria-label="Photos">
        <div className="eyebrow">Front</div>
        <Picture upload={ticket.front} label="The front" width={480} />
        {ticket.back && <><div className="eyebrow">Back</div><Picture upload={ticket.back} label="The back" width={480} /></>}
      </section>
      <Problem error={action.error} />
      {own ? (
        <div className="msg r">Nobody verifies their own ticket: ask another manager.</div>
      ) : (
        <>
          <div className="small">Approving records it as current until the card's date, from today.</div>
          <button type="button" className="btn primary" disabled={action.busy}
                  onClick={() => void decide(() => api.post(`${path}/approve`))}>Approve</button>
          <form className="card flex flex-col gap-3" onSubmit={reject}>
            <div className="eyebrow">Send it back</div>
            <label className="label">Reason (they see this)
              <input className="field" value={reason} maxLength={500} onChange={(e) => setReason(e.target.value)}
                     placeholder="e.g. the photo is blurry: take it again in good light" required />
            </label>
            <button type="submit" className="btn danger" disabled={action.busy || !reason.trim()}>Reject</button>
          </form>
        </>
      )}
    </Drawer>
  );
}
```

In `apps/desktop/src/App.tsx`, replace:
```tsx
import { Competencies } from "./pages/Competencies";
```
with:
```tsx
import { Competencies } from "./pages/Competencies";
import { Inbox } from "./pages/Inbox";
```

In `apps/desktop/src/App.tsx`, replace:
```tsx
          <Route path="/competencies" element={<Competencies />} />
```
with:
```tsx
          <Route path="/competencies" element={<Competencies />} />
          <Route path="/inbox" element={<Inbox />} />
```

In `apps/desktop/src/ui/Layout.tsx`, replace:
```tsx
          {can("competencies:read") && <NavLink to="/competencies">Competencies</NavLink>}
```
with:
```tsx
          {can("competencies:read") && <NavLink to="/competencies">Competencies</NavLink>}
          {can("tickets:verify") && <NavLink to="/inbox">Inbox</NavLink>}
```

**Step 4: Run them to see them pass**

Run: `cd apps/desktop && npm test && npm run typecheck`
Expected: `Tests  33 passed (33)`, and no type errors.

**Step 5: Commit**

```
git add apps/desktop/src
git commit -m "Check tickets in the desktop's Inbox: the photos, then approve or send back with a reason" \
  -m "Photos are fetched with the session's token and shown from blob: URLs; a PDF is offered to save. Nobody is offered their own ticket to check."
```

---

### Task 14: Policy versions on Competencies, a ticket's card expiry, and signatures in the history

**Files:**
- Modify: `apps/desktop/src/pages/Competencies.tsx` (in full below), `apps/desktop/src/pages/HistoryDrawer.tsx`
- Test: `apps/desktop/src/test/Policies.test.tsx`

**Step 1: Write the failing test**

`apps/desktop/src/test/Policies.test.tsx`:
```tsx
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Competency, PolicyVersion } from "../api/types";
import { json, renderApp, stubApi } from "./harness";

const WHS: Competency = { id: 4, key: "whs-policy", name: "WHS policy", kind: "policy", refresher_months: null, card_expires: true, active: true };
const FORKLIFT: Competency = { id: 2, key: "forklift-licence", name: "Forklift licence", kind: "ticket", refresher_months: null, card_expires: true, active: true };
const V1: PolicyVersion = {
  id: 1, version: 1, body: "Wear your PPE on the floor.", note: null,
  published_by: { code: "MG001", name: "Mel Grant" }, created_at: "2026-09-01T01:00:00Z",
};

describe("competencies", () => {
  it("shows a policy's versions and publishes the next", async () => {
    let versions = [V1];
    const { calls } = stubApi((method, url, body) => {
      if (url === "/v1/competencies") return json(200, { items: [WHS], total: 1 });
      if (url === "/v1/policies/whs-policy/versions") {
        if (method === "POST") {
          versions = [{ ...V1, id: 2, version: 2, ...(body as object) }, ...versions];
          return json(201, versions[0]);
        }
        return json(200, versions);
      }
      return null;
    });
    renderApp("/competencies");
    await userEvent.click(await screen.findByRole("button", { name: /WHS policy/ }));
    const drawer = await screen.findByRole("dialog", { name: "WHS policy" });
    expect(await within(drawer).findByText("Wear your PPE on the floor.")).toBeInTheDocument();
    expect(within(drawer).getByText("Everyone asked for this policy will need to sign version 2.")).toBeInTheDocument();
    await userEvent.type(within(drawer).getByLabelText("The policy's text"), "Wear your PPE, and hi-vis in the yard.");
    await userEvent.type(within(drawer).getByLabelText("What changed (optional)"), "hi-vis in the yard");
    await userEvent.click(within(drawer).getByRole("button", { name: "Publish version 2" }));
    await waitFor(() => expect(calls.find((c) => c.method === "POST")?.body).toEqual({
      body: "Wear your PPE, and hi-vis in the yard.", note: "hi-vis in the yard" }));
    expect(await within(drawer).findByRole("button", { name: "Publish version 3" })).toBeInTheDocument();
  });

  it("says whether a ticket's card runs out", async () => {
    const { calls } = stubApi((method, url) => {
      if (url === "/v1/competencies") return json(200, { items: [FORKLIFT], total: 1 });
      if (method === "PATCH") return json(200, { ...FORKLIFT, card_expires: false });
      return null;
    });
    renderApp("/competencies");
    await userEvent.click(await screen.findByRole("button", { name: /Forklift licence/ }));
    const drawer = await screen.findByRole("dialog", { name: "Forklift licence" });
    await userEvent.click(within(drawer).getByLabelText(/The card has an expiry date/));
    await userEvent.click(within(drawer).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({
      name: "Forklift licence", refresher_months: null, card_expires: false }));
  });

  it("shows who signed which version, and their signature", async () => {
    URL.createObjectURL = vi.fn(() => "blob:signature");
    URL.revokeObjectURL = vi.fn();
    const matrix = {
      today: "2026-10-12", competencies: [{ key: "whs-policy", name: "WHS policy", kind: "policy" }],
      people: [{ code: "LL042", name: "Kim Lee", roles: [], supervisor: null,
                 cells: { "whs-policy": { status: "current", granted_on: "2026-10-12", expires_on: null } } }],
    };
    const signed = {
      id: 9, competency: matrix.competencies[0], kind: "granted", granted_on: "2026-10-12", expires_on: null, note: null,
      recorded_by: { code: "LL042", name: "Kim Lee" }, policy_version: 2, signed_name: "Kim Lee", signature: "s-1",
      ticket: null, created_at: "2026-10-12T01:00:00Z",
    };
    stubApi((_m, url) => {
      if (url.startsWith("/v1/matrix")) return json(200, matrix);
      if (url === "/v1/roles") return json(200, { items: [], total: 0 });
      if (url.startsWith("/v1/people/LL042/records")) return json(200, [signed]);
      if (url === "/v1/uploads/s-1") return new Response(new Uint8Array([0x89, 0x50]), { status: 200, headers: { "Content-Type": "image/png" } });
      return null;
    });
    renderApp("/");
    await userEvent.click(await screen.findByRole("button", { name: /Kim Lee, WHS policy/ }));
    const drawer = await screen.findByRole("dialog", { name: "WHS policy" });
    expect(await within(drawer).findByText("Signed version 2 as “Kim Lee”")).toBeInTheDocument();
    expect(await within(drawer).findByRole("img", { name: "Kim Lee's signature" })).toHaveAttribute("src", "blob:signature");
  });
});
```

**Step 2: Run it to see it fail**

Run: `cd apps/desktop && npm test -- Policies`
Expected: FAIL: `Tests  3 failed | 33 passed (36)`: no versions on the policy's drawer, no `The card has an expiry date` switch, no `Signed version 2 as “Kim Lee”` in the history.

**Step 3: Minimal implementation**

`apps/desktop/src/pages/Competencies.tsx`:
```tsx
import { useState, type FormEvent } from "react";
import { api } from "../api/client";
import type { Competency, Kind, Page, PolicyVersion } from "../api/types";
import { formatDate } from "../lib/status";
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
              <td><button type="button" className="rowbtn" onClick={() => setOpen(c.key)}>
                <b>{c.name}</b><span className="small block">{c.key}</span></button></td>
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
  const [cardExpires, setCardExpires] = useState(competency.card_expires);
  const action = useAction();
  const path = `/v1/competencies/${encodeURIComponent(competency.key)}`;
  const done = async (fn: () => Promise<unknown>) => { if (await action.run(fn)) onChanged(); };
  const ticket = competency.kind === "ticket";

  return (
    <Drawer title={competency.name} sub={`${competency.key} · ${kindLabel(competency.kind)}`} onClose={onClose}>
      <form className="flex flex-col gap-3" onSubmit={(e) => {
        e.preventDefault();
        void done(() => api.patch(path, {
          name, refresher_months: refresher ? Number(refresher) : null, ...(ticket ? { card_expires: cardExpires } : {}),
        }));
      }}>
        <label className="label">Name<input className="field" value={name} onChange={(e) => setName(e.target.value)} required /></label>
        <label className="label">Refresher (months; empty for none)
          <input className="field" type="number" min={1} max={240} value={refresher} onChange={(e) => setRefresher(e.target.value)} />
        </label>
        {ticket && (
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={cardExpires} onChange={(e) => setCardExpires(e.target.checked)} />
            The card has an expiry date (people type it in, and it runs out then)
          </label>
        )}
        <div className="small">A new refresher changes everyone's status at once: status is worked out, never stored.</div>
        <Problem error={action.error} />
        <button type="submit" className="btn primary" disabled={action.busy}>Save</button>
      </form>
      {competency.kind === "policy" && <PolicyVersions policy={competency} />}
      {competency.active
        ? <button type="button" className="btn danger" disabled={action.busy}
                  onClick={() => void done(() => api.post(`${path}/deactivate`))}>Deactivate: no longer asked of anyone</button>
        : <button type="button" className="btn" disabled={action.busy}
                  onClick={() => void done(() => api.post(`${path}/reactivate`))}>Reactivate</button>}
    </Drawer>
  );
}

/** A policy's versions, newest first, and the next one. Each person signs the
 * newest; a new version asks everyone to sign again. */
function PolicyVersions({ policy }: { policy: Competency }) {
  const path = `/v1/policies/${encodeURIComponent(policy.key)}/versions`;
  const versions = useLoad(() => api.get<PolicyVersion[]>(path), [path]);
  const [body, setBody] = useState("");
  const [note, setNote] = useState("");
  const action = useAction();
  const next = (versions.data?.[0]?.version ?? 0) + 1;

  async function publish(e: FormEvent) {
    e.preventDefault();
    if (await action.run(() => api.post(path, { body, note: note.trim() || null }))) {
      setBody("");
      setNote("");
      versions.reload();
    }
  }

  return (
    <section className="flex flex-col gap-3" aria-label="Versions">
      <div className="eyebrow">Versions</div>
      <Problem error={versions.error} />
      {versions.data?.length === 0 && <div className="small">No version yet: nobody can sign it until there is one.</div>}
      {versions.data?.map((v, i) => (
        <details key={v.id} className="card" open={i === 0}>
          <summary className="text-sm"><b>Version {v.version}</b>{i === 0 && " · the one to sign"} · {formatDate(v.created_at.slice(0, 10))} by {v.published_by.name}</summary>
          {v.note && <div className="small mt-2">What changed: {v.note}</div>}
          <div className="text-sm mt-2" style={{ whiteSpace: "pre-wrap" }}>{v.body}</div>
        </details>
      ))}
      <form className="card flex flex-col gap-3" onSubmit={publish}>
        <div className="eyebrow">Publish version {next}</div>
        <label className="label">The policy's text
          <textarea className="field" style={{ height: 160 }} value={body} maxLength={50000} onChange={(e) => setBody(e.target.value)} required />
        </label>
        <label className="label">What changed (optional)
          <input className="field" value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} />
        </label>
        {next > 1 && <div className="small">Everyone asked for this policy will need to sign version {next}.</div>}
        <Problem error={action.error} />
        <button type="submit" className="btn primary" disabled={action.busy || !body.trim()}>Publish version {next}</button>
      </form>
    </section>
  );
}
```

In `apps/desktop/src/pages/HistoryDrawer.tsx`, replace:
```tsx
import { Drawer, Problem } from "../ui/Drawer";
```
with:
```tsx
import { Drawer, Problem } from "../ui/Drawer";
import { Picture } from "../ui/Picture";
```

In `apps/desktop/src/pages/HistoryDrawer.tsx`, replace:
```tsx
            {r.note && <div className="text-sm">{r.note}</div>}
```
with:
```tsx
            {r.policy_version && (
              <div className="text-sm">{r.signed_name
                ? <>Signed version {r.policy_version} as “{r.signed_name}”</>
                : <>For version {r.policy_version}</>}</div>
            )}
            {r.signature && <Picture upload={r.signature} label={`${person.name}'s signature`} width={200} />}
            {r.note && <div className="text-sm">{r.note}</div>}
```

**Step 4: Run it to see it pass, and build**

Run: `cd apps/desktop && npm test && npm run build`
Expected: `Tests  36 passed (36)`, then `✓ built in …`.

**Step 5: Commit**

```
git add apps/desktop/src
git commit -m "Publish a policy's versions from Competencies, and show who signed which in the history" \
  -m "A ticket's drawer says whether its card has an expiry date. A new version says that everyone asked for the policy will need to sign it."
```

---

### Task 15: The learner app's next steps: sign a policy, add a ticket, or wait for the check

**Files:**
- Modify: `apps/learner/src/api/types.ts`, `apps/learner/src/api/client.ts`, `apps/learner/src/ui.tsx`, `apps/learner/src/pages/MyTraining.tsx`, `apps/learner/src/test/setup.ts` (all in full below)
- Modify: `apps/learner/src/lib/training.ts`, `apps/learner/src/index.css`, `apps/learner/src/test/harness.tsx`
- Test: `apps/learner/src/test/client.test.ts`, `apps/learner/src/test/training.test.ts` (both in full below)

**Step 1: Write the failing tests**

`apps/learner/src/test/client.test.ts`:
```ts
import { LearnerApi } from "../api/client";

const answer = (status: number, body: unknown) => async () =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

describe("The learner app's client", () => {
  it.each(["/v1/auth/pin-login", "/v1/auth/login"])("does not sign out on a wrong guess at %s", async (path) => {
    const client = new LearnerApi(answer(401, { detail: "wrong", code: "wrong_pin" }));
    client.token = "lms_s.stale";
    const signedOut = vi.fn();
    client.onSignedOut = signedOut;
    await expect(client.post(path, {})).rejects.toMatchObject({ status: 401, code: "wrong_pin" });
    expect(signedOut).not.toHaveBeenCalled();
  });

  it("signs out when the API no longer takes the token", async () => {
    const client = new LearnerApi(answer(401, { detail: "not signed in" }));
    client.token = "lms_s.stale";
    const signedOut = vi.fn();
    client.onSignedOut = signedOut;
    await expect(client.get("/v1/people/LL042/training")).rejects.toMatchObject({ status: 401 });
    expect(signedOut).toHaveBeenCalledOnce();
  });

  it("sends a file as it is, with its own type", async () => {
    const seen: RequestInit[] = [];
    const client = new LearnerApi(async (_url, init) => {
      seen.push(init);
      return new Response(JSON.stringify({ id: "u-1" }), { status: 201 });
    });
    client.token = "lms_s.kim";
    const photo = new Blob([new Uint8Array([0xff, 0xd8, 0xff])], { type: "image/jpeg" });
    expect(await client.upload("ticket", photo)).toEqual({ id: "u-1" });
    expect(seen[0].body).toBe(photo);
    expect((seen[0].headers as Record<string, string>)["Content-Type"]).toBe("image/jpeg");
  });
});
```

`apps/learner/src/test/training.test.ts`:
```ts
import type { TrainingItem } from "../api/types";
import { groupTraining, nextStep, whenLine } from "../lib/training";

const item = (name: string, status: TrainingItem["status"], expires_on: string | null = null): TrainingItem =>
  ({ key: name.toLowerCase().replace(/ /g, "-"), name, kind: "ticket", status, granted_on: null, expires_on,
     card_expires: true, waiting: false });

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

  it("offers the next step: sign a policy, add a ticket, or wait for the check", () => {
    const policy = { ...item("WHS policy", "missing"), kind: "policy" as const };
    expect(nextStep(policy)).toEqual({ to: "/sign/whs-policy", label: "Read and sign" });
    expect(nextStep({ ...policy, status: "current" })).toBeNull();
    expect(nextStep(item("First aid", "lapsed"))).toEqual({ to: "/ticket/first-aid", label: "Add your ticket" });
    expect(nextStep(item("Forklift licence", "expiring"))).toEqual({ to: "/ticket/forklift-licence", label: "Add your ticket" });
    expect(nextStep({ ...item("Forklift licence", "missing"), waiting: true })).toEqual({ waiting: "Sent in · waiting for a manager's check" });
    expect(nextStep(item("Forklift licence", "current"))).toBeNull();
    expect(nextStep({ ...item("Site induction", "missing"), kind: "module" })).toBeNull();
  });
});
```

The harness keeps a file as it was sent (only JSON is read back), says what type it was sent as, and can open the app at a path. In `apps/learner/src/test/harness.tsx`, replace:
```tsx
export interface Call { method: string; url: string; body: unknown }
```
with:
```tsx
export interface Call { method: string; url: string; body: unknown; contentType?: string }
```

In `apps/learner/src/test/harness.tsx`, replace:
```tsx
    const body = init.body ? JSON.parse(init.body as string) : undefined;
    calls.push({ method, url, body });
```
with:
```tsx
    // JSON is read back; a file (a Blob) is kept as it was sent
    const body = typeof init.body === "string" ? JSON.parse(init.body) : init.body ?? undefined;
    calls.push({ method, url, body, contentType: (init.headers as Record<string, string> | undefined)?.["Content-Type"] });
```

In `apps/learner/src/test/harness.tsx`, replace:
```tsx
/** Signed in already when `who` is given, as if the app had been opened again. */
export function renderApp(who: Me | null = null, activeAt = Date.now()) {
```
with:
```tsx
/** Signed in already when `who` is given, as if the app had been opened again,
 * at `path` (My training unless told). */
export function renderApp(who: Me | null = null, activeAt = Date.now(), path = "/") {
```

In `apps/learner/src/test/harness.tsx`, replace:
```tsx
    <MemoryRouter>
```
with:
```tsx
    <MemoryRouter initialEntries={[path]}>
```

The pad and the photo picker (Task 16) draw on a canvas, which jsdom doesn't have; a test that needs one gives it one.

`apps/learner/src/test/setup.ts`:
```ts
import "@testing-library/jest-dom/vitest";

// jsdom draws nothing: a canvas has no context unless a test gives it one
HTMLCanvasElement.prototype.getContext = (() => null) as typeof HTMLCanvasElement.prototype.getContext;

afterEach(() => {
  window.localStorage.clear();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});
```

**Step 2: Run them to see them fail**

Run: `cd apps/learner && npm test`
Expected: FAIL: `Tests  2 failed | 19 passed (21)`: `client.upload is not a function` and `nextStep is not a function`.

**Step 3: Minimal implementation**

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
  /** a ticket: whether its card has an expiry date to type in */
  card_expires: boolean;
  /** a ticket sent in and waiting for a manager's check */
  waiting: boolean;
}

export interface Training {
  person: { code: string; name: string };
  today: string;
  items: TrainingItem[];
}

export interface Policy {
  key: string;
  name: string;
  version: { id: number; version: number; body: string; note: string | null; created_at: string };
}

export interface Upload { id: string; purpose: string; content_type: string; size_bytes: number }

export interface Ticket {
  id: number;
  competency: { key: string; name: string; kind: string };
  number: string;
  expires_on: string | null;
  status: "pending" | "approved" | "rejected";
  reason: string | null;
  created_at: string;
}
```

`apps/learner/src/api/client.ts`:
```ts
import type { Upload } from "./types";

/** The learner app is an ordinary API client with a session token, however
 * the person signed in. Nothing here a partner could not do (rule 4). */

export class ApiError extends Error {
  status: number;
  /** The API's reason when it gives one: wrong_pin, wrong_password, locked, ... */
  code: string | null;
  /** What a field needs, when the API says (a 422) */
  errors: { field: string; message: string }[];
  constructor(status: number, body: unknown) {
    const detail = (body as { detail?: unknown })?.detail;
    const errors = (body as { errors?: { field: string; message: string }[] })?.errors ?? [];
    super(typeof detail === "string" ? detail
      : errors.length > 0 ? errors.map((e) => e.message).join("; ") : `Simple LMS answered ${status}`);
    this.status = status;
    this.errors = errors;
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

  /** JSON, or a file (a Blob) sent as it is. */
  async request<T>(method: string, path: string, body?: unknown): Promise<T> {
    const headers: Record<string, string> = { Accept: "application/json" };
    const file = body instanceof Blob ? body : null;
    if (body !== undefined) headers["Content-Type"] = file ? file.type || "application/octet-stream" : "application/json";
    if (this.token) headers.Authorization = `Bearer ${this.token}`;
    let res: Response;
    try {
      res = await this.fetcher(path, { method, headers, body: body === undefined ? undefined : file ?? JSON.stringify(body) });
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
  /** A ticket's photo or a signature, kept by the API before what names it. */
  upload(purpose: "ticket" | "signature", file: Blob) {
    return this.request<Upload>("POST", `/v1/uploads?purpose=${purpose}`, file);
  }
}

export const api = new LearnerApi();
```

Append to `apps/learner/src/lib/training.ts`:
```ts
export type Step = { to: string; label: string } | { waiting: string } | null;

/** What the learner can do about an item here: sign a policy that wants
 * their signature, or send in a ticket that is missing, running out or run
 * out. A ticket already sent in waits for a manager. */
export function nextStep(item: TrainingItem): Step {
  const key = encodeURIComponent(item.key);
  if (item.kind === "policy" && item.status !== "current") return { to: `/sign/${key}`, label: "Read and sign" };
  if (item.kind === "ticket") {
    if (item.waiting) return { waiting: "Sent in · waiting for a manager's check" };
    if (item.status !== "current") return { to: `/ticket/${key}`, label: "Add your ticket" };
  }
  return null;
}
```

`plain()` says what went wrong in words, a field error as what the field needs; `Back` is the way back to My training from the screens of Tasks 16 and 17.

`apps/learner/src/ui.tsx`:
```tsx
import { Link } from "react-router-dom";
import { ApiError } from "./api/client";

export function Logo({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
      <path d="M3 7 15 10V28L3 25Z" fill="#5B93D6" />
      <path d="M29 7 17 10V28L29 25Z" fill="#2F6FB8" />
      <path d="M19.5 17.5 22 20l4.5-6" fill="none" stroke="#E8F0FA" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/** What went wrong, in plain words: never "Simple LMS answered 500". A field
 * error says what the field needs. */
export function plain(e: unknown): string {
  if (!(e instanceof ApiError)) return (e as Error).message;
  if (e.status >= 500) return "Simple LMS isn't answering right now. Try again in a moment.";
  const first = e.errors[0];
  if (first) return first.message.charAt(0).toUpperCase() + first.message.slice(1) + ".";
  return e.message.charAt(0).toUpperCase() + e.message.slice(1) + ".";
}

/** The top of a screen reached from My training, with the way back. */
export function Back() {
  return (
    <div className="top"><Logo /><Link to="/" className="chip" style={{ marginLeft: "auto", textDecoration: "none" }}>Back to My training</Link></div>
  );
}
```

`apps/learner/src/pages/MyTraining.tsx`:
```tsx
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError } from "../api/client";
import type { Training, TrainingItem } from "../api/types";
import { useSession } from "../auth/Session";
import { groupTraining, nextStep, whenLine } from "../lib/training";
import { Logo } from "../ui";

function Group({ title, tone, items, empty }: { title: string; tone: string; items: TrainingItem[]; empty: string }) {
  return (
    <section className="group" aria-label={title}>
      <h2>{title}<span className="sr-only">, </span><span className={`count ${tone}`}>{items.length}</span></h2>
      {items.length === 0 && <div className="small" style={{ color: "var(--color-muted)" }}>{empty}</div>}
      {items.map((i) => {
        const step = nextStep(i);
        return (
          <div key={i.key} className="item"><b>{i.name}</b><span>{whenLine(i)}</span>
            {step && "to" in step && <Link className="act" to={step.to} aria-label={`${step.label}: ${i.name}`}>{step.label}</Link>}
            {step && "waiting" in step && <span className="waiting">{step.waiting}</span>}
          </div>
        );
      })}
    </section>
  );
}

/** What is overdue, what is due soon and what is done; a policy to sign or a
 * ticket to send in opens from its item. */
export function MyTraining() {
  const { person, signOut } = useSession();
  const [training, setTraining] = useState<Training | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setTraining(await api.get<Training>(`/v1/people/${encodeURIComponent(person!.code)}/training`));
    } catch (e) {
      // plain words, never "Simple LMS answered 500"
      setError(e instanceof ApiError && e.status >= 500
        ? "Simple LMS isn't answering right now. Try again in a moment."
        : (e as Error).message);
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
      {!g && !error && <div aria-live="polite" style={{ color: "var(--color-muted)" }}>Loading…</div>}
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

In `apps/learner/src/index.css`, replace:
```css
  .t-green { background: var(--color-green-bg); color: var(--color-green-ink); }
}
```
with:
```css
  .t-green { background: var(--color-green-bg); color: var(--color-green-ink); }
  .act { align-self: flex-start; margin-top: 8px; padding: 10px 16px; border-radius: 12px; background: var(--color-blue); color: #fff; font-weight: 800; font-size: 15px; text-decoration: none; }
  .item .waiting { margin-top: 6px; color: var(--color-amber-ink); font-weight: 700; }
}
```

**Step 4: Run them to see them pass**

Run: `cd apps/learner && npm test && npm run typecheck`
Expected: `Tests  21 passed (21)`, and no type errors.

**Step 5: Commit**

```
git add apps/learner/src
git commit -m "Offer the next step in My training: read and sign, add your ticket, or wait for the check" \
  -m "The client sends a file as it is, with its own type, for the uploads that come next."
```

---

### Task 16: Sign a policy: read it, type your name, sign with a finger

**Files:**
- Create: `apps/learner/src/lib/picture.ts`, `apps/learner/src/pictures.tsx`, `apps/learner/src/pages/SignPolicy.tsx`
- Modify: `apps/learner/src/App.tsx`, `apps/learner/src/index.css`
- Test: `apps/learner/src/test/policies.test.tsx`

**Step 1: Write the failing test**

`apps/learner/src/test/policies.test.tsx`:
```tsx
import { fireEvent, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { json, KIM, renderApp, stubApi } from "./harness";

vi.mock("../lib/picture", () => ({
  toBlob: async () => new Blob([new Uint8Array([0x89, 0x50, 0x4e, 0x47])], { type: "image/png" }),
  forSending: async (f: Blob) => f,
}));

const TRAINING = {
  person: { code: "LL042", name: "Kim Lee" }, today: "2026-10-12",
  items: [{ key: "whs-policy", name: "WHS policy", kind: "policy", status: "missing", granted_on: null,
            expires_on: null, card_expires: true, waiting: false }],
};
const V2: { id: number; version: number; body: string; note: string | null; created_at: string } = { id: 2, version: 2, body: "Wear your PPE, and hi-vis in the yard.", note: "hi-vis in the yard", created_at: "2026-10-01T00:00:00Z" };
const WHS = { key: "whs-policy", name: "WHS policy", version: V2 };

/** jsdom draws nothing, so the pad gets a context that takes the strokes. */
function canDraw() {
  const ctx = { scale() {}, fillRect() {}, beginPath() {}, moveTo() {}, lineTo() {}, stroke() {} };
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(ctx as unknown as CanvasRenderingContext2D);
}

function signWithAFinger() {
  const pad = screen.getByRole("img", { name: "Signature pad: empty" });
  fireEvent.pointerDown(pad, { clientX: 10, clientY: 10 });
  fireEvent.pointerMove(pad, { clientX: 60, clientY: 30 });
  fireEvent.pointerUp(pad);
}

describe("signing a policy", () => {
  beforeEach(canDraw);

  it("reads it, takes a typed name and a finger signature, and says Ding!", async () => {
    const calls = stubApi((method, url) => {
      if (url === "/v1/people/LL042/training") return json(200, TRAINING);
      if (url === "/v1/policies/whs-policy") return json(200, WHS);
      if (method === "POST" && url === "/v1/uploads?purpose=signature") return json(201, { id: "sig-1" });
      if (method === "POST" && url === "/v1/policies/whs-policy/sign") return json(201, { kind: "granted" });
      return null;
    });
    renderApp(KIM);
    await userEvent.click(await screen.findByRole("link", { name: "Read and sign: WHS policy" }));
    expect(await screen.findByRole("article", { name: "The policy" })).toHaveTextContent("Wear your PPE, and hi-vis in the yard.");
    expect(screen.getByText(/What changed: hi-vis in the yard/)).toBeInTheDocument();
    const button = screen.getByRole("button", { name: "Sign" });
    await userEvent.type(screen.getByLabelText("Type your name"), "Kim Lee");
    expect(button).toBeDisabled();
    signWithAFinger();
    expect(screen.getByRole("img", { name: "Signature pad: signed" })).toBeInTheDocument();
    await userEvent.click(button);
    expect(await screen.findByRole("status", { name: "Signed" })).toHaveTextContent("Ding!");
    expect(calls.find((c) => c.url === "/v1/uploads?purpose=signature")?.contentType).toBe("image/png");
    expect(calls.find((c) => c.url === "/v1/policies/whs-policy/sign")?.body).toEqual({
      version: 2, signed_name: "Kim Lee", signature: "sig-1" });
  });

  it("shows the new version when one came out while they read", async () => {
    let policy: typeof WHS = { ...WHS, version: { ...V2, version: 1, body: "Wear your PPE on the floor." } };
    stubApi((method, url) => {
      if (url === "/v1/policies/whs-policy") return json(200, policy);
      if (method === "POST" && url.startsWith("/v1/uploads")) return json(201, { id: "sig-1" });
      if (method === "POST" && url === "/v1/policies/whs-policy/sign") {
        policy = WHS;
        return json(409, { detail: "version 2 is the one to sign now: read it first", code: "new_version" });
      }
      return null;
    });
    renderApp(KIM, Date.now(), "/sign/whs-policy");
    await userEvent.type(await screen.findByLabelText("Type your name"), "Kim Lee");
    signWithAFinger();
    await userEvent.click(screen.getByRole("button", { name: "Sign" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("A new version came out while you were reading.");
    expect(await screen.findByRole("article", { name: "The policy" })).toHaveTextContent("hi-vis in the yard");
  });

  it("says what the name needs, and keeps what was typed", async () => {
    stubApi((method, url) => {
      if (url === "/v1/policies/whs-policy") return json(200, WHS);
      if (method === "POST" && url.startsWith("/v1/uploads")) return json(201, { id: "sig-1" });
      if (method === "POST" && url === "/v1/policies/whs-policy/sign") {
        return json(422, { errors: [{ field: "signed_name", message: "type your name as it is on your record: Kim Lee" }] });
      }
      return null;
    });
    renderApp(KIM, Date.now(), "/sign/whs-policy");
    await userEvent.type(await screen.findByLabelText("Type your name"), "Kimberley");
    signWithAFinger();
    await userEvent.click(screen.getByRole("button", { name: "Sign" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Type your name as it is on your record: Kim Lee.");
    expect(screen.getByLabelText("Type your name")).toHaveValue("Kimberley");
  });

  it("says plainly when there is nothing to sign yet", async () => {
    stubApi((_m, url) => url === "/v1/policies/whs-policy" ? json(404, { detail: "WHS policy has no version to sign yet" }) : null);
    renderApp(KIM, Date.now(), "/sign/whs-policy");
    expect(await screen.findByRole("alert")).toHaveTextContent("There's nothing to sign here yet. Ask your manager.");
  });
});
```

**Step 2: Run it to see it fail**

Run: `cd apps/learner && npm test -- policies`
Expected: FAIL: `Tests  4 failed | 21 passed (25)`: there is no `/sign/…` yet, so the app goes back to My training.

**Step 3: Minimal implementation**

Simple TMS's driver app's pictures, with `forSending`: a PDF goes as it is, a photo is made small.

`apps/learner/src/lib/picture.ts`:
```ts
/** Pictures made small enough to send from a phone: a photo becomes a JPEG
 * at most 1600 pixels on its long side (and loses the camera's EXIF,
 * location included); a signature is a PNG. As in the Simple TMS driver app. */

export const PHOTO_MAX_SIDE = 1600;

export async function shrinkPhoto(file: Blob, maxSide = PHOTO_MAX_SIDE, quality = 0.8): Promise<Blob> {
  const image = await createImageBitmap(file);
  const scale = Math.min(1, maxSide / Math.max(image.width, image.height));
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(image.width * scale);
  canvas.height = Math.round(image.height * scale);
  canvas.getContext("2d")!.drawImage(image, 0, 0, canvas.width, canvas.height);
  image.close();
  return toBlob(canvas, "image/jpeg", quality);
}

export function toBlob(canvas: HTMLCanvasElement, type: "image/png" | "image/jpeg", quality?: number): Promise<Blob> {
  return new Promise((resolve, reject) => {
    canvas.toBlob((b) => (b ? resolve(b) : reject(new Error("That picture couldn't be made. Try again."))), type, quality);
  });
}

/** A ticket as it is sent: a PDF as it is, a photo made small. */
export function forSending(file: File): Promise<Blob> {
  return file.type === "application/pdf" ? Promise.resolve(file) : shrinkPhoto(file);
}
```

`apps/learner/src/pictures.tsx`:
```tsx
/** A ticket's photos and a finger signature, as in the Simple TMS driver app. */
import { useEffect, useRef, useState, type RefObject } from "react";
import { forSending } from "./lib/picture";

/** A photo of the card (the phone offers its camera) or a PDF, made small on
 * the phone before it is kept. */
export function PhotoPicker({ label, hint, file, onFile }: {
  label: string; hint: string; file: Blob | null; onFile: (b: Blob | null) => void;
}) {
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pdf = file?.type === "application/pdf";
  useEffect(() => {
    if (!file || pdf) { setUrl(null); return; }
    const u = URL.createObjectURL(file);
    setUrl(u);
    return () => URL.revokeObjectURL(u);
  }, [file, pdf]);

  async function picked(chosen: File | undefined) {
    if (!chosen) return;
    setError(null);
    try {
      onFile(await forSending(chosen));
    } catch {
      setError("That photo couldn't be read. Take it again.");
    }
  }

  return (
    <div className="pick">
      <label className="pickbox">
        {url && <img src={url} alt={label} />}
        <span><b>{file ? `${label}: added` : label}</b><small>{pdf ? "PDF added · tap to change" : file ? "Tap to take it again" : hint}</small></span>
        <input type="file" accept="image/*,application/pdf" className="sr-only"
               onChange={(e) => { void picked(e.target.files?.[0]); e.target.value = ""; }} />
      </label>
      {error && <div className="msg r" role="alert">{error}</div>}
    </div>
  );
}

/** Sign here: a canvas signed with a finger. `onSigned` says whether
 * anything has been drawn. */
export function SignaturePad({ canvas, onSigned }: { canvas: RefObject<HTMLCanvasElement | null>; onSigned: (signed: boolean) => void }) {
  const drawing = useRef(false);
  // a drawing can't be read out, so say what it is for and whether it holds one
  const [hasInk, setHasInk] = useState(false);

  function context(): CanvasRenderingContext2D | null {
    return canvas.current?.getContext("2d") ?? null;
  }

  function clear() {
    const el = canvas.current;
    const ctx = context();
    if (el && ctx) {
      ctx.fillStyle = "#fff";
      ctx.fillRect(0, 0, el.width, el.height);
    }
    setHasInk(false);
    onSigned(false);
  }

  useEffect(() => {
    // as many pixels as the screen has, so the signature isn't blurred
    const el = canvas.current;
    if (!el) return;
    const ratio = window.devicePixelRatio || 1;
    el.width = Math.round(el.clientWidth * ratio) || 600;
    el.height = Math.round(el.clientHeight * ratio) || 300;
    const ctx = context();
    if (ctx) {
      ctx.scale(ratio, ratio);
      ctx.lineWidth = 3;
      ctx.lineCap = "round";
      ctx.lineJoin = "round";
      ctx.strokeStyle = "#17202B";
    }
    clear();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function at(e: React.PointerEvent<HTMLCanvasElement>) {
    const r = e.currentTarget.getBoundingClientRect();
    return [e.clientX - r.left, e.clientY - r.top] as const;
  }

  return (
    <section aria-label="Signature" className="padbox">
      <div className="padhead">
        <span>Sign here</span>
        <button type="button" className="link" onClick={clear} aria-label="Clear the signature">Clear</button>
      </div>
      <canvas ref={canvas} className="pad" role="img" aria-describedby="sign-how"
              aria-label={hasInk ? "Signature pad: signed" : "Signature pad: empty"}
              onPointerDown={(e) => {
                const ctx = context();
                if (!ctx) return;
                e.currentTarget.setPointerCapture?.(e.pointerId);
                drawing.current = true;
                const [x, y] = at(e);
                ctx.beginPath();
                ctx.moveTo(x, y);
              }}
              onPointerMove={(e) => {
                const ctx = context();
                if (!drawing.current || !ctx) return;
                const [x, y] = at(e);
                ctx.lineTo(x, y);
                ctx.stroke();
                setHasInk(true);
                onSigned(true);
              }}
              onPointerUp={() => { drawing.current = false; }}
              onPointerCancel={() => { drawing.current = false; }} />
      <span id="sign-how" className="sr-only">Sign with your finger (or the mouse).</span>
    </section>
  );
}
```

`apps/learner/src/pages/SignPolicy.tsx`:
```tsx
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { api, ApiError } from "../api/client";
import type { Policy } from "../api/types";
import { useSession } from "../auth/Session";
import { toBlob } from "../lib/picture";
import { SignaturePad } from "../pictures";
import { Back, plain } from "../ui";

/** Read the policy, then type your name and sign with a finger. */
export function SignPolicy() {
  const { key = "" } = useParams();
  const { person } = useSession();
  const [policy, setPolicy] = useState<Policy | null>(null);
  const [trouble, setTrouble] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [signed, setSigned] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const canvas = useRef<HTMLCanvasElement>(null);

  const load = useCallback(async () => {
    setTrouble(null);
    try {
      setPolicy(await api.get<Policy>(`/v1/policies/${encodeURIComponent(key)}`));
    } catch (e) {
      setTrouble(e instanceof ApiError && e.status === 404
        ? "There's nothing to sign here yet. Ask your manager." : plain(e));
    }
  }, [key]);

  useEffect(() => { void load(); }, [load]);

  async function sign(e: FormEvent) {
    e.preventDefault();
    if (!policy || !canvas.current) return;
    setBusy(true);
    setError(null);
    try {
      const signature = await api.upload("signature", await toBlob(canvas.current, "image/png"));
      await api.post(`/v1/policies/${encodeURIComponent(key)}/sign`, {
        version: policy.version.version, signed_name: name.trim(), signature: signature.id,
      });
      setDone(true);
    } catch (err) {
      if (err instanceof ApiError && err.code === "new_version") {
        setError("A new version came out while you were reading. Read it, then sign again.");
        await load();
      } else if (err instanceof ApiError && err.code === "already_signed") {
        setDone(true);
      } else {
        setError(plain(err));
      }
    } finally {
      setBusy(false);
    }
  }

  if (done && policy) {
    return (
      <main className="screen">
        <Back />
        <section className="ding" role="status" aria-label="Signed">
          <b>Ding!</b>
          <span>You've signed {policy.name}, version {policy.version.version}.</span>
        </section>
        <Link to="/" className="big primary as-button">Back to My training</Link>
      </main>
    );
  }

  return (
    <main className="screen">
      <Back />
      {trouble && <div className="msg r" role="alert">{trouble}</div>}
      {!policy && !trouble && <div aria-live="polite" style={{ color: "var(--color-muted)" }}>Loading…</div>}
      {policy && (
        <>
          <h1 style={{ margin: 0, fontSize: 26, fontWeight: 800 }}>{policy.name}</h1>
          <div className="small" style={{ color: "var(--color-muted)" }}>Version {policy.version.version}
            {policy.version.note && <> · What changed: {policy.version.note}</>}</div>
          <article className="policy" aria-label="The policy">{policy.version.body}</article>
          <form onSubmit={sign} style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            <label className="label">Type your name
              <input className="input" autoComplete="off" value={name} onChange={(e) => setName(e.target.value)}
                     placeholder={person?.name} required />
            </label>
            <SignaturePad canvas={canvas} onSigned={setSigned} />
            <p className="small" style={{ margin: 0, color: "var(--color-muted)" }}>
              Signing says you have read this policy and will follow it.</p>
            {error && <div className="msg r" role="alert">{error}</div>}
            <button type="submit" className="big primary" disabled={busy || !signed || !name.trim()}>Sign</button>
          </form>
        </>
      )}
    </main>
  );
}
```

In `apps/learner/src/App.tsx`, replace:
```tsx
import { MyTraining } from "./pages/MyTraining";
```
with:
```tsx
import { MyTraining } from "./pages/MyTraining";
import { SignPolicy } from "./pages/SignPolicy";
```

In `apps/learner/src/App.tsx`, replace:
```tsx
        <Route index element={<MyTraining />} />
```
with:
```tsx
        <Route index element={<MyTraining />} />
        <Route path="/sign/:key" element={<SignPolicy />} />
```

In `apps/learner/src/index.css`, replace:
```css
  .item .waiting { margin-top: 6px; color: var(--color-amber-ink); font-weight: 700; }
```
with:
```css
  .item .waiting { margin-top: 6px; color: var(--color-amber-ink); font-weight: 700; }
  .as-button { display: flex; align-items: center; justify-content: center; text-decoration: none; }
  .policy { background: #fff; border: 1px solid var(--color-line); border-radius: 16px; padding: 16px; font-size: 16px; line-height: 1.55; white-space: pre-wrap; }
  .padbox { border-radius: 18px; background: #fff; border: 2px solid var(--color-line-2); padding: 10px 12px; display: flex; flex-direction: column; gap: 4px; }
  .padhead { display: flex; justify-content: space-between; align-items: center; font-size: 14px; font-weight: 800; }
  .pad { width: 100%; height: 180px; touch-action: none; border-radius: 10px; background: #fff; }
  .pickbox { display: flex; align-items: center; gap: 12px; min-height: 72px; padding: 12px 16px; border-radius: 16px; border: 2px dashed var(--color-line-2); background: #fff; cursor: pointer; }
  .pickbox img { width: 76px; height: 56px; border-radius: 10px; object-fit: cover; flex: none; }
  .pickbox span { display: flex; flex-direction: column; gap: 2px; }
  .pickbox small { color: var(--color-ink-2); font-size: 13px; }
  .ding { background: var(--color-green-bg); color: var(--color-green-ink); border-radius: 18px; padding: 24px 16px; display: flex; flex-direction: column; gap: 6px; text-align: center; }
  .ding b { font-size: 32px; font-weight: 800; }
```

**Step 4: Run it to see it pass**

Run: `cd apps/learner && npm test`
Expected: `Tests  25 passed (25)`.

**Step 5: Commit**

```
git add apps/learner/src
git commit -m "Sign a policy in the learner app: read it, type your name, sign with a finger" \
  -m "The signature is sent first, then the signing names it, for the version read. If a newer one came out meanwhile, the app shows it and asks again."
```

---

### Task 17: Add a ticket: the front and back, the number, the date on the card

**Files:**
- Create: `apps/learner/src/pages/AddTicket.tsx`
- Modify: `apps/learner/src/App.tsx`
- Test: `apps/learner/src/test/tickets.test.tsx`

**Step 1: Write the failing test**

`apps/learner/src/test/tickets.test.tsx`:
```tsx
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { json, KIM, renderApp, stubApi } from "./harness";

vi.mock("../lib/picture", () => ({
  toBlob: async () => new Blob([new Uint8Array([0x89, 0x50])], { type: "image/png" }),
  // a photo is made small on the phone: here, a JPEG of its own
  forSending: async (f: File) => f.type === "application/pdf" ? f : new Blob([new Uint8Array([0xff, 0xd8, 0xff])], { type: "image/jpeg" }),
}));

const ITEM = { key: "forklift-licence", name: "Forklift licence", kind: "ticket", status: "missing", granted_on: null,
               expires_on: null, card_expires: true, waiting: false };
const training = (items: unknown[]) => ({ person: { code: "LL042", name: "Kim Lee" }, today: "2026-10-12", items });

describe("adding a ticket", () => {
  beforeEach(() => {
    URL.createObjectURL = vi.fn(() => "blob:photo");
    URL.revokeObjectURL = vi.fn();
  });

  it("sends the photos, the number and the date, and it waits for a check", async () => {
    let uploads = 0;
    const calls = stubApi((method, url) => {
      if (url === "/v1/people/LL042/training") return json(200, training([ITEM]));
      if (url === "/v1/people/LL042/tickets") return json(200, []);
      if (method === "POST" && url === "/v1/uploads?purpose=ticket") return json(201, { id: `u-${++uploads}` });
      if (method === "POST" && url === "/v1/tickets") return json(201, { id: 7, status: "pending" });
      return null;
    });
    renderApp(KIM);
    await userEvent.click(await screen.findByRole("link", { name: "Add your ticket: Forklift licence" }));
    const user = userEvent.setup();
    await user.upload(await screen.findByLabelText(/Photo of the front/), new File(["x"], "front.jpg", { type: "image/jpeg" }));
    expect(await screen.findByRole("img", { name: "Photo of the front" })).toHaveAttribute("src", "blob:photo");
    await user.upload(screen.getByLabelText(/Photo of the back/), new File(["x"], "back.jpg", { type: "image/jpeg" }));
    await user.type(screen.getByLabelText("Number on the card"), "LF0012345");
    const send = screen.getByRole("button", { name: "Send for checking" });
    expect(send).toBeDisabled();
    await user.type(screen.getByLabelText("Good until (the date on the card)"), "2031-03-01");
    await user.click(send);
    expect(await screen.findByRole("status", { name: "Sent" })).toHaveTextContent("waits for a manager's check");
    expect(calls.filter((c) => c.url === "/v1/uploads?purpose=ticket").map((c) => c.contentType)).toEqual(["image/jpeg", "image/jpeg"]);
    expect(calls.find((c) => c.url === "/v1/tickets")?.body).toEqual({
      competency: "forklift-licence", number: "LF0012345", expires_on: "2031-03-01", front: "u-1", back: "u-2" });
  });

  it("takes a PDF as it is, and no date for a card that doesn't run out", async () => {
    const calls = stubApi((method, url) => {
      if (url === "/v1/people/LL042/training") return json(200, training([{ ...ITEM, key: "white-card", name: "White card", card_expires: false }]));
      if (url === "/v1/people/LL042/tickets") return json(200, []);
      if (method === "POST" && url.startsWith("/v1/uploads")) return json(201, { id: "u-1" });
      if (method === "POST" && url === "/v1/tickets") return json(201, { id: 8 });
      return null;
    });
    renderApp(KIM, Date.now(), "/ticket/white-card");
    const user = userEvent.setup();
    await user.upload(await screen.findByLabelText(/Photo of the front/), new File(["%PDF-"], "card.pdf", { type: "application/pdf" }));
    expect(await screen.findByText("PDF added · tap to change")).toBeInTheDocument();
    expect(screen.queryByLabelText(/Good until/)).not.toBeInTheDocument();
    await user.type(screen.getByLabelText("Number on the card"), "WC 1234");
    await user.click(screen.getByRole("button", { name: "Send for checking" }));
    await waitFor(() => expect(calls.find((c) => c.url === "/v1/tickets")?.body).toEqual({
      competency: "white-card", number: "WC 1234", expires_on: null, front: "u-1", back: null }));
    expect(calls.find((c) => c.url.startsWith("/v1/uploads"))?.contentType).toBe("application/pdf");
  });

  it("says why the last one was sent back", async () => {
    stubApi((_m, url) => {
      if (url === "/v1/people/LL042/training") return json(200, training([ITEM]));
      if (url === "/v1/people/LL042/tickets") {
        return json(200, [{ id: 3, competency: { key: "forklift-licence", name: "Forklift licence", kind: "ticket" }, number: "LF1",
                            expires_on: "2031-03-01", status: "rejected", reason: "The photo is blurry.", created_at: "2026-10-01T00:00:00Z" }]);
      }
      return null;
    });
    renderApp(KIM, Date.now(), "/ticket/forklift-licence");
    expect(await screen.findByText("Your last one was sent back: The photo is blurry.")).toBeInTheDocument();
  });

  it("shows a ticket sent in as waiting, with nothing to add", async () => {
    stubApi((_m, url) => url === "/v1/people/LL042/training" ? json(200, training([{ ...ITEM, waiting: true }])) : null);
    renderApp(KIM);
    expect(await screen.findByText("Sent in · waiting for a manager's check")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Add your ticket/ })).not.toBeInTheDocument();
  });

  it("says what the API wants changed", async () => {
    stubApi((method, url) => {
      if (url === "/v1/people/LL042/training") return json(200, training([ITEM]));
      if (url === "/v1/people/LL042/tickets") return json(200, []);
      if (method === "POST" && url.startsWith("/v1/uploads")) return json(201, { id: "u-1" });
      if (method === "POST" && url === "/v1/tickets") {
        return json(422, { errors: [{ field: "expires_on", message: "this card has run out: send the new one" }] });
      }
      return null;
    });
    renderApp(KIM, Date.now(), "/ticket/forklift-licence");
    const user = userEvent.setup();
    await user.upload(await screen.findByLabelText(/Photo of the front/), new File(["x"], "front.jpg", { type: "image/jpeg" }));
    await user.type(screen.getByLabelText("Number on the card"), "LF1");
    await user.type(screen.getByLabelText("Good until (the date on the card)"), "2026-10-01");
    await user.click(screen.getByRole("button", { name: "Send for checking" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("This card has run out: send the new one.");
  });
});
```

**Step 2: Run it to see it fail**

Run: `cd apps/learner && npm test -- tickets`
Expected: FAIL: `Tests  4 failed | 26 passed (30)`: `Unable to find a label with the text of: /Photo of the front/` (there is no `/ticket/…` yet, so the app goes back to My training).

**Step 3: Minimal implementation**

`apps/learner/src/pages/AddTicket.tsx`:
```tsx
import { useEffect, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { Ticket, Training, TrainingItem } from "../api/types";
import { useSession } from "../auth/Session";
import { PhotoPicker } from "../pictures";
import { Back, plain } from "../ui";

/** A photo of the front and back, the number and the expiry. It waits for a
 * manager's check. */
export function AddTicket() {
  const { key = "" } = useParams();
  const { person } = useSession();
  const [item, setItem] = useState<TrainingItem | null>(null);
  const [sentBack, setSentBack] = useState<string | null>(null);
  const [trouble, setTrouble] = useState<string | null>(null);
  const [front, setFront] = useState<Blob | null>(null);
  const [back, setBack] = useState<Blob | null>(null);
  const [number, setNumber] = useState("");
  const [expiresOn, setExpiresOn] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  useEffect(() => {
    const code = encodeURIComponent(person!.code);
    Promise.all([api.get<Training>(`/v1/people/${code}/training`), api.get<Ticket[]>(`/v1/people/${code}/tickets`)])
      .then(([training, tickets]) => {
        const found = training.items.find((i) => i.key === key);
        if (!found || found.kind !== "ticket") { setTrouble("That ticket isn't asked of you. Check with your supervisor."); return; }
        setItem(found);
        const last = tickets.find((t) => t.competency.key === key);
        if (last?.status === "rejected") setSentBack(last.reason);
      })
      .catch((e) => setTrouble(plain(e)));
  }, [key, person]);

  async function send(e: FormEvent) {
    e.preventDefault();
    if (!item || !front) return;
    setBusy(true);
    setError(null);
    try {
      const f = await api.upload("ticket", front);
      const b = back ? await api.upload("ticket", back) : null;
      await api.post("/v1/tickets", {
        competency: item.key, number: number.trim(), expires_on: item.card_expires ? expiresOn : null,
        front: f.id, back: b?.id ?? null,
      });
      setDone(true);
    } catch (err) {
      setError(plain(err));
    } finally {
      setBusy(false);
    }
  }

  if (done && item) {
    return (
      <main className="screen">
        <Back />
        <section className="ding" role="status" aria-label="Sent">
          <b>Sent</b>
          <span>Your {item.name} waits for a manager's check. It shows as done once they approve it.</span>
        </section>
        <Link to="/" className="big primary as-button">Back to My training</Link>
      </main>
    );
  }

  const ready = front && number.trim() && (!item?.card_expires || expiresOn);
  return (
    <main className="screen">
      <Back />
      {trouble && <div className="msg r" role="alert">{trouble}</div>}
      {!item && !trouble && <div aria-live="polite" style={{ color: "var(--color-muted)" }}>Loading…</div>}
      {item && (
        <>
          <h1 style={{ margin: 0, fontSize: 26, fontWeight: 800 }}>{item.name}</h1>
          {sentBack && <div className="msg r">Your last one was sent back: {sentBack}</div>}
          <form onSubmit={send} style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            <PhotoPicker label="Photo of the front" hint="Tap to take it, or choose a PDF" file={front} onFile={setFront} />
            <PhotoPicker label="Photo of the back" hint="If there's anything on the back" file={back} onFile={setBack} />
            <label className="label">Number on the card
              <input className="input" autoComplete="off" autoCapitalize="characters" value={number}
                     onChange={(e) => setNumber(e.target.value)} maxLength={64} required />
            </label>
            {item.card_expires && (
              <label className="label">Good until (the date on the card)
                <input className="input" type="date" value={expiresOn} onChange={(e) => setExpiresOn(e.target.value)} required />
              </label>
            )}
            {error && <div className="msg r" role="alert">{error}</div>}
            <button type="submit" className="big primary" disabled={busy || !ready}>Send for checking</button>
          </form>
        </>
      )}
    </main>
  );
}
```

In `apps/learner/src/App.tsx`, replace:
```tsx
import { MyTraining } from "./pages/MyTraining";
```
with:
```tsx
import { AddTicket } from "./pages/AddTicket";
import { MyTraining } from "./pages/MyTraining";
```

In `apps/learner/src/App.tsx`, replace:
```tsx
        <Route path="/sign/:key" element={<SignPolicy />} />
```
with:
```tsx
        <Route path="/sign/:key" element={<SignPolicy />} />
        <Route path="/ticket/:key" element={<AddTicket />} />
```

**Step 4: Run it to see it pass, and build**

Run: `cd apps/learner && npm test && npm run build`
Expected: `Tests  30 passed (30)`, then `✓ built in …`.

**Step 5: Commit**

```
git add apps/learner/src
git commit -m "Add a ticket from the learner app: photos of the front and back, the number and the card's date" \
  -m "A photo is made small on the phone and a PDF sent as it is. The screen says why the last one was sent back, and My training says it waits for a check."
```

---

### Task 18: The README and CLAUDE.md

**Files:**
- Modify: `README.md`, `CLAUDE.md`

**Step 1: Write it**

In `README.md`, replace:
````markdown
Status: **build step 1, the skeleton.** People with a code and PIN or an
email and password, roles and the competencies each requires, extras and
waivers, completions recorded by hand on the desktop, the matrix (with a CSV
export), and a learner app that shows each person's training. Policies,
tickets, modules, practicals, Entra sign-in and the outward links come with
the next steps in `docs/plans/2026-10-12-simple-lms-design.md`.
````
with:
````markdown
Status: **build step 2, policies and tickets.** People with a code and PIN
or an email and password, roles and the competencies each requires, extras
and waivers, completions recorded by hand on the desktop, the matrix (with a
CSV export), and a learner app that shows each person's training. People
sign policies and send in their tickets from the learner app; a manager
checks each ticket in the desktop's Inbox; the worker emails reminders and a
Monday digest. Modules, practicals, Entra sign-in and the outward links come
with the next steps in `docs/plans/2026-10-12-simple-lms-design.md`.
````

In `README.md`, replace:
````markdown
docker-compose.yml   api, db, caddy
```
````
with:
````markdown
docker-compose.yml   api, worker, db, caddy
```
````

In `README.md`, replace:
````markdown
`create-user` asks for a password (12 characters or more) and makes an
admin unless you give `--permission`.
````
with:
````markdown
`create-user` asks for a password (12 characters or more) and makes an
admin unless you give `--permission`.

For email, set `LMS_SMTP_HOST`, `LMS_SMTP_FROM` and the rest of the
`LMS_SMTP_*` settings in `.env` (and `LMS_PUBLIC_URL`, for the links in
them), then `docker compose up -d worker` again. Until then emails wait in
the outbox and nothing else is held up.
````

In `README.md`, replace:
````markdown
The learner app is at `https://<LMS_DOMAIN>/learn/`.
````
with:
````markdown
**Policies.** Add a competency of kind *Signed policy*, open it under
**Competencies** and publish version 1 of its text. Each person asked for
it reads it in the learner app, types their name and signs with a finger.
Publishing version 2 asks everyone to sign again; the matrix shows them red
until they do. A policy signed on paper can still be recorded by hand: it
counts for the version people are asked to sign now.

**Tickets.** A competency of kind *Ticket or licence* says whether its card
has an expiry date. A person adds a photo of the front and back (or a PDF),
the number and the expiry in the learner app; it waits in the desktop's
**Inbox**, where a manager who is not them checks the photos and approves it
(current until the card's date) or sends it back with a reason they see.

**Reminders.** Each morning (from `LMS_DAILY_HOUR`, 6 am in `LMS_TIMEZONE`)
the worker emails each person with an email when something of theirs has 30,
14 or 0 days left, and on Mondays sends each manager and admin with an email
a digest of what is expiring and lapsed. Each is sent once. A failed email
is tried again after 1 minute, 5, 30 and 2 hours. To queue them now:
`docker compose exec worker lms daily-job`.

The learner app is at `https://<LMS_DOMAIN>/learn/`.
````

In `README.md`, replace:
````markdown
| See their own training | ✓ | ✓ | ✓ | ✓ |
````
with:
````markdown
| See their own training | ✓ | ✓ | ✓ | ✓ |
| Sign a policy, send in their own ticket | ✓ | ✓ | ✓ | ✓ |
````

In `README.md`, replace:
````markdown
| Record or revoke a completion (never their own) | | | ✓ | ✓ |
````
with:
````markdown
| Record or revoke a completion (never their own) | | | ✓ | ✓ |
| Approve or reject a ticket (never their own) | | | ✓ | ✓ |
````

In `README.md`, replace:
````markdown
.venv/bin/uvicorn lms.api.app:app --reload --port 8033
```

Stop the `api` container first (`docker compose stop api`), as it holds
8033.
````
with:
````markdown
.venv/bin/uvicorn lms.api.app:app --reload --port 8033
.venv/bin/python -m lms.worker   # in another terminal, for email and the daily job
```

Outside Docker, set `LMS_UPLOAD_DIR` to a folder of your own (the default
is `/data/uploads`). Stop the `api` and `worker` containers first
(`docker compose stop api worker`), as the API holds 8033.
````

In `CLAUDE.md`, replace:
````markdown
   `competency_record`, `quiz_attempt` or `signoff` row (nor a
   `person_override`). A mistake is corrected by a new row (`revoked`, with a
   note). People are deactivated, never deleted.
````
with:
````markdown
   `competency_record`, `quiz_attempt` or `signoff` row (nor a
   `person_override` or `policy_version`; a `ticket_submission` is decided
   once and never deleted). A mistake is corrected by a new row (`revoked`,
   with a note). People are deactivated, never deleted.
````

In `CLAUDE.md`, replace:
````markdown
  or RabbitMQ. (The worker arrives with build step 2.)
````
with:
````markdown
  or RabbitMQ. The worker (`python -m lms.worker`) drains the `outbox`.
````

In `CLAUDE.md`, replace:
````markdown
docker-compose.yml   api, db, caddy (the worker comes with step 2)
````
with:
````markdown
docker-compose.yml   api, worker, db, caddy
````

**Step 2: Commit**

```
git add README.md CLAUDE.md
git commit -m "Describe policies, tickets, the Inbox and the reminders in the README"
```

---

### Task 19: Every suite, and a clean Compose start

**Step 1: Every suite**

```
(cd api && .venv/bin/pytest -q)
(cd apps/desktop && npm test && npm run typecheck && npm run build)
(cd apps/learner && npm test && npm run typecheck && npm run build)
```
Expected: `222 passed`; `Tests  36 passed (36)` and a build; `Tests  30 passed (30)` and a build.

**Step 2: Compose from nothing**

This drops the local database and its uploads: only on a machine with nothing to keep.
```
docker compose down -v
docker compose up -d --build
for i in $(seq 1 30); do curl -fsS http://127.0.0.1:8033/v1/health && break; sleep 2; done; echo
docker compose ps --format '{{.Service}} {{.State}}'
docker compose logs worker | grep "worker started"
```
Expected: `{"status":"ok"}`; `api running`, `caddy running`, `db running`, `worker running`; and the worker's `worker started` line. Fix anything that is not, then commit the fix with a message that says what it fixes.

---

### Task 20: Manual walkthrough: a policy signed, a ticket checked, a reminder emailed

Run against the Compose stack, with `LMS_HTTP_PORT=8280`, `LMS_HTTPS_PORT=8643` in `.env` and both apps built. Mailpit stands in for the mail server:
```
docker run -d --name lms-mailpit --network simple-lms_default -p 127.0.0.1:8025:8025 axllent/mailpit
```
and in `.env`: `LMS_SMTP_HOST=lms-mailpit`, `LMS_SMTP_PORT=1025`, `LMS_SMTP_SECURITY=none`, `LMS_PUBLIC_URL=https://localhost:8643`; then `docker compose up -d worker`. Mailpit's inbox is at http://127.0.0.1:8025.

**Step 1: A policy with a version.** On the desktop (https://localhost:8643/) as the admin from step 1: add **WHS policy** (kind *Signed policy*) and **Forklift licence** (*Ticket or licence*, its card has an expiry date), and a role **Forklift operator** requiring both. Open WHS policy: "No version yet". Publish version 1 with a few lines of text. Add a manager Mel (email and password) and a learner Kim (email `kim@example.com.au`, PIN `2468`, the role). The matrix shows Kim red for both.

**Step 2: Kim signs.** At https://localhost:8643/learn/ sign in as `LL042` / `2468`. WHS policy is under Overdue with **Read and sign**. Open it, read, type `kim lee`, sign with the mouse, **Sign**: Ding! Back in My training it is under Done. On the desktop, the WHS policy cell for Kim is green and its history says "Signed version 1 as “kim lee”" with the signature.

**Step 3: A new version.** Publish version 2 ("What changed: hi-vis in the yard"). Kim's cell goes red; the learner app offers Read and sign again and shows version 2's text and note. Sign it: green again.

**Step 4: Kim sends in a ticket.** In the learner app, Forklift licence → **Add your ticket**. Add a photo of the front (any picture), the number `LF0012345` and a date on the card about 30 days from today; **Send for checking**: "Sent". My training says "Sent in · waiting for a manager's check".

**Step 5: Nobody checks their own.** Sign in to the desktop as Mel: an **Inbox** tab, with Kim's ticket. Open it: the photo shows. Add Mel a Forklift licence extra (as the admin), send one in as Mel from the learner app (with Mel's email and password), and see Mel's own ticket in Mel's Inbox say "Nobody verifies their own ticket: ask another manager." with no Approve button. The admin approves Mel's.

**Step 6: Approve and reject.** As Mel, reject Kim's with "The photo is blurry"; the learner app's Add your ticket screen says "Your last one was sent back: The photo is blurry." Send it again; Mel approves it. The matrix cell turns amber (about 30 days left) and the history says `Ticket LF0012345, checked`, by Mel.

**Step 7: The reminder and the digest.** Run `docker compose exec worker lms daily-job`: `… 1 reminders and … digests queued`. Within seconds Mailpit has "Forklift licence: 30 days left" to `kim@example.com.au`, with the link to https://localhost:8643/learn/. Run it again: `0 reminders`. Run `docker compose exec worker lms daily-job --on <a Monday>` (say the next one): Mel and the admin each get "Training this week: … lapsed, … expiring", listing Kim's Forklift licence under "Expiring in the next 30 days".

**Step 8: When the mail server is down.** `docker stop lms-mailpit`, then `docker compose exec worker lms daily-job --on <the day 14 days before the card's date>`. The worker logs `email reminder:… try 1 failed: …`; `docker compose exec -T db psql -U lms -d lms -c "select key, status, attempts, next_attempt_at from outbox order by id desc limit 1"` shows it pending a minute on. `docker start lms-mailpit`: within the minute it is `done` and in Mailpit. Remove Mailpit afterwards: `docker rm -f lms-mailpit`.
