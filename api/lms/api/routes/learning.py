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
