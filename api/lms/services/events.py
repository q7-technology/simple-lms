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

from lms.models import Competency, CompetencyRecord, EventSeen, Outbox, Person, Webhook
from lms.services import clock, standing
from lms.services.status import Status, expiry

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


# --- what each event says ----------------------------------------------------

def person_ref(p: Person) -> dict:
    return {"code": p.code, "name": p.name}


def competency_ref(c: Competency) -> dict:
    return {"key": c.key, "name": c.name, "kind": c.kind}


def _iso(d) -> str | None:
    return d.isoformat() if d is not None else None


def status_now(db: Db, person_id: int, competency_id: int) -> Status:
    """status.py's word on it as it stands in this transaction, as the
    competency API would answer."""
    st = standing.load(db, [person_id], clock.today())
    if competency_id not in st.competencies:
        return Status("not_required")
    return st.status(person_id, competency_id)


# TODO(step 4): fire competency.granted for a sign-off grant. Where step 4's
# sign-off route adds the CompetencyRecord for a practical signed off, call
# events.granted(db, r) after db.add(r) and before db.commit(), as records.py,
# tickets.py, policies.py and learning.py do, and add its test to
# tests/test_competency_events.py (the TODO there).
def granted(db: Db, r: CompetencyRecord) -> uuid.UUID:
    """competency.granted, for a grant just added: by hand, a ticket checked,
    a policy signed, a module passed or a practical signed off. Call it
    after db.add(r) and before the commit, so the event is kept only with
    the grant."""
    db.flush()
    c = db.get(Competency, r.competency_id)
    return emit(db, "competency.granted", {
        "person": person_ref(db.get(Person, r.person_id)), "competency": competency_ref(c),
        "record_id": r.id, "granted_on": _iso(r.granted_on),
        # its last good day, worked out as status.py does: the card's date,
        # or the refresher after the grant, or none
        "expires_on": _iso(expiry(r.granted_on, r.expires_on, c.refresher_months)),
        "status": status_now(db, r.person_id, r.competency_id).status,
        "recorded_by": person_ref(db.get(Person, r.recorded_by_id)),
    })


def revoked(db: Db, r: CompetencyRecord) -> uuid.UUID:
    """competency.revoked, for a revoke just added, with why."""
    db.flush()
    return emit(db, "competency.revoked", {
        "person": person_ref(db.get(Person, r.person_id)),
        "competency": competency_ref(db.get(Competency, r.competency_id)),
        "record_id": r.id, "note": r.note,
        "status": status_now(db, r.person_id, r.competency_id).status,
        "recorded_by": person_ref(db.get(Person, r.recorded_by_id)),
    })


def person_updated(db: Db, p: Person) -> uuid.UUID:
    """person.updated: what another system keeps about a person, as it is
    now. Added, details changed, roles changed, deactivated or back; never
    a PIN or password."""
    return emit(db, "person.updated", {"person": {
        "code": p.code, "name": p.name, "email": p.email, "permission": p.permission,
        "active": p.active,
        "supervisor": person_ref(p.supervisor) if p.supervisor else None,
        "roles": [{"key": r.key, "name": r.name} for r in p.roles],
    }})
