"""Links to a module page's picture, PDF or video that an <img>, a
<video> or a new tab can open by themselves: they can't send the session's
token, and the token never goes in a URL. A link names one file and the
session it was made for, and carries an expiry; it is signed with that
session's token hash, which only the database knows. It stops working when
it expires or when the session ends, whichever is first."""
from __future__ import annotations

import hashlib
import hmac
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

from sqlalchemy.orm import Session as Db

from lms.models import Person, Session
from lms.services import sessions

LIFETIME = timedelta(hours=6)
# only a module's files have links: a ticket's photo or a signature is
# someone's own, and is fetched with the token
PURPOSES = {"page-image", "page-pdf", "page-video"}


def _sign(session: Session, upload_id: uuid.UUID, expires: int) -> str:
    message = f"{upload_id}:{session.id}:{expires}".encode()
    return hmac.new(session.token_hash.encode(), message, hashlib.sha256).hexdigest()


def link(session: Session, upload_id: uuid.UUID, now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    expires = int(min(now + LIFETIME, session.expires_at).timestamp())
    query = urlencode({"session": session.id, "expires": expires,
                       "sig": _sign(session, upload_id, expires)})
    return f"/v1/media/{upload_id}?{query}"


def opens(db: Db, upload_id: uuid.UUID, session_id: int, expires: int, sig: str,
          now: datetime | None = None) -> bool:
    """Signed for this file and this session, not expired, and the session
    still live (which counts as using it, as any request does)."""
    now = now or datetime.now(UTC)
    if expires < now.timestamp():
        return False
    session = db.get(Session, session_id)
    if session is None or not hmac.compare_digest(sig, _sign(session, upload_id, expires)):
        return False
    person = db.get(Person, session.person_id)
    return person is not None and person.active and sessions.alive(db, session, now)
