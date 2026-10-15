"""API keys: made by an admin on the Settings screen for another system,
with the scopes it needs, shown once, and revoked when it is done with.
Never deleted."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select

from lms.api.deps import DB, Principal, require
from lms.api.errors import Conflict, FieldError, NotFound, commit_unique
from lms.api.schemas import PersonRef, person_ref
from lms.models import ApiKey
from lms.services import api_keys

router = APIRouter(tags=["api keys"])

# an admin's, on the Settings screen
SCOPE = "settings:write"

KeyScope = Literal["competencies:read"]


class ApiKeyIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    # who it is for, e.g. Simple TMS
    name: str = Field(min_length=1, max_length=120)
    scopes: list[KeyScope] = Field(min_length=1, max_length=len(api_keys.SCOPES))

    @field_validator("scopes")
    @classmethod
    def _each_once(cls, v):
        return list(dict.fromkeys(v))


class ApiKeyOut(BaseModel):
    id: int
    name: str
    # its first characters, to tell which key is which
    prefix: str
    scopes: list[str]
    created_by: PersonRef
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None


class ApiKeyMade(ApiKeyOut):
    # shown this once: Simple LMS keeps only its hash
    key: str


def key_out(k: ApiKey) -> ApiKeyOut:
    return ApiKeyOut(id=k.id, name=k.name, prefix=k.prefix, scopes=k.scopes,
                     created_by=person_ref(k.created_by), created_at=k.created_at,
                     last_used_at=k.last_used_at, revoked_at=k.revoked_at)


def _name_taken(name: str) -> FieldError:
    return FieldError("name", f"there is already a key called {name}")


@router.get("/api-keys", response_model=list[ApiKeyOut])
def list_keys(db: DB, who: Principal = require(SCOPE)):
    """By name, revoked or not."""
    rows = db.execute(select(ApiKey).order_by(ApiKey.name)).scalars().all()
    return [key_out(k) for k in rows]


@router.post("/api-keys", status_code=201, response_model=ApiKeyMade)
def make_key(body: ApiKeyIn, db: DB, who: Principal = require(SCOPE)):
    if db.execute(select(ApiKey.id).where(ApiKey.name == body.name)).first():
        raise _name_taken(body.name)
    key, raw = api_keys.create(db, body.name, body.scopes, who.person)
    commit_unique(db, {"uq_api_key_name": _name_taken(body.name)})
    out = ApiKeyMade(**key_out(key).model_dump(), key=raw)
    return JSONResponse(status_code=201, content=out.model_dump(mode="json"))


@router.post("/api-keys/{key_id}/revoke", response_model=ApiKeyOut)
def revoke_key(key_id: int, db: DB, who: Principal = require(SCOPE)):
    """It stops working at once, for good."""
    k = db.get(ApiKey, key_id, with_for_update=True)
    if k is None:
        raise NotFound(f"no API key {key_id}")
    if k.revoked_at is not None:
        raise Conflict("revoked", f"the key {k.name} was revoked already")
    k.revoked_at = datetime.now(UTC)
    db.commit()
    return key_out(k)
