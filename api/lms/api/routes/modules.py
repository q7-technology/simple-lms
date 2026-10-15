"""Modules, as their editors see them: versions of pages and a quiz with a
pass mark. A draft is written and saved in full as often as needed, then
published, which freezes it: what someone answered is always what they
were asked (rule 1). A change after that is a new version, started as a
copy of the last."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Literal
from urllib.parse import urlsplit

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
    # the `saved_at` the editor loaded: a save since then is refused, not undone
    based_on: datetime | None = None


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


class AnsweredQuestionOut(QuestionOut):
    # which answer is right, counting from 0: only for those who write it
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
    # changed by every save: send it back as `based_on`
    saved_at: datetime


class AnsweredVersionOut(VersionOut):
    questions: list[AnsweredQuestionOut]


def page_out(p: ModulePage, session: Session) -> PageOut:
    file = None
    if p.upload is not None:
        file = FileOut(id=p.upload.id, content_type=p.upload.content_type,
                       size_bytes=p.upload.size_bytes, link=media.link(session, p.upload.id))
    return PageOut(kind=p.kind, title=p.title, body=p.body, url=p.url, file=file)


def version_out(v: ModuleVersion, session: Session) -> AnsweredVersionOut:
    """The editor's view, with the right answers."""
    return AnsweredVersionOut(
        id=v.id, version=v.version, pass_mark=v.pass_mark,
        published_at=v.published_at, published_by=person_ref(v.published_by),
        pages=[page_out(p, session) for p in v.pages],
        questions=[AnsweredQuestionOut(prompt=q.prompt, options=q.options, correct=q.correct)
                   for q in v.questions],
        created_at=v.created_at, saved_at=v.saved_at)


def unanswered(v: AnsweredVersionOut) -> VersionOut:
    """The same without the right answers, for someone who may yet sit it."""
    return VersionOut.model_validate(v.model_dump(exclude={"questions": {"__all__": {"correct"}}}))


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


def _web_address(url: str | None) -> bool:
    """An http(s) address with a site in it, and no spaces or control
    characters: `https://` alone goes nowhere."""
    if not url or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in url):
        return False
    parts = urlsplit(url)
    return parts.scheme.lower() in ("http", "https") and bool(parts.hostname)


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
        if not _web_address(p.url):
            raise FieldError(f"{at}.url", "a link is a web address starting with https://")
    elif p.url is not None:
        raise FieldError(f"{at}.url", "only a link page has a web address")
    return ModulePage(position=i, kind=p.kind, title=p.title, body=p.body or None,
                      upload_id=p.file, url=p.url)


@router.get("/modules/{key}/versions",
            response_model=list[AnsweredVersionOut] | list[VersionOut])
def list_versions(key: str, db: DB, who: Principal = require("competencies:read")):
    """Newest first: a draft (if there is one), then what has been published.
    The right answers only for its editors: a supervisor may have to sit it."""
    c = get_module(db, key)
    rows = db.execute(select(ModuleVersion).where(ModuleVersion.competency_id == c.id)
                      .order_by(ModuleVersion.version.desc())).scalars().all()
    out = [version_out(v, who.session) for v in rows]
    if who.has_scope("competencies:write"):
        return out
    return [unanswered(v) for v in out]


@router.post("/modules/{key}/draft", status_code=201, response_model=AnsweredVersionOut)
def start_draft(key: str, db: DB, who: Principal = require("competencies:write")):
    """The next version, a copy of the newest published one (or empty)."""
    c = get_module(db, key)
    # one at a time per module, so two at once don't both start one, and
    # still active once it's ours: deactivating waits for us, or we for it
    db.refresh(c, with_for_update=True)
    _active(c)
    existing = modules.draft(db, c)
    if existing is not None:
        raise Conflict("draft_exists", f"version {existing.version} is being written already")
    v = modules.start_draft(db, c)
    db.commit()
    out = version_out(v, who.session)
    return JSONResponse(status_code=201, content=out.model_dump(mode="json"))


@router.put("/modules/{key}/draft", response_model=AnsweredVersionOut)
def save_draft(key: str, body: DraftIn, db: DB, who: Principal = require("competencies:write")):
    """The draft in full: its pass mark, its pages and its questions, in
    order. Whatever was there before is replaced, unless someone else saved
    it since the editor loaded it (`based_on`)."""
    c = get_module(db, key)
    v = _draft(db, c)
    if body.based_on is not None and body.based_on != v.saved_at:
        raise Conflict("changed", "the draft was saved by someone else since: reload it")
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
    v.saved_at = datetime.now(UTC)
    db.commit()
    db.expire(v, ["pages", "questions"])
    return version_out(v, who.session)


@router.post("/modules/{key}/draft/publish", response_model=AnsweredVersionOut)
def publish(key: str, db: DB, who: Principal = require("competencies:write")):
    """Frozen from now on, and the one people take. Their passes so far
    still count: a new version doesn't ask anyone to take it again."""
    c = get_module(db, key)
    # checked once the module is locked, so one deactivated meanwhile isn't
    # published: deactivating waits for us, or we for it
    db.refresh(c, with_for_update=True)
    _active(c)
    v = _draft(db, c)
    if not v.pages or not v.questions:
        raise Conflict("incomplete", "a module needs at least one page and one question")
    v.published_at = datetime.now(UTC)
    v.published_by = who.person
    db.commit()
    return version_out(v, who.session)
