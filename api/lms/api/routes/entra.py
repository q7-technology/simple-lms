"""Sign in with Microsoft, from either app, in three steps:

1. The app sends `POST /auth/entra/start` with a secret it keeps in the tab,
   and sends the person to the address it gets back: Microsoft's sign-in.
2. Microsoft sends them back to `GET /auth/entra/callback` with a code. The
   API swaps it for an ID token, checks it, matches the person, and sends
   them back to their app's sign-in page with a one-time hand-off code in
   the address's fragment (never sent to a server, nor in a Referer).
3. The app sends `POST /auth/entra/finish` with that code and its secret,
   and gets a session token, as from any other sign-in.

The session token never goes in an address. A hand-off code alone is no
use: only the tab that started the sign-in has the secret that goes with it,
so a link to someone else's sign-in signs nobody in."""
from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import urllib.parse
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from lms.api.deps import DB
from lms.api.errors import Unauthorised
from lms.api.routes.auth import SessionOut, signed_in, switched_on
from lms.config import get_settings
from lms.models import EntraSignIn, Person
from lms.services import entra, settings

router = APIRouter(prefix="/auth/entra", tags=["auth"])
log = logging.getLogger("lms.entra")

# from start to Microsoft sending them back
STARTED_FOR = timedelta(minutes=10)
# from coming back to the app finishing
HANDED_FOR = timedelta(minutes=2)
# then the row is cleared away
KEPT_FOR = timedelta(days=1)
# a shared tablet asks for the password every time; a desktop lets them pick
PROMPT = {"learner": "login", "desktop": "select_account"}


class StartIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    app: Literal["desktop", "learner"]
    # a random secret the app keeps in the tab (sessionStorage) until it finishes
    verifier: str = Field(min_length=32, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")


class StartOut(BaseModel):
    # Microsoft's sign-in page: the app sends the person there
    url: str


class FinishIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(max_length=128)
    verifier: str = Field(max_length=128)


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _on() -> bool:
    """Switched on in Settings, and set up in .env."""
    return settings.offered(settings.current())["entra"]


def _must_be_on() -> None:
    switched_on(_on(), "Microsoft")


def _back(app: str, **fragment: str) -> RedirectResponse:
    """To the app's sign-in page, with what it needs after the #."""
    page = "/learn/sign-in" if app == "learner" else "/sign-in"
    url = f"{settings.current().public_url}{page}#{urllib.parse.urlencode(fragment)}"
    return RedirectResponse(url, status_code=303, headers={
        "Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})


@router.post("/start", response_model=StartOut)
def start(body: StartIn, db: DB):
    """Where to send the person to sign in with Microsoft."""
    _must_be_on()
    now = datetime.now(UTC)
    db.execute(delete(EntraSignIn).where(EntraSignIn.created_at < now - KEPT_FOR))
    state, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    db.add(EntraSignIn(state_hash=_hash(state), nonce=nonce, code_verifier=verifier,
                       app=body.app, browser_hash=_hash(body.verifier), created_at=now))
    db.commit()
    return StartOut(url=entra.authorise_url(get_settings(), settings.current().public_url,
                                            state=state, nonce=nonce, verifier=verifier,
                                            prompt=PROMPT[body.app]))


@router.get("/callback", include_in_schema=False)
def callback(db: DB, state: str = "", code: str = "", error: str = "",
             error_description: str = ""):
    """Microsoft sends the person here. Always a redirect back to their app:
    `#entra=<hand-off code>`, or `#entra_error=` with not_matched (nobody
    here has that account), method_off, or failed (anything else)."""
    now = datetime.now(UTC)
    row = db.execute(select(EntraSignIn).where(
        EntraSignIn.state_hash == _hash(state), EntraSignIn.returned_at.is_(None),
        EntraSignIn.created_at > now - STARTED_FOR).with_for_update()).scalar_one_or_none()
    if row is None:
        # a state we never gave, or one used or too old: nobody to send back
        return _back("desktop", entra_error="failed")
    # each state comes back once, whatever happens next
    row.returned_at = now
    db.commit()
    if error or not code:
        log.info("Microsoft sign-in did not finish: %s %s", error, error_description[:200])
        return _back(row.app, entra_error="failed")
    if not _on():
        return _back(row.app, entra_error="method_off")
    try:
        claims = entra.redeem(get_settings(), settings.current().public_url, code,
                              row.code_verifier, row.nonce)
    except entra.EntraError as e:
        log.warning("Microsoft sign-in refused: %s", e)
        return _back(row.app, entra_error="failed")
    person = entra.match(db, claims)
    if person is None:
        db.rollback()
        log.info("Microsoft sign-in by someone Simple LMS doesn't know: oid %s", claims["oid"])
        return _back(row.app, entra_error="not_matched")
    handoff = secrets.token_urlsafe(32)
    row.person_id, row.handoff_hash = person.id, _hash(handoff)
    try:
        db.commit()
    except IntegrityError:
        # the same Microsoft account linked to someone else a moment ago
        db.rollback()
        return _back(row.app, entra_error="not_matched")
    return _back(row.app, entra=handoff)


@router.post("/finish", response_model=SessionOut)
def finish(body: FinishIn, db: DB):
    """A session for whoever Microsoft said it was. The hand-off code works
    once, for 2 minutes, with the secret its app started with."""
    _must_be_on()
    now = datetime.now(UTC)
    row = db.execute(select(EntraSignIn).where(
        EntraSignIn.handoff_hash == _hash(body.code), EntraSignIn.finished_at.is_(None))
        .with_for_update()).scalar_one_or_none()
    if row is None:
        raise Unauthorised("that Microsoft sign-in has finished or expired; try again")
    row.finished_at = now
    ok = (row.returned_at > now - HANDED_FOR
          and hmac.compare_digest(row.browser_hash, _hash(body.verifier)))
    person = db.get(Person, row.person_id)
    if not ok or person is None or not person.active:
        db.commit()
        raise Unauthorised("that Microsoft sign-in has finished or expired; try again")
    return signed_in(db, person, "entra")
