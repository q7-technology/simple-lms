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
    """The checklist to tick now. A deactivated practical is signed off by
    nobody: only its editors still see it."""
    c = get_practical(db, key)
    if not c.active and not who.has_scope("competencies:write"):
        raise Conflict("inactive", f"{c.name} isn't in use any more")
    return PracticalOut(key=c.key, name=c.name, version=checklist_out(to_tick(db, c)))
