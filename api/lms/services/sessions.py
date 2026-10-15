"""Sessions: one random token per signed-in device, kept only as its hash.
A PIN session (the learner app, perhaps a shared tablet) ends after 15
minutes idle; a password session after 12 hours idle. Either ends on
sign-out, or when its PIN or password is changed."""
from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session as Db

from lms.models import Person, Session

PREFIX = "lms_s."
IDLE = {"password": timedelta(hours=12), "pin": timedelta(minutes=15)}
LIFETIME = {"password": timedelta(days=14), "pin": timedelta(hours=12)}
# last_seen_at is written at most once a minute, not on every request
TOUCH_EVERY = timedelta(minutes=1)

# What each permission level may do (the design's table). Admin-only areas
# are the admin's "*" alone: settings:write (Settings, sign-in methods among
# them) now, webhooks and API keys with their step.
# training:write is doing your own training: signing a policy, adding a
# ticket. tickets:verify is checking someone else's ticket. signoffs:write
# is signing off someone else's practical.
SCOPES: dict[str, list[str]] = {
    "learner": ["training:read", "training:write"],
    "supervisor": ["training:read", "training:write", "matrix:read", "roles:read",
                   "competencies:read", "signoffs:write"],
    "manager": ["training:read", "training:write", "matrix:read", "roles:read",
                "competencies:read", "people:read", "people:write", "roles:write",
                "competencies:write", "records:write", "tickets:verify", "signoffs:write"],
    "admin": ["*"],
}
# A PIN is short, so a PIN session is for the learner app: your own
# training, whoever signs in with it (seeing it, signing a policy, adding a
# ticket), and for a supervisor, manager or admin, signing off a practical
# on the phone, where the learner is.
PIN_SCOPES = ["training:read", "training:write"]
SIGNS_OFF = ("supervisor", "manager", "admin")


def scopes_for(permission: str, method: str) -> list[str]:
    if method == "pin":
        return PIN_SCOPES + (["signoffs:write"] if permission in SIGNS_OFF else [])
    return list(SCOPES.get(permission, []))


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def start(db: Db, person: Person, method: str, now: datetime | None = None) -> str:
    """A new session; the raw token is returned once and never stored."""
    now = now or datetime.now(UTC)
    raw = PREFIX + secrets.token_urlsafe(32)
    db.add(Session(person_id=person.id, token_hash=_hash(raw), method=method,
                   last_seen_at=now, expires_at=now + LIFETIME[method]))
    db.flush()
    return raw


def alive(db: Db, row: Session, now: datetime | None = None) -> bool:
    """Not ended, not too old and not idle too long; marked as just used."""
    now = now or datetime.now(UTC)
    if (row.revoked_at is not None or row.expires_at <= now
            or now - row.last_seen_at > IDLE[row.method]):
        return False
    if now - row.last_seen_at >= TOUCH_EVERY:
        row.last_seen_at = now
        db.flush()
    return True


def find(db: Db, raw: str, now: datetime | None = None) -> Session | None:
    """The live session for this token, marked as just used; None if it is
    not ours, ended, too old or idle too long."""
    if not raw.startswith(PREFIX):
        return None
    row = db.execute(select(Session).where(Session.token_hash == _hash(raw))).scalar_one_or_none()
    return row if row is not None and alive(db, row, now) else None


def end(db: Db, raw: str) -> None:
    db.execute(update(Session).where(Session.token_hash == _hash(raw),
                                     Session.revoked_at.is_(None))
               .values(revoked_at=datetime.now(UTC)))
    db.flush()


def end_all(db: Db, person: Person, method: str | None = None) -> None:
    """End every session of this person (or only their PIN or password ones)."""
    q = update(Session).where(Session.person_id == person.id, Session.revoked_at.is_(None))
    if method is not None:
        q = q.where(Session.method == method)
    db.execute(q.values(revoked_at=datetime.now(UTC)))
    db.flush()
