"""Printing a certificate of completion or a skills card: queued here,
sent to Platen by the worker. Asked for from the desktop, never printed by
itself: nobody wants a page for every grant."""
from __future__ import annotations

import uuid

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from lms.api.deps import DB, Principal, require
from lms.api.errors import Conflict, NotFound
from lms.api.routes.people import get_person
from lms.api.routes.records import latest_record
from lms.models import CompetencyRecord, Person
from lms.services import clock, printing, settings

router = APIRouter(tags=["printing"])


class PrintOut(BaseModel):
    job_id: uuid.UUID
    template: str
    printer: str


def _set_up() -> None:
    if not printing.set_up():
        raise Conflict("printing_not_set_up",
                       "Printing is not set up: give Platen's address in Settings, under "
                       "Printing.")


def _person(db, code: str, who: Principal) -> Person:
    p = get_person(db, code)
    if not who.sees(p):
        raise NotFound(f"no person {code}")
    return p


def _queued(job: dict) -> JSONResponse:
    out = PrintOut(job_id=job["job_id"], template=job["template"], printer=job["printer"])
    return JSONResponse(status_code=202, content=out.model_dump(mode="json"))


@router.post("/people/{code}/records/{record_id}/certificate", status_code=202,
             response_model=PrintOut)
def print_certificate(code: str, record_id: int, db: DB,
                      who: Principal = require("printing:write")):
    """A certificate for the completion that counts now: not one that has
    been recorded again since, nor revoked."""
    _set_up()
    p = _person(db, code, who)
    r = db.get(CompetencyRecord, record_id)
    if r is None or r.person_id != p.id:
        raise NotFound(f"no record {record_id} for {p.code}")
    latest = latest_record(db, p.id, r.competency_id)
    if r.kind != "granted" or latest.id != r.id:
        raise Conflict("not_current", "only the completion that counts now gets a certificate")
    job = printing.queue(db, printing.CERTIFICATE, printing.CERTIFICATE_VERSION,
                         settings.current().certificate_printer,
                         {"type": "record", "ref": str(r.id)},
                         printing.certificate_data(r, p, clock.today()))
    db.commit()
    return _queued(job)


@router.post("/people/{code}/skills-card", status_code=202, response_model=PrintOut)
def print_skills_card(code: str, db: DB, who: Principal = require("printing:write")):
    """A card listing what they are current for today."""
    _set_up()
    p = _person(db, code, who)
    data = printing.skills_card_data(db, p, clock.today())
    if not data["lines"]:
        raise Conflict("nothing_current", f"{p.name} is current for nothing yet")
    job = printing.queue(db, printing.SKILLS_CARD, printing.SKILLS_CARD_VERSION,
                         settings.current().skills_card_printer_or_default,
                         {"type": "person", "ref": p.code}, data)
    db.commit()
    return _queued(job)
