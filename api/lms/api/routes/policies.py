"""Policies: versions of the text, published by a manager, and signed by
each person in the learner app with their typed name and a finger
signature. A new version needs a new signature (status.py says so)."""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from lms.api.deps import DB, Principal, require
from lms.api.errors import Conflict, FieldError, NotFound
from lms.api.routes.competencies import get_competency
from lms.api.routes.records import RecordOut, latest_record, one_at_a_time, record_out
from lms.api.schemas import PersonRef, person_ref
from lms.models import Competency, CompetencyRecord, PolicyVersion
from lms.services import clock, policies, uploads

router = APIRouter(tags=["policies"])


class VersionIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    body: str = Field(min_length=1, max_length=50_000)
    note: str | None = Field(default=None, max_length=500)


class VersionOut(BaseModel):
    id: int
    version: int
    body: str
    note: str | None
    published_by: PersonRef
    created_at: datetime


class PolicyOut(BaseModel):
    key: str
    name: str
    version: VersionOut


class SignIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    # the version they read: if a newer one came out meanwhile, they read that
    version: int
    signed_name: str = Field(min_length=1, max_length=120)
    # the finger signature, sent first to POST /v1/uploads?purpose=signature
    signature: uuid.UUID


def version_out(v: PolicyVersion) -> VersionOut:
    return VersionOut(id=v.id, version=v.version, body=v.body, note=v.note,
                      published_by=person_ref(v.published_by), created_at=v.created_at)


def get_policy(db, key: str) -> Competency:
    c = get_competency(db, key)
    if c.kind != "policy":
        raise NotFound(f"no policy {key}")
    return c


@router.get("/policies/{key}/versions", response_model=list[VersionOut])
def list_versions(key: str, db: DB, who: Principal = require("competencies:read")):
    """Newest first: the first is the one to sign."""
    c = get_policy(db, key)
    rows = db.execute(select(PolicyVersion).where(PolicyVersion.competency_id == c.id)
                      .order_by(PolicyVersion.id.desc())).scalars().all()
    return [version_out(v) for v in rows]


@router.post("/policies/{key}/versions", status_code=201, response_model=VersionOut)
def publish_version(key: str, body: VersionIn, db: DB,
                    who: Principal = require("competencies:write")):
    """The next version. Everyone asked for the policy needs to sign it."""
    c = get_policy(db, key)
    # one at a time per policy, so two published at once get 1 and 2
    db.refresh(c, with_for_update=True)
    last = db.execute(select(func.max(PolicyVersion.version))
                      .where(PolicyVersion.competency_id == c.id)).scalar() or 0
    v = PolicyVersion(competency=c, version=last + 1, body=body.body, note=body.note or None,
                      published_by=who.person)
    db.add(v)
    db.commit()
    return JSONResponse(status_code=201, content=version_out(v).model_dump(mode="json"))


@router.get("/policies/{key}", response_model=PolicyOut)
def read_policy(key: str, db: DB, who: Principal = require("training:read")):
    """The version to read and sign now."""
    c = get_policy(db, key)
    v = policies.newest(db, c)
    if v is None:
        raise NotFound(f"{c.name} has no version to sign yet")
    return PolicyOut(key=c.key, name=c.name, version=version_out(v))


@router.post("/policies/{key}/sign", status_code=201, response_model=RecordOut)
def sign(key: str, body: SignIn, db: DB, who: Principal = require("training:write")):
    """Your own signature, for the newest version. Like a module pass, it
    is something you do yourself: it says you have read the policy, and it
    is recorded as yours."""
    p = one_at_a_time(db, who.person.code)
    c = get_policy(db, key)
    if not c.active:
        raise Conflict("inactive", f"{c.key} is deactivated")
    v = policies.newest(db, c)
    if v is None:
        raise NotFound(f"{c.name} has no version to sign yet")
    if body.version != v.version:
        raise Conflict("new_version", f"version {v.version} is the one to sign now: read it first")
    latest = latest_record(db, p.id, c.id)
    if latest is not None and latest.kind == "granted" and latest.policy_version_id == v.id:
        raise Conflict("already_signed", f"you have signed version {v.version} already")
    if not policies.same_name(body.signed_name, p.name):
        raise FieldError("signed_name", f"type your name as it is on your record: {p.name}")
    signature = uploads.mine(db, p, body.signature, "signature")
    if signature is None or policies.signature_used(db, signature.id):
        raise FieldError("signature", "sign with your finger first")
    r = CompetencyRecord(person_id=p.id, competency=c, kind="granted", granted_on=clock.today(),
                         recorded_by=p, policy_version=v, signed_name=body.signed_name,
                         signature_upload_id=signature.id)
    db.add(r)
    db.commit()
    return JSONResponse(status_code=201, content=record_out(r).model_dump(mode="json"))
