"""Keys for other systems, not people: Simple TMS reading who is current,
say. The key is shown once; only its SHA-256 is kept, which is enough for
256 random bits: there is nothing to guess back. A key opens only what its
scopes say, and nothing a person's session does."""
from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session as Db

from lms.models import ApiKey, Person

PREFIX = "lms_k."
# what a key may be given: reading people's status, with the competency API
SCOPES = ("competencies:read",)
# last_used_at is written at most once a minute, as a session's last_seen_at is
TOUCH_EVERY = timedelta(minutes=1)


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def create(db: Db, name: str, scopes: list[str], by: Person) -> tuple[ApiKey, str]:
    """A new key; the raw key is returned once and never stored."""
    raw = PREFIX + secrets.token_urlsafe(32)
    key = ApiKey(name=name, key_hash=_hash(raw), prefix=raw[:len(PREFIX) + 4],
                 scopes=list(scopes), created_by=by)
    db.add(key)
    return key, raw


def find(db: Db, raw: str, now: datetime | None = None) -> ApiKey | None:
    """The key this is, if it is ours and not revoked, marked as just used."""
    now = now or datetime.now(UTC)
    key = db.execute(select(ApiKey).where(ApiKey.key_hash == _hash(raw))).scalar_one_or_none()
    if key is None or key.revoked_at is not None:
        return None
    if key.last_used_at is None or now - key.last_used_at >= TOUCH_EVERY:
        key.last_used_at = now
        db.commit()
    return key
