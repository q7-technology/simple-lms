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
