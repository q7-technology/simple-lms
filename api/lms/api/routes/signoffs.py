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
    if practicals.set_their_pin(db, who.person, p):
        raise Conflict("you_set_their_pin", f"You set {p.name}'s PIN this week: ask another "
                                            "supervisor or manager to sign them off")
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
    pin = practicals.last_pin_change(db, p)
    s = Signoff(person_id=p.id, competency=c, practical_version_id=v.id,
                supervisor_id=who.person.id, note=body.note or None,
                photo_upload_id=photo.id if photo else None,
                supervisor_signature_upload_id=theirs.id,
                learner_signature_upload_id=learners.id,
                learner_pin_set_at=pin.created_at if pin else None,
                learner_pin_set_by_id=pin.changed_by_id if pin else None)
    db.add(s)
    db.flush()
    db.add_all([SignoffItem(signoff_id=s.id, practical_item_id=i, practical_version_id=v.id)
                for i in body.ticked])
    r = CompetencyRecord(person_id=p.id, competency=c, kind="granted", granted_on=clock.today(),
                         recorded_by=who.person, signoff=s)
    db.add(r)
    db.commit()
    return JSONResponse(status_code=201, content=record_out(r).model_dump(mode="json"))
