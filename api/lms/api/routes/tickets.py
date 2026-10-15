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
from lms.services import clock, events, uploads

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
    if front.id == getattr(back, "id", None):
        raise FieldError("back", "the back needs its own photo")
    if uploads.on_a_ticket(db, front.id):
        raise FieldError("front", "this photo was sent in already: take a new one")
    if back is not None and uploads.on_a_ticket(db, back.id):
        raise FieldError("back", "this photo was sent in already: take a new one")
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
    # deactivated while it waited: a grant by hand is refused too, so send it back
    if not t.competency.active:
        raise Conflict("inactive", f"{t.competency.key} is deactivated: send it back")
    today = clock.today()
    if t.expires_on is not None and t.expires_on <= today:
        raise Conflict("card_ran_out", "this card ran out while it waited: send it back and ask "
                                       "for the new one")
    r = CompetencyRecord(person_id=t.person_id, competency_id=t.competency_id, kind="granted",
                         granted_on=today, expires_on=t.expires_on,
                         note=f"Ticket {t.number}, checked", recorded_by=who.person,
                         ticket_submission_id=t.id)
    db.add(r)
    events.granted(db, r)
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
