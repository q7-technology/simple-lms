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
from lms.api.errors import Conflict, Forbidden, NotFound
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
    if not who.sees(p):
        raise NotFound(f"no person {code}")
    rows = [o for o in latest_overrides(db, p.id) if o.kind != "clear"]
    return [override_out(o) for o in sorted(rows, key=lambda o: o.competency.name)]


@router.post("/people/{code}/overrides", status_code=201, response_model=OverrideOut)
def add_override(code: str, body: OverrideIn, db: DB, who: Principal = require("people:write")):
    p = get_person(db, code)
    # a waiver of your own does what a grant of your own would (rule 3), admins included
    if p.id == who.person.id:
        raise Forbidden("nobody changes what is asked of them: ask another manager", "own_override")
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
