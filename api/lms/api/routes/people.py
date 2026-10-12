"""People: added, changed, given roles and a supervisor, deactivated. Never
deleted. A manager looks after learners and supervisors; only an admin adds
or changes a manager or an admin."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import or_, select

from lms.api.deps import DB, Principal, require
from lms.api.errors import Conflict, FieldError, Forbidden, NotFound, commit_unique
from lms.api.schemas import (
    CODE, EMAIL, PIN, Page, PersonRef, RoleRef, normal_code, normal_key, person_ref, role_ref,
)
from lms.models import Person, PersonRole, Role
from lms.services import access, sessions

router = APIRouter(tags=["people"])

Permission = Literal["learner", "supervisor", "manager", "admin"]
SUPERVISES = ("supervisor", "manager", "admin")
ABOVE_MANAGERS = ("manager", "admin")


class PersonIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    code: str = Field(min_length=1, max_length=32, pattern=CODE)
    name: str = Field(min_length=1, max_length=120)
    email: str | None = Field(default=None, max_length=254, pattern=EMAIL)
    permission: Permission = "learner"
    supervisor: str | None = Field(default=None, max_length=32)
    roles: list[str] = Field(default_factory=list, max_length=50)
    pin: str | None = Field(default=None, pattern=PIN)
    password: str | None = Field(default=None, min_length=access.MIN_PASSWORD, max_length=200)

    @field_validator("email", mode="before")
    @classmethod
    def _email(cls, v):
        # kept lower case, so an email matches however it is typed
        return v.strip().lower() if isinstance(v, str) else v


class PersonPatch(BaseModel):
    """Leave a field out to keep it; send null to clear an email or a supervisor."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    email: str | None = Field(default=None, max_length=254, pattern=EMAIL)
    permission: Permission | None = None
    supervisor: str | None = Field(default=None, max_length=32)

    @field_validator("email", mode="before")
    @classmethod
    def _email(cls, v):
        # kept lower case, so an email matches however it is typed
        return v.strip().lower() if isinstance(v, str) else v


class RolesIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    roles: list[str] = Field(max_length=50)


class PinIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pin: str = Field(pattern=PIN)


class PasswordIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: str = Field(min_length=access.MIN_PASSWORD, max_length=200)


class PersonOut(BaseModel):
    id: int
    code: str
    name: str
    email: str | None
    permission: str
    supervisor: PersonRef | None
    roles: list[RoleRef]
    active: bool
    has_pin: bool
    pin_locked: bool
    has_password: bool
    created_at: datetime
    last_login_at: datetime | None


def person_out(p: Person) -> PersonOut:
    return PersonOut(id=p.id, code=p.code, name=p.name, email=p.email, permission=p.permission,
                     supervisor=person_ref(p.supervisor), roles=[role_ref(r) for r in p.roles],
                     active=p.active, has_pin=p.pin_hash is not None, pin_locked=p.pin_locked,
                     has_password=p.password_hash is not None, created_at=p.created_at,
                     last_login_at=p.last_login_at)


def get_person(db, code: str) -> Person:
    p = db.execute(select(Person).where(Person.code == normal_code(code))).scalar_one_or_none()
    if p is None:
        raise NotFound(f"no person {code}")
    return p


def may_manage(who: Principal, current: str | None, new: str | None = None) -> None:
    """A manager looks after learners and supervisors; managers and admins
    are an admin's to add and change."""
    if who.person.permission == "admin":
        return
    if current in ABOVE_MANAGERS or new in ABOVE_MANAGERS:
        raise Forbidden("only an admin can add or change a manager or an admin", "admin_only")


def _supervisor(db, code: str, person: Person | None = None) -> Person:
    sup = db.execute(select(Person).where(Person.code == normal_code(code))).scalar_one_or_none()
    if sup is None or not sup.active:
        raise FieldError("supervisor", f"no active person {code}")
    if person is not None and sup.id == person.id:
        raise FieldError("supervisor", "a person can't be their own supervisor")
    if sup.permission not in SUPERVISES:
        raise FieldError("supervisor",
                         f"{sup.code} can't supervise yet: give them the supervisor permission")
    return sup


def _keeps_no_team(db, p: Person) -> None:
    """A supervisor's team needs someone who can still supervise it."""
    team = db.execute(select(Person.id).where(Person.supervisor_id == p.id,
                                              Person.active.is_(True)).limit(1)).first()
    if team is not None:
        raise Conflict("has_team", f"{p.code} still supervises a team: "
                                   "give their team another supervisor first")


def _roles(db, keys: list[str]) -> list[Role]:
    keys = list(dict.fromkeys(normal_key(k) for k in keys))
    found = {r.key: r for r in db.execute(select(Role).where(Role.key.in_(keys))).scalars()}
    missing = [k for k in keys if k not in found]
    if missing:
        raise FieldError("roles", f"no role {missing[0]}")
    return [found[k] for k in keys]


def _email_free(db, email: str | None, person: Person | None = None) -> None:
    if email is None:
        return
    other = db.execute(select(Person).where(Person.email == email)).scalar_one_or_none()
    if other is not None and other is not person:
        raise FieldError("email", f"{email} is already {other.code}'s")


def _email_taken(email: str | None) -> FieldError:
    # someone else took it between the check and the commit
    return FieldError("email", f"{email} is already taken")


@router.post("/people", status_code=201, response_model=PersonOut)
def create_person(body: PersonIn, db: DB, who: Principal = require("people:write")):
    may_manage(who, None, body.permission)
    code = normal_code(body.code)
    code_taken = FieldError("code", f"{code} is already taken")
    if db.execute(select(Person).where(Person.code == code)).scalar_one_or_none():
        raise code_taken
    _email_free(db, body.email)
    p = Person(code=code, name=body.name, email=body.email, permission=body.permission,
               pin_hash=access.hash_password(body.pin) if body.pin else None,
               password_hash=access.hash_password(body.password) if body.password else None,
               pin_failed_attempts=0, pin_locked=False, password_failed_attempts=0, active=True)
    if body.supervisor:
        p.supervisor = _supervisor(db, body.supervisor)
    p.roles = _roles(db, body.roles)
    db.add(p)
    commit_unique(db, {"uq_person_code": code_taken,
                       "uq_person_email": _email_taken(body.email)})
    db.refresh(p)
    return JSONResponse(status_code=201, content=person_out(p).model_dump(mode="json"))


@router.get("/people", response_model=Page[PersonOut])
def list_people(db: DB, active: bool | None = None,
                q: str | None = Query(default=None, max_length=120), role: str | None = None,
                who: Principal = require("people:read")):
    """By name. `q` matches part of the code, name or email."""
    query = select(Person)
    if active is not None:
        query = query.where(Person.active.is_(active))
    if q:
        like = f"%{q.strip()}%"
        query = query.where(or_(Person.code.ilike(like), Person.name.ilike(like),
                                Person.email.ilike(like)))
    if role:
        query = query.join(PersonRole, PersonRole.person_id == Person.id).join(
            Role, Role.id == PersonRole.role_id).where(Role.key == normal_key(role))
    rows = db.execute(query.order_by(Person.name, Person.code)).scalars().all()
    return Page(items=[person_out(p) for p in rows], total=len(rows))


@router.get("/people/{code}", response_model=PersonOut)
def read_person(code: str, db: DB, who: Principal = require("people:read")):
    return person_out(get_person(db, code))


@router.patch("/people/{code}", response_model=PersonOut)
def update_person(code: str, body: PersonPatch, db: DB, who: Principal = require("people:write")):
    p = get_person(db, code)
    may_manage(who, p.permission, body.permission)
    if body.name is not None:
        p.name = body.name
    if "email" in body.model_fields_set:
        _email_free(db, body.email, p)
        p.email = body.email
    if body.permission is not None and body.permission != p.permission:
        if p.id == who.person.id:
            raise Conflict("self", "you can't change your own permission")
        if body.permission not in SUPERVISES:
            _keeps_no_team(db, p)
        p.permission = body.permission
    if "supervisor" in body.model_fields_set:
        p.supervisor = _supervisor(db, body.supervisor, p) if body.supervisor else None
    commit_unique(db, {"uq_person_email": _email_taken(body.email)})
    return person_out(p)


@router.put("/people/{code}/roles", response_model=PersonOut)
def set_roles(code: str, body: RolesIn, db: DB, who: Principal = require("people:write")):
    """All of this person's roles, in full: what is left out is taken away."""
    p = get_person(db, code)
    may_manage(who, p.permission)
    p.roles = _roles(db, body.roles)
    db.commit()
    db.refresh(p)
    return person_out(p)


@router.post("/people/{code}/pin", response_model=PersonOut)
def reset_pin(code: str, body: PinIn, db: DB, who: Principal = require("people:write")):
    """A new PIN, which also unlocks one locked after five wrong tries. Their
    PIN sessions end."""
    p = get_person(db, code)
    may_manage(who, p.permission)
    p.pin_hash = access.hash_password(body.pin)
    p.pin_failed_attempts = 0
    p.pin_locked = False
    sessions.end_all(db, p, "pin")
    db.commit()
    return person_out(p)


@router.post("/people/{code}/password", response_model=PersonOut)
def set_password(code: str, body: PasswordIn, db: DB, who: Principal = require("people:write")):
    """A new password, which also lifts a lock. Their password sessions end."""
    p = get_person(db, code)
    may_manage(who, p.permission)
    p.password_hash = access.hash_password(body.password)
    p.password_failed_attempts = 0
    p.password_locked_until = None
    sessions.end_all(db, p, "password")
    db.commit()
    return person_out(p)


@router.post("/people/{code}/deactivate", response_model=PersonOut)
def deactivate_person(code: str, db: DB, who: Principal = require("people:write")):
    """They have left. Their records stay; their sessions end."""
    p = get_person(db, code)
    may_manage(who, p.permission)
    if p.id == who.person.id:
        raise Conflict("self", "you can't deactivate yourself")
    _keeps_no_team(db, p)
    p.active = False
    sessions.end_all(db, p)
    db.commit()
    return person_out(p)


@router.post("/people/{code}/reactivate", response_model=PersonOut)
def reactivate_person(code: str, db: DB, who: Principal = require("people:write")):
    p = get_person(db, code)
    may_manage(who, p.permission)
    p.active = True
    db.commit()
    return person_out(p)
