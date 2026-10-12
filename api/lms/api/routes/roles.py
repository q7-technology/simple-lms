"""Roles, and the competencies each requires."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select

from lms.api.deps import DB, Principal, require
from lms.api.errors import FieldError, NotFound
from lms.api.schemas import KEY, CompetencyRef, Page, competency_ref, normal_key
from lms.models import Competency, PersonRole, Role

router = APIRouter(tags=["roles"])


class RoleIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    key: str = Field(min_length=1, max_length=64, pattern=KEY)
    name: str = Field(min_length=1, max_length=120)

    @field_validator("key", mode="before")
    @classmethod
    def _key(cls, v):
        return normal_key(v) if isinstance(v, str) else v


class RolePatch(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=120)


class RequirementsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    competencies: list[str] = Field(max_length=500)


class RoleOut(BaseModel):
    id: int
    key: str
    name: str
    competencies: list[CompetencyRef]
    people: int
    created_at: datetime


def role_out(db, r: Role) -> RoleOut:
    people = db.execute(select(func.count()).select_from(PersonRole)
                        .where(PersonRole.role_id == r.id)).scalar_one()
    return RoleOut(id=r.id, key=r.key, name=r.name,
                   competencies=[competency_ref(c) for c in r.competencies], people=people,
                   created_at=r.created_at)


def get_role(db, key: str) -> Role:
    r = db.execute(select(Role).where(Role.key == normal_key(key))).scalar_one_or_none()
    if r is None:
        raise NotFound(f"no role {key}")
    return r


@router.post("/roles", status_code=201, response_model=RoleOut)
def create_role(body: RoleIn, db: DB, who: Principal = require("roles:write")):
    if db.execute(select(Role).where(Role.key == body.key)).scalar_one_or_none():
        raise FieldError("key", f"role {body.key} already exists")
    r = Role(key=body.key, name=body.name)
    db.add(r)
    db.commit()
    return JSONResponse(status_code=201, content=role_out(db, r).model_dump(mode="json"))


@router.get("/roles", response_model=Page[RoleOut])
def list_roles(db: DB, who: Principal = require("roles:read")):
    rows = db.execute(select(Role).order_by(Role.name)).scalars().all()
    return Page(items=[role_out(db, r) for r in rows], total=len(rows))


@router.get("/roles/{key}", response_model=RoleOut)
def read_role(key: str, db: DB, who: Principal = require("roles:read")):
    return role_out(db, get_role(db, key))


@router.patch("/roles/{key}", response_model=RoleOut)
def update_role(key: str, body: RolePatch, db: DB, who: Principal = require("roles:write")):
    r = get_role(db, key)
    r.name = body.name
    db.commit()
    return role_out(db, r)


@router.put("/roles/{key}/requirements", response_model=RoleOut)
def set_requirements(key: str, body: RequirementsIn, db: DB,
                     who: Principal = require("roles:write")):
    """Everything this role requires, in full: what is left out is no longer required."""
    r = get_role(db, key)
    keys = list(dict.fromkeys(normal_key(k) for k in body.competencies))
    found = {c.key: c for c in db.execute(
        select(Competency).where(Competency.key.in_(keys))).scalars()}
    already = {c.key for c in r.competencies}  # a deactivated one already required may stay
    for k in keys:
        if k not in found:
            raise FieldError("competencies", f"no competency {k}")
        if not found[k].active and k not in already:
            raise FieldError("competencies", f"{k} is deactivated")
    r.competencies = [found[k] for k in keys]
    db.commit()
    db.refresh(r)
    return role_out(db, r)
