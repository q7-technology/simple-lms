# Simple LMS step 4: Practicals — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build step 4 of `docs/plans/2026-10-12-simple-lms-design.md`: practicals, signed off on the phone. A manager writes a practical's checklist on the desktop's **Competencies** screen (the things to see a learner do) and publishes it. A supervisor opens **Sign someone off** in the learner app on their phone, chooses a person from their team and the practical, watches them do it, ticks each item, adds a note or a photo if they like, and signs; then they hand the phone over, and the learner checks what was ticked, signs on the same phone and types their PIN to say it was them. Nobody signs off their own practical (rule 3): the grant is recorded by the supervisor, and everything about it (the checklist version, each item ticked, the note, the photo, both signatures) is kept as it was (rule 1). Usable end to end: a manager writes the forklift practical's checklist, Sam signs Kim off in the yard, the matrix goes green, and the refresher brings it round again a year on.

**Architecture:** The same FastAPI app (`api/`, package `lms`). Migration `0004` adds `practical_version` and `practical_item` (a checklist, published whole and append-only), `signoff` and `signoff_item` (append-only; what was ticked is tied by foreign keys to the version signed off), `competency_record.signoff_id`, and an upload purpose for a sign-off's photo. Triggers keep it honest whatever the API does: `block_change()` on all four tables, `written_with()` so an item is only ever written in the same transaction as its version (and a ticked item with its sign-off), and `signoff_grant()` so a grant from a sign-off is that learner's, for that practical, recorded by the supervisor who signed it. A new scope, `signoffs:write`, is carried by supervisors, managers and admins, PIN sessions included. Status still comes only from `lms/services/status.py`: a sign-off is an ordinary grant and the refresher does the rest. The desktop gains a checklist editor in the practical's drawer and shows a sign-off in the history; the learner app gains **Sign someone off** at `/learn/signoff`.

**Tech Stack:** as step 3: Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, psycopg 3, pytest against a real PostgreSQL 16; Vite 6, React 19, TypeScript 5, Tailwind 4, Vitest 3 with Testing Library; Docker Compose, Caddy 2, GitHub Actions. No new dependencies.

---

## Context

The design is settled; this plan does not change any of its decisions. The decisions in the step 1 to step 3 plans' Contexts still hold (ports, sessions and scopes, the latest row counts, `expires_on` is the last good day, today in `LMS_TIMEZONE`, files sent as the raw body and checked by their first bytes as they stream to disk, the person's row locked while a record is made, signatures from `SignaturePad`, and the rest). The code on `main` is the truth where it went further than those plans: `errors.commit_unique`, `records.one_at_a_time` and `latest_record`, `uploads.Incoming` and the per-purpose limits, `status.py` and `standing.py`, the desktop's `Drawer` (with `useCloseGuard`), `.rowbtn` rows and `Picture`, the learner app's shared-tab sessions, idle wipe, `stillHere()`, `plain()`, `PhotoPicker` and `SignaturePad`, `lms/services/settings.py` and the admin's **Settings** screen (sign-in switches, the quiz wait), and Game Mode: the desktop opens on the classroom with every screen in `ScreenPanel` over it (`ui/screens.ts`, `Layout.tsx`; the matrix at `/matrix`), and the learner app's ring and `useDing()`.

### Decisions this plan makes that the design leaves open

- **A checklist is versioned, and a version is frozen once published, like a policy's text.** A `practical_version` belongs to a competency of kind `practical` and holds its items (`practical_item`, in order). A version is published whole (`POST /v1/practicals/{key}/versions` with every item) and never changed or deleted: `block_change()` refuses an UPDATE or DELETE of either table, and `written_with()` refuses an item inserted in any transaction but the one that wrote its version (the version's `created_at` is that transaction's `now()`), so nothing is ever added to a checklist after the event. A sign-off names its version, so what was ticked always means what the supervisor saw. No draft, unlike a module: a checklist is a short list written in one sitting, so the desktop starts the next version on screen as a copy of the newest, and publishing it (asked once) is the only save. Up to 50 items of up to 300 characters.
- **A new checklist asks nobody to be signed off again** (like a module, unlike a policy): sign-offs so far still count, and the refresher brings people back. Status for a practical is unchanged in `status.py`.
- **A sign-off ticks every item.** Signing off says the learner did all of it; a learner who isn't there yet simply isn't signed off yet, and nothing is recorded (no partial or failed sign-offs: nothing in the design asks for them). Each item ticked is a `signoff_item`, so the record holds exactly what was ticked, and its foreign keys hold it to the sign-off's own version: an item from another checklist can't be ticked on it. The API checks that every item, and nothing else, is ticked.
- **Who signs off.** A new scope, `signoffs:write`, for supervisors, managers and admins, whether signed in with a password or a PIN (step 1 said step 4 would add it to supervisors' PIN sessions: the phone in the yard is a PIN session). A supervisor signs off their own team (the people whose supervisor they are); a manager or admin, anyone. Nobody signs off themselves, admins included (`403 { "code": "own_signoff" }`), and the database says so twice: `ck_signoff_not_own`, and `signoff_grant()`, which holds a grant from a sign-off to that sign-off's learner, practical and supervisor (`recorded_by`). Someone a supervisor may not sign off is `404`, as anywhere a person isn't the caller's to see. Who may sign off whom is said once, in `practicals.may_sign_off()`.
- **The learner confirms on the supervisor's phone with a finger signature and their own PIN.** The design says the learner signs on the same device to confirm; a drawn signature alone could be drawn by anyone holding the phone, so the learner also types their PIN, which only they know: the confirmation is theirs, and an auditor can rely on it. No typed name: the PIN says who they are. The learner never signs in on the supervisor's phone: no session is made for them, nothing of theirs is loaded, and their PIN goes once in the sign-off request (`learner_pin`) and is never stored, on the phone or in the API (the field is emptied after every try). A wrong PIN counts against the same five tries as signing in (otherwise the supervisor's phone would be a way round the lock-out), and the fifth locks it until a manager resets it, as at sign-in; the PIN is checked last, so a mistake anywhere else never spends one of the learner's tries, and both people's rows are locked (in id order) while it is checked, so guesses sent at once can't get past five. These are `422` on `learner_pin`, never `401`, which the learner app would take to mean the supervisor's own session had ended. A learner with no PIN (one who signs in with a password) can't confirm until a manager sets one. The learner's screen on the phone has no way back to the supervisor's training: only **Confirm**, or **Give it back**.
- **Both signatures and the photo are sent from the supervisor's phone**, before the sign-off that names them, so they are the supervisor's uploads (`uploads.mine()` checks that): both signatures are purpose `signature` (`training:write`, as now), and the photo is a new purpose, `signoff-photo` (JPEG or PNG, 20 MB, `signoffs:write`; a PDF is no photo). The two signatures differ, and each signature or photo goes on one record or sign-off only: unique indexes on `signoff`, and `policies.signature_used()` now looks at sign-offs too, so a signature can't move between a policy and a sign-off either. `GET /v1/uploads/{id}` shows a sign-off's photo and signatures to whoever may see the learner as well as the supervisor, so Kim sees what signed her off.
- **The grant** is a `competency_record` granted today, recorded by the supervisor, with `signoff_id` pointing at the sign-off and no `expires_on`, so the competency's refresher works out the last good day in `status.py`, as for any grant. The learner's row is locked first, as for every record, so a sign-off and a revoke at once are weighed one after the other. Signing off again while current is allowed (a renewal, as for a module). A mistake is put right by a revoke with a note, as for any grant; a practical done on paper can still be recorded by hand on the desktop. The record answers with `signoff: { version, ticked, note, photo, supervisor_signature, learner_signature }`.
- **The phone's list:** `GET /v1/signoffs/people` gives the people the caller may sign off, by name, each with the practicals they are asked for and not let off (status and last good day), worked out by `standing.py` as My training is. `GET /v1/practicals/{key}` gives the checklist to tick now, with each item's id.
- **Learner app:** My training gets a **Sign someone off** button for anyone with `signoffs:write`; it opens `/learn/signoff`: each person with a button per practical ("Forklift practical · Not done yet"), and a search once there are more than six. `/learn/signoff/<code>/<key>`: the checklist to tick ("1 of 3 ticked"), a note, a photo, the supervisor's signature, and **Hand the phone to Kim Lee** once everything is ticked and signed; then Kim's screen: what was ticked and the note, her signature, **Your PIN**, **Confirm**; then Ding! A newer checklist meanwhile (`409 new_version`) goes back to the supervisor to tick it again. A practical in a learner's own My training says "Your supervisor signs this off with you".
- **Desktop:** the drawer of a practical on **Competencies** shows the checklist supervisors tick now and the next version, a copy to change (add, move up and down, remove, "What changed"), with **Publish version N**, which asks once: "Its items are frozen once it is, and every sign-off from now on ticks them." Closing it with changes not published asks first. The history drawer says "Signed off on checklist version 1, every item ticked:", the items, the note, the photo and both signatures, "Kim Lee signed too, and confirmed it with their PIN.", and "by Sam Vu".
- **Game Mode, Settings and the migration chain.** Nothing here is a new desktop screen: the checklist lives in the practical's own drawer on **Competencies** and the sign-off in the history drawer a matrix cell opens, so both open over the classroom inside `ScreenPanel` like everything else, and work the same with Game Mode off (a test says so); `ui/screens.ts` is untouched. The learner app's sign-off is a screen of its own reached from My training, and a completed sign-off says Ding! out loud as a pass does (`useDing()`: woken by the tap on **Confirm**, played when the API says yes, only with Sound on). No new setting: who signs off whom and the five tries are rules, not choices. The learner confirms with their PIN even where signing in with a PIN is switched off in **Settings**: confirming is not signing in, no session is made, and the switch is about sessions; a site that turns PINs off still sets one under **People** for anyone who is signed off on a practical (the README says so). Migration `0004` follows `0003b`.
- **Reminders and the daily job are unchanged:** a practical's expiry already comes from its refresher, and the reminders and digest already cover every kind. Online only, as the design says (no offline sign-off).
- **Left for later steps:** Entra (step 5), `competency.granted` events, the competency API and Platen certificates (6), Game Mode (7).

---

## Before you start

Step 3 and everything merged after it (the follow-ups, the quiz wait, Settings with migration `0003b`, and Game Mode) are on `main` (`c193b0c` or later).

```
cd "/Users/leightonlauton/Q7 Technology/Software/q7/simple-lms"
git switch main && git pull --ff-only
git switch -c step-4-practicals
docker compose up -d db
(cd api && uv pip install -e ".[dev]")
(cd apps/desktop && npm ci)
(cd apps/learner && npm ci)
```

As before: `pytest` runs from `api/` against the compose `db` on 127.0.0.1:5435 (`TEST_DATABASE_URL` points it elsewhere), and `npm` commands run from the app's folder. Every test still runs on 12 October 2026, a Monday. Before step 4 the suites are at `446 passed`, `Tests  110 passed (110)` (desktop) and `Tests  72 passed (72)` (learner), on `main` at `c193b0c` (steps 1 to 3, the follow-ups, the quiz wait, Settings and Game Mode). (If `main` gains tests before this is built, every count below goes up by as many.)

---
### Task 1: Checklist versions, sign-offs and what they ticked, kept as they were

**Files:**
- Create: `api/lms/models/practicals.py`, `api/alembic/versions/0004_practicals.py`
- Modify: `api/lms/models/evidence.py`, `api/lms/models/records.py`, `api/lms/models/__init__.py`
- Test: `api/tests/test_migrations.py`; create `api/tests/test_signoff_rows.py`

**Step 1: Write the failing tests**

In `api/tests/test_migrations.py`, replace:
```python
          "ticket_submission", "outbox", "module_version", "module_page", "quiz_question",
          "quiz_attempt", "module_progress", "setting", "alembic_version"}
TRIGGERS = {"competency_record_append_only", "person_override_append_only",
            "policy_version_append_only", "upload_append_only", "ticket_submission_decide_once",
            "quiz_attempt_append_only", "module_version_publish_once", "module_page_draft_only",
            "quiz_question_draft_only", "quiz_attempt_published_only",
            "competency_record_quiz_pass"}
```
with:
```python
          "ticket_submission", "outbox", "module_version", "module_page", "quiz_question",
          "quiz_attempt", "module_progress", "setting", "practical_version", "practical_item",
          "signoff", "signoff_item", "alembic_version"}
TRIGGERS = {"competency_record_append_only", "person_override_append_only",
            "policy_version_append_only", "upload_append_only", "ticket_submission_decide_once",
            "quiz_attempt_append_only", "module_version_publish_once", "module_page_draft_only",
            "quiz_question_draft_only", "quiz_attempt_published_only",
            "competency_record_quiz_pass", "practical_version_append_only",
            "practical_item_append_only", "signoff_append_only", "signoff_item_append_only",
            "practical_item_written_with_version", "signoff_item_written_with_signoff",
            "competency_record_signoff"}
```

`api/tests/test_signoff_rows.py`:
```python
"""A practical's checklist is written whole and never changed; a sign-off
and the items it ticked are kept as they were, by someone who is not the
learner, and its grant is theirs. The database says so (rules 1 and 3),
whatever the API does."""
import uuid
from datetime import date

import pytest
from sqlalchemy import delete, insert, update
from sqlalchemy.exc import DBAPIError, IntegrityError

from lms.models import (
    Competency, CompetencyRecord, Person, PracticalItem, PracticalVersion, Signoff, SignoffItem,
    Upload,
)


def upload(db, owner, purpose="signature") -> uuid.UUID:
    row = Upload(id=uuid.uuid4(), person_id=owner.id, purpose=purpose, content_type="image/png",
                 size_bytes=3, sha256="0" * 64, path=f"ab/{uuid.uuid4()}.png")
    db.add(row)
    db.flush()
    return row.id


def checklist(db, practical, boss, n, items) -> PracticalVersion:
    """Version n, items and all, in one transaction."""
    v = PracticalVersion(competency_id=practical.id, version=n, published_by_id=boss.id)
    db.add(v)
    db.flush()
    db.add_all([PracticalItem(practical_version_id=v.id, position=i, text=t)
                for i, t in enumerate(items)])
    db.commit()
    return v


def signoff(db, version, kim, sam, *, competency_id=None, items=None, **more) -> Signoff:
    """Kim signed off by Sam on this version, every item ticked, in one transaction."""
    signatures = {"supervisor_signature_upload_id": upload(db, sam),
                  "learner_signature_upload_id": upload(db, sam)}
    s = Signoff(person_id=kim.id, competency_id=competency_id or version.competency_id,
                practical_version_id=version.id, supervisor_id=sam.id, **{**signatures, **more})
    db.add(s)
    db.flush()
    db.add_all([SignoffItem(signoff_id=s.id, practical_item_id=i.id,
                            practical_version_id=version.id)
                for i in (items if items is not None else version.items)])
    db.commit()
    return s


@pytest.fixture
def yard(db):
    """Forklift practical: version 1 of two items; Kim on Sam's team."""
    boss = Person(code="MG001", name="Mel Grant", permission="manager")
    sam = Person(code="SV001", name="Sam Vu", permission="supervisor")
    db.add_all([boss, sam])
    db.flush()
    kim = Person(code="LL042", name="Kim Lee", supervisor_id=sam.id)
    forklift = Competency(key="forklift-practical", name="Forklift practical", kind="practical")
    db.add_all([kim, forklift])
    db.commit()
    one = checklist(db, forklift, boss, 1, ["Checks the forks and chains", "Lifts a pallet"])
    return boss, sam, kim, forklift, one


@pytest.mark.parametrize("change", [
    update(PracticalVersion).values(note="Changed afterwards"),
    update(PracticalItem).values(text="Changed afterwards"),
    delete(PracticalItem),
])
def test_a_checklist_is_kept_as_it_was(db, yard, change):
    with pytest.raises(DBAPIError, match="append-only"):
        db.execute(change)
        db.commit()


def test_nothing_is_added_to_a_checklist_afterwards(db, yard):
    one = yard[4]
    with pytest.raises(DBAPIError, match="written with their practical_version, never after"):
        db.execute(insert(PracticalItem).values(practical_version_id=one.id, position=2,
                                                text="One more"))
        db.commit()


def test_an_item_says_something(db, yard):
    boss, sam, kim, forklift, one = yard
    v = PracticalVersion(competency_id=forklift.id, version=2, published_by_id=boss.id)
    db.add(v)
    db.flush()
    db.add(PracticalItem(practical_version_id=v.id, position=0, text="  "))
    with pytest.raises(IntegrityError, match="ck_practical_item_text"):
        db.commit()


@pytest.mark.parametrize("change", [
    update(Signoff).values(note="Changed afterwards"),
    delete(SignoffItem),
    delete(Signoff),
])
def test_a_signoff_and_what_it_ticked_are_kept_as_they_were(db, yard, change):
    boss, sam, kim, forklift, one = yard
    signoff(db, one, kim, sam)
    with pytest.raises(DBAPIError, match="append-only"):
        db.execute(change)
        db.commit()


def test_nothing_is_ticked_afterwards(db, yard):
    boss, sam, kim, forklift, one = yard
    s = signoff(db, one, kim, sam, items=one.items[:1])
    with pytest.raises(DBAPIError, match="written with their signoff, never after"):
        db.execute(insert(SignoffItem).values(signoff_id=s.id, practical_item_id=one.items[1].id,
                                              practical_version_id=one.id))
        db.commit()


def test_what_is_ticked_is_on_the_checklist_signed_off(db, yard):
    boss, sam, kim, forklift, one = yard
    two = checklist(db, forklift, boss, 2, ["Checks the forks", "Lifts a pallet", "Parks it"])
    with pytest.raises(IntegrityError, match="fk_signoff_item_practical_item_id_practical_item"):
        signoff(db, one, kim, sam, items=two.items)


def test_nobody_signs_off_their_own(db, yard):
    boss, sam, kim, forklift, one = yard
    with pytest.raises(IntegrityError, match="ck_signoff_not_own"):
        signoff(db, one, sam, sam)


def test_a_signoff_is_on_its_own_practicals_checklist(db, yard):
    boss, sam, kim, forklift, one = yard
    other = Competency(key="ewp-practical", name="EWP practical", kind="practical")
    db.add(other)
    db.commit()
    with pytest.raises(IntegrityError, match="fk_signoff_practical_version_id_practical_version"):
        signoff(db, one, kim, sam, competency_id=other.id)


def test_two_people_sign_two_signatures(db, yard):
    boss, sam, kim, forklift, one = yard
    ink = upload(db, sam)
    with pytest.raises(IntegrityError, match="ck_signoff_two_signatures"):
        signoff(db, one, kim, sam, items=[], supervisor_signature_upload_id=ink,
                learner_signature_upload_id=ink)


def test_a_signature_goes_on_one_signoff_only(db, yard):
    boss, sam, kim, forklift, one = yard
    first = signoff(db, one, kim, sam)
    with pytest.raises(IntegrityError, match="uq_signoff_learner_signature_upload_id"):
        signoff(db, one, kim, sam, learner_signature_upload_id=first.learner_signature_upload_id)


def grant(db, s: Signoff, **more):
    row = {"person_id": s.person_id, "competency_id": s.competency_id,
           "recorded_by_id": s.supervisor_id, **more}
    db.add(CompetencyRecord(kind="granted", granted_on=date(2026, 10, 12), signoff_id=s.id, **row))
    db.commit()


def test_a_signoff_is_granted_by_its_supervisor(db, yard):
    boss, sam, kim, forklift, one = yard
    grant(db, signoff(db, one, kim, sam))


@pytest.mark.parametrize("whose", ["person_id", "recorded_by_id"])
def test_a_grant_from_a_signoff_is_that_learners_by_that_supervisor(db, yard, whose):
    boss, sam, kim, forklift, one = yard
    s = signoff(db, one, kim, sam)
    with pytest.raises(DBAPIError, match="needs a sign-off of the same person"):
        grant(db, s, **{whose: boss.id})


def test_a_signoff_grants_once(db, yard):
    boss, sam, kim, forklift, one = yard
    s = signoff(db, one, kim, sam)
    grant(db, s)
    with pytest.raises(IntegrityError, match="uq_competency_record_signoff_id"):
        grant(db, s)


def test_a_signoff_photo_is_one_kind_of_upload(db, yard):
    sam = yard[1]
    upload(db, sam, "signoff-photo")
    db.commit()
    db.add(Upload(id=uuid.uuid4(), person_id=sam.id, purpose="selfie", content_type="image/png",
                  size_bytes=3, sha256="0" * 64, path="ab/s.png"))
    with pytest.raises(IntegrityError, match="ck_upload_purpose"):
        db.commit()
```

**Step 2: Run them to see them fail**

Run: `cd api && .venv/bin/pytest tests/test_migrations.py tests/test_signoff_rows.py -q`
Expected: FAIL: `ImportError: cannot import name 'PracticalItem' from 'lms.models'`, so the run stops while collecting the tests (and a fresh database has none of the new tables or triggers).

**Step 3: Minimal implementation**

`api/lms/models/practicals.py`:
```python
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint, ForeignKey, ForeignKeyConstraint, Index, Integer, String, UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from lms.models.base import Base, created_at_column
from lms.models.catalogue import Competency
from lms.models.people import Person


class PracticalVersion(Base):
    """One version of a practical's checklist: the items a supervisor ticks
    while they watch. Append-only, items and all (triggers say so): a
    sign-off names its version, so what was ticked never changes under it.
    The newest version is the one signed off now."""

    __tablename__ = "practical_version"
    __table_args__ = (
        UniqueConstraint("competency_id", "version"),
        # what a sign-off names as its practical and version agree
        UniqueConstraint("id", "competency_id"),
        CheckConstraint("version >= 1", name="version"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    competency_id: Mapped[int] = mapped_column(ForeignKey("competency.id"), index=True)
    # 1, 2, 3 … for each practical
    version: Mapped[int] = mapped_column(Integer)
    # what changed, for the supervisors
    note: Mapped[str | None] = mapped_column(String(500))
    published_by_id: Mapped[int] = mapped_column(ForeignKey("person.id"))
    created_at: Mapped[datetime] = created_at_column()

    competency: Mapped[Competency] = relationship()
    published_by: Mapped[Person] = relationship()
    items: Mapped[list[PracticalItem]] = relationship(order_by="PracticalItem.position")


class PracticalItem(Base):
    """One thing to see the learner do, e.g. "Checks the forks and chains".
    Written with its version and never after (a trigger says so)."""

    __tablename__ = "practical_item"
    __table_args__ = (
        UniqueConstraint("practical_version_id", "position"),
        # what a ticked item names as its version agrees
        UniqueConstraint("id", "practical_version_id"),
        CheckConstraint("position >= 0", name="position"),
        CheckConstraint("length(trim(text)) > 0", name="text"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    practical_version_id: Mapped[int] = mapped_column(ForeignKey("practical_version.id"),
                                                      index=True)
    # 0, 1, 2 …: the order they are ticked in
    position: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(String(300))


class Signoff(Base):
    """A supervisor watched a learner do a practical, ticked every item on
    its checklist and signed; the learner signed on the same device to
    confirm. Append-only (rule 1), and never by the learner themselves
    (rule 3). Its grant is in the training record, recorded by the
    supervisor."""

    __tablename__ = "signoff"
    __table_args__ = (
        # a version of this practical
        ForeignKeyConstraint(["practical_version_id", "competency_id"],
                             ["practical_version.id", "practical_version.competency_id"]),
        # what a ticked item names as its sign-off's version agrees
        UniqueConstraint("id", "practical_version_id"),
        # nobody signs off their own practical
        CheckConstraint("supervisor_id <> person_id", name="not_own"),
        CheckConstraint("supervisor_signature_upload_id <> learner_signature_upload_id",
                        name="two_signatures"),
        CheckConstraint("note is null or length(trim(note)) > 0", name="note"),
        # a photo or a signature goes on one sign-off only
        Index("uq_signoff_photo_upload_id", "photo_upload_id", unique=True,
              postgresql_where=text("photo_upload_id is not null")),
        Index("uq_signoff_supervisor_signature_upload_id", "supervisor_signature_upload_id",
              unique=True),
        Index("uq_signoff_learner_signature_upload_id", "learner_signature_upload_id",
              unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # the learner
    person_id: Mapped[int] = mapped_column(ForeignKey("person.id"), index=True)
    competency_id: Mapped[int] = mapped_column(ForeignKey("competency.id"), index=True)
    # the checklist ticked, whose items never change
    practical_version_id: Mapped[int] = mapped_column(Integer)
    # who watched and signed it off
    supervisor_id: Mapped[int] = mapped_column(ForeignKey("person.id"))
    note: Mapped[str | None] = mapped_column(String(500))
    photo_upload_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("upload.id"))
    supervisor_signature_upload_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("upload.id"))
    # the learner's own, drawn on the supervisor's device once their PIN said it was them
    learner_signature_upload_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("upload.id"))
    created_at: Mapped[datetime] = created_at_column()

    competency: Mapped[Competency] = relationship()
    practical_version: Mapped[PracticalVersion] = relationship(
        primaryjoin="PracticalVersion.id == Signoff.practical_version_id",
        foreign_keys=[practical_version_id])
    supervisor: Mapped[Person] = relationship(foreign_keys=[supervisor_id])
    ticked: Mapped[list[SignoffItem]] = relationship(
        primaryjoin="Signoff.id == SignoffItem.signoff_id", foreign_keys="SignoffItem.signoff_id",
        order_by="SignoffItem.practical_item_id")


class SignoffItem(Base):
    """An item ticked on a sign-off: one of its version's own (the foreign
    keys say so). Written with its sign-off and never after."""

    __tablename__ = "signoff_item"
    __table_args__ = (
        ForeignKeyConstraint(["signoff_id", "practical_version_id"],
                             ["signoff.id", "signoff.practical_version_id"]),
        ForeignKeyConstraint(["practical_item_id", "practical_version_id"],
                             ["practical_item.id", "practical_item.practical_version_id"]),
    )

    signoff_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    practical_item_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    practical_version_id: Mapped[int] = mapped_column(Integer)

    item: Mapped[PracticalItem] = relationship(
        primaryjoin="PracticalItem.id == SignoffItem.practical_item_id",
        foreign_keys=[practical_item_id])
```

In `api/lms/models/evidence.py`, replace:
```python
class Upload(Base):
    """A file someone sent: a ticket's photo or PDF, a policy signature, or
    a module page's picture, PDF or video. Kept on disk under
    LMS_UPLOAD_DIR, named by its random id; served only through the API to
    people who may see it. Append-only: a trigger refuses UPDATE and DELETE,
    since records, tickets and pages point at it."""

    __tablename__ = "upload"
    __table_args__ = (CheckConstraint("purpose in ('ticket', 'signature', 'page-image', "
                                      "'page-pdf', 'page-video')", name="purpose"),)
```
with:
```python
class Upload(Base):
    """A file someone sent: a ticket's photo or PDF, a signature, a module
    page's picture, PDF or video, or a sign-off's photo. Kept on disk under
    LMS_UPLOAD_DIR, named by its random id; served only through the API to
    people who may see it. Append-only: a trigger refuses UPDATE and DELETE,
    since records, tickets, pages and sign-offs point at it."""

    __tablename__ = "upload"
    __table_args__ = (CheckConstraint("purpose in ('ticket', 'signature', 'page-image', "
                                      "'page-pdf', 'page-video', 'signoff-photo')",
                                      name="purpose"),)
```

In `api/lms/models/records.py`, replace:
```python
from lms.models.modules import QuizAttempt
from lms.models.people import Person
```
with:
```python
from lms.models.modules import QuizAttempt
from lms.models.people import Person
from lms.models.practicals import Signoff
```

In `api/lms/models/records.py`, replace:
```python
        CheckConstraint("quiz_attempt_id is null or kind = 'granted'", name="quiz_grant"),
```
with:
```python
        CheckConstraint("quiz_attempt_id is null or kind = 'granted'", name="quiz_grant"),
        # a practical signed off is a grant; a trigger says it is that
        # person's sign-off, for this competency, by whoever recorded it
        CheckConstraint("signoff_id is null or kind = 'granted'", name="signoff_grant"),
```

In `api/lms/models/records.py`, replace:
```python
    quiz_attempt_id: Mapped[int | None] = mapped_column(ForeignKey("quiz_attempt.id"), unique=True)
    created_at: Mapped[datetime] = created_at_column()
```
with:
```python
    quiz_attempt_id: Mapped[int | None] = mapped_column(ForeignKey("quiz_attempt.id"), unique=True)
    # a practical signed off on the phone: the sign-off
    signoff_id: Mapped[int | None] = mapped_column(ForeignKey("signoff.id"), unique=True)
    created_at: Mapped[datetime] = created_at_column()
```

In `api/lms/models/records.py`, replace:
```python
    quiz_attempt: Mapped[QuizAttempt | None] = relationship()
```
with:
```python
    quiz_attempt: Mapped[QuizAttempt | None] = relationship()
    signoff: Mapped[Signoff | None] = relationship()
```

In `api/lms/models/__init__.py`, replace:
```python
from lms.models.records import CompetencyRecord, PersonOverride
```
with:
```python
from lms.models.practicals import PracticalItem, PracticalVersion, Signoff, SignoffItem
from lms.models.records import CompetencyRecord, PersonOverride
```

In `api/lms/models/__init__.py`, replace:
```python
    "QuizQuestion", "QuizAttempt", "ModuleProgress", "Setting",
]
```
with:
```python
    "QuizQuestion", "QuizAttempt", "ModuleProgress", "Setting", "PracticalVersion",
    "PracticalItem", "Signoff", "SignoffItem",
]
```

`api/alembic/versions/0004_practicals.py`:
```python
"""practicals: checklist versions and their items, sign-offs and what they ticked

Revision ID: 0004
Revises: 0003b
Create Date: 2026-10-16
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PURPOSES_BEFORE = "purpose in ('ticket', 'signature', 'page-image', 'page-pdf', 'page-video')"
PURPOSES_NOW = ("purpose in ('ticket', 'signature', 'page-image', 'page-pdf', 'page-video', "
                "'signoff-photo')")
APPEND_ONLY = ("practical_version", "practical_item", "signoff", "signoff_item")
# a row written with its parent, in the same transaction, and never after
WRITTEN_WITH = {"practical_item": ("practical_version", "practical_version_id", "version"),
                "signoff_item": ("signoff", "signoff_id", "signoff")}


def _created_at() -> sa.Column:
    return sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
                     nullable=False)


def upgrade() -> None:
    # a sign-off's photo is a file sent like any other
    op.drop_constraint(op.f("ck_upload_purpose"), "upload", type_="check")
    op.create_check_constraint(op.f("ck_upload_purpose"), "upload", PURPOSES_NOW)

    op.create_table(
        "practical_version",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("competency_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("published_by_id", sa.Integer(), nullable=False),
        _created_at(),
        sa.CheckConstraint("version >= 1", name=op.f("ck_practical_version_version")),
        sa.ForeignKeyConstraint(["competency_id"], ["competency.id"],
                                name=op.f("fk_practical_version_competency_id_competency")),
        sa.ForeignKeyConstraint(["published_by_id"], ["person.id"],
                                name=op.f("fk_practical_version_published_by_id_person")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_practical_version")),
        sa.UniqueConstraint("competency_id", "version",
                            name=op.f("uq_practical_version_competency_id_version")),
        # what a sign-off names as its practical and version agree
        sa.UniqueConstraint("id", "competency_id",
                            name=op.f("uq_practical_version_id_competency_id")),
    )
    op.create_index(op.f("ix_practical_version_competency_id"), "practical_version",
                    ["competency_id"])

    op.create_table(
        "practical_item",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("practical_version_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("text", sa.String(length=300), nullable=False),
        sa.CheckConstraint("position >= 0", name=op.f("ck_practical_item_position")),
        sa.CheckConstraint("length(trim(text)) > 0", name=op.f("ck_practical_item_text")),
        sa.ForeignKeyConstraint(["practical_version_id"], ["practical_version.id"],
                                name=op.f("fk_practical_item_practical_version_id_practical_version")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_practical_item")),
        sa.UniqueConstraint("practical_version_id", "position",
                            name=op.f("uq_practical_item_practical_version_id_position")),
        # what a ticked item names as its version agrees
        sa.UniqueConstraint("id", "practical_version_id",
                            name=op.f("uq_practical_item_id_practical_version_id")),
    )
    op.create_index(op.f("ix_practical_item_practical_version_id"), "practical_item",
                    ["practical_version_id"])

    op.create_table(
        "signoff",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("person_id", sa.Integer(), nullable=False),
        sa.Column("competency_id", sa.Integer(), nullable=False),
        sa.Column("practical_version_id", sa.Integer(), nullable=False),
        sa.Column("supervisor_id", sa.Integer(), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("photo_upload_id", sa.Uuid(), nullable=True),
        sa.Column("supervisor_signature_upload_id", sa.Uuid(), nullable=False),
        sa.Column("learner_signature_upload_id", sa.Uuid(), nullable=False),
        _created_at(),
        # nobody signs off their own practical
        sa.CheckConstraint("supervisor_id <> person_id", name=op.f("ck_signoff_not_own")),
        sa.CheckConstraint("supervisor_signature_upload_id <> learner_signature_upload_id",
                           name=op.f("ck_signoff_two_signatures")),
        sa.CheckConstraint("note is null or length(trim(note)) > 0",
                           name=op.f("ck_signoff_note")),
        sa.ForeignKeyConstraint(["person_id"], ["person.id"],
                                name=op.f("fk_signoff_person_id_person")),
        sa.ForeignKeyConstraint(["competency_id"], ["competency.id"],
                                name=op.f("fk_signoff_competency_id_competency")),
        # a version of this practical
        sa.ForeignKeyConstraint(["practical_version_id", "competency_id"],
                                ["practical_version.id", "practical_version.competency_id"],
                                name=op.f("fk_signoff_practical_version_id_practical_version")),
        sa.ForeignKeyConstraint(["supervisor_id"], ["person.id"],
                                name=op.f("fk_signoff_supervisor_id_person")),
        sa.ForeignKeyConstraint(["photo_upload_id"], ["upload.id"],
                                name=op.f("fk_signoff_photo_upload_id_upload")),
        sa.ForeignKeyConstraint(["supervisor_signature_upload_id"], ["upload.id"],
                                name=op.f("fk_signoff_supervisor_signature_upload_id_upload")),
        sa.ForeignKeyConstraint(["learner_signature_upload_id"], ["upload.id"],
                                name=op.f("fk_signoff_learner_signature_upload_id_upload")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_signoff")),
        # what a ticked item names as its sign-off's version agrees
        sa.UniqueConstraint("id", "practical_version_id",
                            name=op.f("uq_signoff_id_practical_version_id")),
    )
    op.create_index(op.f("ix_signoff_person_id"), "signoff", ["person_id"])
    op.create_index(op.f("ix_signoff_competency_id"), "signoff", ["competency_id"])
    # a photo or a signature goes on one sign-off only
    op.create_index("uq_signoff_photo_upload_id", "signoff", ["photo_upload_id"], unique=True,
                    postgresql_where=sa.text("photo_upload_id is not null"))
    op.create_index("uq_signoff_supervisor_signature_upload_id", "signoff",
                    ["supervisor_signature_upload_id"], unique=True)
    op.create_index("uq_signoff_learner_signature_upload_id", "signoff",
                    ["learner_signature_upload_id"], unique=True)

    op.create_table(
        "signoff_item",
        sa.Column("signoff_id", sa.Integer(), nullable=False),
        sa.Column("practical_item_id", sa.Integer(), nullable=False),
        sa.Column("practical_version_id", sa.Integer(), nullable=False),
        # an item of the version the sign-off is for, and of no other
        sa.ForeignKeyConstraint(["signoff_id", "practical_version_id"],
                                ["signoff.id", "signoff.practical_version_id"],
                                name=op.f("fk_signoff_item_signoff_id_signoff")),
        sa.ForeignKeyConstraint(["practical_item_id", "practical_version_id"],
                                ["practical_item.id", "practical_item.practical_version_id"],
                                name=op.f("fk_signoff_item_practical_item_id_practical_item")),
        sa.PrimaryKeyConstraint("signoff_id", "practical_item_id", name=op.f("pk_signoff_item")),
    )

    op.add_column("competency_record", sa.Column("signoff_id", sa.Integer(), nullable=True))
    op.create_foreign_key(op.f("fk_competency_record_signoff_id_signoff"),
                          "competency_record", "signoff", ["signoff_id"], ["id"])
    op.create_unique_constraint(op.f("uq_competency_record_signoff_id"),
                                "competency_record", ["signoff_id"])
    op.create_check_constraint(op.f("ck_competency_record_signoff_grant"), "competency_record",
                               "signoff_id is null or kind = 'granted'")

    # What a supervisor ticked, and the checklist they ticked it on, are
    # kept as they were (rule 1).
    for table in APPEND_ONLY:
        op.execute(f"create trigger {table}_append_only before update or delete "
                   f"on {table} for each row execute function block_change()")
    # An item is written in the transaction that wrote its parent (a
    # version, a sign-off), and never added to it after: the parent's
    # created_at is that transaction's now().
    op.execute("""
        create or replace function written_with() returns trigger
        language plpgsql as $$
        declare
            fresh boolean;
        begin
            execute format('select created_at = now() from %I where id = $1', tg_argv[0])
                into fresh using (to_jsonb(new) ->> tg_argv[1])::int;
            if fresh is not true then
                raise exception '% rows are written with their %, never after',
                    tg_table_name, tg_argv[0] using errcode = 'restrict_violation';
            end if;
            return new;
        end
        $$
    """)
    for table, (parent, column, name) in WRITTEN_WITH.items():
        op.execute(f"create trigger {table}_written_with_{name} before insert on {table} "
                   f"for each row execute function written_with('{parent}', '{column}')")
    # A grant from a sign-off is that person's, for that practical, and
    # recorded by the supervisor who signed it off. Sign-offs never change,
    # so there is nothing to wait for.
    op.execute("""
        create or replace function signoff_grant() returns trigger
        language plpgsql as $$
        begin
            if new.signoff_id is not null and not exists (
                select 1 from signoff s
                where s.id = new.signoff_id and s.person_id = new.person_id
                  and s.competency_id = new.competency_id
                  and s.supervisor_id = new.recorded_by_id) then
                raise exception '% needs a sign-off of the same person, for the same '
                    'competency, by whoever records it', tg_table_name
                    using errcode = 'restrict_violation';
            end if;
            return new;
        end
        $$
    """)
    op.execute("create trigger competency_record_signoff before insert "
               "on competency_record for each row execute function signoff_grant()")


def downgrade() -> None:
    # before 0004 there are no sign-off photos: with them kept, going back
    # is refused rather than losing them
    op.execute("""
        do $$
        begin
            if exists (select 1 from upload where purpose = 'signoff-photo') then
                raise exception 'sign-off photos are kept: remove them by hand before going '
                    'back past 0004';
            end if;
        end
        $$
    """)
    op.execute("drop trigger if exists competency_record_signoff on competency_record")
    op.execute("drop function if exists signoff_grant()")
    for table, (parent, column, name) in WRITTEN_WITH.items():
        op.execute(f"drop trigger if exists {table}_written_with_{name} on {table}")
    op.execute("drop function if exists written_with()")
    for table in APPEND_ONLY:
        op.execute(f"drop trigger if exists {table}_append_only on {table}")
    op.drop_constraint(op.f("ck_competency_record_signoff_grant"), "competency_record",
                       type_="check")
    op.drop_constraint(op.f("uq_competency_record_signoff_id"), "competency_record",
                       type_="unique")
    op.drop_constraint(op.f("fk_competency_record_signoff_id_signoff"), "competency_record",
                       type_="foreignkey")
    op.drop_column("competency_record", "signoff_id")
    op.drop_table("signoff_item")
    op.drop_index("uq_signoff_learner_signature_upload_id", table_name="signoff")
    op.drop_index("uq_signoff_supervisor_signature_upload_id", table_name="signoff")
    op.drop_index("uq_signoff_photo_upload_id", table_name="signoff")
    op.drop_index(op.f("ix_signoff_competency_id"), table_name="signoff")
    op.drop_index(op.f("ix_signoff_person_id"), table_name="signoff")
    op.drop_table("signoff")
    op.drop_index(op.f("ix_practical_item_practical_version_id"), table_name="practical_item")
    op.drop_table("practical_item")
    op.drop_index(op.f("ix_practical_version_competency_id"), table_name="practical_version")
    op.drop_table("practical_version")
    op.drop_constraint(op.f("ck_upload_purpose"), "upload", type_="check")
    op.create_check_constraint(op.f("ck_upload_purpose"), "upload", PURPOSES_BEFORE)
```

The models and the migration say the same constraints by the same names (`test_the_models_match_the_migrations` checks), as in step 3.

**Step 4: Run them, and the whole suite, to see them pass**

Run: `cd api && .venv/bin/pytest tests/test_migrations.py tests/test_signoff_rows.py -q`
Expected: `21 passed`

Run: `cd api && .venv/bin/pytest -q`
Expected: `465 passed` (nothing else uses the new tables yet).

**Step 5: Commit**

```
git add api/lms/models api/alembic/versions/0004_practicals.py api/tests/test_migrations.py api/tests/test_signoff_rows.py
git commit -m "Keep practical checklists, sign-offs and what they ticked, as they were" \
  -m "A checklist is written whole and never changed; a sign-off and its ticked items are append-only, by someone who is not the learner, and its grant is theirs. A sign-off's photo is a new kind of upload."
```

---

### Task 2: Supervisors, managers and admins sign off, on the phone too

**Files:**
- Modify: `api/lms/services/sessions.py`
- Test: `api/tests/test_sessions.py`, `api/tests/test_auth.py`

**Step 1: Write the failing tests**

In `api/tests/test_sessions.py`, replace:
```python
def test_a_pin_session_only_does_its_own_training_whoever_has_it():
    assert sessions.scopes_for("admin", "pin") == ["training:read", "training:write"]
    assert sessions.scopes_for("admin", "password") == ["*"]
    assert sessions.scopes_for("learner", "password") == ["training:read", "training:write"]
```
with:
```python
def test_a_pin_session_does_its_own_training_and_signs_off_practicals():
    assert sessions.scopes_for("learner", "pin") == ["training:read", "training:write"]
    for permission in ("supervisor", "manager", "admin"):
        assert sessions.scopes_for(permission, "pin") == [
            "training:read", "training:write", "signoffs:write"]
    assert sessions.scopes_for("admin", "password") == ["*"]
    assert sessions.scopes_for("learner", "password") == ["training:read", "training:write"]
    for permission in ("supervisor", "manager"):
        assert "signoffs:write" in sessions.scopes_for(permission, "password")
```

In `api/tests/test_auth.py`, replace:
```python
def test_a_supervisor_signed_in_by_pin_only_does_their_own_training(client, supervisor):
    by_pin = pin_login(client, supervisor.code)["person"]
    assert (by_pin["permission"], by_pin["scopes"]) == ("supervisor", ["training:read", "training:write"])
    by_password = login(client, supervisor.email)["person"]
    assert "matrix:read" in by_password["scopes"]
```
with:
```python
def test_a_supervisor_signed_in_by_pin_does_their_training_and_signs_off(client, supervisor):
    by_pin = pin_login(client, supervisor.code)["person"]
    assert (by_pin["permission"], by_pin["scopes"]) == (
        "supervisor", ["training:read", "training:write", "signoffs:write"])
    by_password = login(client, supervisor.email)["person"]
    assert "matrix:read" in by_password["scopes"] and "signoffs:write" in by_password["scopes"]
```

**Step 2: Run them to see them fail**

Run: `cd api && .venv/bin/pytest tests/test_sessions.py tests/test_auth.py -q`
Expected: FAIL: `2 failed, 25 passed`: a PIN session still carries `['training:read', 'training:write']`, with no `signoffs:write`.

**Step 3: Minimal implementation**

In `api/lms/services/sessions.py`, replace:
```python
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


def scopes_for(permission: str, method: str) -> list[str]:
    if method == "pin":
        return list(PIN_SCOPES)
    return list(SCOPES.get(permission, []))
```
with:
```python
# training:write is doing your own training: signing a policy, adding a
# ticket. tickets:verify is checking someone else's ticket. signoffs:write
# is signing off someone else's practical.
SCOPES: dict[str, list[str]] = {
    "learner": ["training:read", "training:write"],
    "supervisor": ["training:read", "training:write", "matrix:read", "roles:read",
                   "competencies:read", "signoffs:write"],
    "manager": ["training:read", "training:write", "matrix:read", "roles:read",
                "competencies:read", "people:read", "people:write", "roles:write",
                "competencies:write", "records:write", "tickets:verify", "signoffs:write"],
    "admin": ["*"],
}
# A PIN is short, so a PIN session is for the learner app: your own
# training, whoever signs in with it (seeing it, signing a policy, adding a
# ticket), and for a supervisor, manager or admin, signing off a practical
# on the phone, where the learner is.
PIN_SCOPES = ["training:read", "training:write"]
SIGNS_OFF = ("supervisor", "manager", "admin")


def scopes_for(permission: str, method: str) -> list[str]:
    if method == "pin":
        return PIN_SCOPES + (["signoffs:write"] if permission in SIGNS_OFF else [])
    return list(SCOPES.get(permission, []))
```

The desktop and the learner app read `scopes` from the session as they are, so nothing else changes for them here.

**Step 4: Run them to see them pass**

Run: `cd api && .venv/bin/pytest tests/test_sessions.py tests/test_auth.py -q`
Expected: `27 passed`

**Step 5: Commit**

```
git add api/lms/services/sessions.py api/tests/test_sessions.py api/tests/test_auth.py
git commit -m "Give supervisors, managers and admins the sign-off scope, on a PIN too"
```

---

### Task 3: A sign-off's photo, and a sign-off's files shown to the learner

**Files:**
- Modify: `api/lms/services/uploads.py`, `api/lms/api/routes/uploads.py`
- Test: `api/tests/test_uploads.py`

**Step 1: Write the failing tests**

Append to `api/tests/test_uploads.py`:
```python
@pytest.mark.parametrize("data, content_type", [(JPEG, "image/jpeg"), (PNG, "image/png")],
                         ids=["jpeg", "png"])
def test_a_supervisor_sends_a_signoffs_photo(client, supervisor_headers, data, content_type):
    r = send(client, supervisor_headers, "signoff-photo", data, "application/octet-stream")
    assert r.status_code == 201, r.text
    assert (r.json()["purpose"], r.json()["content_type"]) == ("signoff-photo", content_type)


def test_a_signoffs_photo_is_a_picture_of_20_mb_at_most(client, supervisor_headers):
    assert uploads.PURPOSES["signoff-photo"][1] == 20_000_000
    r = send(client, supervisor_headers, "signoff-photo", PDF, "application/pdf")
    assert r.status_code == 415 and r.json() == {
        "detail": "a signoff-photo file must be one of: JPG, PNG", "code": "unsupported_type"}


def test_only_someone_who_signs_off_sends_a_signoffs_photo(client, learner_headers):
    r = send(client, learner_headers, "signoff-photo", JPEG, "image/jpeg")
    assert r.status_code == 403 and r.json()["detail"] == "you do not have the signoffs:write scope"


def test_a_signoffs_files_are_shown_to_the_learner_too(
        client, db, learner, supervisor, supervisor_headers, learner_headers):
    """Sent from Sam's phone, so they are Sam's; but Kim may see what signed her off."""
    from lms.models import Competency, PracticalVersion, Signoff

    photo = sent(client, supervisor_headers, "signoff-photo", JPEG)
    signatures = [sent(client, supervisor_headers, "signature", PNG, "image/png") for _ in "ab"]
    forklift = Competency(key="forklift-practical", name="Forklift practical", kind="practical")
    db.add(forklift)
    db.flush()
    v = PracticalVersion(competency_id=forklift.id, version=1, published_by_id=supervisor.id)
    db.add(v)
    db.flush()
    db.add(Signoff(person_id=learner.id, competency_id=forklift.id, practical_version_id=v.id,
                   supervisor_id=supervisor.id, photo_upload_id=uuid.UUID(photo),
                   supervisor_signature_upload_id=uuid.UUID(signatures[0]),
                   learner_signature_upload_id=uuid.UUID(signatures[1])))
    db.commit()
    for file_id in (photo, *signatures):
        assert client.get(f"/v1/uploads/{file_id}", headers=learner_headers).status_code == 200
    make_person(db, "LL099", "Pat Other", pin="1357", supervisor=supervisor)
    pat = bearer(pin_login(client, "LL099", "1357")["token"])
    assert client.get(f"/v1/uploads/{photo}", headers=pat).status_code == 404
```

**Step 2: Run them to see them fail**

Run: `cd api && .venv/bin/pytest tests/test_uploads.py -q`
Expected: FAIL: `5 failed, 38 passed`: `signoff-photo` is refused as unknown (`Input should be 'ticket', 'signature', 'page-image', 'page-pdf' or 'page-video'`), and `KeyError: 'signoff-photo'`.

**Step 3: Minimal implementation**

In `api/lms/services/uploads.py`, replace:
```python
"""Files people send: a ticket's photos (or a PDF of it), policy
signatures, and a module page's picture, PDF or video. Kept on disk under
```
with:
```python
"""Files people send: a ticket's photos (or a PDF of it), signatures, a
module page's picture, PDF or video, and a sign-off's photo. Kept on disk under
```

In `api/lms/services/uploads.py`, replace:
```python
from lms.models import Person, TicketSubmission, Upload
```
with:
```python
from lms.models import Person, Signoff, TicketSubmission, Upload
```

In `api/lms/services/uploads.py`, replace:
```python
    "page-video": ({"video/mp4", "video/webm"}, 200_000_000),
}
# who may send each: anyone, for their own training; an editor, for a module
SENDERS = {
    "ticket": "training:write",
    "signature": "training:write",
    "page-image": "competencies:write",
    "page-pdf": "competencies:write",
    "page-video": "competencies:write",
}
```
with:
```python
    "page-video": ({"video/mp4", "video/webm"}, 200_000_000),
    "signoff-photo": ({"image/jpeg", "image/png"}, 20_000_000),
}
# who may send each: anyone, for their own training (and a signature, on a
# sign-off, for the learner beside them); an editor, for a module; whoever
# signs off a practical, for its photo
SENDERS = {
    "ticket": "training:write",
    "signature": "training:write",
    "page-image": "competencies:write",
    "page-pdf": "competencies:write",
    "page-video": "competencies:write",
    "signoff-photo": "signoffs:write",
}
```

In `api/lms/services/uploads.py`, replace:
```python
def on_a_ticket(db: Db, upload_id: uuid.UUID) -> bool:
```
with:
```python
def signed_off(db: Db, upload_id: uuid.UUID) -> Person | None:
    """The learner whose sign-off has this photo or signature on it, if one
    does. They were sent from the supervisor's phone, so they are the
    supervisor's; the learner may see them too."""
    return db.execute(select(Person).join(Signoff, Signoff.person_id == Person.id).where(or_(
        Signoff.photo_upload_id == upload_id,
        Signoff.supervisor_signature_upload_id == upload_id,
        Signoff.learner_signature_upload_id == upload_id))).scalar_one_or_none()


def on_a_ticket(db: Db, upload_id: uuid.UUID) -> bool:
```

In `api/lms/api/routes/uploads.py`, replace:
```python
"""Files: sent by the learner app before the ticket or signature that names
them, or by the desktop before the module page that shows them; and shown
only to who may see the person they belong to."""
```
with:
```python
"""Files: sent by the learner app before the ticket, signature or sign-off
that names them, or by the desktop before the module page that shows them;
and shown only to who may see the person they belong to (or, on a
sign-off, the learner it signs off)."""
```

In `api/lms/api/routes/uploads.py`, replace:
```python
Purpose = Literal["ticket", "signature", "page-image", "page-pdf", "page-video"]
```
with:
```python
Purpose = Literal["ticket", "signature", "page-image", "page-pdf", "page-video", "signoff-photo"]
```

In `api/lms/api/routes/uploads.py`, replace:
```python
@router.get("/uploads/{upload_id}", response_class=Response)
def get_file(upload_id: uuid.UUID, db: DB, who: Who):
    """For the person it belongs to, their supervisor, and managers and
    admins: whoever may see that person's training."""
    row = db.get(Upload, upload_id)
    if row is None or not who.sees(db.get(Person, row.person_id)):
        raise NotFound(f"no file {upload_id}")
```
with:
```python
def may_see(db, who: Principal, row: Upload) -> bool:
    """Whoever may see the training of the person it belongs to; and a
    sign-off's photo and signatures, whoever may see the learner too."""
    if who.sees(db.get(Person, row.person_id)):
        return True
    learner = uploads.signed_off(db, row.id)
    return learner is not None and who.sees(learner)


@router.get("/uploads/{upload_id}", response_class=Response)
def get_file(upload_id: uuid.UUID, db: DB, who: Who):
    """For the person it belongs to, their supervisor, and managers and
    admins: whoever may see that person's training. A sign-off's photo and
    signatures, sent from the supervisor's phone, for the learner's too."""
    row = db.get(Upload, upload_id)
    if row is None or not may_see(db, who, row):
        raise NotFound(f"no file {upload_id}")
```

**Step 4: Run them to see them pass**

Run: `cd api && .venv/bin/pytest tests/test_uploads.py -q`
Expected: `43 passed`

**Step 5: Commit**

```
git add api/lms/services/uploads.py api/lms/api/routes/uploads.py api/tests/test_uploads.py
git commit -m "Take a sign-off's photo from whoever signs off, and show a sign-off's files to the learner"
```

---
### Task 4: A practical's checklist: published whole, the newest the one to tick

**Files:**
- Create: `api/lms/services/practicals.py`, `api/lms/api/routes/practicals.py`, `api/tests/checklist.py`, `api/tests/test_practicals.py`
- Modify: `api/lms/api/app.py`

**Step 1: Write the failing test**

A practical for the tests that follow, as `course.py` is for the modules.

`api/tests/checklist.py`:
```python
"""A practical written through the API for the sign-off tests: the forklift
practical, refreshed every 12 months, and its checklist."""

FORKLIFT = "/v1/practicals/forklift-practical"

ITEMS = ["Checks the forks, chains and tyres", "Lifts a pallet to the top rack",
         "Parks with the forks down"]


def practical(client, headers, refresher_months=12):
    r = client.post("/v1/competencies", headers=headers, json={
        "key": "forklift-practical", "name": "Forklift practical", "kind": "practical",
        "refresher_months": refresher_months})
    assert r.status_code == 201, r.text


def published(client, headers, items=ITEMS, note=None) -> dict:
    """The next version of its checklist."""
    r = client.post(f"{FORKLIFT}/versions", headers=headers, json={"items": items, "note": note})
    assert r.status_code == 201, r.text
    return r.json()
```

`api/tests/test_practicals.py`:
```python
"""A practical's checklist: versions published whole by a manager, never
changed, the newest the one a supervisor ticks."""
import pytest

from checklist import FORKLIFT, ITEMS, practical, published
from conftest import all_at_once, bearer, fresh_client, pin_login


@pytest.fixture
def forklift(client, manager_headers):
    practical(client, manager_headers)


def test_versions_are_numbered_newest_first_with_their_items_in_order(client, manager_headers,
                                                                       forklift):
    one = published(client, manager_headers)
    two = published(client, manager_headers, [*ITEMS, "Signs the pre-start book"],
                    note="the pre-start book")
    assert (one["version"], two["version"]) == (1, 2)
    assert [i["text"] for i in one["items"]] == ITEMS
    assert two["published_by"] == {"code": "MG001", "name": "Mel Grant"}
    r = client.get(f"{FORKLIFT}/versions", headers=manager_headers).json()
    assert [v["version"] for v in r] == [2, 1] and r[0]["note"] == "the pre-start book"
    assert [i["text"] for i in r[0]["items"]][-1] == "Signs the pre-start book"


def test_a_checklist_has_one_to_fifty_things_to_see(client, manager_headers, forklift):
    for items in ([], ["  "], ["x"] * 51, ["x" * 301]):
        r = client.post(f"{FORKLIFT}/versions", headers=manager_headers, json={"items": items})
        assert r.status_code == 422, items


def test_only_a_practical_has_a_checklist(client, manager_headers, forklift):
    r = client.post("/v1/competencies", headers=manager_headers,
                    json={"key": "whs-policy", "name": "WHS policy", "kind": "policy"})
    assert r.status_code == 201
    r = client.post("/v1/practicals/whs-policy/versions", headers=manager_headers,
                    json={"items": ITEMS})
    assert r.status_code == 404 and r.json()["detail"] == "no practical whs-policy"
    assert client.get("/v1/practicals/nothing", headers=manager_headers).status_code == 404


def test_a_learner_or_supervisor_cannot_publish(client, learner_headers, supervisor_headers,
                                                forklift):
    for headers in (learner_headers, supervisor_headers):
        r = client.post(f"{FORKLIFT}/versions", headers=headers, json={"items": ITEMS})
        assert r.status_code == 403


def test_the_checklist_to_tick_now(client, manager_headers, supervisor, forklift):
    sam = bearer(pin_login(client, supervisor.code)["token"])
    r = client.get(FORKLIFT, headers=sam)
    assert r.status_code == 404
    assert r.json()["detail"] == "Forklift practical has no checklist yet"
    published(client, manager_headers)
    published(client, manager_headers, ITEMS[:2])
    out = client.get(FORKLIFT, headers=sam).json()
    assert (out["key"], out["name"], out["version"]["version"]) == (
        "forklift-practical", "Forklift practical", 2)
    assert [i["text"] for i in out["version"]["items"]] == ITEMS[:2]


def test_a_deactivated_practical_gets_no_new_checklist(client, manager_headers, forklift):
    client.post("/v1/competencies/forklift-practical/deactivate", headers=manager_headers)
    r = client.post(f"{FORKLIFT}/versions", headers=manager_headers, json={"items": ITEMS})
    assert r.status_code == 409 and r.json()["code"] == "inactive"


def test_two_published_at_once_are_1_and_2(client, manager_headers, forklift):
    def publish():
        return fresh_client().post(f"{FORKLIFT}/versions", headers=manager_headers,
                                   json={"items": ITEMS}).json()["version"]

    assert sorted(all_at_once(2, publish)) == [1, 2]
```

**Step 2: Run it to see it fail**

Run: `cd api && .venv/bin/pytest tests/test_practicals.py -q`
Expected: FAIL: `7 failed`: every `/v1/practicals/…` call is `404 {"detail": "Not Found"}`.

**Step 3: Minimal implementation**

`api/lms/services/practicals.py`:
```python
"""Practicals: a checklist a supervisor ticks while they watch, in
versions. The newest version is the one signed off now."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session as Db

from lms.models import Competency, PracticalVersion


def newest(db: Db, practical: Competency) -> PracticalVersion | None:
    return db.execute(select(PracticalVersion)
                      .where(PracticalVersion.competency_id == practical.id)
                      .order_by(PracticalVersion.version.desc()).limit(1)).scalar_one_or_none()
```

`api/lms/api/routes/practicals.py`:
```python
"""Practicals, as their editors and supervisors see them: a checklist of
things to see the learner do, published whole by a manager and never
changed, so a sign-off always says what was ticked (rule 1). A change is a
new version; the newest is the one ticked from then on."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import func, select

from lms.api.deps import DB, Principal, require
from lms.api.errors import Conflict, NotFound
from lms.api.routes.competencies import get_competency
from lms.api.schemas import PersonRef, person_ref
from lms.models import Competency, PracticalItem, PracticalVersion
from lms.services import practicals

router = APIRouter(tags=["practicals"])

Item = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]


class ChecklistIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    # what to see the learner do, in the order it is ticked
    items: list[Item] = Field(min_length=1, max_length=50)
    note: str | None = Field(default=None, max_length=500)


class ItemOut(BaseModel):
    # what a sign-off sends back as ticked
    id: int
    text: str


class ChecklistOut(BaseModel):
    id: int
    version: int
    items: list[ItemOut]
    note: str | None
    published_by: PersonRef
    created_at: datetime


class PracticalOut(BaseModel):
    key: str
    name: str
    version: ChecklistOut


def checklist_out(v: PracticalVersion) -> ChecklistOut:
    return ChecklistOut(id=v.id, version=v.version,
                        items=[ItemOut(id=i.id, text=i.text) for i in v.items], note=v.note,
                        published_by=person_ref(v.published_by), created_at=v.created_at)


def get_practical(db, key: str) -> Competency:
    c = get_competency(db, key)
    if c.kind != "practical":
        raise NotFound(f"no practical {key}")
    return c


def to_tick(db, c: Competency) -> PracticalVersion:
    v = practicals.newest(db, c)
    if v is None:
        raise NotFound(f"{c.name} has no checklist yet")
    return v


@router.get("/practicals/{key}/versions", response_model=list[ChecklistOut])
def list_versions(key: str, db: DB, who: Principal = require("competencies:read")):
    """Newest first: the first is the one ticked now."""
    c = get_practical(db, key)
    rows = db.execute(select(PracticalVersion).where(PracticalVersion.competency_id == c.id)
                      .order_by(PracticalVersion.version.desc())).scalars().all()
    return [checklist_out(v) for v in rows]


@router.post("/practicals/{key}/versions", status_code=201, response_model=ChecklistOut)
def publish_version(key: str, body: ChecklistIn, db: DB,
                    who: Principal = require("competencies:write")):
    """The next version, items and all. Sign-offs so far still count."""
    c = get_practical(db, key)
    # one at a time per practical, so two published at once get 1 and 2
    db.refresh(c, with_for_update=True)
    if not c.active:
        raise Conflict("inactive", f"{c.key} is deactivated")
    last = db.execute(select(func.max(PracticalVersion.version))
                      .where(PracticalVersion.competency_id == c.id)).scalar() or 0
    v = PracticalVersion(competency=c, version=last + 1, note=body.note or None,
                         published_by=who.person)
    db.add(v)
    db.flush()
    db.add_all([PracticalItem(practical_version_id=v.id, position=n, text=text)
                for n, text in enumerate(body.items)])
    db.commit()
    return JSONResponse(status_code=201, content=checklist_out(v).model_dump(mode="json"))


@router.get("/practicals/{key}", response_model=PracticalOut)
def read_practical(key: str, db: DB, who: Principal = require("training:read")):
    """The checklist to tick now."""
    c = get_practical(db, key)
    return PracticalOut(key=c.key, name=c.name, version=checklist_out(to_tick(db, c)))
```

The competency is locked before its next number is worked out, so two managers publishing at once get 1 and 2, and a practical deactivated meanwhile is seen as deactivated.

In `api/lms/api/app.py`, replace:
```python
    auth, competencies, learning, matrix, media, modules, overrides, people, policies, records,
    roles, settings, tickets, uploads,
)
```
with:
```python
    auth, competencies, learning, matrix, media, modules, overrides, people, policies,
    practicals, records, roles, settings, tickets, uploads,
)
```

In `api/lms/api/app.py`, replace:
```python
v1.include_router(learning.router)
```
with:
```python
v1.include_router(learning.router)
v1.include_router(practicals.router)
```

**Step 4: Run it to see it pass**

Run: `cd api && .venv/bin/pytest tests/test_practicals.py -q`
Expected: `7 passed`

**Step 5: Commit**

```
git add api/lms/services/practicals.py api/lms/api/routes/practicals.py api/lms/api/app.py api/tests/checklist.py api/tests/test_practicals.py
git commit -m "Publish a practical's checklist whole, and give supervisors the newest to tick"
```

---

### Task 5: Who a supervisor may sign off

**Files:**
- Create: `api/lms/api/routes/signoffs.py`, `api/tests/test_signoffs.py`
- Modify: `api/lms/services/practicals.py` (in full below), `api/lms/api/app.py`

**Step 1: Write the failing test**

`api/tests/test_signoffs.py`:
```python
"""Signing off a practical on the phone: a supervisor, for their own team
(a manager or admin, for anyone), never for themselves (rule 3), ticks every
item and signs; the learner confirms with their signature and their PIN.
The grant is recorded by the supervisor, and the refresher does the rest."""
import pytest

import yard
from checklist import practical
from conftest import bearer, make_person, pin_login

PEOPLE = "/v1/signoffs/people"


@pytest.fixture
def team(client, db, manager_headers, supervisor, learner):
    """Kim is on Sam's team, Pat on nobody's; both drive forklifts, and
    forklift drivers are signed off on the forklift practical."""
    practical(client, manager_headers)
    assert client.post("/v1/roles", headers=manager_headers,
                       json={"key": "forklift-driver", "name": "Forklift driver"}).status_code == 201
    assert client.put("/v1/roles/forklift-driver/requirements", headers=manager_headers,
                      json={"competencies": ["forklift-practical"]}).status_code == 200
    make_person(db, "LL099", "Pat Other", pin="1357")
    for code in ("LL042", "LL099"):
        yard.give_roles(client, manager_headers, code, "forklift-driver")
    return learner


@pytest.fixture
def sam(client, supervisor):
    """Sam on the phone, signed in with his PIN."""
    return bearer(pin_login(client, supervisor.code)["token"])


def test_a_supervisor_signs_off_their_own_team(client, sam, team):
    r = client.get(PEOPLE, headers=sam)
    assert r.status_code == 200, r.text
    assert r.json() == [{"code": "LL042", "name": "Kim Lee", "practicals": [
        {"key": "forklift-practical", "name": "Forklift practical", "status": "missing",
         "expires_on": None}]}]


def test_a_manager_signs_off_anyone_but_themselves(client, db, manager, manager_headers, team):
    make_person(db, "LL100", "Lee Gone").active = False
    db.commit()
    people = client.get(PEOPLE, headers=manager_headers).json()
    assert [p["code"] for p in people] == ["LL042", "LL099", "SV001"]
    assert people[2]["practicals"] == []


def test_a_practical_waived_is_not_to_sign_off(client, sam, manager_headers, team):
    r = client.post("/v1/people/LL042/overrides", headers=manager_headers, json={
        "competency": "forklift-practical", "kind": "waive", "note": "Moved to the office"})
    assert r.status_code == 201
    assert client.get(PEOPLE, headers=sam).json()[0]["practicals"] == []


def test_a_learner_signs_nobody_off(client, learner_headers, team):
    r = client.get(PEOPLE, headers=learner_headers)
    assert r.status_code == 403 and r.json()["detail"] == "you do not have the signoffs:write scope"
```

**Step 2: Run it to see it fail**

Run: `cd api && .venv/bin/pytest tests/test_signoffs.py -q`
Expected: FAIL: `4 failed`: `GET /v1/signoffs/people` is `404 {"detail": "Not Found"}`.

**Step 3: Minimal implementation**

`api/lms/services/practicals.py`:
```python
"""Practicals: a checklist a supervisor ticks while they watch, in
versions. The newest version is the one signed off now. Who signs off whom
is said here and nowhere else."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session as Db

from lms.models import Competency, Person, PracticalVersion

# who signs off anyone, not only their own team
ANYONE = ("manager", "admin")


def newest(db: Db, practical: Competency) -> PracticalVersion | None:
    return db.execute(select(PracticalVersion)
                      .where(PracticalVersion.competency_id == practical.id)
                      .order_by(PracticalVersion.version.desc()).limit(1)).scalar_one_or_none()


def may_sign_off(signer: Person, learner: Person) -> bool:
    """A supervisor signs off their own team (the people whose supervisor
    they are); a manager or admin, anyone. Nobody signs off themselves
    (rule 3)."""
    if learner.id == signer.id:
        return False
    return signer.permission in ANYONE or (signer.permission == "supervisor"
                                           and learner.supervisor_id == signer.id)
```

`api/lms/api/routes/signoffs.py`:
```python
"""Signing off a practical, on the phone where the learner is: a
supervisor (for their own team) or a manager or admin (for anyone), never
the learner themselves (rule 3)."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from lms.api.deps import DB, Principal, require
from lms.api.routes.matrix import TO_DO
from lms.models import Person
from lms.services import clock, practicals, standing

router = APIRouter(tags=["signoffs"])


class ToSignOff(BaseModel):
    key: str
    name: str
    status: str
    expires_on: date | None


class SignsOffOut(BaseModel):
    code: str
    name: str
    # the practicals they are asked for and not let off, by name
    practicals: list[ToSignOff]


@router.get("/signoffs/people", response_model=list[SignsOffOut])
def people_to_sign_off(db: DB, who: Principal = require("signoffs:write")):
    """Who the caller may sign off, by name: their team, or everyone active
    for a manager or admin; never themselves."""
    q = select(Person).where(Person.active.is_(True), Person.id != who.person.id)
    if who.person.permission not in practicals.ANYONE:
        q = q.where(Person.supervisor_id == who.person.id)
    people = [p for p in db.execute(q.order_by(Person.name, Person.code)).scalars()
              if practicals.may_sign_off(who.person, p)]
    st = standing.load(db, [p.id for p in people], clock.today())
    out = []
    for p in people:
        items = []
        for c in st.asked_for(p.id):
            comp, s = st.competencies[c], st.status(p.id, c)
            if comp.kind == "practical" and s.status in TO_DO:
                items.append(ToSignOff(key=comp.key, name=comp.name, status=s.status,
                                       expires_on=s.expires_on))
        items.sort(key=lambda i: (i.name, i.key))
        out.append(SignsOffOut(code=p.code, name=p.name, practicals=items))
    return out
```

In `api/lms/api/app.py`, replace:
```python
    practicals, records, roles, settings, tickets, uploads,
)
```
with:
```python
    practicals, records, roles, settings, signoffs, tickets, uploads,
)
```

In `api/lms/api/app.py`, replace:
```python
v1.include_router(practicals.router)
```
with:
```python
v1.include_router(practicals.router)
v1.include_router(signoffs.router)
```

**Step 4: Run it to see it pass**

Run: `cd api && .venv/bin/pytest tests/test_signoffs.py -q`
Expected: `4 passed`

**Step 5: Commit**

```
git add api/lms/services/practicals.py api/lms/api/routes/signoffs.py api/lms/api/app.py api/tests/test_signoffs.py
git commit -m "List who a supervisor may sign off, with the practicals each is asked for"
```

---

### Task 6: Signing off: every item ticked, both signatures, the learner's PIN, a grant by the supervisor

**Files:**
- Modify: `api/lms/api/routes/signoffs.py`, `api/lms/services/practicals.py` (both in full below), `api/lms/api/routes/records.py`, `api/lms/services/policies.py`
- Test: `api/tests/test_signoffs.py`

**Step 1: Write the failing test**

In `api/tests/test_signoffs.py`, replace:
```python
import pytest

import yard
from checklist import practical
from conftest import bearer, make_person, pin_login
```
with:
```python
from datetime import date

import pytest

import yard
from checklist import FORKLIFT, ITEMS, practical, published
from conftest import PIN, all_at_once, bearer, fresh_client, make_person, pin_login
from files import JPEG, PNG, sent
```

Append to `api/tests/test_signoffs.py`:
```python
def signed(client, headers, purpose="signature"):
    """A finger signature (or a photo) sent from the phone."""
    if purpose == "signoff-photo":
        return sent(client, headers, purpose, JPEG)
    return sent(client, headers, purpose, PNG, "image/png")


def body(client, headers, version=1, ticked=None, pin=PIN, **more) -> dict:
    """Every item on the newest checklist ticked, both signatures, the learner's PIN."""
    if ticked is None:
        ticked = [i["id"] for i in client.get(FORKLIFT, headers=headers).json()["version"]["items"]]
    return {"competency": "forklift-practical", "version": version, "ticked": ticked,
            "supervisor_signature": signed(client, headers),
            "learner_signature": signed(client, headers), "learner_pin": pin, **more}


def sign_off(client, headers, code="LL042", **more):
    return client.post(f"/v1/people/{code}/signoffs", headers=headers,
                       json=body(client, headers, **more))


@pytest.fixture
def checklist(client, manager_headers, team):
    return published(client, manager_headers)


def forklift(client, headers, code="LL042"):
    items = client.get(f"/v1/people/{code}/training", headers=headers).json()["items"]
    return next(i for i in items if i["key"] == "forklift-practical")


def test_signed_off_it_is_current_until_the_refresher(client, sam, learner_headers,
                                                       manager_headers, checklist):
    r = sign_off(client, sam, note="Smooth on the ramp", photo=signed(client, sam, "signoff-photo"))
    assert r.status_code == 201, r.text
    out = r.json()
    assert (out["kind"], out["granted_on"], out["expires_on"]) == ("granted", "2026-10-12", None)
    assert out["recorded_by"] == {"code": "SV001", "name": "Sam Vu"}
    s = out["signoff"]
    assert (s["version"], s["ticked"], s["note"]) == (1, ITEMS, "Smooth on the ramp")
    assert s["photo"] and s["supervisor_signature"] != s["learner_signature"]
    item = forklift(client, learner_headers)
    assert (item["status"], item["expires_on"]) == ("current", "2027-10-12")
    m = client.get("/v1/matrix", headers=manager_headers).json()
    assert next(p for p in m["people"] if p["code"] == "LL042")["cells"]["forklift-practical"][
        "status"] == "current"
    # Kim sees it in her history, photo and signatures too
    record = client.get("/v1/people/LL042/records", headers=learner_headers).json()[0]
    assert record["signoff"] == s
    for upload in (s["photo"], s["supervisor_signature"], s["learner_signature"]):
        assert client.get(f"/v1/uploads/{upload}", headers=learner_headers).status_code == 200


def test_the_refresher_brings_it_round_again(client, sam, learner_headers, checklist, today):
    sign_off(client, sam)
    today.set(date(2027, 9, 20))
    assert forklift(client, learner_headers)["status"] == "expiring"
    today.set(date(2027, 10, 13))
    assert forklift(client, learner_headers)["status"] == "lapsed"
    assert sign_off(client, sam).status_code == 201
    assert forklift(client, learner_headers)["expires_on"] == "2028-10-13"


def test_nobody_signs_off_their_own(client, manager_headers, checklist):
    r = sign_off(client, manager_headers, "MG001")
    assert r.status_code == 403 and r.json() == {
        "detail": "nobody signs off their own practical: ask your supervisor",
        "code": "own_signoff"}


def test_a_supervisor_signs_off_their_own_team_only(client, sam, manager_headers, checklist):
    r = sign_off(client, sam, "LL099", pin="1357")
    assert r.status_code == 404 and r.json()["detail"] == "no person LL099"
    assert sign_off(client, manager_headers, "LL099", pin="1357").status_code == 201


def test_every_item_is_ticked(client, sam, manager_headers, checklist):
    ids = [i["id"] for i in checklist["items"]]
    for ticked in (ids[:2], [*ids, ids[0]], [*ids[:2], 999_999]):
        r = sign_off(client, sam, ticked=ticked)
        assert r.status_code == 422 and r.json()["errors"] == [
            {"field": "ticked", "message": "tick all 3 items on the checklist"}]
    assert sign_off(client, sam, ticked=list(reversed(ids))).status_code == 201


def test_the_checklist_changed_meanwhile(client, sam, manager_headers, checklist):
    ids = [i["id"] for i in checklist["items"]]
    published(client, manager_headers, ITEMS[:2])
    r = sign_off(client, sam, ticked=ids)
    assert r.status_code == 409 and r.json() == {
        "detail": "version 2 is the checklist now: tick it again", "code": "new_version"}


def test_the_learner_confirms_with_their_own_pin(client, db, sam, learner, learner_headers,
                                                 checklist):
    # not a PIN at all: refused before it is checked, so it costs no try
    r = sign_off(client, sam, pin="12ab")
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "learner_pin"
    r = sign_off(client, sam, pin="1357")
    assert r.status_code == 422 and r.json()["errors"] == [
        {"field": "learner_pin", "message": "that isn't Kim Lee's PIN: try again"}]
    assert forklift(client, learner_headers)["status"] == "missing"
    db.refresh(learner)
    assert learner.pin_failed_attempts == 1
    assert sign_off(client, sam).status_code == 201
    db.refresh(learner)
    assert learner.pin_failed_attempts == 0


def test_five_wrong_pins_lock_it_as_signing_in_would(client, db, sam, learner, checklist):
    for _ in range(4):
        assert sign_off(client, sam, pin="0000").status_code == 422
    r = sign_off(client, sam, pin="0000")
    assert r.json()["errors"][0]["message"] == (
        "wrong PIN 5 times: Kim Lee's PIN is locked until a manager resets it")
    r = sign_off(client, sam)
    assert r.json()["errors"][0]["message"] == (
        "Kim Lee's PIN is locked after too many wrong tries: a manager resets it")
    r = client.post("/v1/auth/pin-login", json={"code": "LL042", "pin": PIN})
    assert r.status_code == 401 and r.json()["code"] == "locked"


def test_wrong_pins_sent_all_at_once_still_lock_after_five(client, db, sam, learner, checklist):
    bodies = [body(client, sam, pin="0000") for _ in range(8)]

    def guess():
        r = fresh_client().post("/v1/people/LL042/signoffs", headers=sam, json=bodies.pop())
        return r.json()["errors"][0]["message"]

    messages = all_at_once(8, guess)
    assert messages.count("that isn't Kim Lee's PIN: try again") == 4
    db.refresh(learner)
    assert learner.pin_locked is True


def test_a_learner_with_no_pin_cant_confirm(client, db, sam, learner, checklist):
    learner.pin_hash = None
    db.commit()
    r = sign_off(client, sam)
    assert r.status_code == 422 and r.json()["errors"] == [{
        "field": "learner_pin",
        "message": "Kim Lee has no PIN yet: a manager sets one on People, then sign off again"}]


def test_the_signatures_and_photo_are_the_supervisors_own_and_used_once(
        client, sam, learner_headers, checklist):
    ink = signed(client, sam)
    r = sign_off(client, sam, supervisor_signature=ink, learner_signature=ink)
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "learner_signature"
    kims = signed(client, learner_headers)
    r = sign_off(client, sam, supervisor_signature=kims)
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "supervisor_signature"
    r = sign_off(client, sam, photo=signed(client, sam))
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "photo"
    photo = signed(client, sam, "signoff-photo")
    first = sign_off(client, sam, photo=photo).json()["signoff"]
    for more in ({"photo": photo}, {"supervisor_signature": first["supervisor_signature"]},
                 {"learner_signature": first["learner_signature"]},
                 {"learner_signature": first["supervisor_signature"]}):
        r = sign_off(client, sam, **more)
        assert r.status_code == 422, more
        assert "already on" in r.json()["errors"][0]["message"]


def test_only_a_practical_with_a_checklist_is_signed_off(client, sam, manager_headers, team):
    r = sign_off(client, sam, ticked=[], competency="nothing")
    assert r.status_code == 404 and r.json()["detail"] == "no competency nothing"
    r = sign_off(client, sam, ticked=[])
    assert r.status_code == 404 and r.json()["detail"] == "Forklift practical has no checklist yet"
    client.post("/v1/competencies", headers=manager_headers,
                json={"key": "whs-policy", "name": "WHS policy", "kind": "policy"})
    r = sign_off(client, sam, ticked=[], competency="whs-policy")
    assert r.status_code == 422 and r.json()["errors"] == [
        {"field": "competency", "message": "whs-policy is not a practical"}]


def test_not_for_a_deactivated_practical_or_person(client, db, sam, manager_headers, learner,
                                                   checklist):
    client.post("/v1/competencies/forklift-practical/deactivate", headers=manager_headers)
    r = sign_off(client, sam)
    assert r.status_code == 409 and r.json()["code"] == "inactive"
    client.post("/v1/competencies/forklift-practical/reactivate", headers=manager_headers)
    learner.active = False
    db.commit()
    r = sign_off(client, sam)
    assert r.status_code == 409 and r.json()["detail"] == "LL042 is deactivated"


def test_a_signoff_put_right_by_a_revoke(client, sam, manager_headers, learner_headers,
                                         checklist):
    sign_off(client, sam)
    r = client.post("/v1/people/LL042/records/revoke", headers=manager_headers,
                    json={"competency": "forklift-practical", "note": "Signed off the wrong Kim"})
    assert r.status_code == 201
    assert forklift(client, learner_headers)["status"] == "missing"
```

**Step 2: Run it to see it fail**

Run: `cd api && .venv/bin/pytest tests/test_signoffs.py -q`
Expected: FAIL: `14 failed, 4 passed`: `POST /v1/people/LL042/signoffs` is `404 {"detail": "Not Found"}`, and nothing is granted (`assert 'missing' == 'expiring'` and the like).

**Step 3: Minimal implementation**

`api/lms/services/practicals.py`:
```python
"""Practicals: a checklist a supervisor ticks while they watch, in
versions. The newest version is the one signed off now. Who signs off whom
is said here and nowhere else."""
from __future__ import annotations

import uuid

from sqlalchemy import exists, select
from sqlalchemy.orm import Session as Db

from lms.models import Competency, Person, PracticalVersion, Signoff

# who signs off anyone, not only their own team
ANYONE = ("manager", "admin")


def newest(db: Db, practical: Competency) -> PracticalVersion | None:
    return db.execute(select(PracticalVersion)
                      .where(PracticalVersion.competency_id == practical.id)
                      .order_by(PracticalVersion.version.desc()).limit(1)).scalar_one_or_none()


def may_sign_off(signer: Person, learner: Person) -> bool:
    """A supervisor signs off their own team (the people whose supervisor
    they are); a manager or admin, anyone. Nobody signs off themselves
    (rule 3)."""
    if learner.id == signer.id:
        return False
    return signer.permission in ANYONE or (signer.permission == "supervisor"
                                           and learner.supervisor_id == signer.id)


def photo_used(db: Db, upload_id: uuid.UUID) -> bool:
    """A photo goes on one sign-off only. Its sender is locked while it is
    used, so two at once can't both find it unused."""
    return db.execute(select(exists().where(Signoff.photo_upload_id == upload_id))).scalar()
```

`api/lms/api/routes/signoffs.py`:
```python
"""Signing off a practical, on the phone where the learner is: a
supervisor (for their own team) or a manager or admin (for anyone) watches,
ticks every item on the checklist, adds a note or a photo if they like, and
signs; the learner then signs on the same phone and types their PIN to say
it was them. Never the learner themselves (rule 3). The grant is recorded
by whoever signed it off, and the refresher does the rest."""
from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from lms.api.deps import DB, Principal, require
from lms.api.errors import Conflict, FieldError, Forbidden, NotFound
from lms.api.routes.auth import TRIES
from lms.api.routes.competencies import get_competency
from lms.api.routes.matrix import TO_DO
from lms.api.routes.people import get_person
from lms.api.routes.practicals import to_tick
from lms.api.routes.records import RecordOut, record_out
from lms.api.schemas import PIN
from lms.models import CompetencyRecord, Person, Signoff, SignoffItem
from lms.services import access, clock, policies, practicals, standing, uploads

router = APIRouter(tags=["signoffs"])


class ToSignOff(BaseModel):
    key: str
    name: str
    status: str
    expires_on: date | None


class SignsOffOut(BaseModel):
    code: str
    name: str
    # the practicals they are asked for and not let off, by name
    practicals: list[ToSignOff]


class SignoffIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    competency: str = Field(max_length=64)
    # the checklist ticked: if a newer one came out meanwhile, tick that
    version: int
    # every item on it, by id
    ticked: list[int] = Field(max_length=50)
    note: str | None = Field(default=None, max_length=500)
    # sent first from the phone: POST /v1/uploads?purpose=signoff-photo
    photo: uuid.UUID | None = None
    # both drawn on the phone and sent first, purpose signature
    supervisor_signature: uuid.UUID
    learner_signature: uuid.UUID
    # typed by the learner on the supervisor's phone: never kept
    learner_pin: str = Field(pattern=PIN)


@router.get("/signoffs/people", response_model=list[SignsOffOut])
def people_to_sign_off(db: DB, who: Principal = require("signoffs:write")):
    """Who the caller may sign off, by name: their team, or everyone active
    for a manager or admin; never themselves."""
    q = select(Person).where(Person.active.is_(True), Person.id != who.person.id)
    if who.person.permission not in practicals.ANYONE:
        q = q.where(Person.supervisor_id == who.person.id)
    people = [p for p in db.execute(q.order_by(Person.name, Person.code)).scalars()
              if practicals.may_sign_off(who.person, p)]
    st = standing.load(db, [p.id for p in people], clock.today())
    out = []
    for p in people:
        items = []
        for c in st.asked_for(p.id):
            comp, s = st.competencies[c], st.status(p.id, c)
            if comp.kind == "practical" and s.status in TO_DO:
                items.append(ToSignOff(key=comp.key, name=comp.name, status=s.status,
                                       expires_on=s.expires_on))
        items.sort(key=lambda i: (i.name, i.key))
        out.append(SignsOffOut(code=p.code, name=p.name, practicals=items))
    return out


def both_at_once(db, learner: Person, signer: Person) -> None:
    """The learner stays locked until this is in, so a sign-off and a
    revoke (or their PIN typed twice at once) are weighed one after the
    other; and the signer, whose photo and signatures go on one sign-off
    only. In id order, so two sign-offs at once never wait on each other."""
    for p in sorted({learner, signer}, key=lambda p: p.id):
        db.refresh(p, with_for_update=True)


def mine(db, who: Principal, upload_id: uuid.UUID | None, purpose: str, field: str,
         missing: str):
    row = uploads.mine(db, who.person, upload_id, purpose)
    if row is None:
        raise FieldError(field, missing)
    return row


def learner_confirms(db, p: Person, pin: str) -> None:
    """The learner's own PIN, typed on the signer's phone, says it was them.
    It counts against the same five tries as signing in: a wrong one here
    is a wrong one there."""
    if not p.pin_hash:
        raise FieldError("learner_pin", f"{p.name} has no PIN yet: a manager sets one on "
                                        "People, then sign off again")
    if p.pin_locked:
        raise FieldError("learner_pin", f"{p.name}'s PIN is locked after too many wrong tries: "
                                        "a manager resets it")
    if not access.verify_password(pin, p.pin_hash):
        p.pin_failed_attempts += 1
        p.pin_locked = p.pin_failed_attempts >= TRIES
        db.commit()
        if p.pin_locked:
            raise FieldError("learner_pin", f"wrong PIN {TRIES} times: {p.name}'s PIN is locked "
                                            "until a manager resets it")
        raise FieldError("learner_pin", f"that isn't {p.name}'s PIN: try again")
    p.pin_failed_attempts = 0


@router.post("/people/{code}/signoffs", status_code=201, response_model=RecordOut)
def sign_off(code: str, body: SignoffIn, db: DB, who: Principal = require("signoffs:write")):
    """Every item ticked, both signatures, and the learner's PIN: a grant
    from today, recorded by the caller."""
    p = get_person(db, code)
    if p.id == who.person.id:
        raise Forbidden("nobody signs off their own practical: ask your supervisor",
                        "own_signoff")
    both_at_once(db, p, who.person)
    # asked once both are locked: a new supervisor meanwhile is the one that counts
    if not practicals.may_sign_off(who.person, p):
        raise NotFound(f"no person {code}")
    if not p.active:
        raise Conflict("inactive", f"{p.code} is deactivated")
    c = get_competency(db, body.competency)
    if c.kind != "practical":
        raise FieldError("competency", f"{c.key} is not a practical")
    if not c.active:
        raise Conflict("inactive", f"{c.key} is deactivated")
    v = to_tick(db, c)
    if body.version != v.version:
        raise Conflict("new_version", f"version {v.version} is the checklist now: tick it again")
    items = {i.id for i in v.items}
    if len(body.ticked) != len(items) or set(body.ticked) != items:
        raise FieldError("ticked", f"tick all {len(items)} items on the checklist")
    photo = None
    if body.photo is not None:
        photo = mine(db, who, body.photo, "signoff-photo", "photo", "send the photo first")
        if practicals.photo_used(db, photo.id):
            raise FieldError("photo", "this photo is already on a sign-off: take another")
    theirs = mine(db, who, body.supervisor_signature, "signature", "supervisor_signature",
                  "sign with your finger first")
    learners = mine(db, who, body.learner_signature, "signature", "learner_signature",
                    f"{p.name} signs with their finger first")
    if learners.id == theirs.id:
        raise FieldError("learner_signature", f"{p.name} signs for themselves: not with yours")
    for field, row in (("supervisor_signature", theirs), ("learner_signature", learners)):
        if policies.signature_used(db, row.id):
            raise FieldError(field, "this signature is already on a record: sign again")
    # last, so nothing else wastes one of the learner's tries
    learner_confirms(db, p, body.learner_pin)
    s = Signoff(person_id=p.id, competency=c, practical_version_id=v.id,
                supervisor_id=who.person.id, note=body.note or None,
                photo_upload_id=photo.id if photo else None,
                supervisor_signature_upload_id=theirs.id,
                learner_signature_upload_id=learners.id)
    db.add(s)
    db.flush()
    db.add_all([SignoffItem(signoff_id=s.id, practical_item_id=i, practical_version_id=v.id)
                for i in body.ticked])
    r = CompetencyRecord(person_id=p.id, competency=c, kind="granted", granted_on=clock.today(),
                         recorded_by=who.person, signoff=s)
    db.add(r)
    db.commit()
    return JSONResponse(status_code=201, content=record_out(r).model_dump(mode="json"))
```

The order of the checks matters: the person and both rows locked first (in id order, so two sign-offs at once never wait on each other), then everything that can be wrong without the learner, and the PIN last, so a mistake elsewhere never spends one of their five tries. A wrong PIN is counted and committed before the `422`, as at sign-in.

In `api/lms/services/policies.py`, replace:
```python
from sqlalchemy import exists, select
from sqlalchemy.orm import Session as Db

from lms.models import Competency, CompetencyRecord, PolicyVersion
```
with:
```python
from sqlalchemy import exists, or_, select
from sqlalchemy.orm import Session as Db

from lms.models import Competency, CompetencyRecord, PolicyVersion, Signoff
```

In `api/lms/services/policies.py`, replace:
```python
def signature_used(db: Db, upload_id: uuid.UUID) -> bool:
    """A drawn signature goes on one record only: it can't be put on another
    version later. The signer's row is locked while they sign, so two at once
    can't both find it unused."""
    return db.execute(select(exists().where(
        CompetencyRecord.signature_upload_id == upload_id))).scalar()
```
with:
```python
def signature_used(db: Db, upload_id: uuid.UUID) -> bool:
    """A drawn signature goes on one record or sign-off only: it can't be
    put on another version, or another sign-off, later. Whoever sent it is
    locked while it is used, so two at once can't both find it unused."""
    return db.execute(select(
        exists().where(CompetencyRecord.signature_upload_id == upload_id)
        | exists().where(or_(Signoff.supervisor_signature_upload_id == upload_id,
                             Signoff.learner_signature_upload_id == upload_id)))).scalar()
```

In `api/lms/api/routes/records.py`, replace:
```python
from lms.models import Competency, CompetencyRecord
```
with:
```python
from lms.models import Competency, CompetencyRecord, Signoff
```

In `api/lms/api/routes/records.py`, replace:
```python
class RecordOut(BaseModel):
```
with:
```python
class SignoffOut(BaseModel):
    """A practical signed off on the phone: the checklist version, what was
    ticked, the note and photo, and both signatures (GET /v1/uploads/{id}).
    The supervisor is the record's recorded_by."""
    version: int
    ticked: list[str]
    note: str | None
    photo: uuid.UUID | None
    supervisor_signature: uuid.UUID
    learner_signature: uuid.UUID


class RecordOut(BaseModel):
```

In `api/lms/api/routes/records.py`, replace:
```python
    # a module passed in the learner app: the quiz that passed it
    quiz: QuizOut | None
    created_at: datetime


def record_out(r: CompetencyRecord) -> RecordOut:
```
with:
```python
    # a module passed in the learner app: the quiz that passed it
    quiz: QuizOut | None
    # a practical signed off on the phone
    signoff: SignoffOut | None
    created_at: datetime


def signoff_out(s: Signoff) -> SignoffOut:
    return SignoffOut(version=s.practical_version.version,
                      ticked=[t.item.text for t in sorted(s.ticked, key=lambda t: t.item.position)],
                      note=s.note, photo=s.photo_upload_id,
                      supervisor_signature=s.supervisor_signature_upload_id,
                      learner_signature=s.learner_signature_upload_id)


def record_out(r: CompetencyRecord) -> RecordOut:
```

In `api/lms/api/routes/records.py`, replace:
```python
                                  pass_mark=a.module_version.pass_mark) if a else None,
                     created_at=r.created_at)
```
with:
```python
                                  pass_mark=a.module_version.pass_mark) if a else None,
                     signoff=signoff_out(r.signoff) if r.signoff else None,
                     created_at=r.created_at)
```

**Step 4: Run it, and the whole suite, to see them pass**

Run: `cd api && .venv/bin/pytest tests/test_signoffs.py -q`
Expected: `18 passed`

Run: `cd api && .venv/bin/pytest -q`
Expected: `495 passed` (every record now says `"signoff": null` unless it is one, and a policy's signature is still checked as before).

**Step 5: Commit**

```
git add api/lms/api/routes/signoffs.py api/lms/services/practicals.py api/lms/services/policies.py api/lms/api/routes/records.py api/tests/test_signoffs.py
git commit -m "Sign off a practical: every item ticked, both signatures and the learner's PIN" \
  -m "A grant from today, recorded by whoever signed it off, never the learner. The PIN counts against the same five tries as signing in and is never kept."
```

---
### Task 7: CI checks the new triggers

**Files:**
- Modify: `.github/workflows/ci.yml`

**Step 1: The check that fails**

```
cd "/Users/leightonlauton/Q7 Technology/Software/q7/simple-lms"
docker compose up -d --build db api
for i in $(seq 1 30); do curl -fsS http://127.0.0.1:8033/v1/health && break; sleep 2; done; echo
docker compose exec -T db psql -U lms -d lms -tAc "select count(*) from pg_trigger where tgname like '%_append_only'"
docker compose exec -T db psql -U lms -d lms -tAc "select count(*) from pg_trigger where tgname like '%_written_with_%' or tgname = 'competency_record_signoff'"
```
Expected: `{"status":"ok"}`, then `9` and `3` (the API ran migration `0004` as it started), while CI still looks for `5` append-only triggers and nothing of the sign-offs'.

**Step 2: Implementation**

In `.github/workflows/ci.yml`, replace:
```yaml
          # the append-only triggers, the ticket's decide-once one, and the
          # module's: published once, pages and questions changed only in a
          # draft, attempts only at a published version, a quiz's grant only
          # from that person's own passing attempt
          docker compose exec -T db psql -U lms -d lms -tAc \
            "select count(*) from pg_trigger where tgname like '%_append_only'" | grep -qx 5
```
with:
```yaml
          # the append-only triggers, the ticket's decide-once one, and the
          # module's: published once, pages and questions changed only in a
          # draft, attempts only at a published version, a quiz's grant only
          # from that person's own passing attempt. And the practical's: a
          # checklist's items and a sign-off's ticks written with them and
          # never after, a sign-off's grant only by its supervisor
          docker compose exec -T db psql -U lms -d lms -tAc \
            "select count(*) from pg_trigger where tgname like '%_append_only'" | grep -qx 9
          docker compose exec -T db psql -U lms -d lms -tAc \
            "select count(*) from pg_trigger where tgname like '%_written_with_%' or tgname = 'competency_record_signoff'" | grep -qx 3
```

**Step 3: Run the check to see it pass**

The lines CI runs, here:
```
docker compose exec -T db psql -U lms -d lms -tAc "select count(*) from pg_trigger where tgname like '%_append_only'" | grep -qx 9 && echo ok
docker compose exec -T db psql -U lms -d lms -tAc "select count(*) from pg_trigger where tgname like '%_written_with_%' or tgname = 'competency_record_signoff'" | grep -qx 3 && echo ok
```
Expected: `ok` and `ok`.

**Step 4: Commit**

```
git add .github/workflows/ci.yml
git commit -m "Check the practical's triggers in CI"
```

---

### Task 8: `docs/api.md`

**Files:**
- Modify: `docs/api.md`

**Step 1: Write it**

In `docs/api.md`, replace:
````markdown
  row for a person and competency is the one that counts. Every quiz attempt
  is kept, and a module version is frozen once it is published.
````
with:
````markdown
  row for a person and competency is the one that counts. Every quiz attempt
  is kept, and a module version is frozen once it is published. A
  practical's checklist versions and every sign-off, with what it ticked,
  are kept as they were.
````

In `docs/api.md`, replace:
````markdown
| `supervisor` | `training:read`, `training:write`, `matrix:read`, `roles:read`, `competencies:read` |
| `manager` | the supervisor's, plus `people:read`, `people:write`, `roles:write`, `competencies:write`, `records:write`, `tickets:verify` |
| `admin` | `*` (everything, `settings:write` among it) |

`training:write` is doing your own training: sending a file, signing a
policy, sending in a ticket, reading a module and taking its quiz. A
session signed in with a **PIN** carries
`training:read` and `training:write` only, whoever it is: a PIN is short, so
it opens the learner app's own training and nothing more.
````
with:
````markdown
| `supervisor` | `training:read`, `training:write`, `matrix:read`, `roles:read`, `competencies:read`, `signoffs:write` |
| `manager` | the supervisor's, plus `people:read`, `people:write`, `roles:write`, `competencies:write`, `records:write`, `tickets:verify` |
| `admin` | `*` (everything, `settings:write` among it) |

`training:write` is doing your own training: sending a file, signing a
policy, sending in a ticket, reading a module and taking its quiz.
`signoffs:write` is signing off someone else's practical. A session signed
in with a **PIN** carries `training:read` and `training:write`, whoever it
is, and `signoffs:write` too for a supervisor, manager or admin: a PIN is
short, so it opens the learner app's own training, and signing off a
practical on the phone where the learner is, and nothing more.
````

In `docs/api.md`, replace:
````markdown
Every kind can still be recorded by hand. Policies are signed in the
learner app, tickets sent in from it and modules taken in it (below);
practicals get their own way in with a later build step.
````
with:
````markdown
Every kind can still be recorded by hand. Policies are signed in the
learner app, tickets sent in from it and modules taken in it, and
practicals are signed off on a supervisor's phone (below).
````

In `docs/api.md`, replace:
````markdown
     "policy_version": null, "signed_name": null, "signature": null, "ticket": null,
     "quiz": null, "created_at": "…" }]
  ```
  `policy_version` is the policy version a grant is for; `signed_name` and
  `signature` (an upload id) are there when it was signed in the learner
  app; `ticket` is the ticket's id when a manager approved one; `quiz` is
  `{ "version", "score", "pass_mark" }` when the person passed a module's
  quiz (recorded as theirs).
````
with:
````markdown
     "policy_version": null, "signed_name": null, "signature": null, "ticket": null,
     "quiz": null, "signoff": null, "created_at": "…" }]
  ```
  `policy_version` is the policy version a grant is for; `signed_name` and
  `signature` (an upload id) are there when it was signed in the learner
  app; `ticket` is the ticket's id when a manager approved one; `quiz` is
  `{ "version", "score", "pass_mark" }` when the person passed a module's
  quiz (recorded as theirs); `signoff` is `{ "version", "ticked", "note",
  "photo", "supervisor_signature", "learner_signature" }` when a practical
  was signed off on the phone (recorded by whoever signed it off): the
  checklist version, the text of each item ticked in order, and upload ids
  for the photo (or `null`) and both signatures.
````

In `docs/api.md`, replace:
````markdown
Tickets' photos (or a PDF), policy signatures, and a module page's
picture, PDF or video. Sent before the ticket, signature or page that names
them; kept on the host under `LMS_UPLOAD_DIR` (`/data/uploads`), named by a
````
with:
````markdown
Tickets' photos (or a PDF), signatures, a module page's picture, PDF or
video, and a sign-off's photo. Sent before the ticket, signature, page or
sign-off that names them; kept on the host under `LMS_UPLOAD_DIR` (`/data/uploads`), named by a
````

In `docs/api.md`, replace:
````markdown
  | `page-video` | `competencies:write` | MP4 or WebM | 200 MB |
````
with:
````markdown
  | `page-video` | `competencies:write` | MP4 or WebM | 200 MB |
  | `signoff-photo` | `signoffs:write` | JPEG or PNG | 20 MB |
````

In `docs/api.md`, replace:
````markdown
  person, their supervisor, and managers and admins. Anyone else gets `404`
  (and so does a file missing from disk). Sent with `Cache-Control: private, no-store`,
````
with:
````markdown
  person, their supervisor, and managers and admins. A sign-off's photo and
  signatures are sent from the supervisor's phone, so they are the
  supervisor's; whoever may see the learner they sign off gets them too.
  Anyone else gets `404`
  (and so does a file missing from disk). Sent with `Cache-Control: private, no-store`,
````

In `docs/api.md`, replace:
````markdown
A ticket or signature may only name the caller's own uploads of the right
purpose. Each upload goes on one record or ticket only: the database holds
each signature to one record and each photo to one ticket.
````
with:
````markdown
A ticket, signature or sign-off may only name the caller's own uploads of
the right purpose. Each upload goes on one record, ticket or sign-off only:
the database holds each signature to one record or sign-off and each photo
to one ticket or sign-off, and the API holds a signature to one of either.
````

In `docs/api.md`, replace:
````markdown
## Policies

- `POST /v1/policies/{key}/versions` (`competencies:write`) — `{ "body",
````
with:
````markdown
## Practicals

A practical is a competency of kind `practical`: a checklist of things a
supervisor watches the learner do, published whole and never changed (the
database refuses), so a sign-off always says what was ticked. A change is a
new version; supervisors tick the newest from then on, and a new version
asks nobody to be signed off again (sign-offs so far still count).

- `POST /v1/practicals/{key}/versions` (`competencies:write`) — `{ "items":
  [ … ], "note"? }` → `201`, the next version (1, 2, 3 …): 1 to 50 items, in
  the order they are ticked, each up to 300 characters. A deactivated
  practical is `409 { "code": "inactive" }`.
- `GET /v1/practicals/{key}/versions` (`competencies:read`) — newest first:
  `[{ "id", "version", "items": [{ "id", "text" }], "note", "published_by":
  { "code", "name" }, "created_at" }]`.
- `GET /v1/practicals/{key}` (`training:read`) — the checklist to tick now:
  `{ "key", "name", "version": { … } }`; `404` until one is published.

A key that is not a practical is `404` on all of these.

## Signing off

`signoffs:write`. A supervisor signs off their own team; a manager or admin
signs off anyone. Nobody signs off themselves, admins included.

- `GET /v1/signoffs/people` — the people the caller may sign off (their
  team, or every active person for a manager or admin; never themselves),
  by name, each with the practicals they are asked for and not let off:
  `[{ "code", "name", "practicals": [{ "key", "name", "status", "expires_on" }] }]`.
- `POST /v1/people/{code}/signoffs` — on the supervisor's phone, with the
  learner beside them: `{ "competency", "version", "ticked": [item ids],
  "note"?, "photo"?, "supervisor_signature", "learner_signature",
  "learner_pin" }` → `201`, the record (above): a grant from today, recorded
  by the caller, with `signoff` filled in; the competency's refresher, if
  any, says when it runs out. `ticked` is every item on that version, and
  nothing else (`422` on `ticked`). `photo` is an upload of purpose
  `signoff-photo`; both signatures are uploads of purpose `signature`; all
  three are the caller's own, sent from the phone (`422` on the field
  otherwise). The two signatures differ, and each, like the photo, goes on
  one record or sign-off only (`422`: sign or take it again).
  `learner_pin` is the learner's own PIN, typed by them on the phone to say
  it was them: never kept. It is checked last, and counts against the same
  five tries as signing in: a wrong one is `422` on `learner_pin` ("that
  isn't Kim Lee's PIN: try again"), the fifth locks the PIN until a manager
  resets it, and a locked PIN, or none (someone who signs in with a
  password), is `422` there too. `version` is the checklist ticked: if a
  newer one was published meanwhile, `409 { "code": "new_version" }`, and
  it is ticked again. Signing off yourself is `403 { "code": "own_signoff"
  }`; someone a supervisor may not sign off is `404`; a learner (no
  `signoffs:write`) is `403`. A competency that is not a practical is `422`
  on `competency`, one with no checklist yet `404`, and a deactivated
  practical or person `409 { "code": "inactive" }`.

A sign-off is put right like any grant: revoke it with a note
(`POST /v1/people/{code}/records/revoke`).

## Policies

- `POST /v1/policies/{key}/versions` (`competencies:write`) — `{ "body",
````

**Step 2: Check it against the app**

Run: `cd api && .venv/bin/python -c "from lms.api.app import app; print(sorted(p for p in app.openapi()['paths'] if p.startswith('/v1')))"`
Expected: every path in the list has its section in `docs/api.md`; the new ones are `/v1/practicals/{key}`, `/v1/practicals/{key}/versions`, `/v1/signoffs/people` and `/v1/people/{code}/signoffs`.

**Step 3: Commit**

```
git add docs/api.md
git commit -m "Document practicals, signing off and the sign-off scope in docs/api.md"
```

---
### Task 9: Write a practical's checklist on the desktop

**Files:**
- Create: `apps/desktop/src/pages/ChecklistEditor.tsx`, `apps/desktop/src/test/Checklist.test.tsx`
- Modify: `apps/desktop/src/pages/Competencies.tsx`, `apps/desktop/src/api/types.ts`

**Step 1: Write the failing tests**

`apps/desktop/src/test/Checklist.test.tsx`:
```tsx
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Checklist, Competency } from "../api/types";
import { setGamePrefs } from "../lib/gamePrefs";
import { json, renderApp, stubApi } from "./harness";

const FORKLIFT: Competency = { id: 5, key: "forklift-practical", name: "Forklift practical", kind: "practical", refresher_months: 12, card_expires: null, active: true };
const V1: Checklist = {
  id: 1, version: 1, note: null, published_by: { code: "MG001", name: "Mel Grant" }, created_at: "2026-09-01T01:00:00Z",
  items: [{ id: 11, text: "Checks the forks, chains and tyres" }, { id: 12, text: "Lifts a pallet to the top rack" }],
};
const PATH = "/v1/practicals/forklift-practical/versions";

/** Competencies with the forklift practical, whose checklists are `versions`; publishing adds the next. */
function stubChecklist(versions: Checklist[], practical = FORKLIFT) {
  let list = versions;
  return stubApi((method, url, body) => {
    if (url === "/v1/competencies") return json(200, { items: [practical], total: 1 });
    if (url === PATH && method === "POST") {
      const { items, note } = body as { items: string[]; note: string | null };
      list = [{ ...V1, id: list.length + 1, version: list.length + 1, note,
                items: items.map((text, n) => ({ id: 20 + n, text })) }, ...list];
      return json(201, list[0]);
    }
    if (url === PATH) return json(200, list);
    return null;
  });
}

async function openForklift() {
  renderApp("/competencies");
  await userEvent.click(await screen.findByRole("button", { name: /Forklift practical/ }));
  return screen.findByRole("dialog", { name: "Forklift practical" });
}

describe("a practical's checklist", () => {
  it("shows the one supervisors tick, and publishes the next as a changed copy", async () => {
    const { calls } = stubChecklist([V1]);
    const drawer = await openForklift();
    expect(await within(drawer).findByText(/is the one supervisors tick/)).toHaveTextContent(
      "Version 1 is the one supervisors tick · published 1 Sep 2026 by Mel Grant");
    const next = within(drawer).getByRole("form", { name: "Version 2" });
    expect(within(next).getByLabelText("Item 1")).toHaveValue("Checks the forks, chains and tyres");
    // a copy as it is would be the same checklist again
    expect(within(next).getByRole("button", { name: "Publish version 2" })).toBeDisabled();
    await userEvent.click(within(next).getByRole("button", { name: "Add an item" }));
    await userEvent.type(within(next).getByLabelText("Item 3"), "Parks with the forks down");
    await userEvent.click(within(next).getByRole("button", { name: "Move item 3 up" }));
    await userEvent.type(within(next).getByLabelText("What changed (optional)"), "parking");
    await userEvent.click(within(next).getByRole("button", { name: "Publish version 2" }));
    // it can't be undone: ask once first
    expect(within(next).getByText("Publish version 2? Its items are frozen once it is, and every sign-off from now on ticks them.")).toBeInTheDocument();
    expect(calls.some((c) => c.method === "POST")).toBe(false);
    await userEvent.click(within(next).getByRole("button", { name: "Publish" }));
    await waitFor(() => expect(calls.find((c) => c.method === "POST")?.body).toEqual({
      items: ["Checks the forks, chains and tyres", "Parks with the forks down", "Lifts a pallet to the top rack"],
      note: "parking" }));
    expect(await within(drawer).findByText(/Version 2/, { selector: "b" })).toBeInTheDocument();
    expect(within(drawer).getByRole("form", { name: "Version 3" })).toBeInTheDocument();
  });

  it("writes version 1 from nothing, and asks before closing on it", async () => {
    const { calls } = stubChecklist([]);
    const drawer = await openForklift();
    expect(await within(drawer).findByText("No checklist yet: nobody can be signed off until there is one.")).toBeInTheDocument();
    const next = within(drawer).getByRole("form", { name: "Version 1" });
    const publish = within(next).getByRole("button", { name: "Publish version 1" });
    expect(publish).toBeDisabled();
    await userEvent.type(within(next).getByLabelText("Item 1"), "Lifts a pallet");
    await userEvent.click(within(next).getByRole("button", { name: "Add an item" }));
    // an empty item is not something to tick
    expect(publish).toBeDisabled();
    await userEvent.click(within(next).getByRole("button", { name: "Remove item 2" }));
    await userEvent.click(within(drawer).getByRole("button", { name: "Close" }));
    expect(within(drawer).getByText("Version 1 has changes that aren't published. Close it anyway?")).toBeInTheDocument();
    await userEvent.click(within(drawer).getByRole("button", { name: "Keep editing" }));
    await userEvent.click(publish);
    await userEvent.click(within(next).getByRole("button", { name: "Publish" }));
    await waitFor(() => expect(calls.find((c) => c.method === "POST")?.body).toEqual({ items: ["Lifts a pallet"], note: null }));
  });

  it("asks for a deactivated practical to be reactivated before a new checklist, with Game Mode off too", async () => {
    // the plain desktop: Competencies is a page of its own, not a drawer over the classroom
    setGamePrefs({ classroom: false });
    stubChecklist([V1], { ...FORKLIFT, active: false });
    const drawer = await openForklift();
    expect(screen.queryByRole("region", { name: "Competencies" })).not.toBeInTheDocument();
    expect(await within(drawer).findByText("Reactivate it to publish a new checklist.")).toBeInTheDocument();
    expect(within(drawer).queryByRole("button", { name: /Publish version/ })).not.toBeInTheDocument();
  });
});
```

**Step 2: Run them to see them fail**

Run: `cd apps/desktop && npm test`
Expected: FAIL: `Tests  3 failed | 110 passed (113)`: the drawer has no checklist yet (`Unable to find an element with the text: /is the one supervisors tick/`, `… No checklist yet: nobody can be signed off until there is one.` and `… Reactivate it to publish a new checklist.`).

**Step 3: Minimal implementation**

`apps/desktop/src/pages/ChecklistEditor.tsx`:
```tsx
import { useState, type FormEvent } from "react";
import { api } from "../api/client";
import type { Checklist, Competency } from "../api/types";
import { formatDate } from "../lib/status";
import { useAction, useLoad } from "../lib/useLoad";
import { Problem, useCloseGuard } from "../ui/Drawer";

/** The most items a checklist has, as the API has it. */
const MOST = 50;

/** An item as it is written; `uid` keeps it itself as it moves. */
interface Line { uid: number; text: string }
let uids = 0;
const lines = (texts: string[]): Line[] => texts.map((text) => ({ uid: ++uids, text }));

function move<T>(list: T[], from: number, to: number): T[] {
  const out = [...list];
  const [item] = out.splice(from, 1);
  out.splice(to, 0, item);
  return out;
}

/** A practical's checklist: what a supervisor watches the learner do, and
 * ticks. The version supervisors tick now is shown as it is; the next is
 * written whole, starting as a copy, and publishing freezes it, so every
 * sign-off says what was ticked. Sign-offs so far still count. */
export function ChecklistEditor({ practical }: { practical: Competency }) {
  const path = `/v1/practicals/${encodeURIComponent(practical.key)}/versions`;
  const versions = useLoad(() => api.get<Checklist[]>(path), [path]);
  const newest = versions.data?.[0] ?? null;

  return (
    <section className="flex flex-col gap-3" aria-label="Checklist">
      <div className="eyebrow">Checklist</div>
      <Problem error={versions.error} />
      {versions.data?.length === 0 && <div className="small">No checklist yet: nobody can be signed off until there is one.</div>}
      {newest && (
        <div className="card flex flex-col gap-2 text-sm">
          <div><b>Version {newest.version}</b> is the one supervisors tick · published {formatDate(newest.created_at.slice(0, 10))} by {newest.published_by.name}</div>
          {newest.note && <div className="small">What changed: {newest.note}</div>}
          <ol className="list-decimal pl-5">{newest.items.map((i) => <li key={i.id}>{i.text}</li>)}</ol>
        </div>
      )}
      {versions.data && (practical.active
        ? <NextVersion key={newest?.id ?? 0} path={path} from={newest} onPublished={versions.reload} />
        : <div className="small">Reactivate it to publish a new checklist.</div>)}
    </section>
  );
}

function NextVersion({ path, from, onPublished }: { path: string; from: Checklist | null; onPublished: () => void }) {
  const start = from ? from.items.map((i) => i.text) : [""];
  const [items, setItems] = useState<Line[]>(() => lines(start));
  const [note, setNote] = useState("");
  // it can't be undone: ask once
  const [confirming, setConfirming] = useState(false);
  const action = useAction();
  const next = (from?.version ?? 0) + 1;
  const texts = items.map((i) => i.text.trim());
  const same = texts.join("\n") === start.join("\n");
  const ready = texts.length > 0 && texts.every(Boolean) && !same;
  useCloseGuard(same && !note.trim() ? null : `Version ${next} has changes that aren't published.`);

  const edit = (change: (ls: Line[]) => Line[]) => { setConfirming(false); setItems(change); };

  async function publish(e: FormEvent) {
    e.preventDefault();
    if (!confirming) { setConfirming(true); return; }
    setConfirming(false);
    if (await action.run(() => api.post(path, { items: texts, note: note.trim() || null }))) onPublished();
  }

  return (
    <form className="card flex flex-col gap-3" onSubmit={publish} aria-label={`Version ${next}`}>
      <div className="eyebrow">Version {next}</div>
      {from && <div className="small">Version {next} starts as a copy of version {from.version}. Supervisors tick version {from.version} until you publish it, and sign-offs so far still count.</div>}
      <ol className="flex flex-col gap-2">
        {items.map((item, i) => (
          <li key={item.uid} className="flex items-center gap-2">
            <input className="field" aria-label={`Item ${i + 1}`} value={item.text} maxLength={300}
                   placeholder="e.g. Checks the forks, chains and tyres"
                   onChange={(e) => { const text = e.target.value; edit((ls) => ls.map((l) => (l.uid === item.uid ? { ...l, text } : l))); }} />
            <button type="button" className="btn" disabled={i === 0} aria-label={`Move item ${i + 1} up`} onClick={() => edit((ls) => move(ls, i, i - 1))}>↑</button>
            <button type="button" className="btn" disabled={i === items.length - 1} aria-label={`Move item ${i + 1} down`} onClick={() => edit((ls) => move(ls, i, i + 1))}>↓</button>
            <button type="button" className="btn danger" aria-label={`Remove item ${i + 1}`} onClick={() => edit((ls) => ls.filter((l) => l.uid !== item.uid))}>Remove</button>
          </li>
        ))}
      </ol>
      <button type="button" className="btn" disabled={items.length >= MOST} onClick={() => edit((ls) => [...ls, ...lines([""])])}>Add an item</button>
      <label className="label">What changed (optional)
        <input className="field" value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} />
      </label>
      {same && <div className="small">Change an item to publish a new version.</div>}
      <Problem error={action.error} />
      {confirming ? (
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-sm"><b>Publish version {next}? Its items are frozen once it is, and every sign-off from now on ticks them.</b></span>
          <button type="submit" className="btn primary" disabled={action.busy}>Publish</button>
          <button type="button" className="btn" autoFocus onClick={() => setConfirming(false)}>Cancel</button>
        </div>
      ) : (
        <button type="submit" className="btn primary" disabled={action.busy || !ready}>Publish version {next}</button>
      )}
    </form>
  );
}
```

Each item keeps its own `uid` as it moves, as the module editor's pages do, so React never mixes up two inputs. The next version is keyed by the newest's id: once one is published, the form starts again as a copy of it.

Append to `apps/desktop/src/api/types.ts`:
```ts
/** A practical's checklist: the items a supervisor ticks, frozen once published. */
export interface Checklist {
  id: number;
  version: number;
  items: { id: number; text: string }[];
  note: string | null;
  published_by: PersonRef;
  created_at: string;
}
```

In `apps/desktop/src/pages/Competencies.tsx`, replace:
```tsx
import { Drawer, Problem } from "../ui/Drawer";
import { ModuleEditor } from "./ModuleEditor";
```
with:
```tsx
import { Drawer, Problem } from "../ui/Drawer";
import { ChecklistEditor } from "./ChecklistEditor";
import { ModuleEditor } from "./ModuleEditor";
```

In `apps/desktop/src/pages/Competencies.tsx`, replace:
```tsx
/** Competencies: what each is called, its kind and its refresher; a
 * policy's versions, a ticket's card expiry, and a module's pages and quiz. */
```
with:
```tsx
/** Competencies: what each is called, its kind and its refresher; a
 * policy's versions, a ticket's card expiry, a module's pages and quiz, and
 * a practical's checklist. */
```

In `apps/desktop/src/pages/Competencies.tsx`, replace:
```tsx
      {competency.kind === "module" && <ModuleEditor module={competency} />}
```
with:
```tsx
      {competency.kind === "module" && <ModuleEditor module={competency} />}
      {competency.kind === "practical" && <ChecklistEditor practical={competency} />}
```

**Step 4: Run them to see them pass**

Run: `cd apps/desktop && npm test && npm run typecheck`
Expected: `Tests  113 passed (113)`, and no type errors.

**Step 5: Commit**

```
git add apps/desktop/src/pages/ChecklistEditor.tsx apps/desktop/src/pages/Competencies.tsx apps/desktop/src/api/types.ts apps/desktop/src/test/Checklist.test.tsx
git commit -m "Write a practical's checklist in its drawer on Competencies, and ask once before publishing it"
```

---

### Task 10: A sign-off in the history

**Files:**
- Modify: `apps/desktop/src/pages/HistoryDrawer.tsx`, `apps/desktop/src/api/types.ts`
- Test: `apps/desktop/src/test/Checklist.test.tsx`

**Step 1: Write the failing test**

Append to `apps/desktop/src/test/Checklist.test.tsx`:
```tsx
describe("a practical signed off", () => {
  it("shows in the history: what was ticked, the note, the photo and both signatures", async () => {
    URL.createObjectURL = vi.fn(() => "blob:picture");
    URL.revokeObjectURL = vi.fn();
    const matrix = {
      today: "2026-10-12", competencies: [{ key: "forklift-practical", name: "Forklift practical", kind: "practical" }],
      people: [{ code: "LL042", name: "Kim Lee", roles: [], supervisor: { code: "SV001", name: "Sam Vu" },
                 cells: { "forklift-practical": { status: "current", granted_on: "2026-10-12", expires_on: "2027-10-12" } } }],
    };
    const signedOff = {
      id: 9, competency: matrix.competencies[0], kind: "granted", granted_on: "2026-10-12", expires_on: null, note: null,
      recorded_by: { code: "SV001", name: "Sam Vu" }, policy_version: null, signed_name: null, signature: null,
      ticket: null, quiz: null, created_at: "2026-10-12T01:00:00Z",
      signoff: { version: 1, ticked: ["Checks the forks, chains and tyres", "Lifts a pallet to the top rack"],
                 note: "Smooth on the ramp", photo: "p-1", supervisor_signature: "s-1", learner_signature: "s-2" },
    };
    stubApi((_m, url) => {
      if (url.startsWith("/v1/matrix")) return json(200, matrix);
      if (url === "/v1/roles") return json(200, { items: [], total: 0 });
      if (url.startsWith("/v1/people/LL042/records")) return json(200, [signedOff]);
      if (url.startsWith("/v1/uploads/")) return new Response(new Uint8Array([0x89, 0x50]), { status: 200, headers: { "Content-Type": "image/png" } });
      return null;
    });
    renderApp("/matrix");
    await userEvent.click(await screen.findByRole("button", { name: /Kim Lee, Forklift practical/ }));
    const drawer = await screen.findByRole("dialog", { name: "Forklift practical" });
    expect(await within(drawer).findByText("Signed off on checklist version 1, every item ticked:")).toBeInTheDocument();
    expect(within(drawer).getByText("Lifts a pallet to the top rack")).toBeInTheDocument();
    expect(within(drawer).getByText("“Smooth on the ramp”")).toBeInTheDocument();
    expect(await within(drawer).findByRole("img", { name: "The sign-off photo" })).toBeInTheDocument();
    expect(within(drawer).getByRole("img", { name: "Sam Vu's signature" })).toBeInTheDocument();
    expect(within(drawer).getByRole("img", { name: "Kim Lee's signature" })).toBeInTheDocument();
    expect(within(drawer).getByText("Kim Lee signed too, and confirmed it with their PIN.")).toBeInTheDocument();
    expect(within(drawer).getByText(/by Sam Vu/)).toBeInTheDocument();
  });
});
```

**Step 2: Run it to see it fail**

Run: `cd apps/desktop && npm test`
Expected: FAIL: `Tests  1 failed | 113 passed (114)`: `Unable to find an element with the text: Signed off on checklist version 1, every item ticked:`.

**Step 3: Minimal implementation**

In `apps/desktop/src/api/types.ts`, replace:
```ts
  /** a module passed in the learner app: the version, the score and the pass mark */
  quiz: { version: number; score: number; pass_mark: number } | null;
  created_at: string;
}
```
with:
```ts
  /** a module passed in the learner app: the version, the score and the pass mark */
  quiz: { version: number; score: number; pass_mark: number } | null;
  /** a practical signed off on the phone: what was ticked, and upload ids
   * for the photo and both signatures. The supervisor is `recorded_by`. */
  signoff: {
    version: number; ticked: string[]; note: string | null; photo: string | null;
    supervisor_signature: string; learner_signature: string;
  } | null;
  created_at: string;
}
```

In `apps/desktop/src/pages/HistoryDrawer.tsx`, replace:
```tsx
            {r.quiz && (
              <div className="text-sm">Passed the quiz on version {r.quiz.version} with {r.quiz.score}% (pass mark {r.quiz.pass_mark}%)</div>
            )}
```
with:
```tsx
            {r.quiz && (
              <div className="text-sm">Passed the quiz on version {r.quiz.version} with {r.quiz.score}% (pass mark {r.quiz.pass_mark}%)</div>
            )}
            {r.signoff && (
              <>
                <div className="text-sm">Signed off on checklist version {r.signoff.version}, every item ticked:</div>
                <ul className="text-sm list-disc pl-5">{r.signoff.ticked.map((t, n) => <li key={n}>{t}</li>)}</ul>
                {r.signoff.note && <div className="text-sm">“{r.signoff.note}”</div>}
                {r.signoff.photo && <Picture upload={r.signoff.photo} label="The sign-off photo" />}
                <div className="flex flex-wrap gap-3">
                  <Picture upload={r.signoff.supervisor_signature} label={`${r.recorded_by.name}'s signature`} width={160} />
                  <Picture upload={r.signoff.learner_signature} label={`${person.name}'s signature`} width={160} />
                </div>
                <div className="small">{person.name} signed too, and confirmed it with their PIN.</div>
              </>
            )}
```

The supervisor is the record's `recorded_by`, so the card's last line already says "by Sam Vu". `Picture` fetches each file with the session's token; the API lets a manager, the learner's supervisor and the learner have them.

**Step 4: Run it to see it pass, and build**

Run: `cd apps/desktop && npm test && npm run build`
Expected: `Tests  114 passed (114)`, then `✓ built in …`.

**Step 5: Commit**

```
git add apps/desktop/src/pages/HistoryDrawer.tsx apps/desktop/src/api/types.ts apps/desktop/src/test/Checklist.test.tsx
git commit -m "Show a sign-off in the history: what was ticked, the note, the photo and both signatures"
```

---

### Task 11: My training: a practical waits for the supervisor, and Sign someone off

**Files:**
- Modify: `apps/learner/src/lib/training.ts`, `apps/learner/src/pages/MyTraining.tsx`
- Test: `apps/learner/src/test/training.test.ts`, `apps/learner/src/test/learner.test.tsx`

**Step 1: Write the failing tests**

In `apps/learner/src/test/training.test.ts`, replace:
```ts
    expect(nextStep({ ...module, status: "lapsed" })).toEqual({ to: "/module/site-induction", label: "Start the module" });
  });
});
```
with:
```ts
    expect(nextStep({ ...module, status: "lapsed" })).toEqual({ to: "/module/site-induction", label: "Start the module" });
  });

  it("says a practical is signed off with their supervisor", () => {
    const practical = { ...item("Forklift practical", "missing"), kind: "practical" as const };
    expect(nextStep(practical)).toEqual({ waiting: "Your supervisor signs this off with you" });
    expect(nextStep({ ...practical, status: "expiring" })).toEqual({ waiting: "Your supervisor signs this off with you" });
    expect(nextStep({ ...practical, status: "current" })).toBeNull();
  });
});
```

Append to `apps/learner/src/test/learner.test.tsx`:
```tsx
describe("signing someone off", () => {
  it("is offered on My training to someone who signs off practicals, and to nobody else", async () => {
    stubApi(answers);
    const { unmount } = renderApp({ ...KIM, code: "SV001", name: "Sam Vu", permission: "supervisor",
                                    scopes: ["training:read", "training:write", "signoffs:write"] });
    expect(await screen.findByRole("link", { name: "Sign someone off" })).toHaveAttribute("href", "/signoff");
    unmount();
    window.localStorage.clear();
    renderApp(KIM);
    expect(await screen.findByRole("heading", { name: "My training" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Sign someone off" })).not.toBeInTheDocument();
  });
});
```

**Step 2: Run them to see them fail**

Run: `cd apps/learner && npm test`
Expected: FAIL: `Tests  2 failed | 72 passed (74)`: `AssertionError: expected null to deeply equal { Object (waiting) }`, and `Unable to find role="link" and name "Sign someone off"`.

**Step 3: Minimal implementation**

In `apps/learner/src/lib/training.ts`, replace:
```ts
/** What the learner can do about an item here: do a module or sign a
 * policy that isn't current, or send in a ticket that is missing, running
 * out or run out. A ticket already sent in waits for a manager. */
export function nextStep(item: TrainingItem): Step {
  const key = encodeURIComponent(item.key);
```
with:
```ts
/** What the learner can do about an item here: do a module or sign a
 * policy that isn't current, or send in a ticket that is missing, running
 * out or run out. A ticket already sent in waits for a manager; a practical
 * waits for their supervisor to watch them do it. */
export function nextStep(item: TrainingItem): Step {
  const key = encodeURIComponent(item.key);
  if (item.kind === "practical" && item.status !== "current") return { waiting: "Your supervisor signs this off with you" };
```

In `apps/learner/src/pages/MyTraining.tsx`, replace:
```tsx
/** What is overdue, what is due soon and what is done; a policy to sign or a
 * ticket to send in opens from its item. */
```
with:
```tsx
/** What is overdue, what is due soon and what is done; a policy to sign or a
 * ticket to send in opens from its item. Someone who signs off practicals
 * starts one from here. */
```

In `apps/learner/src/pages/MyTraining.tsx`, replace:
```tsx
  const g = training ? groupTraining(training.items) : null;
```
with:
```tsx
  const g = training ? groupTraining(training.items) : null;
  const signsOff = person?.scopes.some((s) => s === "*" || s === "signoffs:write");
```

In `apps/learner/src/pages/MyTraining.tsx`, replace:
```tsx
      <h1 style={{ margin: 0, fontSize: 26, fontWeight: 800 }}>My training</h1>
```
with:
```tsx
      {signsOff && <Link to="/signoff" className="big primary as-button">Sign someone off</Link>}
      <h1 style={{ margin: 0, fontSize: 26, fontWeight: 800 }}>My training</h1>
```

**Step 4: Run them to see them pass**

Run: `cd apps/learner && npm test && npm run typecheck`
Expected: `Tests  74 passed (74)`, and no type errors. (The button goes nowhere yet: the next task adds the screens.)

**Step 5: Commit**

```
git add apps/learner/src/lib/training.ts apps/learner/src/pages/MyTraining.tsx apps/learner/src/test/training.test.ts apps/learner/src/test/learner.test.tsx
git commit -m "Say a practical is signed off with the supervisor, and offer Sign someone off to those who do"
```

---

### Task 12: The sign-off on the phone: tick, sign, hand it over, the learner confirms

**Files:**
- Create: `apps/learner/src/pages/SignOff.tsx`, `apps/learner/src/test/signoff.test.tsx`
- Modify: `apps/learner/src/App.tsx`, `apps/learner/src/api/types.ts`, `apps/learner/src/api/client.ts`, `apps/learner/src/pictures.tsx`

**Step 1: Write the failing tests**

`apps/learner/src/test/signoff.test.tsx`:
```tsx
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Me } from "../api/types";
import { json, KIM, listen, renderApp, stubApi } from "./harness";

vi.mock("../lib/picture", () => ({
  toBlob: async () => new Blob([new Uint8Array([0x89, 0x50, 0x4e, 0x47])], { type: "image/png" }),
  forSending: async (f: File) => f.type === "application/pdf" ? f : new Blob([new Uint8Array([0xff, 0xd8, 0xff])], { type: "image/jpeg" }),
}));

/** Sam, a supervisor, on his phone with his PIN. */
const SAM: Me = { ...KIM, id: 2, code: "SV001", name: "Sam Vu", permission: "supervisor",
                  scopes: ["training:read", "training:write", "signoffs:write"] };
const PEOPLE = [{ code: "LL042", name: "Kim Lee", practicals: [
  { key: "forklift-practical", name: "Forklift practical", status: "missing", expires_on: null }] }];
const V1 = { id: 1, version: 1, note: null, items: [
  { id: 11, text: "Checks the forks, chains and tyres" }, { id: 12, text: "Lifts a pallet to the top rack" }] };
const FORKLIFT = { key: "forklift-practical", name: "Forklift practical", version: V1 };
const KIMS = "/signoff/LL042/forklift-practical";

/** The API as Sam sees it; `signoff` answers the sign-off itself. */
function stubSignoff(signoff: (body: unknown) => Response = () => json(201, { kind: "granted" }),
                     practical: () => unknown = () => FORKLIFT) {
  let signatures = 0;
  return stubApi((method, url, body) => {
    if (url === "/v1/people/SV001/training") return json(200, { person: { code: "SV001", name: "Sam Vu" }, today: "2026-10-12", items: [] });
    if (url === "/v1/signoffs/people") return json(200, PEOPLE);
    if (url === "/v1/practicals/forklift-practical") return json(200, practical());
    if (method === "POST" && url === "/v1/uploads?purpose=signature") return json(201, { id: `sig-${++signatures}` });
    if (method === "POST" && url === "/v1/uploads?purpose=signoff-photo") return json(201, { id: "photo-1" });
    if (method === "POST" && url === "/v1/people/LL042/signoffs") return signoff(body);
    return null;
  });
}

/** jsdom draws nothing, so the pads get a context that takes the strokes. */
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

/** Sam ticks everything and signs, and hands the phone to Kim. */
async function samTicksAndSigns() {
  for (const item of V1.items) await userEvent.click(await screen.findByLabelText(item.text));
  signWithAFinger();
  await userEvent.click(screen.getByRole("button", { name: "Hand the phone to Kim Lee" }));
  return screen.findByRole("heading", { name: "Kim Lee, check and sign" });
}

describe("signing off a practical", () => {
  beforeEach(() => {
    canDraw();
    URL.createObjectURL = vi.fn(() => "blob:photo");
    URL.revokeObjectURL = vi.fn();
  });

  it("Sam ticks every item and signs; Kim checks, signs and types her PIN; Ding!", async () => {
    const heard = listen();
    const calls = stubSignoff();
    renderApp(SAM);
    await userEvent.click(await screen.findByRole("link", { name: "Sign someone off" }));
    const kim = await screen.findByRole("region", { name: "Kim Lee" });
    const link = within(kim).getByRole("link", { name: "Sign off Kim Lee: Forklift practical" });
    expect(link).toHaveTextContent("Forklift practical · Not done yet");
    await userEvent.click(link);
    expect(await screen.findByRole("heading", { name: "Forklift practical" })).toBeInTheDocument();
    const handOver = screen.getByRole("button", { name: "Hand the phone to Kim Lee" });
    await userEvent.click(screen.getByLabelText("Checks the forks, chains and tyres"));
    signWithAFinger();
    // every item, and Sam's signature, before Kim has the phone
    expect(screen.getByText("1 of 2 ticked")).toBeInTheDocument();
    expect(handOver).toBeDisabled();
    await userEvent.click(screen.getByLabelText("Lifts a pallet to the top rack"));
    await userEvent.type(screen.getByLabelText("A note (optional)"), "Smooth on the ramp");
    await userEvent.upload(screen.getByLabelText(/A photo/), new File(["x"], "yard.jpg", { type: "image/jpeg" }));
    await userEvent.click(handOver);

    expect(await screen.findByRole("heading", { name: "Kim Lee, check and sign" })).toBeInTheDocument();
    // Kim holds the phone: nothing leads to Sam's training from here
    expect(screen.queryByRole("link", { name: "Back to My training" })).not.toBeInTheDocument();
    expect(screen.getByRole("list", { name: "What was ticked" })).toHaveTextContent("Lifts a pallet to the top rack");
    expect(screen.getByText("Their note: “Smooth on the ramp”")).toBeInTheDocument();
    const confirm = screen.getByRole("button", { name: "Confirm" });
    await userEvent.type(screen.getByLabelText("Your PIN"), "2468");
    expect(confirm).toBeDisabled();
    signWithAFinger();
    await userEvent.click(confirm);
    expect(await screen.findByRole("status", { name: "Signed off" })).toHaveTextContent("Kim Lee is signed off for Forklift practical.");
    // out loud too, as a pass does, woken by the tap on Confirm
    expect(heard).toEqual({ notes: 2, woken: 1 });
    expect(calls.filter((c) => c.url.startsWith("/v1/uploads")).map((c) => [c.url, c.contentType])).toEqual([
      ["/v1/uploads?purpose=signature", "image/png"], ["/v1/uploads?purpose=signoff-photo", "image/jpeg"],
      ["/v1/uploads?purpose=signature", "image/png"]]);
    expect(calls.find((c) => c.url === "/v1/people/LL042/signoffs")?.body).toEqual({
      competency: "forklift-practical", version: 1, ticked: [11, 12], note: "Smooth on the ramp", photo: "photo-1",
      supervisor_signature: "sig-1", learner_signature: "sig-2", learner_pin: "2468" });
  });

  it("says a wrong PIN, keeps none of it, and lets Kim try again", async () => {
    let tries = 0;
    const calls = stubSignoff(() => ++tries === 1
      ? json(422, { errors: [{ field: "learner_pin", message: "that isn't Kim Lee's PIN: try again" }] })
      : json(201, { kind: "granted" }));
    renderApp(SAM, Date.now(), KIMS);
    await samTicksAndSigns();
    signWithAFinger();
    await userEvent.type(screen.getByLabelText("Your PIN"), "1357");
    await userEvent.click(screen.getByRole("button", { name: "Confirm" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("That isn't Kim Lee's PIN: try again.");
    expect(screen.getByLabelText("Your PIN")).toHaveValue("");
    await userEvent.type(screen.getByLabelText("Your PIN"), "2468");
    await userEvent.click(screen.getByRole("button", { name: "Confirm" }));
    expect(await screen.findByRole("status", { name: "Signed off" })).toBeInTheDocument();
    const sent = calls.filter((c) => c.url === "/v1/people/LL042/signoffs").map((c) => (c.body as { learner_pin: string }).learner_pin);
    expect(sent).toEqual(["1357", "2468"]);
    expect(screen.queryByLabelText("Your PIN")).not.toBeInTheDocument();
  });

  it("goes back to Sam when the checklist changed meanwhile", async () => {
    let practical: unknown = FORKLIFT;
    stubSignoff(() => {
      practical = { ...FORKLIFT, version: { ...V1, id: 2, version: 2, items: [...V1.items, { id: 13, text: "Parks with the forks down" }] } };
      return json(409, { detail: "version 2 is the checklist now: tick it again", code: "new_version" });
    }, () => practical);
    renderApp(SAM, Date.now(), KIMS);
    await samTicksAndSigns();
    signWithAFinger();
    await userEvent.type(screen.getByLabelText("Your PIN"), "2468");
    await userEvent.click(screen.getByRole("button", { name: "Confirm" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The checklist has changed: tick it again, then sign.");
    expect(await screen.findByRole("group", { name: "Checklist, version 2" })).toBeInTheDocument();
    expect(screen.getByLabelText("Parks with the forks down")).not.toBeChecked();
    expect(screen.getByLabelText("Lifts a pallet to the top rack")).not.toBeChecked();
    expect(screen.getByRole("button", { name: "Hand the phone to Kim Lee" })).toBeDisabled();
  });

  it("gives the phone back to Sam, ticks kept and his signature to do again", async () => {
    stubSignoff();
    renderApp(SAM, Date.now(), KIMS);
    await samTicksAndSigns();
    await userEvent.click(screen.getByRole("button", { name: "Give it back to Sam Vu" }));
    expect(await screen.findByLabelText("Lifts a pallet to the top rack")).toBeChecked();
    expect(screen.getByRole("img", { name: "Signature pad: empty" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Hand the phone to Kim Lee" })).toBeDisabled();
  });

  it("takes a photo, not a PDF", async () => {
    stubSignoff();
    renderApp(SAM, Date.now(), KIMS);
    const user = userEvent.setup({ applyAccept: false });
    await user.upload(await screen.findByLabelText(/A photo/), new File(["%PDF-"], "card.pdf", { type: "application/pdf" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Choose a photo, not a PDF.");
  });

  it("says when it can't: someone not on the team, or no checklist yet", async () => {
    stubSignoff(undefined, () => null);
    const { unmount } = renderApp(SAM, Date.now(), "/signoff/LL099/forklift-practical");
    expect(await screen.findByRole("alert")).toHaveTextContent("You can't sign this person off: they aren't on your team.");
    unmount();
    stubApi((_m, url) => url === "/v1/signoffs/people" ? json(200, PEOPLE)
      : url === "/v1/practicals/forklift-practical" ? json(404, { detail: "Forklift practical has no checklist yet" }) : null);
    renderApp(SAM, Date.now(), KIMS);
    expect(await screen.findByRole("alert")).toHaveTextContent("There's no checklist for this practical yet. Ask your manager.");
  });

  it("finds a person in a long list", async () => {
    const many = ["Ana Bell", "Bo Chan", "Cy Dunn", "Di Ezra", "Ed Fox", "Flo Gray", "Kim Lee"].map((name, n) => ({
      code: `LL${n}`, name, practicals: [] }));
    stubApi((_m, url) => url === "/v1/signoffs/people" ? json(200, many) : null);
    renderApp(SAM, Date.now(), "/signoff");
    await userEvent.type(await screen.findByLabelText("Find a person"), "kim");
    await waitFor(() => expect(screen.getAllByRole("region").map((r) => r.getAttribute("aria-label"))).toEqual(["Kim Lee"]));
    expect(screen.getByText("Not asked for any practical.")).toBeInTheDocument();
  });
});
```

**Step 2: Run them to see them fail**

Run: `cd apps/learner && npm test`
Expected: FAIL: `Tests  7 failed | 74 passed (81)`: there is no `/signoff` yet, so the app goes back to My training (`Unable to find role="region" and name "Kim Lee"`, `Unable to find a label with the text of: Checks the forks, chains and tyres` and the like).

**Step 3: Minimal implementation**

`apps/learner/src/pages/SignOff.tsx`:
```tsx
import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { api, ApiError } from "../api/client";
import type { Practical, SignsOff } from "../api/types";
import { useSession } from "../auth/Session";
import { toBlob } from "../lib/picture";
import { useDing } from "../lib/sound";
import { whenLine } from "../lib/training";
import { PhotoPicker, SignaturePad } from "../pictures";
import { Back, Logo, plain } from "../ui";

/** More people than this, and the list offers a search. */
const FIND_PAST = 6;

/** Who you may sign off (your team, or anyone for a manager), each with the
 * practicals they are asked for. */
export function SignOffPeople() {
  const [people, setPeople] = useState<SignsOff[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [find, setFind] = useState("");

  const load = useCallback(async () => {
    setError(null);
    try {
      setPeople(await api.get<SignsOff[]>("/v1/signoffs/people"));
    } catch (e) {
      setError(plain(e));
    }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const wanted = find.trim().toLowerCase();
  const shown = people?.filter((p) => !wanted || p.name.toLowerCase().includes(wanted) || p.code.toLowerCase().includes(wanted));
  return (
    <main className="screen">
      <Back />
      <h1 style={{ margin: 0, fontSize: 26, fontWeight: 800 }}>Sign someone off</h1>
      <p className="small" style={{ margin: 0, color: "var(--color-muted)" }}>Choose the person and the practical, then watch them do it.</p>
      {error && (
        <>
          <div className="msg r" role="alert">{error}</div>
          <button type="button" className="big primary" onClick={() => void load()}>Try again</button>
        </>
      )}
      {!people && !error && <div aria-live="polite" style={{ color: "var(--color-muted)" }}>Loading…</div>}
      {people && people.length === 0 && <div className="item"><b>Nobody to sign off</b><span>Nobody is on your team yet.</span></div>}
      {people && people.length > FIND_PAST && (
        <input className="input" aria-label="Find a person" placeholder="Name or code" value={find} onChange={(e) => setFind(e.target.value)} />
      )}
      {shown?.map((p) => (
        <section key={p.code} className="item" aria-label={p.name}>
          <b>{p.name}</b><span>{p.code}</span>
          {p.practicals.length === 0 && <span>Not asked for any practical.</span>}
          {p.practicals.map((c) => (
            <Link key={c.key} className="act" to={`/signoff/${encodeURIComponent(p.code)}/${encodeURIComponent(c.key)}`}
                  aria-label={`Sign off ${p.name}: ${c.name}`}>
              {c.name} · {whenLine({ ...c, kind: "practical", granted_on: null, card_expires: false, waiting: false })}
            </Link>
          ))}
        </section>
      ))}
    </main>
  );
}

type Step = "watch" | "confirm" | "done";

/** The sign-off itself, on the supervisor's phone. They watch, tick each
 * item, add a note or a photo if they like, and sign; then they hand the
 * phone over, and the learner checks what was ticked, signs, and types
 * their PIN to say it was them. The learner never signs in here: their PIN
 * goes with the sign-off and is never kept. */
export function SignOff() {
  const { code = "", key = "" } = useParams();
  const { person: signer } = useSession();
  const [learner, setLearner] = useState<SignsOff | null>(null);
  const [practical, setPractical] = useState<Practical | null>(null);
  const [trouble, setTrouble] = useState<string | null>(null);
  const [step, setStep] = useState<Step>("watch");
  const [ticked, setTicked] = useState<Set<number>>(new Set());
  const [note, setNote] = useState("");
  const [photo, setPhoto] = useState<Blob | null>(null);
  const [signed, setSigned] = useState(false);
  // the photo and the signer's signature, once sent: the learner's turn next
  const [sent, setSent] = useState<{ photo: string | null; signature: string } | null>(null);
  const [theirsSigned, setTheirsSigned] = useState(false);
  const [pin, setPin] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mine = useRef<HTMLCanvasElement>(null);
  const theirs = useRef<HTMLCanvasElement>(null);
  const { wake, ding } = useDing();

  const load = useCallback(async () => {
    setTrouble(null);
    try {
      const [people, checklist] = await Promise.all([
        api.get<SignsOff[]>("/v1/signoffs/people"),
        api.get<Practical>(`/v1/practicals/${encodeURIComponent(key)}`),
      ]);
      const p = people.find((x) => x.code === code);
      if (!p) { setTrouble("You can't sign this person off: they aren't on your team."); return; }
      setLearner(p);
      setPractical(checklist);
    } catch (e) {
      setTrouble(e instanceof ApiError && e.status === 404
        ? "There's no checklist for this practical yet. Ask your manager." : plain(e));
    }
  }, [code, key]);
  useEffect(() => { void load(); }, [load]);

  const items = useMemo(() => practical?.version.items ?? [], [practical]);
  const all = items.length > 0 && items.every((i) => ticked.has(i.id));

  function tick(id: number, on: boolean) {
    setTicked((t) => { const next = new Set(t); if (on) next.add(id); else next.delete(id); return next; });
  }

  /** Back to the signer, to tick and sign again. */
  function startAgain(why: string | null) {
    setPin("");
    setSent(null);
    setSigned(false);
    setTheirsSigned(false);
    setError(why);
    setStep("watch");
  }

  async function handOver(e: FormEvent) {
    e.preventDefault();
    if (!mine.current) return;
    setBusy(true);
    setError(null);
    try {
      const signature = await api.upload("signature", await toBlob(mine.current, "image/png"));
      const picture = photo ? await api.upload("signoff-photo", photo) : null;
      setSent({ photo: picture?.id ?? null, signature: signature.id });
      setStep("confirm");
    } catch (err) {
      setError(plain(err));
    } finally {
      setBusy(false);
    }
  }

  async function confirm(e: FormEvent) {
    e.preventDefault();
    if (!theirs.current || !sent || !practical || !learner) return;
    // a phone only plays the Ding! that a tap started
    wake();
    setBusy(true);
    setError(null);
    // typed once, sent once, never kept
    const typed = pin;
    setPin("");
    try {
      const signature = await api.upload("signature", await toBlob(theirs.current, "image/png"));
      await api.post(`/v1/people/${encodeURIComponent(learner.code)}/signoffs`, {
        competency: practical.key, version: practical.version.version, ticked: items.map((i) => i.id),
        note: note.trim() || null, photo: sent.photo, supervisor_signature: sent.signature,
        learner_signature: signature.id, learner_pin: typed,
      });
      ding();
      setStep("done");
    } catch (err) {
      if (err instanceof ApiError && err.code === "new_version") {
        setTicked(new Set());
        startAgain("The checklist has changed: tick it again, then sign.");
        await load();
      } else {
        setError(plain(err));
      }
    } finally {
      setBusy(false);
    }
  }

  if (trouble) {
    return <main className="screen"><Back /><div className="msg r" role="alert">{trouble}</div></main>;
  }
  if (!learner || !practical) {
    return <main className="screen"><Back /><div aria-live="polite" style={{ color: "var(--color-muted)" }}>Loading…</div></main>;
  }

  if (step === "done") {
    return (
      <main className="screen">
        <Back />
        <section className="ding" role="status" aria-label="Signed off">
          <b>Ding!</b>
          <span>{learner.name} is signed off for {practical.name}.</span>
        </section>
        <Link to="/signoff" className="big primary as-button">Sign someone else off</Link>
      </main>
    );
  }

  if (step === "confirm") {
    // the learner holds the phone now: nothing here leads to the signer's training
    return (
      <main className="screen">
        <div className="top"><Logo />Handed to {learner.name}</div>
        <h1 style={{ margin: 0, fontSize: 26, fontWeight: 800 }}>{learner.name}, check and sign</h1>
        <p style={{ margin: 0 }}>{signer?.name} watched you do each of these for {practical.name}:</p>
        <ul className="policy" aria-label="What was ticked" style={{ margin: 0, paddingLeft: 32 }}>
          {items.map((i) => <li key={i.id}>{i.text}</li>)}
        </ul>
        {note.trim() && <p className="caption">Their note: “{note.trim()}”</p>}
        <form onSubmit={confirm} style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <SignaturePad key="learner" canvas={theirs} onSigned={setTheirsSigned} />
          <div className="label">
            <label htmlFor="learner-pin">Your PIN</label>
            <span id="learner-pin-hint" className="small" style={{ fontWeight: 400, color: "var(--color-muted)" }}>
              It says it was you. It isn't kept on this phone.</span>
            <input id="learner-pin" className="input" type="password" inputMode="numeric" autoComplete="off" maxLength={8}
                   value={pin} onChange={(e) => setPin(e.target.value.replace(/\D/g, ""))} aria-describedby="learner-pin-hint" />
          </div>
          {error && <div className="msg r" role="alert">{error}</div>}
          <button type="submit" className="big primary" disabled={busy || !theirsSigned || pin.length < 4}>Confirm</button>
          <button type="button" className="big ghost" onClick={() => startAgain(null)}>Give it back to {signer?.name}</button>
        </form>
      </main>
    );
  }

  return (
    <main className="screen">
      <Back />
      <h1 style={{ margin: 0, fontSize: 26, fontWeight: 800 }}>{practical.name}</h1>
      <p style={{ margin: 0 }}>Watch {learner.name} do each of these, and tick it as they do.</p>
      <form onSubmit={handOver} style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        <fieldset className="question">
          <legend>Checklist, version {practical.version.version}</legend>
          {items.map((i) => (
            <label key={i.id} className="choice">
              <input type="checkbox" checked={ticked.has(i.id)} onChange={(e) => tick(i.id, e.target.checked)} />
              {i.text}
            </label>
          ))}
        </fieldset>
        <div className="small" aria-live="polite" style={{ color: "var(--color-muted)" }}>{items.filter((i) => ticked.has(i.id)).length} of {items.length} ticked</div>
        <div className="label">
          <label htmlFor="note">A note (optional)</label>
          <input id="note" className="input" maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} />
        </div>
        <PhotoPicker label="A photo (optional)" hint="Tap to take one" file={photo} onFile={setPhoto} removable pdf={false} />
        <p className="small" style={{ margin: 0, color: "var(--color-muted)" }}>
          Your signature says you watched {learner.name} do every item.</p>
        <SignaturePad key="signer" canvas={mine} onSigned={setSigned} />
        {error && <div className="msg r" role="alert">{error}</div>}
        <button type="submit" className="big primary" disabled={busy || !all || !signed}>Hand the phone to {learner.name}</button>
      </form>
    </main>
  );
}
```

What keeps a shared phone safe: the learner never signs in on it (no session of theirs, nothing of theirs loaded); their PIN is held only while they type it, sent once, and emptied whatever the answer; and their screen leads nowhere but **Confirm** or back to the supervisor. Each `SignaturePad` is mounted on its own step, keyed, so the learner's starts empty and only one pad is on the screen at a time.

In `apps/learner/src/App.tsx`, replace:
```tsx
import { MyTraining } from "./pages/MyTraining";
import { SignPolicy } from "./pages/SignPolicy";
```
with:
```tsx
import { MyTraining } from "./pages/MyTraining";
import { SignOff, SignOffPeople } from "./pages/SignOff";
import { SignPolicy } from "./pages/SignPolicy";
```

In `apps/learner/src/App.tsx`, replace:
```tsx
        <Route path="/module/:key" element={<ModulePlayer />} />
```
with:
```tsx
        <Route path="/module/:key" element={<ModulePlayer />} />
        <Route path="/signoff" element={<SignOffPeople />} />
        <Route path="/signoff/:code/:key" element={<SignOff />} />
```

Append to `apps/learner/src/api/types.ts`:
```ts
/** Someone the caller may sign off, and the practicals they are asked for. */
export interface SignsOff {
  code: string;
  name: string;
  practicals: { key: string; name: string; status: Status; expires_on: string | null }[];
}

/** A practical and the checklist to tick now. */
export interface Practical {
  key: string;
  name: string;
  version: { id: number; version: number; note: string | null; items: { id: number; text: string }[] };
}
```

In `apps/learner/src/api/client.ts`, replace:
```ts
  /** A ticket's photo or a signature, kept by the API before what names it. */
  upload(purpose: "ticket" | "signature", file: Blob) {
```
with:
```ts
  /** A ticket's photo, a signature or a sign-off's photo, kept by the API
   * before what names it. */
  upload(purpose: "ticket" | "signature" | "signoff-photo", file: Blob) {
```

In `apps/learner/src/pictures.tsx`, replace:
```tsx
export function PhotoPicker({ label, hint, file, onFile, removable = false }: {
  label: string; hint: string; file: Blob | null; onFile: (b: Blob | null) => void;
  /** offer to take it away again (for a photo that is optional) */
  removable?: boolean;
}) {
```
with:
```tsx
export function PhotoPicker({ label, hint, file, onFile, removable = false, pdf: takesPdf = true }: {
  label: string; hint: string; file: Blob | null; onFile: (b: Blob | null) => void;
  /** offer to take it away again (for a photo that is optional) */
  removable?: boolean;
  /** a PDF will do instead of a photo (a ticket's, not a sign-off's) */
  pdf?: boolean;
}) {
```

In `apps/learner/src/pictures.tsx`, replace:
```tsx
    if (!chosen) return;
    setError(null);
```
with:
```tsx
    if (!chosen) return;
    setError(null);
    if (!takesPdf && chosen.type === "application/pdf") { setError("Choose a photo, not a PDF."); return; }
```

In `apps/learner/src/pictures.tsx`, replace:
```tsx
        <input type="file" accept="image/*,application/pdf" className="sr-only"
```
with:
```tsx
        <input type="file" accept={takesPdf ? "image/*,application/pdf" : "image/*"} className="sr-only"
```

**Step 4: Run them to see them pass, and build**

Run: `cd apps/learner && npm test && npm run build`
Expected: `Tests  81 passed (81)`, then `✓ built in …`.

**Step 5: Commit**

```
git add apps/learner/src/pages/SignOff.tsx apps/learner/src/App.tsx apps/learner/src/api/types.ts apps/learner/src/api/client.ts apps/learner/src/pictures.tsx apps/learner/src/test/signoff.test.tsx
git commit -m "Sign off a practical on the phone: tick, sign, hand it over, and the learner confirms" \
  -m "The learner signs and types their PIN on the supervisor's phone without signing in; their PIN is sent once and never kept, and their screen leads nowhere else."
```

---
### Task 13: The README and CLAUDE.md

**Files:**
- Modify: `README.md`, `CLAUDE.md`

**Step 1: Write it**

In `README.md`, replace:
````markdown
Status: **build step 7, Game Mode, is done.** People with a code and PIN
````
with:
````markdown
Status: **build steps 1 to 4 and 7 (Game Mode) are done.** People with a code and PIN
````

In `README.md`, replace:
````markdown
tickets from the learner app; a manager checks each ticket in the desktop's
Inbox; the worker emails reminders and a Monday digest. The desktop opens on
a classroom, a desk for each role with its people sitting at it in green,
amber or red, and every screen in a drawer over it; the learner app shows a
ring for how much is done and says Ding! out loud. Practicals, Entra sign-in
and the outward links (build steps 4 to 6) are still to come, as
`docs/plans/2026-10-12-simple-lms-design.md` sets out.
````
with:
````markdown
tickets from the learner app; a supervisor signs off practicals on their
phone, with the learner beside them; a manager checks each ticket in the
desktop's Inbox; the worker emails reminders and a Monday digest. The
desktop opens on a classroom, a desk for each role with its people sitting
at it in green, amber or red, and every screen in a drawer over it; the
learner app shows a ring for how much is done and says Ding! out loud.
Entra sign-in and the outward links (build steps 5 and 6) are still to
come, as `docs/plans/2026-10-12-simple-lms-design.md` sets out.
````

In `README.md`, replace:
````markdown
is kept. A video that is playing counts as a tap, so a
PIN session doesn't end in the middle of it.
````
with:
````markdown
is kept. A video that is playing counts as a tap, so a
PIN session doesn't end in the middle of it.

**Practicals.** Add a competency of kind *Practical sign-off* (with a
refresher, say 12 months, if it should be done again), open it under
**Competencies** and write its checklist: the things to see someone do, in
order. Publishing asks once, then freezes that version: to change it, edit
the copy the drawer offers and publish the next version; sign-offs so far
still count. A supervisor signs off their own team on their phone (a
manager or admin anyone, and nobody themselves): in the learner app,
**Sign someone off**, choose the person and the practical, watch them do
it and tick each item, add a note or a photo if you like, sign, and hand
the phone over. The learner checks what was ticked, signs, and types their
own PIN to say it was them: they never sign in on the supervisor's phone,
and their PIN is never kept (a wrong one counts against the same five tries
as signing in). Ding! It counts as current until the refresher runs out,
and the history shows what was ticked, the note, the photo and both
signatures. The learner needs a PIN for this even where signing in with a
PIN is switched off in Settings (it confirms, it doesn't sign in): set one
under **People**.
````

In `README.md`, replace:
````markdown
the `uploads` volume (tickets' photos, policy signatures and modules'
pictures, PDFs and videos) along with the database: the records and pages
name the files in it. Files are written to disk as they arrive, never held
````
with:
````markdown
the `uploads` volume (tickets' photos, signatures, modules' pictures, PDFs
and videos, and sign-offs' photos) along with the database: the records,
pages and sign-offs name the files in it. Files are written to disk as they arrive, never held
````

In `README.md`, replace:
````markdown
| Write and publish a module's pages and quiz | | | ✓ | ✓ |
| Record or revoke a completion (never their own) | | | ✓ | ✓ |
````
with:
````markdown
| Write and publish a module's pages and quiz, or a practical's checklist | | | ✓ | ✓ |
| Sign off a practical on the phone (never their own) | | own team | everyone | everyone |
| Record or revoke a completion (never their own) | | | ✓ | ✓ |
````

In `README.md`, replace:
````markdown
their own permission or deactivates themselves. Signing in with a PIN only
ever shows your own training, whoever you are, and the desktop turns a
learner away to the learner app.
````
with:
````markdown
their own permission or deactivates themselves. Signing in with a PIN only
ever shows your own training, whoever you are (and, for a supervisor,
manager or admin, signs off practicals), and the desktop turns a learner
away to the learner app.
````

In `CLAUDE.md`, replace:
````markdown
   decided once and never deleted; a `module_version` is frozen once
   published, and its `module_page` and `quiz_question` rows change only
   while it is a draft). A mistake is corrected by a new row (`revoked`,
   with a note). People are deactivated, never deleted.
````
with:
````markdown
   decided once and never deleted; a `module_version` is frozen once
   published, and its `module_page` and `quiz_question` rows change only
   while it is a draft; a `practical_version` and its `practical_item`
   rows, and a `signoff`'s `signoff_item` rows, are written together and
   never after). A mistake is corrected by a new row (`revoked`, with a
   note). People are deactivated, never deleted.
````

In `CLAUDE.md`, replace:
````markdown
  classroom offers stays reachable with Game Mode off.
````
with:
````markdown
  classroom offers stays reachable with Game Mode off.
- Sign-offs: who may sign off whom is `practicals.may_sign_off()` and
  nowhere else. The learner confirms on the supervisor's phone with their
  PIN, which counts against their five tries and is never stored or logged;
  never give the learner a session on someone else's device.
````

**Step 2: Commit**

```
git add README.md CLAUDE.md
git commit -m "Describe practicals and signing off in the README, and the sign-off rules in CLAUDE.md"
```

---

### Task 14: Every suite, and a clean Compose start

**Step 1: Every suite**

```
(cd api && .venv/bin/pytest -q)
(cd apps/desktop && npm test && npm run typecheck && npm run build)
(cd apps/learner && npm test && npm run typecheck && npm run build)
```
Expected: `495 passed`; `Tests  114 passed (114)` and a build; `Tests  81 passed (81)` and a build.

**Step 2: Compose from nothing**

This drops the local database and its uploads: only on a machine with nothing to keep.
```
docker compose down -v
docker compose up -d --build
for i in $(seq 1 30); do curl -fsS http://127.0.0.1:8033/v1/health && break; sleep 2; done; echo
docker compose ps --format '{{.Service}} {{.State}}'
docker compose logs worker | grep "worker started"
docker compose exec -T db psql -U lms -d lms -tAc "select version_num from alembic_version"
```
Expected: `{"status":"ok"}`; `api running`, `caddy running`, `db running`, `worker running`; the worker's `worker started` line; and `0004`. Fix anything that is not, then commit the fix with a message that says what it fixes.

---

### Task 15: Manual walkthrough: a checklist written, a practical signed off on the phone, refreshed

**Step 1: Set it up.** On the desktop as the admin (it opens on the classroom; **Competencies**, **People** and **Matrix** in the bar each open in a drawer over it): add **Forklift practical** (kind *Practical sign-off*, refresher 12 months) and a role **Forklift driver** requiring it. Add Sam (`SV001`, permission *Supervisor*, PIN `1357`) and give Kim (`LL042`, PIN `2468`) the role, with Sam as her supervisor; add Pat (`LL099`, PIN `9753`, the role, no supervisor). The matrix shows Kim and Pat red. Open Forklift practical under **Competencies**: "No checklist yet". Type three items ("Checks the forks, chains and tyres", "Lifts a pallet to the top rack", "Parks with the forks down"), add a fourth and remove it again, move the last one up and back. Press **Close**: it asks "Version 1 has changes that aren't published. Close it anyway?"; **Keep editing**. **Publish version 1**: it asks "Publish version 1? Its items are frozen once it is, and every sign-off from now on ticks them."; **Publish**. The drawer says "Version 1 is the one supervisors tick · published … by …" with the three items, and offers version 2 as a copy, its **Publish version 2** greyed out until something changes.

**Step 2: Sam on his phone.** In the learner app (a phone, or a narrow browser window), sign in as `SV001` / `1357`. My training has **Sign someone off**; Sam's own list doesn't change. **Sign someone off** lists Kim, not Pat (not on Sam's team) and not Sam: "Forklift practical · Not done yet". Open it: the three items, "0 of 3 ticked", and **Hand the phone to Kim Lee** greyed out. Tick two, sign: still greyed out. Tick the third, add the note "Smooth on the ramp" and a photo (the phone offers its camera; a PDF picked with *All files* says "Choose a photo, not a PDF."), and **Hand the phone to Kim Lee**.

**Step 3: Kim confirms.** The screen says "Handed to Kim Lee" and "Kim Lee, check and sign", lists what Sam ticked and his note, and has no way back to Sam's training. Sign, type `1111` and **Confirm**: "That isn't Kim Lee's PIN: try again.", and the PIN box is empty. Type `2468` and **Confirm**: "Ding! Kim Lee is signed off for Forklift practical.", out loud with **Sound** on. `docker compose exec -T db psql -U lms -d lms -c "select pin_failed_attempts from person where code = 'LL042'"` says `0` again.

**Step 4: The record.** On the desktop, Kim sits in green at the Forklift driver desk in the classroom, and on **Matrix** her Forklift practical cell is green; its history says "Signed off on checklist version 1, every item ticked:", the three items, "“Smooth on the ramp”", the photo, Sam's and Kim's signatures, "Kim Lee signed too, and confirmed it with their PIN." and "by Sam Vu". Sign in to the learner app as Kim: Forklift practical is under Done ("good until" a year on). `docker compose exec -T db psql -U lms -d lms -c "select count(*) from signoff_item"` says `3`, and `docker compose exec -T db psql -U lms -d lms -c "update practical_item set text = 'x'"` is refused: "practical_item is append-only: rows cannot be updated or deleted".

**Step 5: Rule 3, and the lock-out.** Sign in to the learner app as the admin (with a PIN set under **People**): **Sign someone off** lists everyone active but the admin. Sign Pat off but type a wrong PIN five times: the fifth says "wrong PIN 5 times: Pat Other's PIN is locked until a manager resets it", and Pat's own sign-in now says the PIN is locked; reset it under **People**. Nobody signs off themselves, whatever the screen offers:
```
TOKEN=$(curl -s http://127.0.0.1:8033/v1/auth/login -H 'Content-Type: application/json' \
  -d '{"email": "you@example.com", "password": "<the admin password>"}' | python3 -c 'import json, sys; print(json.load(sys.stdin)["token"])')
curl -s http://127.0.0.1:8033/v1/people/AD001/signoffs -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"competency": "forklift-practical", "version": 1, "ticked": [], "supervisor_signature": "00000000-0000-0000-0000-000000000001", "learner_signature": "00000000-0000-0000-0000-000000000002", "learner_pin": "0000"}'
```
answers `{"detail":"nobody signs off their own practical: ask your supervisor","code":"own_signoff"}`.

**Step 6: A new checklist, and the refresher.** On the desktop, change version 2's last item to "Parks with the forks down and the key out", **Publish version 2**: Kim's cell stays green (a new checklist asks nobody again). On Sam's phone, start signing Kim off again, tick all three, hand it over, then before Kim confirms publish version 3 on the desktop; Kim's **Confirm** sends the phone back to Sam: "The checklist has changed: tick it again, then sign.", with version 3 to tick. As the admin, open Kim's cell and record a completion by hand dated eleven months and two weeks ago (the latest record is the one that counts): amber, and Kim's My training has it under Due soon with "Your supervisor signs this off with you". `docker compose exec worker lms daily-job --on <30 days before its last good day>` queues its 30-day reminder as for any competency (if Kim has an email).
