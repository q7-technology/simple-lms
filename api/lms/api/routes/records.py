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
from lms.models import Competency, CompetencyRecord, Signoff
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


class QuizOut(BaseModel):
    """A module passed: on which version, with what score, against what pass mark."""
    version: int
    score: int
    pass_mark: int


class SignoffOut(BaseModel):
    """A practical signed off on the phone: the checklist version, what was
    ticked, the note and photo, and both signatures (GET /v1/uploads/{id}).
    The supervisor is the record's recorded_by. When the learner's PIN was
    last set, and by whom, as it was then: unknown for one set before PIN
    changes were kept."""
    version: int
    ticked: list[str]
    note: str | None
    photo: uuid.UUID | None
    supervisor_signature: uuid.UUID
    learner_signature: uuid.UUID
    learner_pin_set_at: datetime | None
    learner_pin_set_by: PersonRef | None


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
                      learner_signature=s.learner_signature_upload_id,
                      learner_pin_set_at=s.learner_pin_set_at,
                      learner_pin_set_by=person_ref(s.learner_pin_set_by)
                      if s.learner_pin_set_by else None)


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
                     signoff=signoff_out(r.signoff) if r.signoff else None,
                     created_at=r.created_at)


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
