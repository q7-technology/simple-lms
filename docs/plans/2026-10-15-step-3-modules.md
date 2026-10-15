# Simple LMS step 3: Modules — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build step 3 of `docs/plans/2026-10-12-simple-lms-design.md`: online modules. A manager writes a module on the desktop's **Competencies** screen: pages of text, a picture, a PDF, a video or a link, then a multiple-choice quiz with a pass mark, and publishes it. A learner opens it from My training on their phone or a shared tablet, reads one page at a time (the place is kept if they leave), plays and seeks the video, and takes the quiz: pass or fail with the score, another go after a fail. A pass is the one thing a learner earns alone (rule 3): a grant of their own, current until the refresher runs out. Every attempt is kept (rule 1), and what a learner answered is never changed under them. Usable end to end: a manager builds the site induction with a short video, publishes it, Kim fails the quiz, reads it again, passes, and the matrix goes green until the refresher brings it round again.

**Architecture:** The same FastAPI app (`api/`, package `lms`). Migration `0003` adds `module_version` (one draft at a time per module, published once and then frozen), `module_page` and `quiz_question` (changed only while their version is a draft), `quiz_attempt` (append-only), `module_progress` (where each person is in a module, kept on the server), `competency_record.quiz_attempt_id`, and three new upload purposes for a page's picture, PDF and video. Uploads are now written to disk as they arrive, refused the moment they pass their purpose's limit (200 MB for a video, 20 MB for anything else), and checked by their first bytes (MP4 and WebM added). A module's files open by a short-lived link the API signs for one session (`GET /v1/media/{id}?session=&expires=&sig=`), served with Range requests so a phone can seek a video; the session's token never goes in a URL. Status still comes only from `lms/services/status.py`: a pass is an ordinary grant and the refresher does the rest. The desktop gains a module editor in the competency's drawer; the learner app gains a module player at `/learn/module/<key>`.

**Tech Stack:** as step 2: Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, psycopg 3, pytest against a real PostgreSQL 16; Vite 6, React 19, TypeScript 5, Tailwind 4, Vitest 3 with Testing Library; Docker Compose, Caddy 2, GitHub Actions. No new dependencies: Range requests are Starlette's own `FileResponse` (FastAPI's Starlette, from 0.40), and Task 3 says so in `pyproject.toml`.

---

## Context

The design is settled; this plan does not change any of its decisions. The decisions in the step 1 and step 2 plans' Contexts still hold (ports, sessions and scopes, the latest row counts, `expires_on` is the last good day, today in `LMS_TIMEZONE`, files sent as the raw body and checked by their first bytes, the person's row locked while a record is made, and the rest). The code on `main` is the truth where it went further than those plans: `errors.commit_unique`, `records.one_at_a_time` and `latest_record`, uploads append-only with per-purpose limits enforced while reading, PDFs sent as attachments and the file removed when its row can't be saved, the desktop's `Drawer` (with `focus="dialog"`), `.rowbtn` rows, the publish confirmation and `ApiClient.blob()`, and the learner app's shared-tab sessions, idle wipe and `plain()`.

### Decisions this plan makes that the design leaves open

- **A module's content is versioned, and a version is frozen once published.** A `module_version` belongs to a competency of kind `module` and holds its pages, its questions and its pass mark. One draft at a time is written and saved as often as needed; publishing it is the last change it ever gets. A `publish_once()` trigger lets a draft's pass mark change and lets it be published, then refuses every change and every delete; a `draft_only()` trigger refuses any insert, update or delete of a `module_page` or `quiz_question` whose version is published. An attempt names its version, so its questions, right answers and pass mark are always what the learner was asked: the attempt stays meaningful (rule 1). This is the policy versions' pattern with a draft in front, and simpler than the alternatives: editing in place with a history to keep would need every attempt to copy its questions, and "editable until the first attempt" can be raced by a learner. A typo is fixed by starting the next version, a copy of the last; people keep taking the old one until it is published.
- **A new module version asks nobody to take it again** (unlike a policy): passes so far still count, and the refresher brings people back. Status for a module is unchanged in `status.py`.
- **The draft is saved in full** (`PUT /v1/modules/{key}/draft` with the pass mark, every page and every question, in order) rather than page by page: adding, moving and removing happen on the screen, there is one place that checks it, and one transaction that writes it. Publishing needs a page and a question.
- **Pages:** `text` (plain text: line breaks are kept and nothing else is formatting, so there is no HTML to make safe; React escapes it and CSS keeps the breaks), `image` (JPEG or PNG), `pdf`, `video` (MP4 or WebM, played as uploaded) and `link` (a web address starting `https://` or `http://`, opened in a new tab with `rel="noopener noreferrer"`; `javascript:` and the like are refused). Every page has a title; every page but a text one may have a line or two under it. A page's file is an upload of purpose `page-image`, `page-pdf` or `page-video`, sent first; any editor's will do, since a module is written by more than one manager.
- **Uploads stream to disk.** `uploads.Incoming` writes each piece of the body to a temporary file beside where it will be kept, counting and hashing as it goes, and refuses the request the moment it passes its purpose's limit; `store()` gives it its real name once its row is flushed, and nothing is left behind on any failure. No file is ever held in memory whole. The new purposes are sent only by editors (`competencies:write`); `ticket` and `signature` stay `training:write`. MP4 is an `ftyp` box whose brand is not QuickTime's (an iPhone's `.mov` is refused with a plain message: most browsers won't play it, so it is converted to MP4 first); WebM is an EBML header whose DocType is `webm` (a Matroska `.mkv` is refused). No transcoding.
- **A module's files open by a signed link, not the token.** An `<img>`, a `<video>` or a new tab can't send the session's token, a token must never go in a URL, and fetching a 200 MB video into a `blob:` on a phone would hold it all in memory and stop the learner seeking until it had all arrived. So each page the API sends carries `file.link`: `/v1/media/{upload_id}?session=<id>&expires=<unix time>&sig=<hmac>`, an HMAC-SHA256 of the upload id, the session id and the expiry, keyed by that session's token hash, which only the database knows (no new secret in `.env`). A link lasts 6 hours or until its session ends (signed out, idle 15 minutes for a PIN, too old), whichever is first; opening it counts as using the session. Anything wrong is a `404`. Only a page's files have links: a ticket's photo and a signature are someone's own and are still fetched with the token. The file is served by Starlette's `FileResponse`, which honours `Range` (`206`, `416`), with the sniffed type, `private, no-store`, the sandbox CSP and `nosniff`; a PDF is an attachment, as before. The links are same-origin, so both apps' CSP (`default-src 'self'`) already allows them; Caddy's CSP now says `media-src 'self'` as well, so nobody tightens it by accident.
- **The quiz:** each question has 2 to 6 answers and one right one (`correct`, counting from 0); the pass mark is 1 to 100 % for the version (80 unless changed). The right answers are never sent to a learner: `GET /v1/modules/{key}` gives the prompts and answers only, and the API marks the attempt. The score is out of 100, rounded down (2 of 3 is 66), and a pass is a score of at least the pass mark. Every attempt is a `quiz_attempt` row with the answers given, pass or fail, append-only through `block_change()`. Re-sits are unlimited. The learner sees the score and whether they passed, as the design says, not which questions they got wrong (or a re-sit would only be guessing again). An attempt names the version it answered: if a newer one came out meanwhile it is `409 new_version`, and the learner app starts the new one.
- **A pass is a grant of the learner's own:** a `competency_record` granted today, recorded by the learner (`recorded_by` is them, as for a policy signature: rule 3's one sanctioned exception), with `quiz_attempt_id` pointing at the pass, and no `expires_on`, so the competency's refresher works out the last good day in `status.py` as for any grant. The person's row is locked first (`one_at_a_time`), as for every record. Taking it again while current is allowed (a renewal); the learner app offers it once it is not current.
- **Progress is kept on the server:** `module_progress` holds each person's version and page for a module (`PUT /v1/modules/{key}/progress` as they move on), so they carry on where they left off on any device, and a shared tablet keeps nothing of theirs. It is not part of the training record, so it is updated in place; a new version starts from the top, and a pass clears it.
- **A playing video keeps the session alive.** Nobody taps while a video plays, so a 20-minute video would wipe a PIN session at 15 minutes. While it plays, the player calls the session's new `stillHere()` once a minute: the same as a tap on the device, and a `GET /v1/auth/me` so the API counts it too. Once it stops, the idle time runs again.
- **Learner app:** My training offers **Start the module** on a module that is not current; it opens `/learn/module/<key>`: one page at a time ("Page 2 of 5" and a bar), Back and Next, then **Start the quiz**; the quiz shows every question and **Hand it in** once each has an answer; a pass says Ding! with the score, a fail gives the score and the pass mark with **Try again** and **Read it again**.
- **Desktop:** the drawer of a module on **Competencies** shows the version people take (published when and by whom, pages, questions, pass mark) and either **Start version N** or the draft: the pass mark, the pages (add one of each kind, move up and down, remove; send a file, which is checked for size before it goes), and the questions (add and remove answers, mark the right one, move up and down, remove), **Save draft**, and **Publish version N**, which asks once: "Its pages and questions are frozen once it is". The history drawer says "Passed the quiz on version 1 with 100% (pass mark 80%)".
- **Reminders and the daily job are unchanged:** a module's expiry already comes from its refresher in `status.py`, and the reminders and digest already cover every kind.
- **Left for later steps:** practicals (step 4), Entra (5), `competency.granted` events, the competency API and Platen certificates (6), Game Mode's ring and sound (7). No SCORM. The desktop doesn't list failed attempts yet; `GET /v1/people/{code}/attempts` has them for an auditor.

---

## Before you start

```
cd "/Users/leightonlauton/Q7 Technology/Software/q7/simple-lms"
git switch main && git pull --ff-only
git switch -c step-3-modules
docker compose up -d db
(cd api && uv pip install -e ".[dev]")
(cd apps/desktop && npm ci)
(cd apps/learner && npm ci)
```

As before: `pytest` runs from `api/` against the compose `db` on 127.0.0.1:5435 (`TEST_DATABASE_URL` points it elsewhere), and `npm` commands run from the app's folder. Every test still runs on 12 October 2026, a Monday. Before step 3 the suites are at `259 passed`, `Tests  42 passed (42)` (desktop) and `Tests  46 passed (46)` (learner).

---

### Task 1: Module versions, pages, questions, attempts and progress, frozen once published

**Files:**
- Create: `api/lms/models/modules.py`, `api/alembic/versions/0003_modules.py`
- Modify: `api/lms/models/evidence.py`, `api/lms/models/records.py`, `api/lms/models/__init__.py` (in full below)
- Test: `api/tests/test_migrations.py`; create `api/tests/test_module_rows.py`

**Step 1: Write the failing tests**

In `api/tests/test_migrations.py`, replace:
```python
TABLES = {"person", "session", "role", "person_role", "competency", "role_requirement",
          "person_override", "competency_record", "upload", "policy_version",
          "ticket_submission", "outbox", "alembic_version"}
TRIGGERS = {"competency_record_append_only", "person_override_append_only",
            "policy_version_append_only", "upload_append_only", "ticket_submission_decide_once"}
```
with:
```python
TABLES = {"person", "session", "role", "person_role", "competency", "role_requirement",
          "person_override", "competency_record", "upload", "policy_version",
          "ticket_submission", "outbox", "module_version", "module_page", "quiz_question",
          "quiz_attempt", "module_progress", "alembic_version"}
TRIGGERS = {"competency_record_append_only", "person_override_append_only",
            "policy_version_append_only", "upload_append_only", "ticket_submission_decide_once",
            "quiz_attempt_append_only", "module_version_publish_once", "module_page_draft_only",
            "quiz_question_draft_only"}
```

`api/tests/test_module_rows.py`:
```python
"""A module version is edited while it is a draft and frozen once
published; every quiz attempt is kept as it was. The database says so
(rule 1), whatever the API does."""
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, insert, update
from sqlalchemy.exc import DBAPIError, IntegrityError

from lms.models import (
    Competency, ModulePage, ModuleVersion, Person, QuizAttempt, QuizQuestion, Upload,
)


@pytest.fixture
def module(db):
    """Site induction: version 1 published, version 2 a draft."""
    boss = Person(code="MG001", name="Mel Grant", permission="manager")
    kim = Person(code="LL042", name="Kim Lee")
    induction = Competency(key="site-induction", name="Site induction", kind="module")
    db.add_all([boss, kim, induction])
    db.flush()

    def version(n: int) -> ModuleVersion:
        v = ModuleVersion(competency_id=induction.id, version=n, pass_mark=80)
        db.add(v)
        db.flush()
        db.add(ModulePage(module_version_id=v.id, position=0, kind="text", title="Welcome",
                          body="Sign in at the gatehouse."))
        db.add(QuizQuestion(module_version_id=v.id, position=0, prompt="Where do you sign in?",
                            options=["The gatehouse", "The canteen"], correct=0))
        db.flush()
        return v

    one = version(1)
    one.published_at = datetime.now(UTC)
    one.published_by_id = boss.id
    db.flush()
    two = version(2)
    db.commit()
    return boss, kim, induction, one, two


@pytest.mark.parametrize("model, values", [
    (ModulePage, {"title": "Changed afterwards"}),
    (QuizQuestion, {"correct": 1}),
])
def test_a_published_versions_pages_and_questions_never_change(db, module, model, values):
    boss, kim, induction, one, two = module
    with pytest.raises(DBAPIError, match="published module version"):
        db.execute(update(model).where(model.module_version_id == one.id).values(**values))
        db.commit()


@pytest.mark.parametrize("model", [ModulePage, QuizQuestion])
def test_nothing_is_taken_from_or_added_to_a_published_version(db, module, model):
    boss, kim, induction, one, two = module
    with pytest.raises(DBAPIError, match="published module version"):
        db.execute(delete(model).where(model.module_version_id == one.id))
        db.commit()
    db.rollback()
    row = ({"kind": "text", "title": "One more", "body": "More."} if model is ModulePage
           else {"prompt": "One more?", "options": ["Yes", "No"], "correct": 0})
    with pytest.raises(DBAPIError, match="published module version"):
        db.execute(insert(model).values(module_version_id=one.id, position=1, **row))
        db.commit()


def test_a_draft_is_edited_freely(db, module):
    boss, kim, induction, one, two = module
    db.execute(update(ModulePage).where(ModulePage.module_version_id == two.id)
               .values(title="Welcome to the yard"))
    db.execute(delete(QuizQuestion).where(QuizQuestion.module_version_id == two.id))
    db.execute(update(ModuleVersion).where(ModuleVersion.id == two.id).values(pass_mark=70))
    db.commit()
    db.refresh(two)
    assert two.pass_mark == 70


def test_a_published_version_is_frozen(db, module):
    boss, kim, induction, one, two = module
    with pytest.raises(DBAPIError, match="frozen once published"):
        db.execute(update(ModuleVersion).where(ModuleVersion.id == one.id).values(pass_mark=50))
        db.commit()


def test_a_draft_keeps_its_number(db, module):
    boss, kim, induction, one, two = module
    with pytest.raises(DBAPIError, match="frozen once published"):
        db.execute(update(ModuleVersion).where(ModuleVersion.id == two.id).values(version=3))
        db.commit()


def test_a_version_is_never_deleted(db, module):
    with pytest.raises(DBAPIError, match="cannot be deleted"):
        db.execute(delete(ModuleVersion))
        db.commit()


def test_one_draft_at_a_time(db, module):
    boss, kim, induction, one, two = module
    db.add(ModuleVersion(competency_id=induction.id, version=3, pass_mark=80))
    with pytest.raises(IntegrityError, match="uq_module_version_draft"):
        db.commit()


def test_published_says_by_whom(db, module):
    boss, kim, induction, one, two = module
    with pytest.raises(IntegrityError, match="ck_module_version_published"):
        db.execute(update(ModuleVersion).where(ModuleVersion.id == two.id)
                   .values(published_at=datetime.now(UTC)))
        db.commit()


@pytest.mark.parametrize("options, correct, constraint", [
    (["Only one"], 0, "ck_quiz_question_options"),
    (["a", "b", "c", "d", "e", "f", "g"], 0, "ck_quiz_question_options"),
    (["Yes", "No"], 2, "ck_quiz_question_correct"),
    (["Yes", "No"], -1, "ck_quiz_question_correct"),
])
def test_a_question_has_two_to_six_answers_and_one_is_right(db, module, options, correct,
                                                            constraint):
    two = module[4]
    db.add(QuizQuestion(module_version_id=two.id, position=1, prompt="Well?", options=options,
                        correct=correct))
    with pytest.raises(IntegrityError, match=constraint):
        db.commit()


@pytest.mark.parametrize("row, constraint", [
    ({"kind": "text", "body": "  "}, "ck_module_page_body"),
    ({"kind": "video"}, "ck_module_page_file"),
    ({"kind": "link"}, "ck_module_page_url"),
    ({"kind": "text", "body": "Words.", "url": "https://example.com.au"}, "ck_module_page_url"),
])
def test_each_kind_of_page_has_what_it_needs(db, module, row, constraint):
    two = module[4]
    db.add(ModulePage(module_version_id=two.id, position=1, title="Next", **row))
    with pytest.raises(IntegrityError, match=constraint):
        db.commit()


def test_a_page_file_is_one_kind_of_upload(db, module):
    boss = module[0]
    db.add(Upload(id=uuid.uuid4(), person_id=boss.id, purpose="page-video",
                  content_type="video/mp4", size_bytes=3, sha256="0" * 64, path="ab/v.mp4"))
    db.commit()
    db.add(Upload(id=uuid.uuid4(), person_id=boss.id, purpose="selfie",
                  content_type="image/png", size_bytes=3, sha256="0" * 64, path="ab/s.png"))
    with pytest.raises(IntegrityError, match="ck_upload_purpose"):
        db.commit()


@pytest.fixture
def attempt(db, module):
    boss, kim, induction, one, two = module
    row = QuizAttempt(person_id=kim.id, competency_id=induction.id, module_version_id=one.id,
                      answers=[1], correct=0, total=1, score=0, passed=False)
    db.add(row)
    db.commit()
    return row


@pytest.mark.parametrize("change", [update(QuizAttempt).values(passed=True), delete(QuizAttempt)])
def test_every_attempt_is_kept_as_it_was(db, attempt, change):
    with pytest.raises(DBAPIError, match="append-only"):
        db.execute(change)
        db.commit()
```

**Step 2: Run them to see them fail**

Run: `cd api && .venv/bin/pytest tests/test_migrations.py tests/test_module_rows.py -q`
Expected: FAIL: `ImportError: cannot import name 'ModulePage' from 'lms.models'`, so the run stops while collecting the tests (and a fresh database has none of the new tables or triggers).

**Step 3: Minimal implementation**

`api/lms/models/modules.py`:
```python
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text,
    UniqueConstraint, Uuid, func, text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from lms.models.base import Base, created_at_column
from lms.models.catalogue import Competency
from lms.models.evidence import Upload
from lms.models.people import Person

PAGE_KINDS = ("text", "image", "pdf", "video", "link")


class ModuleVersion(Base):
    """One version of a module: its pages, its quiz and its pass mark. A
    draft (not yet published) is edited freely; publishing freezes it, and a
    trigger keeps it that way, so an attempt always means what was asked.
    Never deleted. People take the newest published version."""

    __tablename__ = "module_version"
    __table_args__ = (
        UniqueConstraint("competency_id", "version"),
        CheckConstraint("version >= 1", name="version"),
        CheckConstraint("pass_mark between 1 and 100", name="pass_mark"),
        # published, by whom and when, or neither
        CheckConstraint("(published_at is null) = (published_by_id is null)", name="published"),
        # one draft at a time for a module
        Index("uq_module_version_draft", "competency_id", unique=True,
              postgresql_where=text("published_at is null")),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    competency_id: Mapped[int] = mapped_column(ForeignKey("competency.id"), index=True)
    # 1, 2, 3 … for each module
    version: Mapped[int] = mapped_column(Integer)
    # the least score, out of 100, that passes
    pass_mark: Mapped[int] = mapped_column(Integer, default=80)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_by_id: Mapped[int | None] = mapped_column(ForeignKey("person.id"))
    created_at: Mapped[datetime] = created_at_column()

    competency: Mapped[Competency] = relationship()
    published_by: Mapped[Person | None] = relationship()
    pages: Mapped[list[ModulePage]] = relationship(order_by="ModulePage.position")
    questions: Mapped[list[QuizQuestion]] = relationship(order_by="QuizQuestion.position")


class ModulePage(Base):
    """One page of a module version: text, a picture, a PDF, a video or a
    link. Changed only while its version is a draft (a trigger says so)."""

    __tablename__ = "module_page"
    __table_args__ = (
        UniqueConstraint("module_version_id", "position"),
        CheckConstraint("kind in ('text', 'image', 'pdf', 'video', 'link')", name="kind"),
        CheckConstraint("position >= 0", name="position"),
        CheckConstraint("length(trim(title)) > 0", name="title"),
        # a text page has its text; the others may have a line or two under them
        CheckConstraint("kind <> 'text' or coalesce(length(trim(body)), 0) > 0", name="body"),
        # a picture, a PDF and a video are a file; a link is a web address
        CheckConstraint("(kind in ('image', 'pdf', 'video')) = (upload_id is not null)",
                        name="file"),
        CheckConstraint("(kind = 'link') = (url is not null)", name="url"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    module_version_id: Mapped[int] = mapped_column(ForeignKey("module_version.id"), index=True)
    # 0, 1, 2 …: the order they are read in
    position: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(8))
    title: Mapped[str] = mapped_column(String(120))
    body: Mapped[str | None] = mapped_column(Text)
    upload_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("upload.id"), index=True)
    url: Mapped[str | None] = mapped_column(String(2000))

    upload: Mapped[Upload | None] = relationship()


class QuizQuestion(Base):
    """A multiple-choice question: 2 to 6 answers, one of them right.
    Changed only while its version is a draft (a trigger says so)."""

    __tablename__ = "quiz_question"
    __table_args__ = (
        UniqueConstraint("module_version_id", "position"),
        CheckConstraint("position >= 0", name="position"),
        CheckConstraint("length(trim(prompt)) > 0", name="prompt"),
        CheckConstraint("jsonb_typeof(options) = 'array' and jsonb_array_length(options) "
                        "between 2 and 6", name="options"),
        CheckConstraint("correct >= 0 and correct < jsonb_array_length(options)",
                        name="correct"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    module_version_id: Mapped[int] = mapped_column(ForeignKey("module_version.id"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    prompt: Mapped[str] = mapped_column(String(500))
    # the answers to choose from, in the order shown
    options: Mapped[list[str]] = mapped_column(JSONB)
    # which of them is right, counting from 0: never sent to a learner
    correct: Mapped[int] = mapped_column(Integer)


class QuizAttempt(Base):
    """One go at a module's quiz, pass or fail. Append-only: every attempt is
    kept (rule 1). A pass is also a grant in the training record."""

    __tablename__ = "quiz_attempt"
    __table_args__ = (
        CheckConstraint("total >= 1 and correct between 0 and total", name="counts"),
        CheckConstraint("score between 0 and 100", name="score"),
        CheckConstraint("jsonb_typeof(answers) = 'array'", name="answers"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("person.id"), index=True)
    competency_id: Mapped[int] = mapped_column(ForeignKey("competency.id"), index=True)
    # the version they answered, whose questions and pass mark never change
    module_version_id: Mapped[int] = mapped_column(ForeignKey("module_version.id"))
    # the answer chosen for each question, in order, counting from 0
    answers: Mapped[list[int]] = mapped_column(JSONB)
    correct: Mapped[int] = mapped_column(Integer)
    total: Mapped[int] = mapped_column(Integer)
    # out of 100, rounded down; passed when it reaches the version's pass mark
    score: Mapped[int] = mapped_column(Integer)
    passed: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = created_at_column()

    competency: Mapped[Competency] = relationship()
    module_version: Mapped[ModuleVersion] = relationship()


class ModuleProgress(Base):
    """How far a person has read in a module, so they carry on where they
    left off, on any device. Not part of the training record: it moves on
    as they read, and goes once they pass."""

    __tablename__ = "module_progress"
    __table_args__ = (CheckConstraint("page >= 0", name="page"),)

    person_id: Mapped[int] = mapped_column(ForeignKey("person.id"), primary_key=True)
    competency_id: Mapped[int] = mapped_column(ForeignKey("competency.id"), primary_key=True)
    module_version_id: Mapped[int] = mapped_column(ForeignKey("module_version.id"))
    # the page they are on, counting from 0; one past the last is the quiz
    page: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 server_default=func.now())
```

In `api/lms/models/evidence.py`, replace:
```python
class Upload(Base):
    """A file someone sent: a ticket's photo or PDF, or a policy signature.
    Kept on disk under LMS_UPLOAD_DIR, named by its random id; served only
    through the API to people who may see it. Append-only: a trigger refuses
    UPDATE and DELETE, since records and tickets point at it."""

    __tablename__ = "upload"
    __table_args__ = (CheckConstraint("purpose in ('ticket', 'signature')", name="purpose"),)
```
with:
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

`api/lms/models/records.py`:
```python
from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from lms.models.base import Base, created_at_column
from lms.models.catalogue import Competency
from lms.models.evidence import PolicyVersion
from lms.models.modules import QuizAttempt
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
        # a drawn signature goes on one record only
        Index("uq_competency_record_signature_upload_id", "signature_upload_id", unique=True,
              postgresql_where=text("signature_upload_id is not null")),
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
    # a module passed: the quiz attempt that passed it
    quiz_attempt_id: Mapped[int | None] = mapped_column(ForeignKey("quiz_attempt.id"), unique=True)
    created_at: Mapped[datetime] = created_at_column()

    competency: Mapped[Competency] = relationship()
    recorded_by: Mapped[Person] = relationship(foreign_keys=[recorded_by_id])
    policy_version: Mapped[PolicyVersion | None] = relationship()
    quiz_attempt: Mapped[QuizAttempt | None] = relationship()
```

`api/lms/models/__init__.py`:
```python
from lms.models.base import Base
from lms.models.people import PERMISSIONS, Person, Session
from lms.models.catalogue import KINDS, Competency, PersonRole, Role, RoleRequirement
from lms.models.evidence import PolicyVersion, TicketSubmission, Upload
from lms.models.modules import (
    PAGE_KINDS, ModulePage, ModuleProgress, ModuleVersion, QuizAttempt, QuizQuestion,
)
from lms.models.records import CompetencyRecord, PersonOverride
from lms.models.outbox import Outbox

__all__ = [
    "Base", "PERMISSIONS", "KINDS", "PAGE_KINDS", "Person", "Session", "Role", "PersonRole",
    "Competency", "RoleRequirement", "PersonOverride", "CompetencyRecord", "Upload",
    "PolicyVersion", "TicketSubmission", "Outbox", "ModuleVersion", "ModulePage",
    "QuizQuestion", "QuizAttempt", "ModuleProgress",
]
```

`api/alembic/versions/0003_modules.py`:
```python
"""modules: versions of pages and a quiz, attempts, progress, page files

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-15
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PURPOSES_BEFORE = "purpose in ('ticket', 'signature')"
PURPOSES_NOW = "purpose in ('ticket', 'signature', 'page-image', 'page-pdf', 'page-video')"
DRAFT_ONLY = ("module_page", "quiz_question")


def _created_at() -> sa.Column:
    return sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
                     nullable=False)


def upgrade() -> None:
    # a module page's picture, PDF or video is a file sent like any other
    op.drop_constraint(op.f("ck_upload_purpose"), "upload", type_="check")
    op.create_check_constraint(op.f("ck_upload_purpose"), "upload", PURPOSES_NOW)

    op.create_table(
        "module_version",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("competency_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("pass_mark", sa.Integer(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_by_id", sa.Integer(), nullable=True),
        _created_at(),
        sa.CheckConstraint("version >= 1", name=op.f("ck_module_version_version")),
        sa.CheckConstraint("pass_mark between 1 and 100", name=op.f("ck_module_version_pass_mark")),
        # published, by whom and when, or neither
        sa.CheckConstraint("(published_at is null) = (published_by_id is null)",
                           name=op.f("ck_module_version_published")),
        sa.ForeignKeyConstraint(["competency_id"], ["competency.id"],
                                name=op.f("fk_module_version_competency_id_competency")),
        sa.ForeignKeyConstraint(["published_by_id"], ["person.id"],
                                name=op.f("fk_module_version_published_by_id_person")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_module_version")),
        sa.UniqueConstraint("competency_id", "version",
                            name=op.f("uq_module_version_competency_id_version")),
    )
    op.create_index(op.f("ix_module_version_competency_id"), "module_version", ["competency_id"])
    # one draft at a time for a module
    op.create_index("uq_module_version_draft", "module_version", ["competency_id"], unique=True,
                    postgresql_where=sa.text("published_at is null"))

    op.create_table(
        "module_page",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("module_version_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("upload_id", sa.Uuid(), nullable=True),
        sa.Column("url", sa.String(length=2000), nullable=True),
        sa.CheckConstraint("kind in ('text', 'image', 'pdf', 'video', 'link')",
                           name=op.f("ck_module_page_kind")),
        sa.CheckConstraint("position >= 0", name=op.f("ck_module_page_position")),
        sa.CheckConstraint("length(trim(title)) > 0", name=op.f("ck_module_page_title")),
        # a text page has its text; the others may have a line or two under them
        sa.CheckConstraint("kind <> 'text' or coalesce(length(trim(body)), 0) > 0",
                           name=op.f("ck_module_page_body")),
        # a picture, a PDF and a video are a file; a link is a web address
        sa.CheckConstraint("(kind in ('image', 'pdf', 'video')) = (upload_id is not null)",
                           name=op.f("ck_module_page_file")),
        sa.CheckConstraint("(kind = 'link') = (url is not null)", name=op.f("ck_module_page_url")),
        sa.ForeignKeyConstraint(["module_version_id"], ["module_version.id"],
                                name=op.f("fk_module_page_module_version_id_module_version")),
        sa.ForeignKeyConstraint(["upload_id"], ["upload.id"],
                                name=op.f("fk_module_page_upload_id_upload")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_module_page")),
        sa.UniqueConstraint("module_version_id", "position",
                            name=op.f("uq_module_page_module_version_id_position")),
    )
    op.create_index(op.f("ix_module_page_module_version_id"), "module_page", ["module_version_id"])
    op.create_index(op.f("ix_module_page_upload_id"), "module_page", ["upload_id"])

    op.create_table(
        "quiz_question",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("module_version_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("prompt", sa.String(length=500), nullable=False),
        sa.Column("options", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("correct", sa.Integer(), nullable=False),
        sa.CheckConstraint("position >= 0", name=op.f("ck_quiz_question_position")),
        sa.CheckConstraint("length(trim(prompt)) > 0", name=op.f("ck_quiz_question_prompt")),
        sa.CheckConstraint("jsonb_typeof(options) = 'array' and jsonb_array_length(options) "
                           "between 2 and 6", name=op.f("ck_quiz_question_options")),
        sa.CheckConstraint("correct >= 0 and correct < jsonb_array_length(options)",
                           name=op.f("ck_quiz_question_correct")),
        sa.ForeignKeyConstraint(["module_version_id"], ["module_version.id"],
                                name=op.f("fk_quiz_question_module_version_id_module_version")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_quiz_question")),
        sa.UniqueConstraint("module_version_id", "position",
                            name=op.f("uq_quiz_question_module_version_id_position")),
    )
    op.create_index(op.f("ix_quiz_question_module_version_id"), "quiz_question",
                    ["module_version_id"])

    op.create_table(
        "quiz_attempt",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("person_id", sa.Integer(), nullable=False),
        sa.Column("competency_id", sa.Integer(), nullable=False),
        sa.Column("module_version_id", sa.Integer(), nullable=False),
        sa.Column("answers", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("correct", sa.Integer(), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        _created_at(),
        sa.CheckConstraint("total >= 1 and correct between 0 and total",
                           name=op.f("ck_quiz_attempt_counts")),
        sa.CheckConstraint("score between 0 and 100", name=op.f("ck_quiz_attempt_score")),
        sa.CheckConstraint("jsonb_typeof(answers) = 'array'", name=op.f("ck_quiz_attempt_answers")),
        sa.ForeignKeyConstraint(["person_id"], ["person.id"],
                                name=op.f("fk_quiz_attempt_person_id_person")),
        sa.ForeignKeyConstraint(["competency_id"], ["competency.id"],
                                name=op.f("fk_quiz_attempt_competency_id_competency")),
        sa.ForeignKeyConstraint(["module_version_id"], ["module_version.id"],
                                name=op.f("fk_quiz_attempt_module_version_id_module_version")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_quiz_attempt")),
    )
    op.create_index(op.f("ix_quiz_attempt_person_id"), "quiz_attempt", ["person_id"])
    op.create_index(op.f("ix_quiz_attempt_competency_id"), "quiz_attempt", ["competency_id"])

    op.create_table(
        "module_progress",
        sa.Column("person_id", sa.Integer(), nullable=False),
        sa.Column("competency_id", sa.Integer(), nullable=False),
        sa.Column("module_version_id", sa.Integer(), nullable=False),
        sa.Column("page", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
                  nullable=False),
        sa.CheckConstraint("page >= 0", name=op.f("ck_module_progress_page")),
        sa.ForeignKeyConstraint(["person_id"], ["person.id"],
                                name=op.f("fk_module_progress_person_id_person")),
        sa.ForeignKeyConstraint(["competency_id"], ["competency.id"],
                                name=op.f("fk_module_progress_competency_id_competency")),
        sa.ForeignKeyConstraint(["module_version_id"], ["module_version.id"],
                                name=op.f("fk_module_progress_module_version_id_module_version")),
        sa.PrimaryKeyConstraint("person_id", "competency_id", name=op.f("pk_module_progress")),
    )

    op.add_column("competency_record", sa.Column("quiz_attempt_id", sa.Integer(), nullable=True))
    op.create_foreign_key(op.f("fk_competency_record_quiz_attempt_id_quiz_attempt"),
                          "competency_record", "quiz_attempt", ["quiz_attempt_id"], ["id"])
    op.create_unique_constraint(op.f("uq_competency_record_quiz_attempt_id"),
                                "competency_record", ["quiz_attempt_id"])

    # Every attempt is kept as it was (rule 1).
    op.execute("create trigger quiz_attempt_append_only before update or delete "
               "on quiz_attempt for each row execute function block_change()")
    # A draft is edited freely; publishing it is the last change it ever
    # gets, so an attempt always means what was asked. Never deleted.
    op.execute("""
        create or replace function publish_once() returns trigger
        language plpgsql as $$
        begin
            if tg_op = 'DELETE' then
                raise exception '% rows cannot be deleted', tg_table_name
                    using errcode = 'restrict_violation';
            end if;
            if old.published_at is not null
               or (new.id, new.competency_id, new.version, new.created_at)
                  is distinct from (old.id, old.competency_id, old.version, old.created_at) then
                raise exception '% is frozen once published: start a new version', tg_table_name
                    using errcode = 'restrict_violation';
            end if;
            return new;
        end
        $$
    """)
    op.execute("create trigger module_version_publish_once before update or delete "
               "on module_version for each row execute function publish_once()")
    # Pages and questions change only while their version is a draft.
    op.execute("""
        create or replace function draft_only() returns trigger
        language plpgsql as $$
        begin
            if exists (select 1 from module_version v
                       where v.id in (old.module_version_id, new.module_version_id)
                         and v.published_at is not null) then
                raise exception '% belongs to a published module version: start a new version',
                    tg_table_name using errcode = 'restrict_violation';
            end if;
            if tg_op = 'DELETE' then
                return old;
            end if;
            return new;
        end
        $$
    """)
    for table in DRAFT_ONLY:
        op.execute(f"create trigger {table}_draft_only before insert or update or delete "
                   f"on {table} for each row execute function draft_only()")


def downgrade() -> None:
    for table in DRAFT_ONLY:
        op.execute(f"drop trigger if exists {table}_draft_only on {table}")
    op.execute("drop function if exists draft_only()")
    op.execute("drop trigger if exists module_version_publish_once on module_version")
    op.execute("drop function if exists publish_once()")
    op.execute("drop trigger if exists quiz_attempt_append_only on quiz_attempt")
    op.drop_constraint(op.f("uq_competency_record_quiz_attempt_id"), "competency_record",
                       type_="unique")
    op.drop_constraint(op.f("fk_competency_record_quiz_attempt_id_quiz_attempt"),
                       "competency_record", type_="foreignkey")
    op.drop_column("competency_record", "quiz_attempt_id")
    op.drop_table("module_progress")
    op.drop_index(op.f("ix_quiz_attempt_competency_id"), table_name="quiz_attempt")
    op.drop_index(op.f("ix_quiz_attempt_person_id"), table_name="quiz_attempt")
    op.drop_table("quiz_attempt")
    op.drop_index(op.f("ix_quiz_question_module_version_id"), table_name="quiz_question")
    op.drop_table("quiz_question")
    op.drop_index(op.f("ix_module_page_upload_id"), table_name="module_page")
    op.drop_index(op.f("ix_module_page_module_version_id"), table_name="module_page")
    op.drop_table("module_page")
    op.drop_index("uq_module_version_draft", table_name="module_version")
    op.drop_index(op.f("ix_module_version_competency_id"), table_name="module_version")
    op.drop_table("module_version")
    # before 0003 a file is a ticket's or a signature: with page files kept,
    # going back is refused rather than losing them
    op.execute("""
        do $$
        begin
            if exists (select 1 from upload where purpose like 'page-%') then
                raise exception 'module page files are kept: remove them by hand before going '
                    'back past 0003';
            end if;
        end
        $$
    """)
    op.drop_constraint(op.f("ck_upload_purpose"), "upload", type_="check")
    op.create_check_constraint(op.f("ck_upload_purpose"), "upload", PURPOSES_BEFORE)
```

**Step 4: Run them, and the whole suite, to see them pass**

Run: `cd api && .venv/bin/pytest tests/test_migrations.py tests/test_module_rows.py -q`
Expected: `23 passed`

Run: `cd api && .venv/bin/pytest -q`
Expected: `280 passed` (nothing else uses the new tables yet).

**Step 5: Commit**

```
git add api/lms/models api/alembic/versions/0003_modules.py api/tests/test_migrations.py api/tests/test_module_rows.py
git commit -m "Keep module versions, their pages and questions, and every quiz attempt, frozen once published" \
  -m "A draft is edited freely; publishing it is the last change it gets, and the database refuses the rest. Attempts are append-only, and a page's file is a new kind of upload."
```

---

### Task 2: Files written to disk as they arrive, and a module page's pictures, PDFs and videos

**Files:**
- Modify: `api/lms/services/uploads.py`, `api/lms/api/routes/uploads.py` (both in full below)
- Test: `api/tests/files.py` (in full below), `api/tests/test_uploads.py`

**Step 1: Write the failing tests**

`api/tests/files.py`:
```python
"""Small files of each kind, and sending one through the API."""

PNG = b"\x89PNG\r\n\x1a\n" + b"signature" * 20
JPEG = b"\xff\xd8\xff\xe0" + b"photo" * 40
PDF = b"%PDF-1.7\n" + b"card" * 40
# an MP4's ftyp box, and a WebM's EBML header naming its DocType
MP4 = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom" + b"frames" * 40
WEBM = b"\x1a\x45\xdf\xa3\x9f\x42\x86\x81\x01\x42\xf7\x81\x01\x42\x82\x84webm" + b"frames" * 40
# what an iPhone records: QuickTime, which most browsers won't play
MOV = b"\x00\x00\x00\x14ftypqt  \x00\x00\x00\x00qt  " + b"frames" * 40


def send(client, headers, purpose="ticket", data=JPEG, content_type="image/jpeg"):
    return client.post("/v1/uploads", params={"purpose": purpose}, content=data,
                       headers={**headers, "Content-Type": content_type})


def sent(client, headers, purpose="ticket", data=JPEG, content_type="image/jpeg") -> str:
    """The id of a file just sent."""
    r = send(client, headers, purpose, data, content_type)
    assert r.status_code == 201, r.text
    return r.json()["id"]
```

In `api/tests/test_uploads.py`, replace:
```python
from files import JPEG, PDF, PNG, send, sent
```
with:
```python
from files import JPEG, MOV, MP4, PDF, PNG, WEBM, send, sent
```

Append to `api/tests/test_uploads.py`:
```python
@pytest.mark.parametrize("purpose, data, content_type", [
    ("page-image", JPEG, "image/jpeg"),
    ("page-image", PNG, "image/png"),
    ("page-pdf", PDF, "application/pdf"),
    ("page-video", MP4, "video/mp4"),
    ("page-video", WEBM, "video/webm"),
])
def test_an_editor_sends_a_module_pages_files(client, manager_headers, upload_dir, purpose, data,
                                              content_type):
    r = send(client, manager_headers, purpose, data, "application/octet-stream")
    assert r.status_code == 201, r.text
    out = r.json()
    assert (out["purpose"], out["content_type"]) == (purpose, content_type)
    assert [p.name for p in upload_dir.rglob("*") if p.is_file()] == [
        f"{out['id']}.{uploads.EXT[content_type]}"]


@pytest.mark.parametrize("data", [MOV, PDF, b"\x1a\x45\xdf\xa3\x42\x82\x88matroska" + b"x" * 40])
def test_a_video_is_an_mp4_or_a_webm(client, manager_headers, upload_dir, data):
    r = send(client, manager_headers, "page-video", data, "video/quicktime")
    assert r.status_code == 415 and r.json() == {
        "detail": "a page-video file must be one of: MP4, WEBM", "code": "unsupported_type"}
    assert not [p for p in upload_dir.rglob("*") if p.is_file()]


def test_only_an_editor_sends_a_modules_files(client, learner_headers, supervisor_headers):
    for headers in (learner_headers, supervisor_headers):
        r = send(client, headers, "page-video", MP4, "video/mp4")
        assert r.status_code == 403 and r.json()["code"] == "forbidden"


def test_a_video_may_be_200_mb_and_anything_else_20(client, manager_headers):
    assert uploads.PURPOSES["page-video"][1] == 200_000_000
    assert {uploads.PURPOSES[p][1] for p in ("ticket", "page-image", "page-pdf")} == {20_000_000}
    # declared too big: refused before the body is read
    r = client.post("/v1/uploads", params={"purpose": "page-image"}, content=JPEG,
                    headers={**manager_headers, "Content-Length": "20000001"})
    assert r.status_code == 413 and r.json() == {
        "detail": "a page-image file may be 20 MB at most", "code": "too_large"}


def test_a_file_goes_to_disk_as_it_comes(upload_dir):
    """Never held whole in memory: each piece is on disk once it is written."""
    file = uploads.Incoming("page-video")
    for n in range(1, 4):
        file.write(MP4 if n == 1 else b"\x00" * 1_000_000)
        file._file.flush()
        assert file.path.stat().st_size == file.size
    assert file.path.parent == upload_dir and file.path.name.startswith(".upload-")
    assert file.finish() == "video/mp4"
    file.discard()
    assert not file.path.exists()


def test_a_refused_file_leaves_nothing_behind(client, learner_headers, upload_dir, monkeypatch):
    monkeypatch.setitem(uploads.PURPOSES, "ticket", ({"image/jpeg"}, 50))
    r = client.post("/v1/uploads", params={"purpose": "ticket"},
                    content=iter([JPEG[:40], JPEG[40:]]),
                    headers={**learner_headers, "Content-Type": "image/jpeg"})
    assert r.status_code == 413
    assert not [p for p in upload_dir.rglob("*") if p.is_file()]
```

**Step 2: Run them to see them fail**

Run: `cd api && .venv/bin/pytest tests/test_uploads.py -q`
Expected: FAIL: `11 failed, 16 passed`: the page purposes are refused as unknown (`Input should be 'ticket' or 'signature'`), `KeyError: 'page-video'`, and `module 'lms.services.uploads' has no attribute 'Incoming'`. (The last new test passes already: a refused file left nothing behind before either; it keeps it that way now that files go to disk as they come.)

**Step 3: Minimal implementation**

`api/lms/services/uploads.py`:
```python
"""Files people send: a ticket's photos (or a PDF of it), policy
signatures, and a module page's picture, PDF or video. Kept on disk under
LMS_UPLOAD_DIR, one file each, named by a random id; the row says whose it
is and what it is. What a file is comes from its first bytes, never from
what the request says. A file is written to disk as it arrives, never held
in memory whole: a video may be 200 MB."""
from __future__ import annotations

import hashlib
import os
import tempfile
import uuid
from pathlib import Path

from sqlalchemy import exists, or_, select
from sqlalchemy.orm import Session as Db

from lms.api.errors import Refused
from lms.config import get_settings
from lms.models import Person, TicketSubmission, Upload

# what each purpose may be, and how big: 200 MB for a video, 20 MB for
# anything else (the design's limits); a signature is a few kB
PURPOSES = {
    "ticket": ({"image/jpeg", "image/png", "application/pdf"}, 20_000_000),
    "signature": ({"image/png"}, 1_000_000),
    "page-image": ({"image/jpeg", "image/png"}, 20_000_000),
    "page-pdf": ({"application/pdf"}, 20_000_000),
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
MAGIC = {"image/png": b"\x89PNG\r\n\x1a\n", "image/jpeg": b"\xff\xd8\xff",
         "application/pdf": b"%PDF-"}
EXT = {"image/png": "png", "image/jpeg": "jpg", "application/pdf": "pdf",
       "video/mp4": "mp4", "video/webm": "webm"}
# enough of the start of a file to say what it is
HEAD = 64


def sniff(data: bytes) -> str | None:
    for content_type, magic in MAGIC.items():
        if data.startswith(magic):
            return content_type
    # an MP4 starts with its ftyp box; QuickTime's own brand is a .mov, which
    # most browsers won't play
    if data[4:8] == b"ftyp" and data[8:12] != b"qt  ":
        return "video/mp4"
    # a WebM is a Matroska file whose header says webm (an .mkv says matroska)
    if data.startswith(b"\x1a\x45\xdf\xa3") and b"webm" in data[:HEAD]:
        return "video/webm"
    return None


def full_path(row: Upload) -> Path:
    return Path(get_settings().upload_dir) / row.path


def too_large(purpose: str) -> Refused:
    _, limit = PURPOSES[purpose]
    return Refused(413, "too_large", f"a {purpose} file may be {limit // 1_000_000} MB at most")


class Incoming:
    """A file as it arrives: written to a temporary file beside where it
    will be kept, counted and hashed as it comes, and refused the moment it
    passes its purpose's limit. Nothing has the real name until store()."""

    def __init__(self, purpose: str):
        self.purpose = purpose
        self.size = 0
        self.head = b""
        self._hash = hashlib.sha256()
        folder = Path(get_settings().upload_dir)
        folder.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(dir=folder, prefix=".upload-")
        self.path = Path(name)
        self._file = os.fdopen(fd, "wb")

    def write(self, chunk: bytes) -> None:
        self.size += len(chunk)
        if self.size > PURPOSES[self.purpose][1]:
            raise too_large(self.purpose)
        if len(self.head) < HEAD:
            self.head += chunk[:HEAD - len(self.head)]
        self._hash.update(chunk)
        self._file.write(chunk)

    def finish(self) -> str:
        """All of it on disk, and what it is; refused if it is not what its
        purpose may be."""
        self._file.flush()
        os.fsync(self._file.fileno())
        self._file.close()
        allowed, _ = PURPOSES[self.purpose]
        content_type = sniff(self.head)
        if content_type not in allowed:
            wanted = ", ".join(sorted(EXT[t].upper() for t in allowed))
            raise Refused(415, "unsupported_type",
                          f"a {self.purpose} file must be one of: {wanted}")
        self.content_type = content_type
        return content_type

    @property
    def sha256(self) -> str:
        return self._hash.hexdigest()

    def discard(self) -> None:
        self._file.close()
        self.path.unlink(missing_ok=True)


def store(db: Db, person: Person, file: Incoming) -> Upload:
    """The row, then the file under its real name. A row that can't be
    saved leaves nothing on disk; what is left to go wrong is the commit,
    and the route removes the file then."""
    try:
        upload_id = uuid.uuid4()
        relative = f"{upload_id.hex[:2]}/{upload_id}.{EXT[file.content_type]}"
        row = Upload(id=upload_id, person_id=person.id, purpose=file.purpose,
                     content_type=file.content_type, size_bytes=file.size, sha256=file.sha256,
                     path=relative)
        db.add(row)
        db.flush()
        target = Path(get_settings().upload_dir) / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(file.path, target)
        return row
    finally:
        file.discard()


def mine(db: Db, person: Person, upload_id: uuid.UUID | None, purpose: str) -> Upload | None:
    """One of this person's own files for this purpose, or None."""
    if upload_id is None:
        return None
    row = db.get(Upload, upload_id)
    if row is None or row.person_id != person.id or row.purpose != purpose:
        return None
    return row


def on_a_ticket(db: Db, upload_id: uuid.UUID) -> bool:
    """A photo goes on one ticket only, waiting or decided: what a manager
    checked can't turn up again on another. The sender's row is locked while
    they send, so two at once can't both find it unused."""
    return db.execute(select(exists().where(or_(
        TicketSubmission.front_upload_id == upload_id,
        TicketSubmission.back_upload_id == upload_id)))).scalar()
```

`api/lms/api/routes/uploads.py`:
```python
"""Files: sent by the learner app before the ticket or signature that names
them, or by the desktop before the module page that shows them; and shown
only to who may see the person they belong to."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from lms.api.deps import DB, Principal, Who
from lms.api.errors import Forbidden, NotFound
from lms.models import Person, Upload
from lms.services import uploads

router = APIRouter(tags=["uploads"])
log = logging.getLogger("lms.uploads")

Purpose = Literal["ticket", "signature", "page-image", "page-pdf", "page-video"]


class UploadOut(BaseModel):
    id: uuid.UUID
    purpose: str
    content_type: str
    size_bytes: int
    created_at: datetime


def upload_out(row: Upload) -> UploadOut:
    return UploadOut(id=row.id, purpose=row.purpose, content_type=row.content_type,
                     size_bytes=row.size_bytes, created_at=row.created_at)


def sender(who: Who, purpose: Purpose = Query()) -> Principal:
    """Your own training's files for anyone; a module's for its editors.
    Checked before a byte of the body is read."""
    scope = uploads.SENDERS[purpose]
    if not who.has_scope(scope):
        raise Forbidden(f"you do not have the {scope} scope")
    return who


async def sent(request: Request, purpose: Purpose = Query()) -> uploads.Incoming:
    """The purpose, then the body, written to disk as it comes and read no
    further than that purpose's limit. A wrong purpose is refused before a
    byte of the body is read."""
    _, limit = uploads.PURPOSES[purpose]
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit:
        raise uploads.too_large(purpose)
    file = uploads.Incoming(purpose)
    try:
        async for chunk in request.stream():
            # the disk, off the event loop: a big video doesn't hold up others
            await run_in_threadpool(file.write, chunk)
        await run_in_threadpool(file.finish)
    except BaseException:
        file.discard()
        raise
    return file


@router.post("/uploads", status_code=201, response_model=UploadOut)
def send_file(db: DB, who: Principal = Depends(sender),
              file: uploads.Incoming = Depends(sent)):
    """The file as the body (what counts is its first bytes, not its
    Content-Type). The caller is checked before the body is read
    (dependencies run in order)."""
    row = uploads.store(db, who.person, file)
    try:
        db.commit()
    except BaseException:
        # no row, no file: nothing on disk that nothing points to
        uploads.full_path(row).unlink(missing_ok=True)
        raise
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
    # a PDF under the sandbox shows blank in the browser, so it is saved instead
    shown = "attachment" if row.content_type == "application/pdf" else "inline"
    return Response(content=content, media_type=row.content_type,
                    headers={"Cache-Control": "private, no-store",
                             # opened on its own, it runs nothing and reaches nothing
                             "Content-Security-Policy": "default-src 'none'; sandbox",
                             "Content-Disposition":
                                 f'{shown}; filename="{row.id}.{uploads.EXT[row.content_type]}"',
                             "X-Content-Type-Options": "nosniff"})
```

**Step 4: Run them, and the whole suite, to see them pass**

Run: `cd api && .venv/bin/pytest tests/test_uploads.py -q`
Expected: `27 passed`

Run: `cd api && .venv/bin/pytest -q`
Expected: `292 passed` (the tickets and signatures still go through the same door).

**Step 5: Commit**

```
git add api/lms/services/uploads.py api/lms/api/routes/uploads.py api/tests/files.py api/tests/test_uploads.py
git commit -m "Write each file to disk as it arrives, and take a module page's pictures, PDFs and videos" \
  -m "A video may be an MP4 or a WebM of up to 200 MB, anything else 20 MB, refused as soon as it passes that. Only an editor sends a module's files."
```

---

### Task 3: Signed links that open a module's files, and a video seeked with Range requests

**Files:**
- Create: `api/lms/services/media.py`, `api/lms/api/routes/media.py`
- Modify: `api/pyproject.toml`, `api/lms/services/sessions.py`, `api/lms/api/deps.py`, `api/lms/api/app.py`
- Test: `api/tests/test_media.py`

**Step 1: Write the failing test**

`api/tests/test_media.py`:
```python
"""A module's files open by a link the API made: no token in the URL, a
video seeked with Range requests, and the link good only for its file, its
session and a few hours."""
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import update

from conftest import login, pin_login
from files import JPEG, MP4, PDF, sent
from lms.models import Session
from lms.services import media, sessions


@pytest.fixture
def video(client, manager_headers):
    return sent(client, manager_headers, "page-video", MP4, "video/mp4")


def a_link(db, token: str, upload_id: str, now: datetime | None = None) -> str:
    """What the API puts in a module's page for this session."""
    row = sessions.find(db, token)
    db.commit()
    return media.link(row, uuid.UUID(upload_id), now)


def expires(link: str) -> int:
    return int(parse_qs(urlsplit(link).query)["expires"][0])


def test_a_link_opens_the_file_without_a_token(client, db, manager_headers, video):
    link = a_link(db, manager_headers["Authorization"].split()[1], video)
    assert "lms_s." not in link
    r = client.get(link)
    assert r.status_code == 200 and r.content == MP4
    assert r.headers["content-type"] == "video/mp4"
    assert r.headers["accept-ranges"] == "bytes"
    assert r.headers["content-disposition"] == f'inline; filename="{video}.mp4"'
    assert r.headers["cache-control"] == "private, no-store"
    assert r.headers["content-security-policy"] == "default-src 'none'; sandbox"
    assert r.headers["x-content-type-options"] == "nosniff"


def test_a_video_is_seeked_with_a_range(client, db, manager_headers, video):
    link = a_link(db, manager_headers["Authorization"].split()[1], video)
    r = client.get(link, headers={"Range": "bytes=10-19"})
    assert r.status_code == 206 and r.content == MP4[10:20]
    assert r.headers["content-range"] == f"bytes 10-19/{len(MP4)}"
    assert r.headers["content-type"] == "video/mp4"
    r = client.get(link, headers={"Range": f"bytes={len(MP4) - 5}-"})
    assert r.status_code == 206 and r.content == MP4[-5:]
    r = client.get(link, headers={"Range": f"bytes={len(MP4)}-"})
    assert r.status_code == 416


def test_a_pdf_is_saved_and_a_picture_shown(client, db, manager_headers):
    token = manager_headers["Authorization"].split()[1]
    pdf = sent(client, manager_headers, "page-pdf", PDF, "application/pdf")
    picture = sent(client, manager_headers, "page-image", JPEG)
    r = client.get(a_link(db, token, pdf))
    assert r.headers["content-disposition"] == f'attachment; filename="{pdf}.pdf"'
    r = client.get(a_link(db, token, picture))
    assert r.headers["content-disposition"] == f'inline; filename="{picture}.jpg"'
    assert r.content == JPEG


def test_a_link_is_for_its_own_file(client, db, manager_headers, video):
    token = manager_headers["Authorization"].split()[1]
    other = sent(client, manager_headers, "page-video", MP4, "video/mp4")
    link = a_link(db, token, video).replace(video, other)
    assert client.get(link).status_code == 404
    tampered = a_link(db, token, video)[:-4] + "0000"
    assert client.get(tampered).status_code == 404


def test_a_link_is_for_its_own_session(client, db, manager, manager_headers, video):
    link = a_link(db, manager_headers["Authorization"].split()[1], video)
    other = login(client, manager.email)["token"]
    mine = parse_qs(urlsplit(link).query)
    theirs = sessions.find(db, other)
    db.commit()
    moved = link.replace(f"session={mine['session'][0]}", f"session={theirs.id}")
    assert client.get(moved).status_code == 404


def test_a_link_ends_with_its_session(client, db, manager_headers, video):
    link = a_link(db, manager_headers["Authorization"].split()[1], video)
    assert client.post("/v1/auth/logout", headers=manager_headers).status_code == 204
    assert client.get(link).status_code == 404


def test_a_link_ends_when_a_pin_session_is_left_idle(client, db, learner, manager_headers, video):
    token = pin_login(client, learner.code)["token"]
    link = a_link(db, token, video)
    assert client.get(link).status_code == 200
    db.execute(update(Session).where(Session.token_hash == sessions._hash(token))
               .values(last_seen_at=datetime.now(UTC) - timedelta(minutes=16)))
    db.commit()
    assert client.get(link).status_code == 404


def test_opening_a_link_counts_as_using_the_session(client, db, learner, video):
    token = pin_login(client, learner.code)["token"]
    link = a_link(db, token, video)
    db.execute(update(Session).where(Session.token_hash == sessions._hash(token))
               .values(last_seen_at=datetime.now(UTC) - timedelta(minutes=10)))
    db.commit()
    assert client.get(link).status_code == 200
    db.expire_all()
    row = sessions.find(db, token)
    assert datetime.now(UTC) - row.last_seen_at < timedelta(minutes=1)


def test_a_link_lasts_six_hours_and_never_past_its_session(client, db, learner, video):
    token = pin_login(client, learner.code)["token"]
    row = sessions.find(db, token)
    db.commit()
    now = datetime.now(UTC)
    soon = media.link(row, uuid.UUID(video), now)
    assert expires(soon) == int((now + timedelta(hours=6)).timestamp())
    # a PIN session ends 12 hours after it began
    late = media.link(row, uuid.UUID(video), now + timedelta(hours=11))
    assert expires(late) == int(row.expires_at.timestamp())
    old = media.link(row, uuid.UUID(video), now - timedelta(hours=7))
    assert client.get(old).status_code == 404


def test_a_link_never_opens_someones_own_file(client, db, learner, learner_headers):
    """A ticket's photo or a signature is fetched with the token, by who may see it."""
    photo = sent(client, learner_headers)
    link = a_link(db, learner_headers["Authorization"].split()[1], photo)
    assert client.get(link).status_code == 404


def test_a_file_lost_from_disk_is_not_found(client, db, manager_headers, video, upload_dir):
    link = a_link(db, manager_headers["Authorization"].split()[1], video)
    for p in upload_dir.rglob("*.mp4"):
        p.unlink()
    assert client.get(link).status_code == 404
```

**Step 2: Run it to see it fail**

Run: `cd api && .venv/bin/pytest tests/test_media.py -q`
Expected: FAIL: `ImportError: cannot import name 'media' from 'lms.services'`.

**Step 3: Minimal implementation**

In `api/pyproject.toml`, replace:
```toml
  "fastapi>=0.115",
```
with:
```toml
  "fastapi>=0.115",
  # Range requests in FileResponse, so a phone can seek a module's video
  "starlette>=0.40",
```

In `api/lms/services/sessions.py`, replace:
```python
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
```
with:
```python
def alive(db: Db, row: Session, now: datetime | None = None) -> bool:
    """Not ended, not too old and not idle too long; marked as just used."""
    now = now or datetime.now(UTC)
    if (row.revoked_at is not None or row.expires_at <= now
            or now - row.last_seen_at > IDLE[row.method]):
        return False
    if now - row.last_seen_at >= TOUCH_EVERY:
        row.last_seen_at = now
        db.flush()
    return True


def find(db: Db, raw: str, now: datetime | None = None) -> Session | None:
    """The live session for this token, marked as just used; None if it is
    not ours, ended, too old or idle too long."""
    if not raw.startswith(PREFIX):
        return None
    row = db.execute(select(Session).where(Session.token_hash == _hash(raw))).scalar_one_or_none()
    return row if row is not None and alive(db, row, now) else None
```

In `api/lms/api/deps.py`, replace:
```python
from lms.models import Person
```
with:
```python
from lms.models import Person, Session
```

In `api/lms/api/deps.py`, replace:
```python
    person: Person
    method: str  # password | pin
    scopes: list[str]
```
with:
```python
    person: Person
    method: str  # password | pin
    scopes: list[str]
    # the session itself: links to a module's files are made for it
    session: Session
```

In `api/lms/api/deps.py`, replace:
```python
    return Principal(person=person, method=row.method,
                     scopes=sessions.scopes_for(person.permission, row.method))
```
with:
```python
    return Principal(person=person, method=row.method,
                     scopes=sessions.scopes_for(person.permission, row.method), session=row)
```

`api/lms/services/media.py`:
```python
"""Links to a module page's picture, PDF or video that an <img>, a
<video> or a new tab can open by themselves: they can't send the session's
token, and the token never goes in a URL. A link names one file and the
session it was made for, and carries an expiry; it is signed with that
session's token hash, which only the database knows. It stops working when
it expires or when the session ends, whichever is first."""
from __future__ import annotations

import hashlib
import hmac
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

from sqlalchemy.orm import Session as Db

from lms.models import Person, Session
from lms.services import sessions

LIFETIME = timedelta(hours=6)
# only a module's files have links: a ticket's photo or a signature is
# someone's own, and is fetched with the token
PURPOSES = {"page-image", "page-pdf", "page-video"}


def _sign(session: Session, upload_id: uuid.UUID, expires: int) -> str:
    message = f"{upload_id}:{session.id}:{expires}".encode()
    return hmac.new(session.token_hash.encode(), message, hashlib.sha256).hexdigest()


def link(session: Session, upload_id: uuid.UUID, now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    expires = int(min(now + LIFETIME, session.expires_at).timestamp())
    query = urlencode({"session": session.id, "expires": expires,
                       "sig": _sign(session, upload_id, expires)})
    return f"/v1/media/{upload_id}?{query}"


def opens(db: Db, upload_id: uuid.UUID, session_id: int, expires: int, sig: str,
          now: datetime | None = None) -> bool:
    """Signed for this file and this session, not expired, and the session
    still live (which counts as using it, as any request does)."""
    now = now or datetime.now(UTC)
    if expires < now.timestamp():
        return False
    session = db.get(Session, session_id)
    if session is None or not hmac.compare_digest(sig, _sign(session, upload_id, expires)):
        return False
    person = db.get(Person, session.person_id)
    return person is not None and person.active and sessions.alive(db, session, now)
```

`api/lms/api/routes/media.py`:
```python
"""A module page's files, opened by a link the API made (services/media.py)
rather than with the token: a picture shown, a PDF saved, a video played
and seeked with HTTP Range requests, as phones need."""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse, Response

from lms.api.deps import DB
from lms.api.errors import NotFound
from lms.models import Upload
from lms.services import media, uploads

router = APIRouter(tags=["media"])
log = logging.getLogger("lms.media")


@router.get("/media/{upload_id}", response_class=Response)
def open_media(upload_id: uuid.UUID, db: DB, session: int, expires: int,
               sig: str = Query(max_length=128)):
    """Whoever holds the link, while it lasts. A link that is wrong, expired
    or for a session that has ended is a 404, as is a file that is not a
    module's."""
    row = db.get(Upload, upload_id)
    if (row is None or row.purpose not in media.PURPOSES
            or not media.opens(db, upload_id, session, expires, sig)):
        raise NotFound(f"no file {upload_id}")
    db.commit()  # keeps the touch on the session
    path = uploads.full_path(row)
    try:
        stat = path.stat()
    except FileNotFoundError:
        log.warning("upload %s is recorded but missing from disk at %s", upload_id, path)
        raise NotFound(f"no file {upload_id}") from None
    # a PDF under the sandbox shows blank in the browser, so it is saved instead
    shown = "attachment" if row.content_type == "application/pdf" else "inline"
    return FileResponse(path, media_type=row.content_type, stat_result=stat,
                        filename=f"{row.id}.{uploads.EXT[row.content_type]}",
                        content_disposition_type=shown,
                        headers={"Cache-Control": "private, no-store",
                                 # opened on its own, it runs nothing and reaches nothing
                                 "Content-Security-Policy": "default-src 'none'; sandbox",
                                 "X-Content-Type-Options": "nosniff"})
```

In `api/lms/api/app.py`, replace:
```python
    auth, competencies, matrix, overrides, people, policies, records, roles, tickets, uploads,
)
```
with:
```python
    auth, competencies, matrix, media, overrides, people, policies, records, roles, tickets,
    uploads,
)
```

In `api/lms/api/app.py`, replace:
```python
v1.include_router(uploads.router)
```
with:
```python
v1.include_router(uploads.router)
v1.include_router(media.router)
```

**Step 4: Run it, and the sessions, to see them pass**

Run: `cd api && .venv/bin/pytest tests/test_media.py tests/test_sessions.py tests/test_auth.py -q`
Expected: `38 passed`

**Step 5: Commit**

```
git add api/pyproject.toml api/lms/services/sessions.py api/lms/services/media.py api/lms/api/deps.py api/lms/api/routes/media.py api/lms/api/app.py api/tests/test_media.py
git commit -m "Open a module's files by a link signed for one session, and let a phone seek a video" \
  -m "The token never goes in a URL. A link names one file and its session, lasts six hours at most and ends with the session. Range requests come from Starlette's FileResponse."
```

---

### Task 4: Writing a module: a draft saved in full, then published and frozen

**Files:**
- Create: `api/lms/services/modules.py`, `api/lms/api/routes/modules.py`
- Modify: `api/lms/api/app.py`, `api/tests/conftest.py`
- Test: create `api/tests/course.py` (a module written through the API, for this task's tests and the next two) and `api/tests/test_modules.py`

**Step 1: Write the failing test**

`api/tests/course.py`:
```python
"""A module written through the API for the module tests: site induction,
with a page of each kind and two questions."""
from files import JPEG, MP4, PDF, sent

INDUCTION = "/v1/modules/site-induction"

QUESTIONS = [
    {"prompt": "Where do you sign in?", "options": ["The gatehouse", "The canteen"], "correct": 0},
    {"prompt": "What do you wear on the floor?",
     "options": ["Thongs", "Your PPE", "Anything"], "correct": 1},
]
# what gets both questions right
RIGHT = [0, 1]


def pages(client, headers) -> list[dict]:
    """One page of each kind."""
    return [
        {"kind": "text", "title": "Welcome", "body": "Sign in at the gatehouse.\nWear your PPE."},
        {"kind": "image", "title": "The yard", "body": "Walk inside the green lines.",
         "file": sent(client, headers, "page-image", JPEG)},
        {"kind": "pdf", "title": "Site map",
         "file": sent(client, headers, "page-pdf", PDF, "application/pdf")},
        {"kind": "video", "title": "Lifting safely",
         "file": sent(client, headers, "page-video", MP4, "video/mp4")},
        {"kind": "link", "title": "SafeWork", "url": "https://www.safework.nsw.gov.au"},
    ]


def save(client, headers, **body):
    """The draft in full; nothing but what is given."""
    return client.put(f"{INDUCTION}/draft", headers=headers,
                      json={"pass_mark": 80, "pages": [], "questions": [], **body})


def written(client, headers, questions=QUESTIONS, pass_mark=80) -> dict:
    """The next version started and saved with a page of each kind and the questions."""
    assert client.post(f"{INDUCTION}/draft", headers=headers).status_code == 201
    r = save(client, headers, pass_mark=pass_mark, pages=pages(client, headers),
             questions=questions)
    assert r.status_code == 200, r.text
    return r.json()


def published(client, headers, **more) -> dict:
    """Written, then published."""
    written(client, headers, **more)
    r = client.post(f"{INDUCTION}/draft/publish", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()
```

`api/tests/test_modules.py`:
```python
"""Modules, as their editors write them: a draft of pages and a quiz,
saved in full, then published and frozen. A change after that is a new
version."""
import pytest

import yard
from course import INDUCTION, QUESTIONS, save, written
from files import JPEG, MP4, sent


@pytest.fixture
def induction(client, manager_headers):
    yard.build(client, manager_headers)


def test_a_module_starts_as_an_empty_draft(client, manager_headers, induction):
    assert client.get(f"{INDUCTION}/versions", headers=manager_headers).json() == []
    r = client.post(f"{INDUCTION}/draft", headers=manager_headers)
    assert r.status_code == 201, r.text
    out = r.json()
    assert (out["version"], out["pass_mark"], out["published_at"]) == (1, 80, None)
    assert (out["pages"], out["questions"]) == ([], [])


def test_the_draft_is_saved_in_full(client, manager_headers, induction):
    out = written(client, manager_headers)
    assert [p["kind"] for p in out["pages"]] == ["text", "image", "pdf", "video", "link"]
    text, image, pdf, video, link = out["pages"]
    assert text["body"] == "Sign in at the gatehouse.\nWear your PPE." and text["file"] is None
    assert image["body"] == "Walk inside the green lines."
    assert (video["file"]["content_type"], video["file"]["size_bytes"]) == ("video/mp4", len(MP4))
    assert video["file"]["link"].startswith(f"/v1/media/{video['file']['id']}?session=")
    assert pdf["body"] is None and link["url"] == "https://www.safework.nsw.gov.au"
    assert out["questions"] == QUESTIONS


def test_saving_again_replaces_it(client, manager_headers, induction):
    out = written(client, manager_headers)
    text, image, *_ = out["pages"]
    kept = [{"kind": "image", "title": image["title"], "file": image["file"]["id"]},
            {"kind": "text", "title": text["title"], "body": text["body"]}]
    r = save(client, manager_headers, pass_mark=70, pages=kept, questions=QUESTIONS[1:])
    assert r.status_code == 200, r.text
    out = r.json()
    assert [p["title"] for p in out["pages"]] == ["The yard", "Welcome"]
    assert out["pass_mark"] == 70 and len(out["questions"]) == 1


@pytest.mark.parametrize("page, field, message", [
    ({"kind": "text", "title": "Welcome"}, "pages.0.body", "a text page needs its text"),
    ({"kind": "video", "title": "Lifting"}, "pages.0.file", "add the video"),
    ({"kind": "link", "title": "SafeWork"}, "pages.0.url",
     "a link is a web address starting with https://"),
    ({"kind": "link", "title": "SafeWork", "url": "javascript:alert(1)"}, "pages.0.url",
     "a link is a web address starting with https://"),
    ({"kind": "text", "title": "Welcome", "body": "Hi.", "url": "https://example.com.au"},
     "pages.0.url", "only a link page has a web address"),
])
def test_each_page_has_what_its_kind_needs(client, manager_headers, induction, page, field,
                                           message):
    client.post(f"{INDUCTION}/draft", headers=manager_headers)
    r = save(client, manager_headers, pages=[page])
    assert r.status_code == 422 and r.json()["errors"] == [{"field": field, "message": message}]


def test_a_pages_file_is_a_page_file_of_its_kind(client, manager_headers, induction):
    client.post(f"{INDUCTION}/draft", headers=manager_headers)
    picture = sent(client, manager_headers, "page-image", JPEG)
    photo = sent(client, manager_headers, "ticket", JPEG)
    for file in (picture, photo):
        r = save(client, manager_headers, pages=[{"kind": "video", "title": "Lifting",
                                                  "file": file}])
        assert r.status_code == 422 and r.json()["errors"] == [{
            "field": "pages.0.file",
            "message": "that file isn't a video for a page: send it again"}]


@pytest.mark.parametrize("question, field", [
    ({"prompt": "Well?", "options": ["Yes", "No"], "correct": 2}, "questions.0.correct"),
    ({"prompt": "Well?", "options": ["Yes"], "correct": 0}, "questions.0.options"),
    ({"prompt": "Well?", "options": ["Yes", "  "], "correct": 0}, "questions.0.options.1"),
    ({"prompt": "Well?", "options": list("abcdefg"), "correct": 0}, "questions.0.options"),
])
def test_a_question_has_two_to_six_answers_and_one_is_right(client, manager_headers, induction,
                                                            question, field):
    client.post(f"{INDUCTION}/draft", headers=manager_headers)
    r = save(client, manager_headers, questions=[question])
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == field


def test_publishing_freezes_it_and_a_change_is_a_new_version(client, manager_headers, induction):
    written(client, manager_headers)
    r = client.post(f"{INDUCTION}/draft/publish", headers=manager_headers)
    assert r.status_code == 200, r.text
    one = r.json()
    assert one["published_at"] and one["published_by"] == {"code": "MG001", "name": "Mel Grant"}
    r = save(client, manager_headers, pages=[{"kind": "text", "title": "x", "body": "y"}])
    assert r.status_code == 404 and r.json()["detail"] == "Site induction has no draft: start one"
    # the next version starts as a copy of the last, and changes alone
    r = client.post(f"{INDUCTION}/draft", headers=manager_headers)
    two = r.json()
    assert two["version"] == 2 and two["published_at"] is None
    assert [p["title"] for p in two["pages"]] == [p["title"] for p in one["pages"]]
    assert two["questions"] == one["questions"]
    save(client, manager_headers, pages=[{"kind": "text", "title": "New", "body": "New."}],
         questions=QUESTIONS[:1])
    versions = client.get(f"{INDUCTION}/versions", headers=manager_headers).json()
    assert [(v["version"], len(v["pages"])) for v in versions] == [(2, 1), (1, 5)]


def test_publishing_needs_a_page_and_a_question(client, manager_headers, induction):
    client.post(f"{INDUCTION}/draft", headers=manager_headers)
    save(client, manager_headers, pages=[{"kind": "text", "title": "Hi", "body": "Hi."}])
    r = client.post(f"{INDUCTION}/draft/publish", headers=manager_headers)
    assert r.status_code == 409 and r.json()["code"] == "incomplete"


def test_one_draft_at_a_time(client, manager_headers, induction):
    client.post(f"{INDUCTION}/draft", headers=manager_headers)
    r = client.post(f"{INDUCTION}/draft", headers=manager_headers)
    assert r.status_code == 409 and r.json() == {
        "detail": "version 1 is being written already", "code": "draft_exists"}


def test_only_a_module_has_versions(client, manager_headers, induction):
    r = client.post("/v1/modules/whs-policy/draft", headers=manager_headers)
    assert r.status_code == 404 and r.json()["detail"] == "no module whs-policy"
    r = client.get("/v1/modules/nothing/versions", headers=manager_headers)
    assert r.status_code == 404 and r.json()["detail"] == "no competency nothing"


def test_only_an_editor_writes_one(client, learner_headers, supervisor_headers, manager_headers,
                                   induction):
    for headers in (learner_headers, supervisor_headers):
        assert client.post(f"{INDUCTION}/draft", headers=headers).status_code == 403
    assert client.get(f"{INDUCTION}/versions", headers=supervisor_headers).status_code == 200
    assert client.get(f"{INDUCTION}/versions", headers=learner_headers).status_code == 403


def test_a_deactivated_module_gets_no_new_version(client, manager_headers, induction):
    written(client, manager_headers)
    client.post("/v1/competencies/site-induction/deactivate", headers=manager_headers)
    r = client.post(f"{INDUCTION}/draft/publish", headers=manager_headers)
    assert r.status_code == 409 and r.json()["code"] == "inactive"
```

**Step 2: Run it to see it fail**

Run: `cd api && .venv/bin/pytest tests/test_modules.py -q`
Expected: FAIL: `19 failed`: every `/v1/modules/…` call is `404 {"detail": "Not Found"}`.

**Step 3: Minimal implementation**

`api/lms/services/modules.py`:
```python
"""Modules: versions of pages and a quiz. A draft is edited freely;
publishing freezes it. People take the newest published version."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session as Db

from lms.models import Competency, ModulePage, ModuleVersion, QuizQuestion


def newest(db: Db, module: Competency) -> ModuleVersion | None:
    """The version people take now."""
    return db.execute(select(ModuleVersion).where(ModuleVersion.competency_id == module.id,
                                                  ModuleVersion.published_at.is_not(None))
                      .order_by(ModuleVersion.version.desc()).limit(1)).scalar_one_or_none()


def draft(db: Db, module: Competency) -> ModuleVersion | None:
    return db.execute(select(ModuleVersion).where(ModuleVersion.competency_id == module.id,
                                                  ModuleVersion.published_at.is_(None))
                      ).scalar_one_or_none()


def start_draft(db: Db, module: Competency) -> ModuleVersion:
    """The next version, a copy of the newest published one (or empty):
    changed without touching what people have taken."""
    last = db.execute(select(func.max(ModuleVersion.version))
                      .where(ModuleVersion.competency_id == module.id)).scalar() or 0
    base = newest(db, module)
    v = ModuleVersion(competency=module, version=last + 1,
                      pass_mark=base.pass_mark if base else 80)
    db.add(v)
    db.flush()
    for p in base.pages if base else []:
        db.add(ModulePage(module_version_id=v.id, position=p.position, kind=p.kind,
                          title=p.title, body=p.body, upload_id=p.upload_id, url=p.url))
    for q in base.questions if base else []:
        db.add(QuizQuestion(module_version_id=v.id, position=q.position, prompt=q.prompt,
                            options=list(q.options), correct=q.correct))
    db.flush()
    db.expire(v, ["pages", "questions"])
    return v
```

`api/lms/api/routes/modules.py`:
```python
"""Modules, as their editors see them: versions of pages and a quiz with a
pass mark. A draft is written and saved in full as often as needed, then
published, which freezes it: what someone answered is always what they
were asked (rule 1). A change after that is a new version, started as a
copy of the last."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import delete, select

from lms.api.deps import DB, Principal, require
from lms.api.errors import Conflict, FieldError, NotFound
from lms.api.routes.competencies import get_competency
from lms.api.schemas import PersonRef, person_ref
from lms.models import (
    Competency, ModulePage, ModuleVersion, QuizQuestion, Session, Upload,
)
from lms.services import media, modules

router = APIRouter(tags=["modules"])

PageKind = Literal["text", "image", "pdf", "video", "link"]
FILES = {"image": "page-image", "pdf": "page-pdf", "video": "page-video"}
NAMED = {"image": "picture", "pdf": "PDF", "video": "video"}
Answer = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class PageIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    kind: PageKind
    title: str = Field(min_length=1, max_length=120)
    # a text page's text; on any other page, a line or two under it
    body: str | None = Field(default=None, max_length=20_000)
    # a picture, PDF or video: sent first to POST /v1/uploads?purpose=page-<kind>
    file: uuid.UUID | None = None
    # a link: the web address, opened in a new tab
    url: str | None = Field(default=None, max_length=2000)


class QuestionIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    prompt: str = Field(min_length=1, max_length=500)
    options: list[Answer] = Field(min_length=2, max_length=6)
    # which answer is right, counting from 0
    correct: int = Field(ge=0)


class DraftIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pass_mark: int = Field(ge=1, le=100)
    pages: list[PageIn] = Field(max_length=100)
    questions: list[QuestionIn] = Field(max_length=50)


class FileOut(BaseModel):
    id: uuid.UUID
    content_type: str
    size_bytes: int
    # opens it without the token, for this session, for a few hours
    link: str


class PageOut(BaseModel):
    kind: str
    title: str
    body: str | None
    url: str | None
    file: FileOut | None


class QuestionOut(BaseModel):
    prompt: str
    options: list[str]
    correct: int


class VersionOut(BaseModel):
    id: int
    version: int
    pass_mark: int
    published_at: datetime | None
    published_by: PersonRef | None
    pages: list[PageOut]
    questions: list[QuestionOut]
    created_at: datetime


def page_out(p: ModulePage, session: Session) -> PageOut:
    file = None
    if p.upload is not None:
        file = FileOut(id=p.upload.id, content_type=p.upload.content_type,
                       size_bytes=p.upload.size_bytes, link=media.link(session, p.upload.id))
    return PageOut(kind=p.kind, title=p.title, body=p.body, url=p.url, file=file)


def version_out(v: ModuleVersion, session: Session) -> VersionOut:
    return VersionOut(id=v.id, version=v.version, pass_mark=v.pass_mark,
                      published_at=v.published_at, published_by=person_ref(v.published_by),
                      pages=[page_out(p, session) for p in v.pages],
                      questions=[QuestionOut(prompt=q.prompt, options=q.options, correct=q.correct)
                                 for q in v.questions],
                      created_at=v.created_at)


def get_module(db, key: str) -> Competency:
    c = get_competency(db, key)
    if c.kind != "module":
        raise NotFound(f"no module {key}")
    return c


def _active(c: Competency) -> None:
    if not c.active:
        raise Conflict("inactive", f"{c.key} is deactivated")


def _draft(db, c: Competency) -> ModuleVersion:
    """The draft, locked: one save at a time, and never while it is published."""
    v = modules.draft(db, c)
    if v is None:
        raise NotFound(f"{c.name} has no draft: start one")
    db.refresh(v, with_for_update=True)
    if v.published_at is not None:
        raise Conflict("published", f"version {v.version} was published meanwhile: start a new one")
    return v


def _page(db, i: int, p: PageIn) -> ModulePage:
    """What each kind of page needs, and nothing it doesn't."""
    at = f"pages.{i}"
    if p.kind == "text" and not p.body:
        raise FieldError(f"{at}.body", "a text page needs its text")
    if p.kind in FILES:
        if p.file is None:
            raise FieldError(f"{at}.file", f"add the {NAMED[p.kind]}")
        upload = db.get(Upload, p.file)
        if upload is None or upload.purpose != FILES[p.kind]:
            raise FieldError(f"{at}.file", f"that file isn't a {NAMED[p.kind]} for a page: "
                                           "send it again")
    elif p.file is not None:
        raise FieldError(f"{at}.file", "only a picture, PDF or video page has a file")
    if p.kind == "link":
        if not p.url or not p.url.lower().startswith(("https://", "http://")):
            raise FieldError(f"{at}.url", "a link is a web address starting with https://")
    elif p.url is not None:
        raise FieldError(f"{at}.url", "only a link page has a web address")
    return ModulePage(position=i, kind=p.kind, title=p.title, body=p.body or None,
                      upload_id=p.file, url=p.url)


@router.get("/modules/{key}/versions", response_model=list[VersionOut])
def list_versions(key: str, db: DB, who: Principal = require("competencies:read")):
    """Newest first: a draft (if there is one), then what has been published.
    With the right answers: this is the editor's view."""
    c = get_module(db, key)
    rows = db.execute(select(ModuleVersion).where(ModuleVersion.competency_id == c.id)
                      .order_by(ModuleVersion.version.desc())).scalars().all()
    return [version_out(v, who.session) for v in rows]


@router.post("/modules/{key}/draft", status_code=201, response_model=VersionOut)
def start_draft(key: str, db: DB, who: Principal = require("competencies:write")):
    """The next version, a copy of the newest published one (or empty)."""
    c = get_module(db, key)
    _active(c)
    # one at a time per module, so two at once don't both start one
    db.refresh(c, with_for_update=True)
    existing = modules.draft(db, c)
    if existing is not None:
        raise Conflict("draft_exists", f"version {existing.version} is being written already")
    v = modules.start_draft(db, c)
    db.commit()
    out = version_out(v, who.session)
    return JSONResponse(status_code=201, content=out.model_dump(mode="json"))


@router.put("/modules/{key}/draft", response_model=VersionOut)
def save_draft(key: str, body: DraftIn, db: DB, who: Principal = require("competencies:write")):
    """The draft in full: its pass mark, its pages and its questions, in
    order. Whatever was there before is replaced."""
    c = get_module(db, key)
    v = _draft(db, c)
    pages = [_page(db, i, p) for i, p in enumerate(body.pages)]
    for i, q in enumerate(body.questions):
        if q.correct >= len(q.options):
            raise FieldError(f"questions.{i}.correct", "choose which answer is right")
    db.execute(delete(ModulePage).where(ModulePage.module_version_id == v.id))
    db.execute(delete(QuizQuestion).where(QuizQuestion.module_version_id == v.id))
    for page in pages:
        page.module_version_id = v.id
        db.add(page)
    for i, q in enumerate(body.questions):
        db.add(QuizQuestion(module_version_id=v.id, position=i, prompt=q.prompt,
                            options=q.options, correct=q.correct))
    v.pass_mark = body.pass_mark
    db.commit()
    db.expire(v, ["pages", "questions"])
    return version_out(v, who.session)


@router.post("/modules/{key}/draft/publish", response_model=VersionOut)
def publish(key: str, db: DB, who: Principal = require("competencies:write")):
    """Frozen from now on, and the one people take. Their passes so far
    still count: a new version doesn't ask anyone to take it again."""
    c = get_module(db, key)
    _active(c)
    v = _draft(db, c)
    if not v.pages or not v.questions:
        raise Conflict("incomplete", "a module needs at least one page and one question")
    v.published_at = datetime.now(UTC)
    v.published_by = who.person
    db.commit()
    return version_out(v, who.session)
```

In `api/lms/api/app.py`, replace:
```python
    auth, competencies, matrix, media, overrides, people, policies, records, roles, tickets,
    uploads,
)
```
with:
```python
    auth, competencies, matrix, media, modules, overrides, people, policies, records, roles,
    tickets, uploads,
)
```

In `api/lms/api/app.py`, replace:
```python
v1.include_router(tickets.router)
```
with:
```python
v1.include_router(tickets.router)
v1.include_router(modules.router)
```

The app's own engine (`lms.db.get_engine`) is never closed in the tests, and with the new router the garbage collector finds its connections still open at exit (a `ResourceWarning` after the summary). In `api/tests/conftest.py`, replace:
```python
    command.upgrade(cfg, "head")
    yield engine
    engine.dispose()
```
with:
```python
    command.upgrade(cfg, "head")
    yield engine
    engine.dispose()
    # and the app's own, so no connection is left for the garbage collector
    from lms.db import get_engine

    get_engine().dispose()
```

**Step 4: Run it, and the whole suite, to see them pass**

Run: `cd api && .venv/bin/pytest tests/test_modules.py -q`
Expected: `19 passed`, with nothing printed after the summary.

Run: `cd api && .venv/bin/pytest -q`
Expected: `322 passed`

**Step 5: Commit**

```
git add api/lms/services/modules.py api/lms/api/routes/modules.py api/lms/api/app.py api/tests/conftest.py api/tests/course.py api/tests/test_modules.py
git commit -m "Write a module as a draft of pages and a quiz, saved in full, then publish it and freeze it" \
  -m "Each kind of page has what it needs and nothing else; a link is a web address, a file is a page's file of its kind. A change after publishing is a new version, started as a copy of the last."
```

---

### Task 5: Reading a module: the newest published version without the answers, and the place kept

**Files:**
- Create: `api/lms/api/routes/learning.py`
- Modify: `api/lms/api/app.py`
- Test: `api/tests/test_learning.py`

**Step 1: Write the failing test**

`api/tests/test_learning.py`:
```python
"""A module as the learner takes it: the newest published version, its
pages and its questions without the right answers, and how far they have
read kept on the server."""
import pytest

import yard
from conftest import bearer, pin_login
from course import INDUCTION, published, save, written
from files import MP4


@pytest.fixture
def kim(client, manager_headers, learner):
    """Kim is a picker: pickers do the site induction."""
    yard.build(client, manager_headers)
    yard.give_roles(client, manager_headers, "LL042", "picker")
    return learner


def test_nothing_to_take_until_it_is_published(client, manager_headers, learner_headers, kim):
    written(client, manager_headers)
    r = client.get(INDUCTION, headers=learner_headers)
    assert r.status_code == 404 and r.json()["detail"] == "Site induction has nothing to take yet"


def test_the_learner_gets_the_newest_published_version_without_the_answers(
        client, manager_headers, learner_headers, kim):
    published(client, manager_headers)
    # version 2 is being written: nobody takes it until it is published
    client.post(f"{INDUCTION}/draft", headers=manager_headers)
    save(client, manager_headers, pages=[{"kind": "text", "title": "New", "body": "New."}])
    out = client.get(INDUCTION, headers=learner_headers).json()
    assert (out["key"], out["name"], out["resume_at"]) == ("site-induction", "Site induction", 0)
    v = out["version"]
    assert (v["version"], v["pass_mark"], len(v["pages"])) == (1, 80, 5)
    assert v["questions"] == [
        {"prompt": "Where do you sign in?", "options": ["The gatehouse", "The canteen"]},
        {"prompt": "What do you wear on the floor?", "options": ["Thongs", "Your PPE", "Anything"]},
    ]
    assert "correct" not in str(out)


def test_the_learners_links_open_the_files(client, manager_headers, learner_headers, kim):
    published(client, manager_headers)
    video = client.get(INDUCTION, headers=learner_headers).json()["version"]["pages"][3]
    r = client.get(video["file"]["link"])
    assert r.status_code == 200 and r.content == MP4


def test_where_they_left_off_is_kept(client, manager_headers, learner_headers, learner, kim):
    published(client, manager_headers)
    r = client.put(f"{INDUCTION}/progress", headers=learner_headers, json={"version": 1, "page": 3})
    assert r.status_code == 204
    assert client.get(INDUCTION, headers=learner_headers).json()["resume_at"] == 3
    # on another device, the same place
    tablet = bearer(pin_login(client, learner.code)["token"])
    assert client.get(INDUCTION, headers=tablet).json()["resume_at"] == 3
    # one past the last page is the quiz
    client.put(f"{INDUCTION}/progress", headers=tablet, json={"version": 1, "page": 5})
    assert client.get(INDUCTION, headers=learner_headers).json()["resume_at"] == 5


def test_each_person_has_their_own_place(client, manager_headers, learner_headers,
                                         supervisor_headers, kim):
    published(client, manager_headers)
    client.put(f"{INDUCTION}/progress", headers=learner_headers, json={"version": 1, "page": 3})
    assert client.get(INDUCTION, headers=supervisor_headers).json()["resume_at"] == 0


def test_a_new_version_starts_from_the_top(client, manager_headers, learner_headers, kim):
    published(client, manager_headers)
    client.put(f"{INDUCTION}/progress", headers=learner_headers, json={"version": 1, "page": 3})
    published(client, manager_headers)
    assert client.get(INDUCTION, headers=learner_headers).json()["resume_at"] == 0
    r = client.put(f"{INDUCTION}/progress", headers=learner_headers,
                   json={"version": 1, "page": 4})
    assert r.status_code == 409 and r.json()["code"] == "new_version"


def test_the_place_is_within_the_module(client, manager_headers, learner_headers, kim):
    published(client, manager_headers)
    r = client.put(f"{INDUCTION}/progress", headers=learner_headers,
                   json={"version": 1, "page": 6})
    assert r.status_code == 422 and r.json()["errors"] == [
        {"field": "page", "message": "this version has 5 pages, then the quiz"}]
```

**Step 2: Run it to see it fail**

Run: `cd api && .venv/bin/pytest tests/test_learning.py -q`
Expected: FAIL: `7 failed`: `GET /v1/modules/site-induction` is `404 {"detail": "Not Found"}` (`KeyError: 'version'`, `KeyError: 'resume_at'` and the like).

**Step 3: Minimal implementation**

`api/lms/api/routes/learning.py`:
```python
"""Modules, as the people taking them see them: the newest published
version's pages one at a time, then its quiz, without the right answers.
How far each person has read is kept here, not on the device, so they carry
on where they left off on any phone or tablet, and a shared tablet keeps
nothing of theirs."""
from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.dialects.postgresql import insert

from lms.api.deps import DB, Principal, require
from lms.api.errors import Conflict, FieldError, NotFound
from lms.api.routes.modules import PageOut, get_module, page_out
from lms.models import Competency, ModuleProgress, ModuleVersion
from lms.services import modules

router = APIRouter(tags=["modules"])


class AskedOut(BaseModel):
    """A question as the learner sees it: never which answer is right."""
    prompt: str
    options: list[str]


class TakingOut(BaseModel):
    id: int
    version: int
    pass_mark: int
    pages: list[PageOut]
    questions: list[AskedOut]


class ModuleOut(BaseModel):
    key: str
    name: str
    version: TakingOut
    # the page to open at, counting from 0; one past the last is the quiz
    resume_at: int


class ProgressIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # the version they are reading: if a newer one came out, they start that
    version: int
    page: int = Field(ge=0)


def to_take(db, c: Competency) -> ModuleVersion:
    v = modules.newest(db, c)
    if v is None:
        raise NotFound(f"{c.name} has nothing to take yet")
    return v


def same_version(v: ModuleVersion, version: int) -> None:
    if version != v.version:
        raise Conflict("new_version", f"version {v.version} is the one to take now: start it")


@router.get("/modules/{key}", response_model=ModuleOut)
def read_module(key: str, db: DB, who: Principal = require("training:read")):
    """The version to take now, and where the caller left off in it."""
    c = get_module(db, key)
    v = to_take(db, c)
    progress = db.get(ModuleProgress, (who.person.id, c.id))
    resume_at = progress.page if progress and progress.module_version_id == v.id else 0
    return ModuleOut(key=c.key, name=c.name, resume_at=min(resume_at, len(v.pages)),
                     version=TakingOut(id=v.id, version=v.version, pass_mark=v.pass_mark,
                                       pages=[page_out(p, who.session) for p in v.pages],
                                       questions=[AskedOut(prompt=q.prompt, options=q.options)
                                                  for q in v.questions]))


@router.put("/modules/{key}/progress", status_code=204)
def keep_progress(key: str, body: ProgressIn, db: DB,
                  who: Principal = require("training:write")):
    """The page the caller is on now, theirs alone."""
    c = get_module(db, key)
    v = to_take(db, c)
    same_version(v, body.version)
    if body.page > len(v.pages):
        raise FieldError("page", f"this version has {len(v.pages)} pages, then the quiz")
    values = {"person_id": who.person.id, "competency_id": c.id, "module_version_id": v.id,
              "page": body.page, "updated_at": datetime.now(UTC)}
    db.execute(insert(ModuleProgress).values(**values).on_conflict_do_update(
        index_elements=["person_id", "competency_id"],
        set_={k: values[k] for k in ("module_version_id", "page", "updated_at")}))
    db.commit()
    return Response(status_code=204)
```

In `api/lms/api/app.py`, replace:
```python
    auth, competencies, matrix, media, modules, overrides, people, policies, records, roles,
    tickets, uploads,
)
```
with:
```python
    auth, competencies, learning, matrix, media, modules, overrides, people, policies, records,
    roles, tickets, uploads,
)
```

In `api/lms/api/app.py`, replace:
```python
v1.include_router(modules.router)
```
with:
```python
v1.include_router(modules.router)
v1.include_router(learning.router)
```

**Step 4: Run it to see it pass**

Run: `cd api && .venv/bin/pytest tests/test_learning.py -q`
Expected: `7 passed`

**Step 5: Commit**

```
git add api/lms/api/routes/learning.py api/lms/api/app.py api/tests/test_learning.py
git commit -m "Give the learner the module to take, without the answers, and keep their place on the server" \
  -m "They carry on where they left off on any device, and a shared tablet keeps nothing of theirs. A new version starts from the top."
```

---

### Task 6: The quiz: marked on the server, every attempt kept, a pass a grant of the learner's own

**Files:**
- Modify: `api/lms/api/routes/learning.py`, `api/lms/services/modules.py`, `api/lms/api/routes/records.py`
- Test: `api/tests/test_quiz.py`

**Step 1: Write the failing test**

`api/tests/test_quiz.py`:
```python
"""The quiz: marked on the server, every attempt kept, a pass a grant of
the learner's own (the one thing anybody earns alone), and the refresher
saying when it runs out. Try again after a fail."""
from datetime import date

import pytest

import yard
from conftest import bearer, make_person, pin_login
from course import INDUCTION, QUESTIONS, RIGHT, published

ATTEMPTS = f"{INDUCTION}/attempts"


@pytest.fixture
def kim(client, manager_headers, learner):
    """Kim is a picker: pickers do the site induction, refreshed every 24 months."""
    yard.build(client, manager_headers)
    yard.give_roles(client, manager_headers, "LL042", "picker")
    return learner


def take(client, headers, answers=RIGHT, version=1):
    return client.post(ATTEMPTS, headers=headers, json={"version": version, "answers": answers})


def induction(client, headers, code="LL042"):
    items = client.get(f"/v1/people/{code}/training", headers=headers).json()["items"]
    return next(i for i in items if i["key"] == "site-induction")


def test_a_pass_makes_it_current_until_the_refresher(client, manager_headers, learner_headers,
                                                      kim):
    published(client, manager_headers)
    r = take(client, learner_headers)
    assert r.status_code == 201, r.text
    out = r.json()
    assert (out["score"], out["correct"], out["total"], out["pass_mark"], out["passed"]) == (
        100, 2, 2, 80, True)
    item = induction(client, learner_headers)
    assert (item["status"], item["granted_on"], item["expires_on"]) == (
        "current", "2026-10-12", "2028-10-12")
    m = client.get("/v1/matrix", headers=manager_headers).json()
    assert next(p for p in m["people"] if p["code"] == "LL042")["cells"]["site-induction"][
        "status"] == "current"


def test_a_pass_is_recorded_as_the_learners_own(client, manager_headers, learner_headers, kim):
    published(client, manager_headers)
    take(client, learner_headers)
    record = client.get("/v1/people/LL042/records", headers=learner_headers).json()[0]
    assert record["recorded_by"] == {"code": "LL042", "name": "Kim Lee"}
    assert record["quiz"] == {"version": 1, "score": 100, "pass_mark": 80}
    assert record["expires_on"] is None  # worked out from the refresher, never stored


def test_a_fail_is_kept_and_grants_nothing(client, manager_headers, learner_headers, kim):
    published(client, manager_headers)
    out = take(client, learner_headers, answers=[0, 2]).json()
    assert (out["score"], out["passed"]) == (50, False)
    assert induction(client, learner_headers)["status"] == "missing"
    assert client.get("/v1/people/LL042/records", headers=learner_headers).json() == []


def test_try_again_after_a_fail_and_every_attempt_is_kept(client, manager_headers,
                                                          learner_headers, kim):
    published(client, manager_headers)
    take(client, learner_headers, answers=[1, 0])
    take(client, learner_headers, answers=[0, 2])
    assert take(client, learner_headers).json()["passed"] is True
    attempts = client.get("/v1/people/LL042/attempts", headers=learner_headers).json()
    assert [(a["score"], a["passed"]) for a in attempts] == [(100, True), (50, False), (0, False)]
    assert attempts[0]["competency"] == {"key": "site-induction", "name": "Site induction",
                                         "kind": "module"}
    for key, n in (("site-induction", 3), ("first-aid", 0)):
        r = client.get("/v1/people/LL042/attempts", headers=learner_headers,
                       params={"competency": key})
        assert len(r.json()) == n
    assert induction(client, learner_headers)["status"] == "current"


@pytest.mark.parametrize("pass_mark, passed", [(67, False), (66, True)])
def test_the_score_is_rounded_down_and_the_pass_mark_is_the_least_that_passes(
        client, manager_headers, learner_headers, kim, pass_mark, passed):
    three = [*QUESTIONS, {"prompt": "Who signs you in?", "options": ["Security", "Nobody"],
                          "correct": 0}]
    published(client, manager_headers, questions=three, pass_mark=pass_mark)
    out = take(client, learner_headers, answers=[0, 1, 1]).json()
    assert (out["score"], out["passed"]) == (66, passed)


@pytest.mark.parametrize("answers, field, message", [
    ([0], "answers", "answer all 2 questions"),
    ([0, 1, 0], "answers", "answer all 2 questions"),
    ([0, 3], "answers.1", "choose one of the answers"),
    ([-1, 1], "answers.0", "choose one of the answers"),
])
def test_every_question_gets_one_of_its_answers(client, manager_headers, learner_headers, kim,
                                                answers, field, message):
    published(client, manager_headers)
    r = take(client, learner_headers, answers=answers)
    assert r.status_code == 422 and r.json()["errors"] == [{"field": field, "message": message}]
    assert client.get("/v1/people/LL042/attempts", headers=learner_headers).json() == []


def test_the_quiz_is_the_version_they_read(client, manager_headers, learner_headers, kim):
    published(client, manager_headers)
    published(client, manager_headers)
    r = take(client, learner_headers, version=1)
    assert r.status_code == 409 and r.json()["code"] == "new_version"
    assert take(client, learner_headers, version=2).json()["version"] == 2


def test_a_pass_starts_the_module_from_the_top_next_time(client, manager_headers,
                                                         learner_headers, kim):
    published(client, manager_headers)
    client.put(f"{INDUCTION}/progress", headers=learner_headers, json={"version": 1, "page": 5})
    take(client, learner_headers, answers=[1, 1])
    assert client.get(INDUCTION, headers=learner_headers).json()["resume_at"] == 5
    take(client, learner_headers)
    assert client.get(INDUCTION, headers=learner_headers).json()["resume_at"] == 0


def test_the_refresher_runs_it_out_and_taking_it_again_renews_it(client, manager_headers,
                                                                 learner_headers, kim, today):
    published(client, manager_headers)
    take(client, learner_headers)
    today.set(date(2028, 9, 20))
    assert induction(client, learner_headers)["status"] == "expiring"
    today.set(date(2028, 10, 13))
    assert induction(client, learner_headers)["status"] == "lapsed"
    take(client, learner_headers)
    item = induction(client, learner_headers)
    assert (item["status"], item["expires_on"]) == ("current", "2030-10-13")


def test_a_new_version_asks_nobody_to_take_it_again(client, manager_headers, learner_headers,
                                                    kim):
    published(client, manager_headers)
    take(client, learner_headers)
    published(client, manager_headers)
    assert induction(client, learner_headers)["status"] == "current"


def test_nobody_takes_it_for_someone_else(client, manager_headers, kim):
    published(client, manager_headers)
    r = client.post(ATTEMPTS, headers=manager_headers,
                    json={"version": 1, "answers": RIGHT, "person": "LL042"})
    assert r.status_code == 422


def test_attempts_are_seen_by_who_may_see_the_person(client, db, manager_headers,
                                                     learner_headers, supervisor_headers, kim):
    published(client, manager_headers)
    take(client, learner_headers, answers=[1, 1])
    seen = client.get("/v1/people/LL042/attempts", headers=supervisor_headers).json()
    assert [(a["score"], a["passed"]) for a in seen] == [(50, False)]
    make_person(db, "LL099", "Pat Other", pin="1357")
    pat = bearer(pin_login(client, "LL099", "1357")["token"])
    assert client.get("/v1/people/LL042/attempts", headers=pat).status_code == 404


def test_a_deactivated_module_is_not_taken(client, manager_headers, learner_headers, kim):
    published(client, manager_headers)
    client.post("/v1/competencies/site-induction/deactivate", headers=manager_headers)
    r = take(client, learner_headers)
    assert r.status_code == 409 and r.json()["code"] == "inactive"
```

**Step 2: Run it to see it fail**

Run: `cd api && .venv/bin/pytest tests/test_quiz.py -q`
Expected: FAIL: `17 failed`: `POST /v1/modules/site-induction/attempts` and `GET /v1/people/LL042/attempts` are `404 {"detail": "Not Found"}`, and nothing is granted (`assert 'missing' == 'current'`).

**Step 3: Minimal implementation**

Append to `api/lms/services/modules.py`:
```python
def score(correct: int, total: int) -> int:
    """Out of 100, rounded down: 2 of 3 is 66, never a pass mark of 67."""
    return correct * 100 // total
```

In `api/lms/api/routes/learning.py`, replace:
```python
from fastapi import APIRouter, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.dialects.postgresql import insert

from lms.api.deps import DB, Principal, require
from lms.api.errors import Conflict, FieldError, NotFound
from lms.api.routes.modules import PageOut, get_module, page_out
from lms.models import Competency, ModuleProgress, ModuleVersion
from lms.services import modules
```
with:
```python
from fastapi import APIRouter, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from lms.api.deps import DB, Principal, require
from lms.api.errors import Conflict, FieldError, NotFound
from lms.api.routes.modules import PageOut, get_module, page_out
from lms.api.routes.people import get_person
from lms.api.routes.records import one_at_a_time
from lms.api.schemas import CompetencyRef, competency_ref, normal_key
from lms.models import Competency, CompetencyRecord, ModuleProgress, ModuleVersion, QuizAttempt
from lms.services import clock, modules
```

Append to `api/lms/api/routes/learning.py`:
```python
class AttemptIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # the version they answered: if a newer one came out, they take that
    version: int
    # the answer chosen for each question, in order, counting from 0
    answers: list[int] = Field(max_length=50)


class AttemptOut(BaseModel):
    id: int
    competency: CompetencyRef
    version: int
    correct: int
    total: int
    # out of 100, rounded down
    score: int
    pass_mark: int
    passed: bool
    created_at: datetime


def attempt_out(a: QuizAttempt) -> AttemptOut:
    return AttemptOut(id=a.id, competency=competency_ref(a.competency),
                      version=a.module_version.version, correct=a.correct, total=a.total,
                      score=a.score, pass_mark=a.module_version.pass_mark, passed=a.passed,
                      created_at=a.created_at)


@router.post("/modules/{key}/attempts", status_code=201, response_model=AttemptOut)
def take_quiz(key: str, body: AttemptIn, db: DB, who: Principal = require("training:write")):
    """Your own go at the quiz, marked here, pass or fail, and kept for good.
    A pass is a grant from today, recorded as yours: the one thing anybody
    earns alone (rule 3). The refresher, if there is one, says when it runs
    out. After a fail, try again."""
    p = one_at_a_time(db, who.person.code)
    c = get_module(db, key)
    if not c.active:
        raise Conflict("inactive", f"{c.key} is deactivated")
    v = to_take(db, c)
    same_version(v, body.version)
    questions = v.questions
    if len(body.answers) != len(questions):
        raise FieldError("answers", f"answer all {len(questions)} questions")
    for i, (answer, q) in enumerate(zip(body.answers, questions)):
        if not 0 <= answer < len(q.options):
            raise FieldError(f"answers.{i}", "choose one of the answers")
    correct = sum(answer == q.correct for answer, q in zip(body.answers, questions))
    score = modules.score(correct, len(questions))
    attempt = QuizAttempt(person_id=p.id, competency=c, module_version=v, answers=body.answers,
                          correct=correct, total=len(questions), score=score,
                          passed=score >= v.pass_mark)
    db.add(attempt)
    db.flush()
    if attempt.passed:
        db.add(CompetencyRecord(person_id=p.id, competency=c, kind="granted",
                                granted_on=clock.today(), recorded_by=p, quiz_attempt=attempt))
        # done: next time, it starts from the top
        db.execute(delete(ModuleProgress).where(ModuleProgress.person_id == p.id,
                                                ModuleProgress.competency_id == c.id))
    db.commit()
    return JSONResponse(status_code=201, content=attempt_out(attempt).model_dump(mode="json"))


@router.get("/people/{code}/attempts", response_model=list[AttemptOut])
def list_attempts(code: str, db: DB, competency: str | None = None,
                  who: Principal = require("training:read")):
    """Every go at every quiz, pass or fail, newest first. Your own, your
    team's, or (a manager or admin) anyone's."""
    p = get_person(db, code)
    if not who.sees(p):
        raise NotFound(f"no person {code}")
    q = select(QuizAttempt).where(QuizAttempt.person_id == p.id)
    if competency:
        q = q.join(Competency).where(Competency.key == normal_key(competency))
    rows = db.execute(q.order_by(QuizAttempt.id.desc())).scalars().all()
    return [attempt_out(a) for a in rows]
```

In `api/lms/api/routes/records.py`, replace:
```python
class RecordOut(BaseModel):
```
with:
```python
class QuizOut(BaseModel):
    """A module passed: on which version, with what score, against what pass mark."""
    version: int
    score: int
    pass_mark: int


class RecordOut(BaseModel):
```

In `api/lms/api/routes/records.py`, replace:
```python
    # a ticket a manager verified: its submission's id
    ticket: int | None
    created_at: datetime
```
with:
```python
    # a ticket a manager verified: its submission's id
    ticket: int | None
    # a module passed in the learner app: the quiz that passed it
    quiz: QuizOut | None
    created_at: datetime
```

In `api/lms/api/routes/records.py`, replace:
```python
def record_out(r: CompetencyRecord) -> RecordOut:
    return RecordOut(id=r.id, competency=competency_ref(r.competency), kind=r.kind,
                     granted_on=r.granted_on, expires_on=r.expires_on, note=r.note,
                     recorded_by=person_ref(r.recorded_by),
                     policy_version=r.policy_version.version if r.policy_version else None,
                     signed_name=r.signed_name, signature=r.signature_upload_id,
                     ticket=r.ticket_submission_id, created_at=r.created_at)
```
with:
```python
def record_out(r: CompetencyRecord) -> RecordOut:
    a = r.quiz_attempt
    return RecordOut(id=r.id, competency=competency_ref(r.competency), kind=r.kind,
                     granted_on=r.granted_on, expires_on=r.expires_on, note=r.note,
                     recorded_by=person_ref(r.recorded_by),
                     policy_version=r.policy_version.version if r.policy_version else None,
                     signed_name=r.signed_name, signature=r.signature_upload_id,
                     ticket=r.ticket_submission_id,
                     quiz=QuizOut(version=a.module_version.version, score=a.score,
                                  pass_mark=a.module_version.pass_mark) if a else None,
                     created_at=r.created_at)
```

**Step 4: Run it, and the whole suite, to see them pass**

Run: `cd api && .venv/bin/pytest tests/test_quiz.py -q`
Expected: `17 passed`

Run: `cd api && .venv/bin/pytest -q`
Expected: `346 passed`

**Step 5: Commit**

```
git add api/lms/api/routes/learning.py api/lms/services/modules.py api/lms/api/routes/records.py api/tests/test_quiz.py
git commit -m "Mark a module's quiz on the server, keep every attempt, and make a pass the learner's own grant" \
  -m "The score is rounded down and a pass is at least the pass mark. The refresher says when a pass runs out; try again after a fail. The record says which version was passed, with what score."
```

---

### Task 7: Caddy names media-src, and CI checks the new triggers

**Files:**
- Modify: `deploy/Caddyfile`, `.github/workflows/ci.yml`

**Step 1: The check that fails**

```
cd "/Users/leightonlauton/Q7 Technology/Software/q7/simple-lms"
docker compose up -d --build db api caddy
curl -skI https://localhost:8643/learn/ | grep -i content-security-policy
```
Expected: `content-security-policy: default-src 'self'; img-src 'self' blob:; object-src 'none'; …`, with no `media-src` (with `LMS_HTTPS_PORT=8643` in `.env` for local work, as before). `default-src 'self'` already lets a same-origin `/v1/media/` link play; saying `media-src 'self'` keeps anyone tightening `default-src` from breaking the videos without noticing.

**Step 2: Implementation**

In `deploy/Caddyfile`, replace:
```text
	# Photos and signatures are fetched with the session's token and shown
	# from blob: URLs, so both apps allow blob: images and nothing else new.
```
with:
```text
	# Photos and signatures are fetched with the session's token and shown
	# from blob: URLs, so both apps allow blob: images. A module's pictures,
	# PDFs and videos open from /v1/media/ links the API signs, on this
	# origin: media-src 'self' says so, and videos stream with Range requests.
```

In `deploy/Caddyfile`, in both `Content-Security-Policy` headers (the learner app's and the desktop's), replace:
```text
default-src 'self'; img-src 'self' blob:; object-src 'none';
```
with:
```text
default-src 'self'; img-src 'self' blob:; media-src 'self'; object-src 'none';
```

In `.github/workflows/ci.yml`, replace:
```yaml
          # the append-only triggers and the ticket's decide-once one are there
          docker compose exec -T db psql -U lms -d lms -tAc \
            "select count(*) from pg_trigger where tgname like '%_append_only'" | grep -qx 4
          docker compose exec -T db psql -U lms -d lms -tAc \
            "select count(*) from pg_trigger where tgname = 'ticket_submission_decide_once'" | grep -qx 1
```
with:
```yaml
          # the append-only triggers, the ticket's decide-once one, and the
          # module's: published once, pages and questions changed only in a draft
          docker compose exec -T db psql -U lms -d lms -tAc \
            "select count(*) from pg_trigger where tgname like '%_append_only'" | grep -qx 5
          docker compose exec -T db psql -U lms -d lms -tAc \
            "select count(*) from pg_trigger where tgname = 'ticket_submission_decide_once'" | grep -qx 1
          docker compose exec -T db psql -U lms -d lms -tAc \
            "select count(*) from pg_trigger where tgname like '%_draft_only' or tgname = 'module_version_publish_once'" | grep -qx 3
```

**Step 3: Run the check to see it pass**

```
docker compose up -d --build db api caddy
docker compose restart caddy
curl -skI https://localhost:8643/learn/ | grep -i content-security-policy
curl -skI https://localhost:8643/ | grep -i content-security-policy
docker compose exec -T db psql -U lms -d lms -tAc "select count(*) from pg_trigger where tgname like '%_append_only'"
docker compose exec -T db psql -U lms -d lms -tAc "select count(*) from pg_trigger where tgname like '%_draft_only' or tgname = 'module_version_publish_once'"
```
Expected: both `content-security-policy: default-src 'self'; img-src 'self' blob:; media-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'`, then `5` and `3` (the API ran migration `0003` as it started).

**Step 4: Commit**

```
git add deploy/Caddyfile .github/workflows/ci.yml
git commit -m "Say media-src in both apps' CSP, and check the module triggers in CI"
```

---

### Task 8: `docs/api.md`

**Files:**
- Modify: `docs/api.md`

**Step 1: Write it**

In `docs/api.md`, replace:
````markdown
  The training record and the extras and waivers are append-only: the latest
  row for a person and competency is the one that counts.
- **Codes and keys:** a person's code is kept upper case (`ll042` finds
````
with:
````markdown
  The training record and the extras and waivers are append-only: the latest
  row for a person and competency is the one that counts. Every quiz attempt
  is kept, and a module version is frozen once it is published.
- **Codes and keys:** a person's code is kept upper case (`ll042` finds
````

In `docs/api.md`, replace:
````markdown
`training:write` is doing your own training: sending a file, signing a
policy, sending in a ticket. A session signed in with a **PIN** carries
`training:read` and `training:write` only, whoever it is: a PIN is short, so
````
with:
````markdown
`training:write` is doing your own training: sending a file, signing a
policy, sending in a ticket, reading a module and taking its quiz. A
session signed in with a **PIN** carries
`training:read` and `training:write` only, whoever it is: a PIN is short, so
````

In `docs/api.md`, replace:
````markdown
Every kind can still be recorded by hand. Policies are signed in the
learner app and tickets sent in from it (below); modules and practicals get
their own ways in with later build steps.

## Extras and waivers
````
with:
````markdown
Every kind can still be recorded by hand. Policies are signed in the
learner app, tickets sent in from it and modules taken in it (below);
practicals get their own way in with a later build step.

## Extras and waivers
````

In `docs/api.md`, replace:
````markdown
     "policy_version": null, "signed_name": null, "signature": null, "ticket": null,
     "created_at": "…" }]
  ```
````
with:
````markdown
     "policy_version": null, "signed_name": null, "signature": null, "ticket": null,
     "quiz": null, "created_at": "…" }]
  ```
````

In `docs/api.md`, replace:
````markdown
  `signature` (an upload id) are there when it was signed in the learner
  app; `ticket` is the ticket's id when a manager approved one.
- `POST /v1/people/{code}/records` (`records:write`) — `{ "competency",
````
with:
````markdown
  `signature` (an upload id) are there when it was signed in the learner
  app; `ticket` is the ticket's id when a manager approved one; `quiz` is
  `{ "version", "score", "pass_mark" }` when the person passed a module's
  quiz (recorded as theirs).
- `POST /v1/people/{code}/records` (`records:write`) — `{ "competency",
````

In `docs/api.md`, replace:
````markdown
## Files

Tickets' photos (or a PDF) and policy signatures. Sent before the ticket or
signature that names them; kept on the host under `LMS_UPLOAD_DIR`
(`/data/uploads`), named by a random id.

- `POST /v1/uploads?purpose=ticket|signature` (`training:write`) — the file
  as the request body (any `Content-Type`: what counts is its first bytes)
  → `201 { "id", "purpose", "content_type", "size_bytes", "created_at" }`.
  A ticket may be a JPEG, PNG or PDF of up to 20 MB; a signature a PNG of
  up to 1 MB. Anything else is `415 { "code": "unsupported_type" }`. Bigger
  than its purpose allows is `413 { "code": "too_large" }`: before the body
  is read when its `Content-Length` says so, and otherwise as soon as the
  body passes the limit (it is never read further). An unknown purpose is
  `422`, before any of the body is read.
- `GET /v1/uploads/{id}` — the file. Any signed-in session may ask (a PIN
````
with:
````markdown
## Files

Tickets' photos (or a PDF), policy signatures, and a module page's
picture, PDF or video. Sent before the ticket, signature or page that names
them; kept on the host under `LMS_UPLOAD_DIR` (`/data/uploads`), named by a
random id, and written to disk as they arrive (never held in memory whole).

- `POST /v1/uploads?purpose=…` — the file as the request body (any
  `Content-Type`: what counts is its first bytes) → `201 { "id", "purpose",
  "content_type", "size_bytes", "created_at" }`.

  | Purpose | Who (scope) | What it may be | Up to |
  | --- | --- | --- | --- |
  | `ticket` | `training:write` | JPEG, PNG or PDF | 20 MB |
  | `signature` | `training:write` | PNG | 1 MB |
  | `page-image` | `competencies:write` | JPEG or PNG | 20 MB |
  | `page-pdf` | `competencies:write` | PDF | 20 MB |
  | `page-video` | `competencies:write` | MP4 or WebM | 200 MB |

  Anything else is `415 { "code": "unsupported_type" }` (a QuickTime `.mov`
  or a Matroska `.mkv` too: most browsers won't play them, so convert to MP4
  first; videos play as uploaded, with no transcoding). Bigger than its
  purpose allows is `413 { "code": "too_large" }`: before the body is read
  when its `Content-Length` says so, and otherwise as soon as the body
  passes the limit (it is never read further). An unknown purpose is `422`,
  and a purpose the caller may not send `403`, before any of the body is
  read.
- `GET /v1/uploads/{id}` — the file. Any signed-in session may ask (a PIN
````

In `docs/api.md`, replace:
````markdown
each signature to one record and each photo to one ticket.

## Policies
````
with:
````markdown
each signature to one record and each photo to one ticket.

- `GET /v1/media/{id}?session=&expires=&sig=` — a module page's file, by
  the link the API puts in the page (`file.link`, below). No token: an
  `<img>`, a `<video>` or a new tab can't send one, and a token never goes
  in a URL. The link names one file and the session it was made for, and
  is signed with that session's secret; it lasts 6 hours or until the
  session ends (signed out, idle, or too old), whichever is first, and
  opening it counts as using the session. Ranges are honoured
  (`Accept-Ranges: bytes`, `206` with `Content-Range`, `416` past the end),
  so a phone can seek a video. Sent with the type its first bytes say,
  `Cache-Control: private, no-store`, `Content-Security-Policy: default-src
  'none'; sandbox`, `nosniff`, and `inline` (a picture or video) or
  `attachment` (a PDF). A wrong, expired or ended link is `404`, as is a
  link to anything that is not a page's file.

## Modules

A module is a competency of kind `module`: a version of pages (text, a
picture, a PDF, a video or a link), then a multiple-choice quiz with a pass
mark. One draft at a time is written and saved in full as often as needed,
then published, which freezes it: its pages, questions and pass mark never
change again (the database refuses), so an attempt is always marked
against what was asked. A change after that is a new version, started as a
copy of the last. People take the newest published version; a new version
asks nobody to take it again (passes so far still count).

Each version, as its editors see it:
```json
{ "id": 3, "version": 2, "pass_mark": 80, "published_at": null, "published_by": null,
  "pages": [
    { "kind": "text", "title": "Welcome", "body": "Sign in at the gatehouse.", "url": null, "file": null },
    { "kind": "video", "title": "Lifting safely", "body": null, "url": null,
      "file": { "id": "…", "content_type": "video/mp4", "size_bytes": 48211234,
                "link": "/v1/media/…?session=…&expires=…&sig=…" } },
    { "kind": "link", "title": "SafeWork", "body": null, "url": "https://www.safework.nsw.gov.au", "file": null }],
  "questions": [{ "prompt": "Where do you sign in?", "options": ["The gatehouse", "The canteen"], "correct": 0 }],
  "created_at": "…" }
```

- `GET /v1/modules/{key}/versions` (`competencies:read`) — newest first: the
  draft, if there is one, then those published. With the right answers.
- `POST /v1/modules/{key}/draft` (`competencies:write`) → `201`, the next
  version: a copy of the newest published one, or empty with a pass mark of
  80. One at a time (`409 { "code": "draft_exists" }`).
- `PUT /v1/modules/{key}/draft` (`competencies:write`) — the draft in full,
  replacing what was there: `{ "pass_mark": 1–100, "pages": [{ "kind",
  "title", "body"?, "file"?, "url"? }], "questions": [{ "prompt", "options",
  "correct" }] }` → `200`. A text page needs its `body` (plain text; line
  breaks are kept, nothing else is formatting); a picture, PDF or video page
  needs `file`, an upload of purpose `page-image`, `page-pdf` or
  `page-video`; a link page needs `url`, starting `https://` or `http://`.
  On the others `body` is an optional line or two under it. A question has
  2 to 6 answers, and `correct` (counting from 0) is one of them. Up to 100
  pages and 50 questions. Anything amiss is `422` on that field (e.g.
  `pages.2.file`). No draft is `404`.
- `POST /v1/modules/{key}/draft/publish` (`competencies:write`) → `200`,
  frozen, and the one people take from now. It needs a page and a question
  (`409 { "code": "incomplete" }`).
- `GET /v1/modules/{key}` (`training:read`) — the version to take now, as
  the learner sees it: `{ "key", "name", "version": { "id", "version",
  "pass_mark", "pages": [ … ], "questions": [{ "prompt", "options" }] },
  "resume_at" }`. Never which answer is right. `resume_at` is the page they
  left off at (counting from 0; one past the last page is the quiz), on any
  device; `0` for a version they haven't opened. `404` until a version is
  published.
- `PUT /v1/modules/{key}/progress` (`training:write`) — `{ "version",
  "page" }` → `204`: where the caller is now, theirs alone. Kept on the
  server, so nothing of theirs stays on a shared tablet. A page past the
  quiz is `422`.
- `POST /v1/modules/{key}/attempts` (`training:write`) — your own go at the
  quiz: `{ "version", "answers": [ … ] }`, one answer per question in order,
  counting from 0 → `201 { "id", "competency", "version", "correct",
  "total", "score", "pass_mark", "passed", "created_at" }`. Marked here:
  `score` is out of 100, rounded down, and a pass is a score of at least the
  pass mark. Every attempt is kept, pass or fail; try again as often as
  needed. A pass is a grant from today, recorded as the learner's own (the
  one thing anybody earns alone), and the competency's refresher, if any,
  says when it runs out; it also starts the module from the top next time.
  An answer missing or out of range is `422`; a deactivated module is
  `409 { "code": "inactive" }`.
- `GET /v1/people/{code}/attempts?competency=` (`training:read`; your own,
  your team's, or anyone's for a manager; anyone else is `404`) — every
  attempt, newest first, in the shape above.

`version` is the one the learner read: if a newer one was published
meanwhile, progress and attempts are `409 { "code": "new_version" }`, and
they start the new one. A key that is not a module is `404` on all of these;
a deactivated module gets no new version (`409 { "code": "inactive" }`).

## Policies
````

**Step 2: Check it against the app**

Run: `cd api && .venv/bin/python -c "from lms.api.app import app; print(sorted(p for p in app.openapi()['paths'] if p.startswith('/v1')))"`
Expected: every path in the list has its section in `docs/api.md`; the new ones are `/v1/media/{upload_id}`, `/v1/modules/{key}`, `/v1/modules/{key}/versions`, `/v1/modules/{key}/draft`, `/v1/modules/{key}/draft/publish`, `/v1/modules/{key}/progress`, `/v1/modules/{key}/attempts` and `/v1/people/{code}/attempts`.

**Step 3: Commit**

```
git add docs/api.md
git commit -m "Document modules, their files and the media links in docs/api.md"
```

---

### Task 9: The desktop sends a file as it is

**Files:**
- Modify: `apps/desktop/src/api/client.ts` (in full below), `apps/desktop/src/api/types.ts`
- Test: `apps/desktop/src/test/client.test.ts`

**Step 1: Write the failing test**

In `apps/desktop/src/test/client.test.ts`, replace:
```ts
  it("fetches a kept file with the token", async () => {
```
with:
```ts
  it("sends a module's file as it is, with its own type", async () => {
    client.token = "lms_s.abc";
    answers.push(json(201, { id: "u-1", purpose: "page-video", content_type: "video/mp4", size_bytes: 3 }));
    const video = new Blob([new Uint8Array([0, 0, 0])], { type: "video/mp4" });
    expect((await client.upload("page-video", video)).id).toBe("u-1");
    expect(calls[0].url).toBe("/v1/uploads?purpose=page-video");
    expect(calls[0].init.body).toBe(video);
    expect(new Headers(calls[0].init.headers).get("Content-Type")).toBe("video/mp4");
  });

  it("fetches a kept file with the token", async () => {
```

**Step 2: Run it to see it fail**

Run: `cd apps/desktop && npm test`
Expected: FAIL: `Tests  1 failed | 42 passed (43)`: `TypeError: client.upload is not a function`.

**Step 3: Minimal implementation**

Append to `apps/desktop/src/api/types.ts`:
```ts
export interface Upload { id: string; purpose: string; content_type: string; size_bytes: number; created_at: string }
```

`apps/desktop/src/api/client.ts`:
```ts
import type { Upload } from "./types";

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

  /** JSON, or a file (a Blob) sent as it is. */
  private async send(method: string, path: string, body?: unknown): Promise<Response> {
    const headers: Record<string, string> = { Accept: "application/json" };
    const file = body instanceof Blob ? body : null;
    if (body !== undefined) headers["Content-Type"] = file ? file.type || "application/octet-stream" : "application/json";
    const token = this.token;
    if (token) headers.Authorization = `Bearer ${token}`;
    let res: Response;
    try {
      res = await this.fetcher(path, { method, headers, body: body === undefined ? undefined : file ?? JSON.stringify(body) });
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

  /** A module page's picture, PDF or video, kept by the API before the
   * page that shows it is saved. What counts is its first bytes. */
  upload(purpose: "page-image" | "page-pdf" | "page-video", file: Blob) {
    return this.request<Upload>("POST", `/v1/uploads?purpose=${purpose}`, file);
  }

  /** A file kept by the API (a ticket's photo, a signature), fetched with the
   * session's token: an <img> can't send it. */
  async blob(path: string): Promise<Blob> {
    const res = await this.send("GET", path);
    if (!res.ok) throw new ApiError(res.status, await res.json().catch(() => null));
    return res.blob();
  }

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

**Step 4: Run it to see it pass**

Run: `cd apps/desktop && npm test && npm run typecheck`
Expected: `Tests  43 passed (43)`, and no type errors.

**Step 5: Commit**

```
git add apps/desktop/src/api/client.ts apps/desktop/src/api/types.ts apps/desktop/src/test/client.test.ts
git commit -m "Send a module page's file from the desktop as it is, with its own type"
```

---

### Task 10: Write a module's pages and quiz on the desktop, and publish it

**Files:**
- Create: `apps/desktop/src/pages/ModuleEditor.tsx`
- Modify: `apps/desktop/src/pages/Competencies.tsx`, `apps/desktop/src/api/types.ts`
- Test: `apps/desktop/src/test/harness.tsx`; create `apps/desktop/src/test/Modules.test.tsx`

**Step 1: Write the failing tests**

The harness reads every request body as JSON; a file is not. In `apps/desktop/src/test/harness.tsx`, replace:
```tsx
export interface Call { method: string; url: string; body: unknown }
```
with:
```tsx
export interface Call { method: string; url: string; body: unknown; contentType?: string }
```

In `apps/desktop/src/test/harness.tsx`, replace:
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

`apps/desktop/src/test/Modules.test.tsx`:
```tsx
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Competency, ModuleVersion } from "../api/types";
import { json, renderApp, stubApi, type Call } from "./harness";

const INDUCTION: Competency = { id: 1, key: "site-induction", name: "Site induction", kind: "module", refresher_months: 24, card_expires: true, active: true };
const MEL = { code: "MG001", name: "Mel Grant" };
const EMPTY: ModuleVersion = { id: 1, version: 1, pass_mark: 80, published_at: null, published_by: null, pages: [], questions: [], created_at: "2026-10-12T01:00:00Z" };
const V1: ModuleVersion = {
  ...EMPTY, published_at: "2026-10-12T02:00:00Z", published_by: MEL,
  pages: [
    { kind: "text", title: "Welcome", body: "Sign in at the gatehouse.", url: null, file: null },
    { kind: "video", title: "Lifting safely", body: null, url: null,
      file: { id: "v-1", content_type: "video/mp4", size_bytes: 12_300_000, link: "/v1/media/v-1?session=1&expires=1&sig=x" } },
    { kind: "link", title: "SafeWork", body: null, url: "https://www.safework.nsw.gov.au", file: null },
  ],
  questions: [{ prompt: "Where do you sign in?", options: ["The gatehouse", "The canteen"], correct: 0 }],
};

/** Competencies with the site induction, whose versions are `versions`;
 * starting a draft adds `draft`, and publishing publishes it. */
function stubModule(versions: ModuleVersion[], draft: ModuleVersion = EMPTY) {
  let list = versions;
  return stubApi((method, url, body) => {
    if (url === "/v1/competencies") return json(200, { items: [INDUCTION], total: 1 });
    if (url === "/v1/modules/site-induction/versions") return json(200, list);
    if (method === "POST" && url === "/v1/modules/site-induction/draft") { list = [draft, ...list]; return json(201, draft); }
    if (method === "PUT" && url === "/v1/modules/site-induction/draft") return json(200, { ...list[0], ...(body as object) });
    if (method === "POST" && url === "/v1/modules/site-induction/draft/publish") {
      list = [{ ...list[0], published_at: "2026-10-12T03:00:00Z", published_by: MEL }, ...list.slice(1)];
      return json(200, list[0]);
    }
    if (method === "POST" && url.startsWith("/v1/uploads?purpose=")) {
      return json(201, { id: "u-1", purpose: url.split("=")[1], content_type: "video/mp4", size_bytes: 4_200_000, created_at: "2026-10-12T01:00:00Z" });
    }
    return null;
  });
}

async function openInduction() {
  renderApp("/competencies");
  await userEvent.click(await screen.findByRole("button", { name: /Site induction/ }));
  return screen.findByRole("dialog", { name: "Site induction" });
}

const put = (calls: Call[]) => calls.find((c) => c.method === "PUT")?.body;

async function addPage(drawer: HTMLElement, kind: string) {
  await userEvent.selectOptions(within(drawer).getByLabelText("New page"), kind);
  await userEvent.click(within(drawer).getByRole("button", { name: "Add a page" }));
}

describe("a module's pages and quiz", () => {
  it("starts version 1 and saves its pages, its questions and its pass mark", async () => {
    const { calls } = stubModule([]);
    const drawer = await openInduction();
    expect(await within(drawer).findByText(/Nothing published yet/)).toBeInTheDocument();
    await userEvent.click(within(drawer).getByRole("button", { name: "Start version 1" }));
    expect(await within(drawer).findByText(/Version 1 is a draft/)).toBeInTheDocument();

    await addPage(drawer, "Text");
    const one = within(drawer).getByRole("group", { name: "Page 1" });
    await userEvent.type(within(one).getByLabelText("Title"), "Welcome");
    await userEvent.type(within(one).getByLabelText("Text"), "Sign in at the gatehouse.");
    await addPage(drawer, "Link");
    const two = within(drawer).getByRole("group", { name: "Page 2" });
    await userEvent.type(within(two).getByLabelText("Title"), "SafeWork");
    await userEvent.type(within(two).getByLabelText("Web address"), "https://www.safework.nsw.gov.au");

    await userEvent.click(within(drawer).getByRole("button", { name: "Add a question" }));
    const q = within(drawer).getByRole("group", { name: "Question 1" });
    await userEvent.type(within(q).getByLabelText("Question"), "Where do you sign in?");
    await userEvent.click(within(q).getByRole("button", { name: "Add an answer" }));
    await userEvent.type(within(q).getByLabelText("Answer 1"), "The canteen");
    await userEvent.type(within(q).getByLabelText("Answer 2"), "The gatehouse");
    await userEvent.type(within(q).getByLabelText("Answer 3"), "Anywhere");
    await userEvent.click(within(q).getByLabelText("Answer 2 is the right one"));
    await userEvent.click(within(q).getByRole("button", { name: "Remove answer 3" }));
    const mark = within(drawer).getByLabelText("Pass mark (%)");
    await userEvent.clear(mark);
    await userEvent.type(mark, "70");

    await userEvent.click(within(drawer).getByRole("button", { name: "Save draft" }));
    expect(await within(drawer).findByText("Draft saved.")).toBeInTheDocument();
    expect(put(calls)).toEqual({
      pass_mark: 70,
      pages: [
        { kind: "text", title: "Welcome", body: "Sign in at the gatehouse." },
        { kind: "link", title: "SafeWork", url: "https://www.safework.nsw.gov.au", body: null },
      ],
      questions: [{ prompt: "Where do you sign in?", options: ["The canteen", "The gatehouse"], correct: 1 }],
    });
  });

  it("sends a page's video as it is, then names it on the page", async () => {
    const { calls } = stubModule([EMPTY]);
    const drawer = await openInduction();
    await within(drawer).findByText(/Version 1 is a draft/);
    await addPage(drawer, "Video");
    const page = within(drawer).getByRole("group", { name: "Page 1" });
    await userEvent.type(within(page).getByLabelText("Title"), "Lifting safely");
    const video = new File([new Uint8Array([0, 0, 0, 0x18])], "lifting.mp4", { type: "video/mp4" });
    await userEvent.upload(within(page).getByLabelText("File"), video);
    expect(await within(page).findByText("MP4 · 4.2 MB")).toBeInTheDocument();
    const sent = calls.find((c) => c.url === "/v1/uploads?purpose=page-video")!;
    expect(sent.body).toBe(video);
    expect(sent.contentType).toBe("video/mp4");
    await userEvent.click(within(drawer).getByRole("button", { name: "Save draft" }));
    await waitFor(() => expect(put(calls)).toMatchObject({
      pages: [{ kind: "video", title: "Lifting safely", file: "u-1", body: null }] }));
  });

  it("won't send a video over 200 MB", async () => {
    const { calls } = stubModule([EMPTY]);
    const drawer = await openInduction();
    await within(drawer).findByText(/Version 1 is a draft/);
    await addPage(drawer, "Video");
    const huge = new File([new Uint8Array([0])], "long.mp4", { type: "video/mp4" });
    Object.defineProperty(huge, "size", { value: 200_000_001 });
    await userEvent.upload(within(drawer).getByLabelText("File"), huge);
    expect(await within(drawer).findByRole("alert")).toHaveTextContent("That file is too big: the most is 200 MB.");
    expect(calls.some((c) => c.url.startsWith("/v1/uploads"))).toBe(false);
  });

  it("moves and removes pages before it is saved", async () => {
    const { calls } = stubModule([{ ...V1, published_at: null, published_by: null, version: 2, id: 2 }]);
    const drawer = await openInduction();
    await within(drawer).findByText(/Version 2 is a draft/);
    await userEvent.click(within(drawer).getByRole("button", { name: "Move page 3 up" }));
    await userEvent.click(within(drawer).getByRole("button", { name: "Remove page 1" }));
    await userEvent.click(within(drawer).getByRole("button", { name: "Save draft" }));
    await waitFor(() => expect((put(calls) as { pages: { title: string }[] }).pages.map((p) => p.title))
      .toEqual(["SafeWork", "Lifting safely"]));
    expect((put(calls) as { pages: unknown[] }).pages[1]).toEqual({ kind: "video", title: "Lifting safely", file: "v-1", body: null });
  });

  it("asks before publishing, since publishing freezes it", async () => {
    const { calls } = stubModule([{ ...V1, published_at: null, published_by: null }]);
    const drawer = await openInduction();
    await userEvent.click(await within(drawer).findByRole("button", { name: "Publish version 1" }));
    expect(within(drawer).getByText("Publish version 1? Its pages and questions are frozen once it is, and everyone takes it from now.")).toBeInTheDocument();
    await userEvent.click(within(drawer).getByRole("button", { name: "Cancel" }));
    expect(calls.some((c) => c.method !== "GET")).toBe(false);

    await userEvent.click(within(drawer).getByRole("button", { name: "Publish version 1" }));
    await userEvent.click(within(drawer).getByRole("button", { name: "Publish" }));
    // saved as it is on the screen, then published
    await waitFor(() => expect(calls.filter((c) => c.method !== "GET").map((c) => `${c.method} ${c.url}`)).toEqual([
      "PUT /v1/modules/site-induction/draft", "POST /v1/modules/site-induction/draft/publish"]));
    expect(await within(drawer).findByText(/is the one people take/)).toHaveTextContent(
      "Version 1 is the one people take · published 12 Oct 2026 by Mel Grant · 3 pages · 1 question · pass mark 80%");
    expect(within(drawer).getByRole("button", { name: "Start version 2" })).toBeInTheDocument();
  });

  it("can't publish a draft without a page and a question", async () => {
    stubModule([EMPTY]);
    const drawer = await openInduction();
    expect(await within(drawer).findByRole("button", { name: "Publish version 1" })).toBeDisabled();
    expect(within(drawer).getByText("It needs a page and a question before it can be published.")).toBeInTheDocument();
  });

  it("shows the published version and starts the next as a copy of it", async () => {
    const copy = { ...V1, id: 2, version: 2, published_at: null, published_by: null };
    stubModule([V1], copy);
    const drawer = await openInduction();
    expect(await within(drawer).findByText(/People keep taking version 1 until you publish it/)).toBeInTheDocument();
    await userEvent.click(within(drawer).getByRole("button", { name: "Start version 2" }));
    expect(await within(drawer).findByText(/Version 2 is a draft/)).toBeInTheDocument();
    expect(within(within(drawer).getByRole("group", { name: "Page 1" })).getByLabelText("Title")).toHaveValue("Welcome");
    expect(within(within(drawer).getByRole("group", { name: "Page 2" })).getByText("MP4 · 12.3 MB")).toBeInTheDocument();
  });
});
```

**Step 2: Run them to see them fail**

Run: `cd apps/desktop && npm test`
Expected: FAIL: `Tests  7 failed | 43 passed (50)`: the drawer has no pages or quiz yet (`Unable to find an element with the text: /Nothing published yet/`, `Unable to find role="button" and name "Publish version 1"` and the like).

**Step 3: Minimal implementation**

Append to `apps/desktop/src/api/types.ts`:
```ts
export type PageKind = "text" | "image" | "pdf" | "video" | "link";

export interface ModulePage {
  kind: PageKind;
  title: string;
  body: string | null;
  url: string | null;
  /** a picture, PDF or video; `link` opens it without the token, for a few hours */
  file: { id: string; content_type: string; size_bytes: number; link: string } | null;
}

export interface Question { prompt: string; options: string[]; correct: number }

export interface ModuleVersion {
  id: number;
  version: number;
  pass_mark: number;
  /** null while it is a draft */
  published_at: string | null;
  published_by: PersonRef | null;
  pages: ModulePage[];
  questions: Question[];
  created_at: string;
}
```

`apps/desktop/src/pages/ModuleEditor.tsx`:
```tsx
import { useState, type FormEvent } from "react";
import { api } from "../api/client";
import type { Competency, ModulePage, ModuleVersion, PageKind, Question } from "../api/types";
import { formatDate } from "../lib/status";
import { useAction, useLoad } from "../lib/useLoad";
import { Problem } from "../ui/Drawer";

const KINDS: { kind: PageKind; label: string }[] = [
  { kind: "text", label: "Text" },
  { kind: "image", label: "Picture" },
  { kind: "pdf", label: "PDF" },
  { kind: "video", label: "Video" },
  { kind: "link", label: "Link" },
];
const kindLabel = (k: PageKind) => KINDS.find((x) => x.kind === k)?.label ?? k;

type FileKind = "image" | "pdf" | "video";
/** What each page's file may be, as the API has it: 200 MB for a video, 20 MB for the rest. */
const FILES: Record<FileKind, { accept: string; most: number }> = {
  image: { accept: "image/jpeg,image/png", most: 20_000_000 },
  pdf: { accept: "application/pdf", most: 20_000_000 },
  video: { accept: "video/mp4,video/webm", most: 200_000_000 },
};
const hasFile = (k: PageKind): k is FileKind => k in FILES;
const TYPES: Record<string, string> = {
  "image/jpeg": "JPEG", "image/png": "PNG", "application/pdf": "PDF", "video/mp4": "MP4", "video/webm": "WebM",
};
const megabytes = (bytes: number) => `${(bytes / 1_000_000).toFixed(1)} MB`;
const count = (n: number, one: string) => `${n} ${one}${n === 1 ? "" : "s"}`;

/** A page or question as it is being written; `uid` keeps it itself as it moves. */
interface PageFile { id: string; content_type: string; size_bytes: number; link: string | null }
interface Page { uid: number; kind: PageKind; title: string; body: string; url: string; file: PageFile | null }
interface Ask extends Question { uid: number }

let uids = 0;
const uid = () => ++uids;
const fromApi = (p: ModulePage): Page => ({ uid: uid(), kind: p.kind, title: p.title, body: p.body ?? "", url: p.url ?? "", file: p.file });

/** What the API takes for each kind of page, and nothing it doesn't. */
function toApi(p: Page) {
  const title = p.title.trim();
  if (p.kind === "text") return { kind: p.kind, title, body: p.body };
  const body = p.body.trim() || null;
  if (p.kind === "link") return { kind: p.kind, title, url: p.url.trim(), body };
  return { kind: p.kind, title, file: p.file?.id ?? null, body };
}

function move<T>(list: T[], from: number, to: number): T[] {
  const out = [...list];
  const [item] = out.splice(from, 1);
  out.splice(to, 0, item);
  return out;
}

/** A module's pages and quiz. The version people take is shown as it is;
 * the next is written as a draft, saved as often as needed, then published,
 * which freezes it. */
export function ModuleEditor({ module }: { module: Competency }) {
  const path = `/v1/modules/${encodeURIComponent(module.key)}`;
  const versions = useLoad(() => api.get<ModuleVersion[]>(`${path}/versions`), [path]);
  const action = useAction();
  const draft = versions.data?.find((v) => !v.published_at);
  const live = versions.data?.find((v) => v.published_at);
  const next = (versions.data?.[0]?.version ?? 0) + 1;

  async function start() {
    if (await action.run(() => api.post(`${path}/draft`))) versions.reload();
  }

  return (
    <section className="flex flex-col gap-3" aria-label="Pages and quiz">
      <div className="eyebrow">Pages and quiz</div>
      <Problem error={versions.error ?? action.error} />
      {versions.data && !live && !draft && <div className="small">Nothing published yet: nobody can take it until there is a version.</div>}
      {live && (
        <div className="card text-sm">
          <b>Version {live.version}</b> is the one people take · published {formatDate(live.published_at!.slice(0, 10))}
          {live.published_by && <> by {live.published_by.name}</>}
          {` · ${count(live.pages.length, "page")} · ${count(live.questions.length, "question")} · pass mark ${live.pass_mark}%`}
        </div>
      )}
      {versions.data && !draft && (module.active ? (
        <>
          {live && <div className="small">Version {next} starts as a copy of version {live.version}. People keep taking version {live.version} until you publish it, and passes so far still count.</div>}
          <button type="button" className="btn primary" disabled={action.busy} onClick={() => void start()}>Start version {next}</button>
        </>
      ) : <div className="small">Reactivate it to write a new version.</div>)}
      {draft && <Draft key={draft.id} draft={draft} path={path} active={module.active} onPublished={versions.reload} />}
    </section>
  );
}

function Draft({ draft, path, active, onPublished }: {
  draft: ModuleVersion; path: string; active: boolean; onPublished: () => void;
}) {
  const [passMark, setPassMark] = useState(String(draft.pass_mark));
  const [pages, setPages] = useState<Page[]>(() => draft.pages.map(fromApi));
  const [questions, setQuestions] = useState<Ask[]>(() => draft.questions.map((q) => ({ ...q, uid: uid() })));
  const [adding, setAdding] = useState<PageKind>("text");
  const [saved, setSaved] = useState(false);
  // publishing can't be undone: ask once
  const [confirming, setConfirming] = useState(false);
  const action = useAction();
  const ready = pages.length > 0 && questions.length > 0;

  const changed = () => { setSaved(false); setConfirming(false); };
  const setPage = (i: number, change: Partial<Page>) => { changed(); setPages((ps) => ps.map((p, j) => (j === i ? { ...p, ...change } : p))); };
  const setQuestion = (i: number, change: Partial<Ask>) => { changed(); setQuestions((qs) => qs.map((q, j) => (j === i ? { ...q, ...change } : q))); };
  const body = () => ({
    pass_mark: Number(passMark),
    pages: pages.map(toApi),
    questions: questions.map((q) => ({ prompt: q.prompt.trim(), options: q.options.map((o) => o.trim()), correct: q.correct })),
  });

  async function save(e: FormEvent) {
    e.preventDefault();
    if (await action.run(() => api.put(`${path}/draft`, body()))) setSaved(true);
  }

  async function publish() {
    if (!confirming) { setConfirming(true); return; }
    setConfirming(false);
    const done = await action.run(async () => {
      await api.put(`${path}/draft`, body());
      await api.post(`${path}/draft/publish`);
    });
    if (done) onPublished();
  }

  return (
    <form className="flex flex-col gap-3" onSubmit={save}>
      <div className="small">Version {draft.version} is a draft: change it as often as you like, then publish it. Once it is published its pages and questions are frozen, so every attempt stays what was asked.</div>
      <label className="label">Pass mark (%)
        <input className="field" style={{ width: 120 }} type="number" min={1} max={100} value={passMark}
               onChange={(e) => { changed(); setPassMark(e.target.value); }} required />
      </label>

      <div className="eyebrow">Pages</div>
      {pages.length === 0 && <div className="small">No pages yet. People read them one at a time, then take the quiz.</div>}
      {pages.map((p, i) => (
        <PageCard key={p.uid} page={p} n={i + 1} count={pages.length} onChange={(c) => setPage(i, c)}
                  onMove={(by) => { changed(); setPages((ps) => move(ps, i, i + by)); }}
                  onRemove={() => { changed(); setPages((ps) => ps.filter((_, j) => j !== i)); }} />
      ))}
      <div className="flex items-end gap-2">
        <label className="label">New page
          <select className="field" value={adding} onChange={(e) => setAdding(e.target.value as PageKind)}>
            {KINDS.map((k) => <option key={k.kind} value={k.kind}>{k.label}</option>)}
          </select>
        </label>
        <button type="button" className="btn" disabled={pages.length >= 100}
                onClick={() => { changed(); setPages((ps) => [...ps, { uid: uid(), kind: adding, title: "", body: "", url: "", file: null }]); }}>
          Add a page</button>
      </div>

      <div className="eyebrow">Quiz</div>
      {questions.length === 0 && <div className="small">No questions yet. Each has 2 to 6 answers, one of them right.</div>}
      {questions.map((q, i) => (
        <QuestionCard key={q.uid} question={q} n={i + 1} count={questions.length} onChange={(c) => setQuestion(i, c)}
                      onMove={(by) => { changed(); setQuestions((qs) => move(qs, i, i + by)); }}
                      onRemove={() => { changed(); setQuestions((qs) => qs.filter((_, j) => j !== i)); }} />
      ))}
      <button type="button" className="btn" disabled={questions.length >= 50}
              onClick={() => { changed(); setQuestions((qs) => [...qs, { uid: uid(), prompt: "", options: ["", ""], correct: 0 }]); }}>
        Add a question</button>

      <Problem error={action.error} />
      {saved && <div className="msg g" role="status">Draft saved.</div>}
      <button type="submit" className="btn" disabled={action.busy}>Save draft</button>
      {!active && <div className="small">Reactivate it to publish this version.</div>}
      {active && !ready && <div className="small">It needs a page and a question before it can be published.</div>}
      {active && (confirming ? (
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-sm"><b>Publish version {draft.version}? Its pages and questions are frozen once it is, and everyone takes it from now.</b></span>
          <button type="button" className="btn primary" disabled={action.busy} onClick={() => void publish()}>Publish</button>
          <button type="button" className="btn" autoFocus onClick={() => setConfirming(false)}>Cancel</button>
        </div>
      ) : (
        <button type="button" className="btn primary" disabled={action.busy || !ready} onClick={() => void publish()}>
          Publish version {draft.version}</button>
      ))}
    </form>
  );
}

/** Up, down and remove, for a page or a question. */
function Moves({ what, n, count, onMove, onRemove }: {
  what: string; n: number; count: number; onMove: (by: number) => void; onRemove: () => void;
}) {
  return (
    <span className="ml-auto flex gap-1">
      <button type="button" className="btn" disabled={n === 1} aria-label={`Move ${what} ${n} up`} onClick={() => onMove(-1)}>↑</button>
      <button type="button" className="btn" disabled={n === count} aria-label={`Move ${what} ${n} down`} onClick={() => onMove(1)}>↓</button>
      <button type="button" className="btn danger" aria-label={`Remove ${what} ${n}`} onClick={onRemove}>Remove</button>
    </span>
  );
}

function PageCard({ page, n, count, onChange, onMove, onRemove }: {
  page: Page; n: number; count: number; onChange: (c: Partial<Page>) => void; onMove: (by: number) => void; onRemove: () => void;
}) {
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function pick(file: File | undefined) {
    if (!file || !hasFile(page.kind)) return;
    setError(null);
    const { most } = FILES[page.kind];
    if (file.size > most) { setError(`That file is too big: the most is ${most / 1_000_000} MB.`); return; }
    setSending(true);
    try {
      const u = await api.upload(`page-${page.kind}`, file);
      onChange({ file: { id: u.id, content_type: u.content_type, size_bytes: u.size_bytes, link: null } });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSending(false);
    }
  }

  return (
    <fieldset className="card flex flex-col gap-2" aria-label={`Page ${n}`}>
      <div className="flex items-center gap-2">
        <b className="text-sm">Page {n} · {kindLabel(page.kind)}</b>
        <Moves what="page" n={n} count={count} onMove={onMove} onRemove={onRemove} />
      </div>
      <label className="label">Title
        <input className="field" value={page.title} maxLength={120} onChange={(e) => onChange({ title: e.target.value })} required />
      </label>
      {page.kind === "text" && (
        <label className="label">Text
          <textarea className="field" style={{ height: 140 }} value={page.body} maxLength={20000}
                    onChange={(e) => onChange({ body: e.target.value })} required />
        </label>
      )}
      {hasFile(page.kind) && (
        <>
          <label className="label">File
            <input type="file" accept={FILES[page.kind].accept} disabled={sending}
                   onChange={(e) => { void pick(e.target.files?.[0]); e.target.value = ""; }} />
          </label>
          {sending && <div className="small" role="status">Sending…</div>}
          {page.file && !sending && <div className="small">{TYPES[page.file.content_type] ?? page.file.content_type} · {megabytes(page.file.size_bytes)}</div>}
          {page.file?.link && page.kind === "image" && <img src={page.file.link} alt={page.title} width={240} style={{ borderRadius: 10 }} />}
          {page.file?.link && page.kind === "video" && <video src={page.file.link} controls preload="metadata" width={320} />}
          {page.file?.link && page.kind === "pdf" && <a href={page.file.link} target="_blank" rel="noopener noreferrer">Save the PDF</a>}
          {error && <div className="msg r" role="alert">{error}</div>}
        </>
      )}
      {page.kind === "link" && (
        <label className="label">Web address
          <input className="field" type="url" value={page.url} maxLength={2000} placeholder="https://…"
                 onChange={(e) => onChange({ url: e.target.value })} required />
        </label>
      )}
      {page.kind !== "text" && (
        <label className="label">Words under it (optional)
          <input className="field" value={page.body} maxLength={2000} onChange={(e) => onChange({ body: e.target.value })} />
        </label>
      )}
    </fieldset>
  );
}

function QuestionCard({ question: q, n, count, onChange, onMove, onRemove }: {
  question: Ask; n: number; count: number; onChange: (c: Partial<Ask>) => void; onMove: (by: number) => void; onRemove: () => void;
}) {
  function drop(j: number) {
    const correct = q.correct === j ? 0 : q.correct > j ? q.correct - 1 : q.correct;
    onChange({ options: q.options.filter((_, k) => k !== j), correct });
  }

  return (
    <fieldset className="card flex flex-col gap-2" aria-label={`Question ${n}`}>
      <div className="flex items-center gap-2">
        <b className="text-sm">Question {n}</b>
        <Moves what="question" n={n} count={count} onMove={onMove} onRemove={onRemove} />
      </div>
      <label className="label">Question
        <input className="field" value={q.prompt} maxLength={500} onChange={(e) => onChange({ prompt: e.target.value })} required />
      </label>
      <div className="small">Mark the right answer.</div>
      {q.options.map((o, j) => (
        <div key={j} className="flex items-center gap-2">
          <input type="radio" name={`right-${q.uid}`} checked={q.correct === j} onChange={() => onChange({ correct: j })}
                 aria-label={`Answer ${j + 1} is the right one`} />
          <input className="field" value={o} maxLength={200} aria-label={`Answer ${j + 1}`} required
                 onChange={(e) => onChange({ options: q.options.map((x, k) => (k === j ? e.target.value : x)) })} />
          {q.options.length > 2 && (
            <button type="button" className="btn" aria-label={`Remove answer ${j + 1}`} onClick={() => drop(j)}>✕</button>
          )}
        </div>
      ))}
      {q.options.length < 6 && (
        <button type="button" className="btn" onClick={() => onChange({ options: [...q.options, ""] })}>Add an answer</button>
      )}
    </fieldset>
  );
}
```

In `apps/desktop/src/pages/Competencies.tsx`, replace:
```tsx
import { Drawer, Problem } from "../ui/Drawer";
```
with:
```tsx
import { Drawer, Problem } from "../ui/Drawer";
import { ModuleEditor } from "./ModuleEditor";
```

In `apps/desktop/src/pages/Competencies.tsx`, replace:
```tsx
/** Competencies: in step 1 just what each is called, its kind and its refresher. */
```
with:
```tsx
/** Competencies: what each is called, its kind and its refresher; a
 * policy's versions, a ticket's card expiry, and a module's pages and quiz. */
```

In `apps/desktop/src/pages/Competencies.tsx`, replace:
```tsx
      {competency.kind === "policy" && <PolicyVersions policy={competency} />}
```
with:
```tsx
      {competency.kind === "policy" && <PolicyVersions policy={competency} />}
      {competency.kind === "module" && <ModuleEditor module={competency} />}
```

**Step 4: Run them to see them pass**

Run: `cd apps/desktop && npm test && npm run typecheck`
Expected: `Tests  50 passed (50)`, and no type errors.

**Step 5: Commit**

```
git add apps/desktop/src/pages/ModuleEditor.tsx apps/desktop/src/pages/Competencies.tsx apps/desktop/src/api/types.ts apps/desktop/src/test/harness.tsx apps/desktop/src/test/Modules.test.tsx
git commit -m "Write a module's pages and quiz in its drawer on Competencies, and ask once before publishing it" \
  -m "Add a page of each kind, move it up or down, take it out; send its file, checked for size first; mark each question's right answer; save the draft as often as needed. The version people take is shown as it is."
```

---

### Task 11: A module passed, in the history

**Files:**
- Modify: `apps/desktop/src/pages/HistoryDrawer.tsx`, `apps/desktop/src/api/types.ts`
- Test: `apps/desktop/src/test/Modules.test.tsx`

**Step 1: Write the failing test**

Append to `apps/desktop/src/test/Modules.test.tsx`:
```tsx
describe("a module passed", () => {
  it("shows in the history with its score, recorded as the learner's own", async () => {
    const matrix = {
      today: "2026-10-12", competencies: [{ key: "site-induction", name: "Site induction", kind: "module" }],
      people: [{ code: "LL042", name: "Kim Lee", roles: [], supervisor: null,
                 cells: { "site-induction": { status: "current", granted_on: "2026-10-12", expires_on: "2028-10-12" } } }],
    };
    const passed = {
      id: 9, competency: matrix.competencies[0], kind: "granted", granted_on: "2026-10-12", expires_on: null, note: null,
      recorded_by: { code: "LL042", name: "Kim Lee" }, policy_version: null, signed_name: null, signature: null,
      ticket: null, quiz: { version: 1, score: 100, pass_mark: 80 }, created_at: "2026-10-12T01:00:00Z",
    };
    stubApi((_m, url) => {
      if (url.startsWith("/v1/matrix")) return json(200, matrix);
      if (url === "/v1/roles") return json(200, { items: [], total: 0 });
      if (url.startsWith("/v1/people/LL042/records")) return json(200, [passed]);
      return null;
    });
    renderApp("/");
    await userEvent.click(await screen.findByRole("button", { name: /Kim Lee, Site induction/ }));
    const drawer = await screen.findByRole("dialog", { name: "Site induction" });
    expect(await within(drawer).findByText("Passed the quiz on version 1 with 100% (pass mark 80%)")).toBeInTheDocument();
    expect(within(drawer).getByText(/by Kim Lee/)).toBeInTheDocument();
  });
});
```

**Step 2: Run it to see it fail**

Run: `cd apps/desktop && npm test`
Expected: FAIL: `Tests  1 failed | 50 passed (51)`: `Unable to find an element with the text: Passed the quiz on version 1 with 100% (pass mark 80%)`.

**Step 3: Minimal implementation**

In `apps/desktop/src/api/types.ts`, replace:
```ts
  /** a ticket a manager checked: its submission's id */
  ticket: number | null;
  created_at: string;
}
```
with:
```ts
  /** a ticket a manager checked: its submission's id */
  ticket: number | null;
  /** a module passed in the learner app: the version, the score and the pass mark */
  quiz: { version: number; score: number; pass_mark: number } | null;
  created_at: string;
}
```

In `apps/desktop/src/pages/HistoryDrawer.tsx`, replace:
```tsx
            {r.signature && <Picture upload={r.signature} label={`${person.name}'s signature`} width={200} />}
```
with:
```tsx
            {r.signature && <Picture upload={r.signature} label={`${person.name}'s signature`} width={200} />}
            {r.quiz && (
              <div className="text-sm">Passed the quiz on version {r.quiz.version} with {r.quiz.score}% (pass mark {r.quiz.pass_mark}%)</div>
            )}
```

**Step 4: Run it to see it pass, and build**

Run: `cd apps/desktop && npm test && npm run build`
Expected: `Tests  51 passed (51)`, then `✓ built in …`.

**Step 5: Commit**

```
git add apps/desktop/src/pages/HistoryDrawer.tsx apps/desktop/src/api/types.ts apps/desktop/src/test/Modules.test.tsx
git commit -m "Show a module passed in the history: the version, the score and the pass mark"
```

---

### Task 12: Start the module from My training

**Files:**
- Modify: `apps/learner/src/lib/training.ts`, `apps/learner/src/api/client.ts`
- Test: `apps/learner/src/test/training.test.ts`, `apps/learner/src/test/client.test.ts`

**Step 1: Write the failing tests**

In `apps/learner/src/test/training.test.ts`, replace:
```ts
    expect(nextStep({ ...item("Site induction", "missing"), kind: "module" })).toBeNull();
  });
```
with:
```ts
    expect(nextStep({ ...item("Site induction", "current"), kind: "module" })).toBeNull();
  });

  it("offers a module that isn't current", () => {
    const module = { ...item("Site induction", "missing"), kind: "module" as const };
    expect(nextStep(module)).toEqual({ to: "/module/site-induction", label: "Start the module" });
    expect(nextStep({ ...module, status: "expiring" })).toEqual({ to: "/module/site-induction", label: "Start the module" });
    expect(nextStep({ ...module, status: "lapsed" })).toEqual({ to: "/module/site-induction", label: "Start the module" });
  });
```

In `apps/learner/src/test/client.test.ts`, replace:
```ts
    expect((seen[0].headers as Record<string, string>)["Content-Type"]).toBe("image/jpeg");
  });
});
```
with:
```ts
    expect((seen[0].headers as Record<string, string>)["Content-Type"]).toBe("image/jpeg");
  });

  it("puts JSON, as the progress through a module is kept", async () => {
    const seen: { url: string; init: RequestInit }[] = [];
    const client = new LearnerApi(async (url, init) => {
      seen.push({ url, init });
      return new Response(null, { status: 204 });
    });
    client.token = "lms_s.kim";
    await client.put("/v1/modules/site-induction/progress", { version: 1, page: 2 });
    expect(seen[0].init.method).toBe("PUT");
    expect(seen[0].init.body).toBe('{"version":1,"page":2}');
  });
});
```

**Step 2: Run them to see them fail**

Run: `cd apps/learner && npm test`
Expected: FAIL: `Tests  2 failed | 46 passed (48)`: `TypeError: client.put is not a function`, and `expected null to deeply equal { to: '/module/site-induction', …(1) }`.

**Step 3: Minimal implementation**

In `apps/learner/src/lib/training.ts`, replace:
```ts
/** What the learner can do about an item here: sign a policy that wants
 * their signature, or send in a ticket that is missing, running out or run
 * out. A ticket already sent in waits for a manager. */
export function nextStep(item: TrainingItem): Step {
  const key = encodeURIComponent(item.key);
  if (item.kind === "policy" && item.status !== "current") return { to: `/sign/${key}`, label: "Read and sign" };
```
with:
```ts
/** What the learner can do about an item here: do a module or sign a
 * policy that isn't current, or send in a ticket that is missing, running
 * out or run out. A ticket already sent in waits for a manager. */
export function nextStep(item: TrainingItem): Step {
  const key = encodeURIComponent(item.key);
  if (item.kind === "module" && item.status !== "current") return { to: `/module/${key}`, label: "Start the module" };
  if (item.kind === "policy" && item.status !== "current") return { to: `/sign/${key}`, label: "Read and sign" };
```

In `apps/learner/src/api/client.ts`, replace:
```ts
  post<T>(path: string, body: unknown = {}) { return this.request<T>("POST", path, body); }
```
with:
```ts
  post<T>(path: string, body: unknown = {}) { return this.request<T>("POST", path, body); }
  put<T>(path: string, body: unknown) { return this.request<T>("PUT", path, body); }
```

**Step 4: Run them to see them pass**

Run: `cd apps/learner && npm test && npm run typecheck`
Expected: `Tests  48 passed (48)`, and no type errors. (The link goes nowhere yet: the next task adds the player.)

**Step 5: Commit**

```
git add apps/learner/src/lib/training.ts apps/learner/src/api/client.ts apps/learner/src/test/training.test.ts apps/learner/src/test/client.test.ts
git commit -m "Offer Start the module in My training for a module that isn't current"
```

---

### Task 13: The module player: one page at a time, the video, then the quiz

**Files:**
- Create: `apps/learner/src/pages/ModulePlayer.tsx`
- Modify: `apps/learner/src/App.tsx`, `apps/learner/src/auth/Session.tsx`, `apps/learner/src/api/types.ts`, `apps/learner/src/index.css`
- Test: `apps/learner/src/test/modules.test.tsx`

**Step 1: Write the failing tests**

`apps/learner/src/test/modules.test.tsx`:
```tsx
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Module } from "../api/types";
import { json, KIM, renderApp, stubApi, type Call } from "./harness";

const TRAINING = {
  person: { code: "LL042", name: "Kim Lee" }, today: "2026-10-12",
  items: [{ key: "site-induction", name: "Site induction", kind: "module", status: "missing", granted_on: null,
            expires_on: null, card_expires: true, waiting: false }],
};
const link = (id: string) => `/v1/media/${id}?session=1&expires=1&sig=x`;
const INDUCTION: Module = {
  key: "site-induction", name: "Site induction", resume_at: 0,
  version: {
    id: 1, version: 1, pass_mark: 80,
    pages: [
      { kind: "text", title: "Welcome", body: "Sign in at the gatehouse.", url: null, file: null },
      { kind: "image", title: "The yard", body: "Walk inside the green lines.", url: null,
        file: { id: "i-1", content_type: "image/jpeg", size_bytes: 1000, link: link("i-1") } },
      { kind: "pdf", title: "Site map", body: null, url: null,
        file: { id: "p-1", content_type: "application/pdf", size_bytes: 1000, link: link("p-1") } },
      { kind: "video", title: "Lifting safely", body: null, url: null,
        file: { id: "v-1", content_type: "video/mp4", size_bytes: 1000, link: link("v-1") } },
      { kind: "link", title: "SafeWork", body: "Read about lifting.", url: "https://www.safework.nsw.gov.au", file: null },
    ],
    questions: [
      { prompt: "Where do you sign in?", options: ["The gatehouse", "The canteen"] },
      { prompt: "What do you wear on the floor?", options: ["Thongs", "Your PPE", "Anything"] },
    ],
  },
};
const PASS = { id: 1, version: 1, correct: 2, total: 2, score: 100, pass_mark: 80, passed: true, created_at: "2026-10-12T01:00:00Z" };
const FAIL = { ...PASS, correct: 1, score: 50, passed: false };

/** The site induction, opened at `resume_at`; `attempts` answer the quiz in turn. */
function stubModule(module: Module = INDUCTION, attempts: Response[] = [json(201, PASS)]) {
  return stubApi((method, url) => {
    if (url === "/v1/people/LL042/training") return json(200, TRAINING);
    if (url === "/v1/modules/site-induction") return json(200, module);
    if (method === "PUT" && url === "/v1/modules/site-induction/progress") return new Response(null, { status: 204 });
    if (method === "POST" && url === "/v1/modules/site-induction/attempts") return attempts.shift() ?? null;
    if (url === "/v1/auth/me") return json(200, KIM);
    return null;
  });
}

const places = (calls: Call[]) => calls.filter((c) => c.method === "PUT").map((c) => c.body);

describe("the module player", () => {
  it("opens from My training and shows one page at a time, keeping the place", async () => {
    const calls = stubModule();
    renderApp(KIM);
    await userEvent.click(await screen.findByRole("link", { name: "Start the module: Site induction" }));
    expect(await screen.findByRole("article", { name: "Welcome" })).toHaveTextContent("Sign in at the gatehouse.");
    expect(screen.getByLabelText("Page 1 of 5")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Back" })).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByRole("img", { name: "The yard" })).toHaveAttribute("src", link("i-1"));
    expect(screen.getByText("Walk inside the green lines.")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByRole("link", { name: /Open the PDF/ })).toHaveAttribute("href", link("p-1"));

    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByLabelText("Lifting safely")).toHaveAttribute("src", link("v-1"));

    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    const safework = screen.getByRole("link", { name: /Open SafeWork/ });
    expect(safework).toHaveAttribute("href", "https://www.safework.nsw.gov.au");
    expect(safework).toHaveAttribute("target", "_blank");
    expect(safework.getAttribute("rel")).toContain("noopener");

    await userEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(screen.getByLabelText("Page 4 of 5")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    await userEvent.click(screen.getByRole("button", { name: "Start the quiz" }));
    expect(await screen.findByRole("heading", { name: "The quiz" })).toBeInTheDocument();
    await waitFor(() => expect(places(calls)).toEqual([1, 2, 3, 4, 3, 4, 5].map((page) => ({ version: 1, page }))));
  });

  it("carries on where they left off", async () => {
    stubModule({ ...INDUCTION, resume_at: 3 });
    renderApp(KIM, Date.now(), "/module/site-induction");
    expect(await screen.findByLabelText("Page 4 of 5")).toBeInTheDocument();
    expect(screen.getByLabelText("Lifting safely")).toBeInTheDocument();
  });

  it("keeps a playing video's learner signed in, however long nobody taps", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const calls = stubModule({ ...INDUCTION, resume_at: 3 });
      renderApp(KIM, Date.now(), "/module/site-induction");
      const video = await screen.findByLabelText("Lifting safely");
      // twenty minutes of a video playing, and not a tap
      for (let minute = 0; minute < 20; minute++) {
        await act(async () => { vi.advanceTimersByTime(60_000); });
        fireEvent.timeUpdate(video);
      }
      expect(screen.getByLabelText("Lifting safely")).toBeInTheDocument();
      expect(calls.filter((c) => c.url === "/v1/auth/me").length).toBeGreaterThanOrEqual(15);
      // once it stops, the idle time runs again
      await act(async () => { vi.advanceTimersByTime(16 * 60_000); });
      expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("says so when a video can't be played", async () => {
    stubModule({ ...INDUCTION, resume_at: 3 });
    renderApp(KIM, Date.now(), "/module/site-induction");
    fireEvent.error(await screen.findByLabelText("Lifting safely"));
    expect(screen.getByRole("alert")).toHaveTextContent("The video couldn't be played.");
  });

  it("says when there is nothing to take yet", async () => {
    stubApi((_m, url) => url === "/v1/modules/site-induction"
      ? json(404, { detail: "Site induction has nothing to take yet" }) : null);
    renderApp(KIM, Date.now(), "/module/site-induction");
    expect(await screen.findByRole("alert")).toHaveTextContent("There's nothing to do here yet. Ask your manager.");
  });

  it("hands in the answers and says Ding! on a pass", async () => {
    const calls = stubModule({ ...INDUCTION, resume_at: 5 });
    renderApp(KIM, Date.now(), "/module/site-induction");
    const handIn = await screen.findByRole("button", { name: "Hand it in" });
    expect(screen.getByText("2 questions. You need 80% to pass, and you can try again.")).toBeInTheDocument();
    await userEvent.click(within(screen.getByRole("group", { name: "1. Where do you sign in?" })).getByLabelText("The gatehouse"));
    expect(handIn).toBeDisabled();
    await userEvent.click(within(screen.getByRole("group", { name: "2. What do you wear on the floor?" })).getByLabelText("Your PPE"));
    await userEvent.click(handIn);
    expect(await screen.findByRole("status", { name: "Passed" })).toHaveTextContent("Ding!You passed Site induction with 100%.");
    expect(calls.find((c) => c.url === "/v1/modules/site-induction/attempts")?.body).toEqual({ version: 1, answers: [0, 1] });
  });

  it("gives the score after a fail, then another go", async () => {
    const calls = stubModule({ ...INDUCTION, resume_at: 5 }, [json(201, FAIL), json(201, PASS)]);
    renderApp(KIM, Date.now(), "/module/site-induction");
    await userEvent.click(await screen.findByLabelText("The canteen"));
    await userEvent.click(screen.getByLabelText("Your PPE"));
    await userEvent.click(screen.getByRole("button", { name: "Hand it in" }));
    expect(await screen.findByRole("status", { name: "Not passed" })).toHaveTextContent(
      "50%Not this time: you need 80% to pass. Read it again, or have another go.");
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    // a fresh start: nothing chosen
    expect(screen.getByLabelText("The canteen")).not.toBeChecked();
    expect(screen.getByRole("button", { name: "Hand it in" })).toBeDisabled();
    await userEvent.click(screen.getByLabelText("The gatehouse"));
    await userEvent.click(screen.getByLabelText("Your PPE"));
    await userEvent.click(screen.getByRole("button", { name: "Hand it in" }));
    expect(await screen.findByRole("status", { name: "Passed" })).toBeInTheDocument();
    expect(calls.filter((c) => c.method === "POST").map((c) => c.body)).toEqual([
      { version: 1, answers: [1, 1] }, { version: 1, answers: [0, 1] }]);
  });

  it("goes back to the pages after a fail", async () => {
    stubModule({ ...INDUCTION, resume_at: 5 }, [json(201, FAIL)]);
    renderApp(KIM, Date.now(), "/module/site-induction");
    await userEvent.click(await screen.findByLabelText("The canteen"));
    await userEvent.click(screen.getByLabelText("Thongs"));
    await userEvent.click(screen.getByRole("button", { name: "Hand it in" }));
    await userEvent.click(await screen.findByRole("button", { name: "Read it again" }));
    expect(screen.getByLabelText("Page 1 of 5")).toBeInTheDocument();
  });

  it("starts the new version when one came out while they read", async () => {
    let module: Module = { ...INDUCTION, resume_at: 5 };
    stubApi((method, url) => {
      if (url === "/v1/modules/site-induction") return json(200, module);
      if (method === "POST" && url === "/v1/modules/site-induction/attempts") {
        module = { ...INDUCTION, version: { ...INDUCTION.version, id: 2, version: 2 } };
        return json(409, { detail: "version 2 is the one to take now: start it", code: "new_version" });
      }
      return null;
    });
    renderApp(KIM, Date.now(), "/module/site-induction");
    await userEvent.click(await screen.findByLabelText("The gatehouse"));
    await userEvent.click(screen.getByLabelText("Your PPE"));
    await userEvent.click(screen.getByRole("button", { name: "Hand it in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The module has changed: start the new version.");
    expect(await screen.findByLabelText("Page 1 of 5")).toBeInTheDocument();
  });
});
```

**Step 2: Run them to see them fail**

Run: `cd apps/learner && npm test`
Expected: FAIL: `Tests  9 failed | 48 passed (57)`: there is no `/module/…` yet, so the app goes back to My training (`Unable to find role="article" and name "Welcome"`, `Unable to find a label with the text of: Page 4 of 5` and the like).

**Step 3: Minimal implementation**

Append to `apps/learner/src/api/types.ts`:
```ts
export interface ModulePage {
  kind: "text" | "image" | "pdf" | "video" | "link";
  title: string;
  body: string | null;
  url: string | null;
  /** a picture, PDF or video: `link` opens it without the token, for a few hours */
  file: { id: string; content_type: string; size_bytes: number; link: string } | null;
}

export interface Module {
  key: string;
  name: string;
  version: {
    id: number;
    version: number;
    pass_mark: number;
    pages: ModulePage[];
    /** never which answer is right: the API marks it */
    questions: { prompt: string; options: string[] }[];
  };
  /** the page to open at; one past the last is the quiz */
  resume_at: number;
}

export interface Attempt {
  id: number;
  version: number;
  correct: number;
  total: number;
  score: number;
  pass_mark: number;
  passed: boolean;
  created_at: string;
}
```

A playing video is someone being there, though nobody taps. In `apps/learner/src/auth/Session.tsx`, replace:
```tsx
  signInWithPassword: (email: string, password: string) => Promise<void>;
  signOut: () => void;
}
```
with:
```tsx
  signInWithPassword: (email: string, password: string) => Promise<void>;
  signOut: () => void;
  /** Someone is here though nobody taps: a video playing. Counts as a tap,
   * here and at the API, unless the idle time has passed already. */
  stillHere: () => void;
}
```

In `apps/learner/src/auth/Session.tsx`, replace:
```tsx
  // the last tap in any tab on this device: they share one session
  const activeAt = useRef(session?.active_at ?? 0);
```
with:
```tsx
  // the last tap in any tab on this device: they share one session
  const activeAt = useRef(session?.active_at ?? 0);
  // what a tap does, for stillHere()
  const tapped = useRef<() => void>(() => undefined);
```

In `apps/learner/src/auth/Session.tsx`, replace:
```tsx
    const every = setInterval(check, CHECK_EVERY_MS);
```
with:
```tsx
    tapped.current = touch;
    const every = setInterval(check, CHECK_EVERY_MS);
```

In `apps/learner/src/auth/Session.tsx`, replace:
```tsx
    return () => {
      window.removeEventListener("storage", elsewhere);
```
with:
```tsx
    return () => {
      tapped.current = () => undefined;
      window.removeEventListener("storage", elsewhere);
```

In `apps/learner/src/auth/Session.tsx`, replace:
```tsx
  const value = useMemo<State>(() => ({ person: session?.person ?? null, signInWithPin, signInWithPassword, signOut }),
                               [session, signInWithPin, signInWithPassword, signOut]);
```
with:
```tsx
  const stillHere = useCallback(() => {
    tapped.current();
    // the API counts idle time too: any request tells it someone is here
    if (api.token) void api.get("/v1/auth/me").catch(() => undefined);
  }, []);

  const value = useMemo<State>(() => ({ person: session?.person ?? null, signInWithPin, signInWithPassword, signOut, stillHere }),
                               [session, signInWithPin, signInWithPassword, signOut, stillHere]);
```

`apps/learner/src/pages/ModulePlayer.tsx`:
```tsx
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { api, ApiError } from "../api/client";
import type { Attempt, Module, ModulePage } from "../api/types";
import { useSession } from "../auth/Session";
import { Back, plain } from "../ui";

const CHANGED = "The module has changed: start the new version.";
// how often a playing video says someone is still here
const STILL_HERE_MS = 60_000;

/** A module, one page at a time, then the quiz. Where the learner is goes
 * to the API as they go, so they carry on where they left off, on this
 * device or another; nothing of theirs is kept on a shared tablet. */
export function ModulePlayer() {
  const { key = "" } = useParams();
  const [module, setModule] = useState<Module | null>(null);
  const [at, setAt] = useState(0);
  const [trouble, setTrouble] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const top = useRef<HTMLHeadingElement>(null);
  const path = `/v1/modules/${encodeURIComponent(key)}`;

  const load = useCallback(async () => {
    setTrouble(null);
    try {
      const m = await api.get<Module>(path);
      setModule(m);
      setAt(m.resume_at);
    } catch (e) {
      setTrouble(e instanceof ApiError && e.status === 404 ? "There's nothing to do here yet. Ask your manager." : plain(e));
    }
  }, [path]);

  useEffect(() => { void load(); }, [load]);

  /** A newer version came out while they read: it starts from the top. */
  const changed = useCallback(async () => {
    setNotice(CHANGED);
    await load();
  }, [load]);

  /** Go to a page (one past the last is the quiz) and keep the place. A
   * place that doesn't save only means opening a page earlier next time. */
  function go(page: number) {
    if (!module) return;
    setNotice(null);
    setAt(page);
    // a long page was scrolled down: the next one starts at its top
    top.current?.scrollIntoView?.({ block: "start" });
    api.put(`${path}/progress`, { version: module.version.version, page })
      .catch((e) => { if (e instanceof ApiError && e.code === "new_version") void changed(); });
  }

  const pages = module?.version.pages ?? [];
  return (
    <main className="screen">
      <Back />
      {trouble && <div className="msg r" role="alert">{trouble}</div>}
      {!module && !trouble && <div aria-live="polite" style={{ color: "var(--color-muted)" }}>Loading…</div>}
      {module && (
        <>
          <h1 ref={top} style={{ margin: 0, fontSize: 26, fontWeight: 800 }}>{module.name}</h1>
          {notice && <div className="msg r" role="alert">{notice}</div>}
          {at < pages.length ? (
            <PageView key={at} page={pages[at]} n={at + 1} count={pages.length}
                      onBack={() => go(at - 1)} onNext={() => go(at + 1)} />
          ) : (
            <Quiz key={module.version.id} module={module} path={path} onChanged={changed}
                  onBack={() => go(pages.length - 1)} onReadAgain={() => go(0)} />
          )}
        </>
      )}
    </main>
  );
}

function PageView({ page, n, count, onBack, onNext }: {
  page: ModulePage; n: number; count: number; onBack: () => void; onNext: () => void;
}) {
  return (
    <>
      <div className="steps" aria-label={`Page ${n} of ${count}`}>
        <span>Page {n} of {count}</span>
        <span className="bar"><span style={{ width: `${(n / (count + 1)) * 100}%` }} /></span>
      </div>
      <h2 className="pagetitle">{page.title}</h2>
      {page.kind === "text" && <article className="policy" aria-label={page.title}>{page.body}</article>}
      {page.kind === "image" && page.file && <img className="pageimg" src={page.file.link} alt={page.title} />}
      {page.kind === "video" && page.file && <Video link={page.file.link} title={page.title} />}
      {page.kind === "pdf" && page.file && (
        <a className="big ghost as-button" href={page.file.link} target="_blank" rel="noopener noreferrer">
          Open the PDF<span className="sr-only"> (opens on its own)</span></a>
      )}
      {page.kind === "link" && page.url && (
        <a className="big ghost as-button" href={page.url} target="_blank" rel="noopener noreferrer">
          Open {page.title}<span className="sr-only"> (opens in a new tab)</span></a>
      )}
      {page.kind !== "text" && page.body && <p className="caption">{page.body}</p>}
      <div className="pair">
        {n > 1 && <button type="button" className="big ghost" onClick={onBack}>Back</button>}
        <button type="button" className="big primary" onClick={onNext}>{n === count ? "Start the quiz" : "Next"}</button>
      </div>
    </>
  );
}

/** Played as it was uploaded; the phone seeks it with Range requests. While
 * it plays, nobody taps, so it tells the session someone is still here. */
function Video({ link, title }: { link: string; title: string }) {
  const { stillHere } = useSession();
  const last = useRef(Date.now());
  const [failed, setFailed] = useState(false);

  function playing() {
    if (Date.now() - last.current < STILL_HERE_MS) return;
    last.current = Date.now();
    stillHere();
  }

  if (failed) return <div className="msg r" role="alert">The video couldn't be played. Go back to My training and open the module again.</div>;
  return <video className="pagevideo" src={link} controls playsInline preload="metadata" aria-label={title}
                onTimeUpdate={playing} onError={() => setFailed(true)} />;
}

function Quiz({ module, path, onChanged, onBack, onReadAgain }: {
  module: Module; path: string; onChanged: () => Promise<void>; onBack: () => void; onReadAgain: () => void;
}) {
  const { questions, pass_mark: passMark, version } = module.version;
  const none = () => questions.map(() => null as number | null);
  const [answers, setAnswers] = useState(none);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<Attempt | null>(null);

  async function handIn(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      setResult(await api.post<Attempt>(`${path}/attempts`, { version, answers }));
    } catch (err) {
      if (err instanceof ApiError && err.code === "new_version") await onChanged();
      else setError(plain(err));
    } finally {
      setBusy(false);
    }
  }

  if (result?.passed) {
    return (
      <>
        <section className="ding" role="status" aria-label="Passed">
          <b>Ding!</b>
          <span>You passed {module.name} with {result.score}%.</span>
        </section>
        <Link to="/" className="big primary as-button">Back to My training</Link>
      </>
    );
  }
  if (result) {
    return (
      <>
        <section className="miss" role="status" aria-label="Not passed">
          <b>{result.score}%</b>
          <span>Not this time: you need {result.pass_mark}% to pass. Read it again, or have another go.</span>
        </section>
        <button type="button" className="big primary" onClick={() => { setResult(null); setAnswers(none()); }}>Try again</button>
        <button type="button" className="big ghost" onClick={onReadAgain}>Read it again</button>
      </>
    );
  }
  return (
    <form onSubmit={handIn} style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <h2 className="pagetitle">The quiz</h2>
      <div className="small" style={{ color: "var(--color-muted)" }}>
        {questions.length} {questions.length === 1 ? "question" : "questions"}. You need {passMark}% to pass, and you can try again.</div>
      {questions.map((q, i) => (
        <fieldset key={i} className="question">
          <legend>{i + 1}. {q.prompt}</legend>
          {q.options.map((o, j) => (
            <label key={j} className="choice">
              <input type="radio" name={`question-${i}`} checked={answers[i] === j}
                     onChange={() => setAnswers((a) => a.map((x, k) => (k === i ? j : x)))} />
              {o}
            </label>
          ))}
        </fieldset>
      ))}
      {error && <div className="msg r" role="alert">{error}</div>}
      <button type="submit" className="big primary" disabled={busy || answers.some((a) => a === null)}>Hand it in</button>
      <button type="button" className="link" onClick={onBack}>Back to the pages</button>
    </form>
  );
}
```

In `apps/learner/src/App.tsx`, replace:
```tsx
import { AddTicket } from "./pages/AddTicket";
```
with:
```tsx
import { AddTicket } from "./pages/AddTicket";
import { ModulePlayer } from "./pages/ModulePlayer";
```

In `apps/learner/src/App.tsx`, replace:
```tsx
        <Route path="/ticket/:key" element={<AddTicket />} />
```
with:
```tsx
        <Route path="/ticket/:key" element={<AddTicket />} />
        <Route path="/module/:key" element={<ModulePlayer />} />
```

In `apps/learner/src/index.css`, replace:
```css
  .ding b { font-size: 32px; font-weight: 800; }
```
with:
```css
  .ding b { font-size: 32px; font-weight: 800; }
  .miss { background: var(--color-amber-bg); color: var(--color-amber-ink); border-radius: 18px; padding: 24px 16px; display: flex; flex-direction: column; gap: 6px; text-align: center; }
  .miss b { font-size: 32px; font-weight: 800; }
  .big.ghost { background: #fff; color: var(--color-blue-dark); border: 2px solid var(--color-line-2); }
  .pair { display: flex; gap: 12px; }
  .steps { display: flex; flex-direction: column; gap: 6px; font-size: 13px; font-weight: 800; color: var(--color-muted); }
  .steps .bar { height: 8px; border-radius: 999px; background: var(--color-line); overflow: hidden; }
  .steps .bar span { display: block; height: 100%; background: var(--color-blue); }
  .pagetitle { margin: 0; font-size: 20px; font-weight: 800; }
  .pageimg, .pagevideo { width: 100%; border-radius: 16px; display: block; }
  .pagevideo { background: #000; }
  .caption { margin: 0; font-size: 15px; color: var(--color-ink-2); }
  .question { border: 1px solid var(--color-line); border-radius: 16px; background: #fff; padding: 14px 16px; margin: 0; display: flex; flex-direction: column; gap: 8px; }
  .question legend { font-size: 16px; font-weight: 800; padding: 0 4px; }
  .choice { display: flex; align-items: center; gap: 12px; min-height: 48px; padding: 0 12px; border-radius: 12px; border: 1px solid var(--color-line-2); font-size: 16px; cursor: pointer; }
  .choice input { width: 22px; height: 22px; flex: none; }
```

**Step 4: Run them to see them pass, and build**

Run: `cd apps/learner && npm test && npm run build`
Expected: `Tests  57 passed (57)`, then `✓ built in …`.

**Step 5: Commit**

```
git add apps/learner/src/pages/ModulePlayer.tsx apps/learner/src/App.tsx apps/learner/src/auth/Session.tsx apps/learner/src/api/types.ts apps/learner/src/index.css apps/learner/src/test/modules.test.tsx
git commit -m "Play a module in the learner app: one page at a time, the video, then the quiz" \
  -m "The place goes to the API as they go. A pass says Ding! with the score; a fail gives the score and the pass mark, and another go. A playing video counts as someone being there."
```

---

### Task 14: The README and CLAUDE.md

**Files:**
- Modify: `README.md`, `CLAUDE.md`

**Step 1: Write it**

In `README.md`, replace:
````markdown
beside Simple WMS, Simple TMS and Platen and works without any of them.

Status: **build step 2, policies and tickets, is done.** People with a
code and PIN or an email and password, roles and the competencies each
requires, extras and waivers, completions recorded by hand on the desktop,
the matrix (with a CSV export), and a learner app that shows each person's
training. People sign policies and send in their tickets from the learner
app; a manager checks each ticket in the desktop's Inbox; the worker emails
reminders and a Monday digest. Modules, practicals, Entra sign-in and the
outward links come with the next steps in
`docs/plans/2026-10-12-simple-lms-design.md`.
````
with:
````markdown
beside Simple WMS, Simple TMS and Platen and works without any of them.

Status: **build step 3, modules, is done.** People with a code and PIN
or an email and password, roles and the competencies each requires, extras
and waivers, completions recorded by hand on the desktop, the matrix (with a
CSV export), and a learner app that shows each person's training. People
take online modules (pages, then a quiz), sign policies and send in their
tickets from the learner app; a manager checks each ticket in the desktop's
Inbox; the worker emails reminders and a Monday digest. Practicals, Entra
sign-in and the outward links come with the next steps in
`docs/plans/2026-10-12-simple-lms-design.md`.
````

In `README.md`, replace:
````markdown
asked to sign now. Each signature goes on one record only.

**Tickets.** A competency of kind *Ticket or licence* says whether its card
````
with:
````markdown
asked to sign now. Each signature goes on one record only.

**Modules.** Add a competency of kind *Online module* (with a refresher,
say 24 months, if it should be taken again) and open it under
**Competencies**. Start version 1 and add its pages: text, a picture (JPEG
or PNG), a PDF, a video (MP4 or WebM, up to 200 MB, played as uploaded: an
iPhone's `.mov` needs converting to MP4 first) or a link, which opens in a
new tab. Move them up and down or take them out, write the quiz (2 to 6
answers a question, one of them right) and the pass mark, and save the
draft as often as you like. Publishing asks once, then freezes that
version: its pages and questions never change, so every attempt stays
what was asked. To change it, start the next version, a copy of the last;
people keep taking the old one until you publish it, and their passes
still count. In the learner app a person reads one page at a time (where
they are is kept by Simple LMS, so they can carry on from any device), then
takes the quiz: a pass says Ding! and counts as current until the
refresher runs out; a fail gives the score and another go. Every attempt
is kept.

**Tickets.** A competency of kind *Ticket or licence* says whether its card
````

In `README.md`, replace:
````markdown
`deploy/Caddyfile`, `docker compose restart caddy` picks it up. Back up
the `uploads` volume (tickets' photos and policy signatures) along with the
database: the records name the files in it.

On a machine that already runs Simple WMS or Simple TMS, their Caddy has
````
with:
````markdown
`deploy/Caddyfile`, `docker compose restart caddy` picks it up. Back up
the `uploads` volume (tickets' photos, policy signatures and modules'
pictures, PDFs and videos) along with the database: the records and pages
name the files in it. A module's files open by links Simple LMS signs for
each session, so a session's token never goes in a URL.

On a machine that already runs Simple WMS or Simple TMS, their Caddy has
````

In `README.md`, replace:
````markdown
| See their own training | ✓ | ✓ | ✓ | ✓ |
| Sign a policy, send in their own ticket | ✓ | ✓ | ✓ | ✓ |
| See the matrix | | own team | everyone | everyone |
| Add and change people, roles, competencies, extras and waivers | | | ✓ | ✓ |
| Record or revoke a completion (never their own) | | | ✓ | ✓ |
````
with:
````markdown
| See their own training | ✓ | ✓ | ✓ | ✓ |
| Take a module, sign a policy, send in their own ticket | ✓ | ✓ | ✓ | ✓ |
| See the matrix | | own team | everyone | everyone |
| Add and change people, roles, competencies, extras and waivers | | | ✓ | ✓ |
| Write and publish a module's pages and quiz | | | ✓ | ✓ |
| Record or revoke a completion (never their own) | | | ✓ | ✓ |
````

In `CLAUDE.md`, replace:
````markdown
   `competency_record`, `quiz_attempt` or `signoff` row (nor a
   `person_override` or `policy_version`; a `ticket_submission` is decided
   once and never deleted). A mistake is corrected by a new row (`revoked`,
   with a note). People are deactivated, never deleted.
````
with:
````markdown
   `competency_record`, `quiz_attempt` or `signoff` row (nor a
   `person_override`, `policy_version` or `upload`; a `ticket_submission` is
   decided once and never deleted; a `module_version` is frozen once
   published, and its `module_page` and `quiz_question` rows change only
   while it is a draft). A mistake is corrected by a new row (`revoked`,
   with a note). People are deactivated, never deleted.
````

In `CLAUDE.md`, replace:
````markdown
  that counts.
- Sister apps: nothing in Simple WMS or Simple TMS changes for Simple LMS. It
````
with:
````markdown
  that counts.
- Files: written to disk as they arrive, checked by their first bytes, and
  served only through the API. A module's files open by `/v1/media/` links
  signed for one session; never put a session token in a URL.
- Sister apps: nothing in Simple WMS or Simple TMS changes for Simple LMS. It
````

**Step 2: Commit**

```
git add README.md CLAUDE.md
git commit -m "Describe modules in the README, and their frozen versions and media links in CLAUDE.md"
```

---

### Task 15: Every suite, and a clean Compose start

**Step 1: Every suite**

```
(cd api && .venv/bin/pytest -q)
(cd apps/desktop && npm test && npm run typecheck && npm run build)
(cd apps/learner && npm test && npm run typecheck && npm run build)
```
Expected: `346 passed`; `Tests  51 passed (51)` and a build; `Tests  57 passed (57)` and a build.

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
Expected: `{"status":"ok"}`; `api running`, `caddy running`, `db running`, `worker running`; the worker's `worker started` line; and `0003`. Fix anything that is not, then commit the fix with a message that says what it fixes.

---

### Task 16: Manual walkthrough: a module built, failed, passed, refreshed

With the stack from Task 15 (and `LMS_HTTPS_PORT=8643` in `.env`), the first admin made with `docker compose exec api lms create-user --code AD001 --name "…" --email …`, and on the phone the learner app at `https://<this machine's address>:8643/learn/` (accept the self-signed certificate). Have ready: a photo (JPEG or PNG), a PDF, a short MP4 of a few MB (record one on a phone; an iPhone's `.mov` needs converting first, e.g. `ffmpeg -i in.mov -c:v libx264 -c:a aac -movflags +faststart lifting.mp4`), and a `.mov` to see it refused.

**Step 1: Build it.** On the desktop as the admin: add **Site induction** (kind *Online module*, refresher 24 months), a role **Picker** requiring it, and a learner Kim (`LL042`, PIN `2468`, the role). The matrix shows Kim red. Open Site induction under **Competencies**: "Nothing published yet". **Start version 1**. Add a *Text* page ("Welcome", a few lines with a line break), a *Picture* page (the photo), a *PDF* page, a *Video* page (the MP4: it shows "MP4 · … MB" when it has gone), and a *Link* page ("SafeWork", `https://www.safework.nsw.gov.au`). Try the `.mov` on the video page (pick it with *All files*): "a page-video file must be one of: MP4, WEBM". Move the link page above the video and back. Add two questions with three answers each, mark the right ones, set the pass mark to 80, **Save draft**: "Draft saved."

**Step 2: Publish it.** **Publish version 1**: it asks "Publish version 1? Its pages and questions are frozen once it is, and everyone takes it from now." **Publish**. The drawer now says "Version 1 is the one people take · published … by … · 5 pages · 2 questions · pass mark 80%", with **Start version 2**.

**Step 3: Kim plays it on the phone.** Sign in as `LL042` / `2468`: Site induction is under Overdue with **Start the module**. Page 1 of 5 shows the text with its line break kept; Next shows the picture; the PDF opens (or saves) on its own; the video plays inline, and dragging along its bar seeks straight to the middle without waiting for the rest to download (the API answers each jump with a `206`: `docker compose logs api | grep media` shows them). The link page opens SafeWork in a new tab, and the learner app's tab is still there. Leave on page 4: go back to My training and open the module again: it opens at page 4 of 5. Sign in on another browser as Kim: page 4 there too.

**Step 4: Fail, then pass.** **Start the quiz**: Hand it in stays greyed out until both have an answer. Answer one wrong: "50% · Not this time: you need 80% to pass." **Read it again** goes to page 1; Next through to the quiz, answer both right: "Ding! You passed Site induction with 100%." My training has it under Done ("good until" two years on), and on the desktop Kim's cell is green; its history says "Passed the quiz on version 1 with 100% (pass mark 80%)", by Kim Lee. `docker compose exec -T db psql -U lms -d lms -c "select score, passed from quiz_attempt order by id"` shows both attempts, `50 f` and `100 t`.

**Step 5: Frozen.** `docker compose exec -T db psql -U lms -d lms -c "update quiz_question set correct = 1"` is refused: "quiz_question belongs to a published module version: start a new version". On the desktop, **Start version 2**: it starts as a copy; change a question's wording, **Publish version 2**. Kim's cell stays green (a new version asks nobody to take it again), and her attempts still say version 1 with its own pass mark.

**Step 6: The refresher.** As the admin, open Kim's Site induction cell and record a completion by hand dated two weeks short of 24 months ago (as a manager would for a module done on paper; the latest record is the one that counts): the cell turns amber, good for two more weeks, and Kim's My training has it under Due soon with **Start the module** again. Record one dated 25 months ago: red, under Overdue. Kim takes the module again and passes: green, good until 24 months from today. `docker compose exec worker lms daily-job --on <the day 30 days before a last good day>` queues its 30-day reminder as for any competency (if Kim has an email).

**Step 7: Links end with the session.** On the desktop, open Site induction and **Start version 3**: the copy's video page shows the video. Right-click it, **Copy video address** (it is a `/v1/media/…` link with no token in it), and open it in a new tab: it plays. Sign out of the desktop and open the address again: `{"detail":"no file …"}`. On the phone, a PIN session left idle for 15 minutes ends, and its links with it; while a video plays it does not.
