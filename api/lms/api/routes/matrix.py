"""The matrix (people down the side, what they are asked for across the
top, a status in each cell) and each person's own to-do list. Worked out
on every request from the records and today's date (rule 2)."""
from __future__ import annotations

import csv
import io
from datetime import date

from fastapi import APIRouter, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from lms.api.deps import DB, Principal, require
from lms.api.errors import FieldError, NotFound
from lms.api.routes.people import get_person
from lms.api.schemas import (
    CompetencyRef, PersonRef, RoleRef, competency_ref, normal_code, normal_key, person_ref,
    role_ref,
)
from lms.models import Person, PersonRole, Role, TicketSubmission
from lms.services import clock, standing
from lms.services.status import STATUSES

router = APIRouter(tags=["matrix"])

# what My training shows: what they are asked for and not let off
TO_DO = ("lapsed", "missing", "expiring", "current")


class CellOut(BaseModel):
    status: str
    granted_on: date | None
    expires_on: date | None


class MatrixRow(BaseModel):
    code: str
    name: str
    roles: list[RoleRef]
    supervisor: PersonRef | None
    # by competency key: every column has a cell
    cells: dict[str, CellOut]


class MatrixOut(BaseModel):
    today: date
    competencies: list[CompetencyRef]
    people: list[MatrixRow]


class TrainingItem(BaseModel):
    key: str
    name: str
    kind: str
    status: str
    granted_on: date | None
    expires_on: date | None
    # a ticket: whether its card has an expiry date to type in (null otherwise)
    card_expires: bool | None
    # a ticket sent in and waiting for a manager's check
    waiting: bool


class TrainingOut(BaseModel):
    person: PersonRef
    today: date
    items: list[TrainingItem]


def _statuses(status: str | None) -> set[str] | None:
    if not status:
        return None
    wanted = {s.strip() for s in status.split(",") if s.strip()}
    # not_required is never a filter: the columns are what the people shown
    # are asked for, so it would match nobody
    filters = [s for s in STATUSES if s != "not_required"]
    unknown = wanted - set(filters)
    if unknown:
        raise FieldError("status", f"can't filter on {sorted(unknown)[0]}; one of "
                                   f"{', '.join(filters)}")
    return wanted


def build(db, who: Principal, role: str | None, supervisor: str | None,
          status: str | None) -> MatrixOut:
    wanted = _statuses(status)
    q = (select(Person).where(Person.active.is_(True))
         .options(selectinload(Person.roles), selectinload(Person.supervisor)))
    if not who.sees_everyone:
        # a supervisor sees their own team
        q = q.where(Person.supervisor_id == who.person.id)
    if role:
        q = q.join(PersonRole, PersonRole.person_id == Person.id).join(
            Role, Role.id == PersonRole.role_id).where(Role.key == normal_key(role))
    if supervisor:
        boss = db.execute(select(Person.id).where(Person.code == normal_code(supervisor))).scalar()
        if boss is None:
            raise FieldError("supervisor", f"no person {supervisor}")
        q = q.where(Person.supervisor_id == boss)
    people = db.execute(q.order_by(Person.name, Person.code)).scalars().all()

    st = standing.load(db, [p.id for p in people], clock.today())
    rows: list[tuple[Person, set[int]]] = []
    for p in people:
        asked = st.asked_for(p.id)
        if wanted is not None and not any(st.status(p.id, c).status in wanted for c in asked):
            continue
        rows.append((p, asked))
    columns = sorted({c for _, asked in rows for c in asked},
                     key=lambda c: (st.competencies[c].name, st.competencies[c].key))
    return MatrixOut(
        today=st.today,
        competencies=[competency_ref(st.competencies[c]) for c in columns],
        people=[MatrixRow(
            code=p.code, name=p.name, roles=[role_ref(r) for r in p.roles],
            supervisor=person_ref(p.supervisor),
            cells={st.competencies[c].key: CellOut(**_cell(st.status(p.id, c))) for c in columns},
        ) for p, _ in rows],
    )


def _cell(s) -> dict:
    return {"status": s.status, "granted_on": s.granted_on, "expires_on": s.expires_on}


@router.get("/matrix", response_model=MatrixOut)
def matrix(db: DB, role: str | None = None, supervisor: str | None = None,
           status: str | None = None, who: Principal = require("matrix:read")):
    """Active people by name; columns are what any of them is asked for, by
    name. Filters: `role` (key), `supervisor` (code), `status` (comma
    separated: people with at least one cell in it; not `not_required`)."""
    return build(db, who, role, supervisor, status)


def _safe(value: str) -> str:
    # a spreadsheet would run a cell that starts like a formula
    return "'" + value if value[:1] in ("=", "+", "-", "@", "\t", "\r") else value


@router.get("/matrix.csv")
def matrix_csv(db: DB, role: str | None = None, supervisor: str | None = None,
               status: str | None = None, who: Principal = require("matrix:read")):
    """The same matrix as a spreadsheet: a status and an expiry date per competency."""
    m = build(db, who, role, supervisor, status)
    out = io.StringIO()
    w = csv.writer(out)
    head = ["code", "name", "roles", "supervisor"]
    for c in m.competencies:
        head += [_safe(c.name), f"{_safe(c.name)} expires"]
    w.writerow(head)
    for row in m.people:
        line = [_safe(row.code), _safe(row.name), _safe("; ".join(r.name for r in row.roles)),
                _safe(row.supervisor.name) if row.supervisor else ""]
        for c in m.competencies:
            cell = row.cells[c.key]
            line += [cell.status.replace("_", " "),
                     cell.expires_on.isoformat() if cell.expires_on else ""]
        w.writerow(line)
    return Response(content=out.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition":
                             f'attachment; filename="matrix-{m.today.isoformat()}.csv"'})


@router.get("/people/{code}/training", response_model=TrainingOut)
def training(code: str, db: DB, who: Principal = require("training:read")):
    """A person's to-do: everything they are asked for and not let off, by
    name. The learner app sorts it into Overdue, Due soon and Done."""
    p = get_person(db, code)
    if not who.sees(p):
        raise NotFound(f"no person {code}")
    st = standing.load(db, [p.id], clock.today())
    waiting = set(db.execute(select(TicketSubmission.competency_id).where(
        TicketSubmission.person_id == p.id, TicketSubmission.status == "pending")).scalars())
    items = []
    for c in st.asked_for(p.id):
        s = st.status(p.id, c)
        if s.status in TO_DO:
            comp = st.competencies[c]
            items.append(TrainingItem(key=comp.key, name=comp.name, kind=comp.kind,
                                      status=s.status, granted_on=s.granted_on,
                                      expires_on=s.expires_on,
                                      card_expires=comp.card_expires if comp.kind == "ticket"
                                      else None,
                                      waiting=c in waiting))
    items.sort(key=lambda i: (i.name, i.key))
    return TrainingOut(person=person_ref(p), today=st.today, items=items)
