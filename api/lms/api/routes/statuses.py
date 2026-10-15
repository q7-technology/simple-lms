"""The competency API: a person's status for everything they are asked
for, or for one competency, worked out today by status.py (rule 2). For
another system with an API key (Simple TMS checking a driver's licence and
induction before a run) and for the people who may see the person."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter
from pydantic import BaseModel

from lms.api.deps import DB, KeyCaller, Principal, require_reader
from lms.api.errors import NotFound
from lms.api.routes.competencies import get_competency
from lms.api.routes.people import get_person
from lms.models import Competency, Person
from lms.services import clock, standing
from lms.services.status import Status

router = APIRouter(tags=["competency API"])


class PersonStatusOut(BaseModel):
    code: str
    name: str
    # someone deactivated has left: their records stay, and so does their status
    active: bool


class StatusOut(BaseModel):
    key: str
    name: str
    kind: str
    # current, expiring, lapsed, missing, waived or not_required
    status: str
    granted_on: date | None
    # the last good day; null when it doesn't run out, or there is no grant
    expires_on: date | None


class CompetenciesOut(BaseModel):
    person: PersonStatusOut
    today: date
    competencies: list[StatusOut]


class CompetencyOut(StatusOut):
    person: PersonStatusOut
    today: date


def _person(db, code: str, who: Principal | KeyCaller) -> Person:
    p = get_person(db, code)
    if not who.sees(p):
        raise NotFound(f"no person {code}")
    return p


def _out(c: Competency, s: Status) -> dict:
    return {"key": c.key, "name": c.name, "kind": c.kind, "status": s.status,
            "granted_on": s.granted_on, "expires_on": s.expires_on}


def _person_out(p: Person) -> PersonStatusOut:
    return PersonStatusOut(code=p.code, name=p.name, active=p.active)


@router.get("/people/{code}/competencies", response_model=CompetenciesOut)
def competencies(code: str, db: DB,
                 who: Principal | KeyCaller = require_reader("competencies:read")):
    """Everything their roles and extras ask of them, waived or not, by name."""
    p = _person(db, code, who)
    st = standing.load(db, [p.id], clock.today())
    asked = sorted((st.competencies[c] for c in st.asked_for(p.id)),
                   key=lambda c: (c.name, c.key))
    return CompetenciesOut(person=_person_out(p), today=st.today,
                           competencies=[StatusOut(**_out(c, st.status(p.id, c.id)))
                                         for c in asked])


@router.get("/people/{code}/competencies/{key}", response_model=CompetencyOut)
def one_competency(code: str, key: str, db: DB,
                   who: Principal | KeyCaller = require_reader("competencies:read")):
    """Their status for this one: `not_required` when it isn't asked of
    them (or has been deactivated)."""
    p = _person(db, code, who)
    c = get_competency(db, key)
    st = standing.load(db, [p.id], clock.today())
    s = st.status(p.id, c.id) if c.id in st.competencies else Status("not_required")
    return CompetencyOut(person=_person_out(p), today=st.today, **_out(c, s))
