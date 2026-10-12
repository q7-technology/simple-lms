"""Shapes more than one route uses."""
from __future__ import annotations

from pydantic import BaseModel

from lms.models import Competency, Person, Role

KEY = r"^[a-z0-9][a-z0-9-]*$"
CODE = r"^[A-Za-z0-9._-]+$"
PIN = r"^[0-9]{4,8}$"
EMAIL = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class Page[T](BaseModel):
    items: list[T]
    total: int


class PersonRef(BaseModel):
    code: str
    name: str


class RoleRef(BaseModel):
    key: str
    name: str


class CompetencyRef(BaseModel):
    key: str
    name: str
    kind: str


def person_ref(p: Person | None) -> PersonRef | None:
    return None if p is None else PersonRef(code=p.code, name=p.name)


def role_ref(r: Role) -> RoleRef:
    return RoleRef(key=r.key, name=r.name)


def competency_ref(c: Competency) -> CompetencyRef:
    return CompetencyRef(key=c.key, name=c.name, kind=c.kind)


def normal_code(value: str) -> str:
    """'ll042 ' and 'LL042' are the same person."""
    return value.strip().upper()


def normal_key(value: str) -> str:
    return value.strip().lower()
