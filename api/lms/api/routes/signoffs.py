"""Signing off a practical, on the phone where the learner is: a
supervisor (for their own team) or a manager or admin (for anyone), never
the learner themselves (rule 3)."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from lms.api.deps import DB, Principal, require
from lms.api.routes.matrix import TO_DO
from lms.models import Person
from lms.services import clock, practicals, standing

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
