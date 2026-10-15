"""Events out, as Simple WMS sends its own: one envelope per event, queued
for each webhook that wants it, in the transaction that made it happen (so
nothing is told of a change that was never kept), and signed by the worker
on the way out. Nothing is sent here."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session as Db

from lms.models import EventSeen, Outbox, Webhook

EVENT_TYPES = ("competency.granted", "competency.revoked", "competency.expiring",
               "competency.lapsed", "person.updated")


def iso_utc(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def wants(hook: Webhook, event_type: str) -> bool:
    return "*" in hook.events or event_type in hook.events


def emit(db: Db, event_type: str, data: dict, now: datetime | None = None,
         event_id: uuid.UUID | None = None) -> uuid.UUID:
    """Queue the event for every webhook switched on that wants it. Returns
    its id, the same for every webhook, so a receiver told twice knows."""
    now = now or datetime.now(UTC)
    event_id = event_id or uuid.uuid4()
    envelope = {"event_id": str(event_id), "event_type": event_type,
                "occurred_at": iso_utc(now), "data": data}
    hooks = db.execute(select(Webhook).where(Webhook.active.is_(True))
                       .order_by(Webhook.id)).scalars()
    for hook in hooks:
        if wants(hook, event_type):
            db.add(Outbox(kind="webhook", key=f"event:{event_id}:{hook.id}", webhook_id=hook.id,
                          payload=envelope, status="pending", attempts=0, next_attempt_at=now))
    db.flush()
    return event_id


def once(db: Db, key: str, event_type: str, data: dict, now: datetime | None = None) -> bool:
    """Fire it unless it has been fired already, whoever was listening then:
    the daily job's expiring and lapsed, each once (rule 2). True when it
    fired now."""
    event_id = uuid.uuid4()
    seen = db.execute(insert(EventSeen).values(key=key, event_id=event_id)
                      .on_conflict_do_nothing(index_elements=["key"])
                      .returning(EventSeen.key)).scalar()
    if seen is None:
        return False
    emit(db, event_type, data, now, event_id)
    return True
