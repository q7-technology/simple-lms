"""Sign in with an email and password (either app) or a code and PIN (the
learner app). Either way the session token is all a client holds."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Header, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from lms.api.deps import DB, Who, bearer_token
from lms.api.schemas import normal_code
from lms.models import Person
from lms.services import access, sessions

router = APIRouter(prefix="/auth", tags=["auth"])

TRIES = 5
PASSWORD_LOCK_MINUTES = 15


class LoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(max_length=254)
    password: str = Field(max_length=200)


class PinLoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(max_length=32)
    pin: str = Field(max_length=8)


class MeOut(BaseModel):
    id: int
    code: str
    name: str
    email: str | None
    permission: str
    method: str
    scopes: list[str]
    # the session ends after this long without a request
    idle_seconds: int


class SessionOut(BaseModel):
    token: str
    person: MeOut


def me_out(p: Person, method: str) -> MeOut:
    return MeOut(id=p.id, code=p.code, name=p.name, email=p.email, permission=p.permission,
                 method=method, scopes=sessions.scopes_for(p.permission, method),
                 idle_seconds=int(sessions.IDLE[method].total_seconds()))


def _refused(detail: str, code: str) -> JSONResponse:
    return JSONResponse(status_code=401, content={"detail": detail, "code": code},
                        headers={"WWW-Authenticate": "Bearer"})


def _signed_in(db, person: Person, method: str) -> SessionOut:
    token = sessions.start(db, person, method)
    person.last_login_at = datetime.now(UTC)
    db.commit()
    return SessionOut(token=token, person=me_out(person, method))


def _one_at_a_time(db, where) -> Person | None:
    # the row stays locked until this attempt is counted, so guesses sent all
    # at once are weighed one after another and cannot get past the limit
    return db.execute(select(Person).where(where).with_for_update()).scalar_one_or_none()


@router.post("/login", response_model=SessionOut)
def login(body: LoginIn, db: DB):
    """Five wrong passwords lock the password for 15 minutes."""
    person = _one_at_a_time(db, Person.email == body.email.strip().lower())
    if person is None or not person.active or not person.password_hash:
        # an unknown email and a wrong password look alike, and take as long
        access.verify_password(body.password, access.DUMMY_HASH)
        return _refused("wrong email or password", "wrong_password")
    if person.password_locked_until and person.password_locked_until > datetime.now(UTC):
        return _refused("too many wrong passwords; try again in a few minutes", "locked")
    if not access.verify_password(body.password, person.password_hash):
        person.password_failed_attempts += 1
        if person.password_failed_attempts >= TRIES:
            person.password_failed_attempts = 0
            person.password_locked_until = (datetime.now(UTC)
                                            + timedelta(minutes=PASSWORD_LOCK_MINUTES))
            db.commit()
            return _refused(f"too many wrong passwords; locked for {PASSWORD_LOCK_MINUTES} "
                            "minutes", "locked")
        db.commit()
        return _refused("wrong email or password", "wrong_password")
    person.password_failed_attempts = 0
    person.password_locked_until = None
    return _signed_in(db, person, "password")


@router.post("/pin-login", response_model=SessionOut)
def pin_login(body: PinLoginIn, db: DB):
    """Five wrong PINs lock the PIN until a manager sets a new one."""
    person = _one_at_a_time(db, Person.code == normal_code(body.code))
    if person is None or not person.active or not person.pin_hash:
        access.verify_password(body.pin, access.DUMMY_HASH)
        return _refused("wrong code or PIN", "wrong_pin")
    if person.pin_locked:
        return _refused("this PIN is locked after too many wrong tries; ask your manager to "
                        "reset it", "locked")
    if not access.verify_password(body.pin, person.pin_hash):
        person.pin_failed_attempts += 1
        if person.pin_failed_attempts >= TRIES:
            person.pin_locked = True
            db.commit()
            return _refused(f"wrong PIN {TRIES} times; it is locked until your manager resets it",
                            "locked")
        db.commit()
        # no tries left count: an unknown code could not say it without giving itself away
        return _refused("wrong code or PIN", "wrong_pin")
    person.pin_failed_attempts = 0
    return _signed_in(db, person, "pin")


@router.post("/logout", status_code=204)
def logout(db: DB, authorization: Annotated[str | None, Header()] = None):
    """Ends this session. Answers 204 even for a session that already ended."""
    raw = bearer_token(authorization)
    if raw:
        sessions.end(db, raw)
        db.commit()
    return Response(status_code=204)


@router.get("/me", response_model=MeOut)
def me(who: Who):
    return me_out(who.person, who.method)
