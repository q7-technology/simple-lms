"""Competencies: anything a person can be current for. Deactivated, never deleted."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select

from lms.api.deps import DB, Principal, require
from lms.api.errors import FieldError, NotFound, commit_unique
from lms.api.schemas import KEY, Page, normal_key
from lms.models import Competency

router = APIRouter(tags=["competencies"])

Kind = Literal["module", "practical", "ticket", "policy"]


class CompetencyIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    key: str = Field(min_length=1, max_length=64, pattern=KEY)
    name: str = Field(min_length=1, max_length=120)
    kind: Kind
    refresher_months: int | None = Field(default=None, ge=1, le=240)
    # a ticket: whether its card has an expiry date to type in
    card_expires: bool = True

    @field_validator("key", mode="before")
    @classmethod
    def _key(cls, v):
        return normal_key(v) if isinstance(v, str) else v


class CompetencyPatch(BaseModel):
    """The kind stays: it says how the competency is earned."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    refresher_months: int | None = Field(default=None, ge=1, le=240)
    card_expires: bool | None = None


class CompetencyOut(BaseModel):
    id: int
    key: str
    name: str
    kind: str
    refresher_months: int | None
    card_expires: bool
    active: bool
    created_at: datetime


def competency_out(c: Competency) -> CompetencyOut:
    return CompetencyOut(id=c.id, key=c.key, name=c.name, kind=c.kind,
                         refresher_months=c.refresher_months, card_expires=c.card_expires,
                         active=c.active,
                         created_at=c.created_at)


def get_competency(db, key: str) -> Competency:
    c = db.execute(select(Competency).where(Competency.key == normal_key(key))).scalar_one_or_none()
    if c is None:
        raise NotFound(f"no competency {key}")
    return c


@router.post("/competencies", status_code=201, response_model=CompetencyOut)
def create_competency(body: CompetencyIn, db: DB, who: Principal = require("competencies:write")):
    taken = FieldError("key", f"competency {body.key} already exists")
    if db.execute(select(Competency).where(Competency.key == body.key)).scalar_one_or_none():
        raise taken
    c = Competency(key=body.key, name=body.name, kind=body.kind,
                   refresher_months=body.refresher_months, card_expires=body.card_expires,
                   active=True)
    db.add(c)
    commit_unique(db, {"uq_competency_key": taken})
    return JSONResponse(status_code=201, content=competency_out(c).model_dump(mode="json"))


@router.get("/competencies", response_model=Page[CompetencyOut])
def list_competencies(db: DB, kind: Kind | None = None, active: bool | None = None,
                      who: Principal = require("competencies:read")):
    q = select(Competency)
    if kind is not None:
        q = q.where(Competency.kind == kind)
    if active is not None:
        q = q.where(Competency.active.is_(active))
    rows = db.execute(q.order_by(Competency.name)).scalars().all()
    return Page(items=[competency_out(c) for c in rows], total=len(rows))


@router.get("/competencies/{key}", response_model=CompetencyOut)
def read_competency(key: str, db: DB, who: Principal = require("competencies:read")):
    return competency_out(get_competency(db, key))


@router.patch("/competencies/{key}", response_model=CompetencyOut)
def update_competency(key: str, body: CompetencyPatch, db: DB,
                      who: Principal = require("competencies:write")):
    c = get_competency(db, key)
    if body.name is not None:
        c.name = body.name
    if "refresher_months" in body.model_fields_set:
        # null takes the refresher away: worked out again for everyone at once
        c.refresher_months = body.refresher_months
    if body.card_expires is not None:
        c.card_expires = body.card_expires
    db.commit()
    return competency_out(c)


@router.post("/competencies/{key}/deactivate", response_model=CompetencyOut)
def deactivate_competency(key: str, db: DB, who: Principal = require("competencies:write")):
    """No longer asked of anyone. Its records stay."""
    c = get_competency(db, key)
    c.active = False
    db.commit()
    return competency_out(c)


@router.post("/competencies/{key}/reactivate", response_model=CompetencyOut)
def reactivate_competency(key: str, db: DB, who: Principal = require("competencies:write")):
    c = get_competency(db, key)
    c.active = True
    db.commit()
    return competency_out(c)
