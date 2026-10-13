"""Putting something on the queue the worker drains."""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session as Db

from lms.models import Outbox


def queue_email(db: Db, key: str, to: str, subject: str, text: str,
                now: datetime | None = None) -> bool:
    """Queue an email once: a second time with the same key does nothing.
    True when it was queued now."""
    stmt = insert(Outbox).values(
        kind="email", key=key, payload={"to": to, "subject": subject, "text": text},
        status="pending", attempts=0, next_attempt_at=now or datetime.now(UTC),
    ).on_conflict_do_nothing(index_elements=["key"]).returning(Outbox.id)
    return db.execute(stmt).scalar() is not None
