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
# (users, sign-in settings, webhooks, API keys) arrive with their steps.
# training:write is doing your own training: signing a policy, adding a
# ticket. tickets:verify is checking someone else's ticket.
SCOPES: dict[str, list[str]] = {
    "learner": ["training:read", "training:write"],
    "supervisor": ["training:read", "training:write", "matrix:read", "roles:read",
                   "competencies:read"],
    "manager": ["training:read", "training:write", "matrix:read", "roles:read",
                "competencies:read", "people:read", "people:write", "roles:write",
                "competencies:write", "records:write", "tickets:verify"],
    "admin": ["*"],
}
# A PIN is short, so a PIN session is for the learner app's own training,
# whoever signs in with it: seeing it, signing a policy, adding a ticket.
PIN_SCOPES = ["training:read", "training:write"]


def scopes_for(permission: str, method: str) -> list[str]:
    if method == "pin":
        return list(PIN_SCOPES)
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


def find(db: Db, raw: str, now: datetime | None = None) -> Session | None:
    """The live session for this token, marked as just used; None if it is
    not ours, ended, too old or idle too long."""
    if not raw.startswith(PREFIX):
        return None
    now = now or datetime.now(UTC)
    row = db.execute(select(Session).where(Session.token_hash == _hash(raw))).scalar_one_or_none()
    if (row is None or row.revoked_at is not None or row.expires_at <= now
            or now - row.last_seen_at > IDLE[row.method]):
        return None
    if now - row.last_seen_at >= TOUCH_EVERY:
        row.last_seen_at = now
        db.flush()
    return row


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
