"""Events out: one envelope per event, queued for each webhook that wants
it, in the same transaction as what made it happen."""
import uuid
from datetime import UTC, datetime

from lms.models import EventSeen, Outbox, Webhook
from lms.services import events

AT = datetime(2026, 10, 12, 1, 30, tzinfo=UTC)


def hooks(db, *wanted: list[str], active=True) -> list[Webhook]:
    rows = [Webhook(name=f"Hook {i}", url=f"https://h{i}.example.com.au/in", secret=f"whsec_{i}",
                    events=w, active=active) for i, w in enumerate(wanted)]
    db.add_all(rows)
    db.commit()
    return rows


def deliveries(db) -> list[Outbox]:
    db.expire_all()
    return db.query(Outbox).filter_by(kind="webhook").order_by(Outbox.id).all()


def test_one_envelope_for_each_webhook_that_wants_it(db):
    tms, wms, other = hooks(db, ["*"], ["competency.granted"], ["person.updated"])
    event_id = events.emit(db, "competency.granted", {"person": {"code": "LL042"}}, now=AT)
    db.commit()
    rows = deliveries(db)
    assert [r.webhook_id for r in rows] == [tms.id, wms.id]
    assert rows[0].payload == rows[1].payload == {
        "event_id": str(event_id), "event_type": "competency.granted",
        "occurred_at": "2026-10-12T01:30:00Z", "data": {"person": {"code": "LL042"}}}
    assert [r.key for r in rows] == [f"event:{event_id}:{tms.id}", f"event:{event_id}:{wms.id}"]
    assert all(r.status == "pending" and r.next_attempt_at == AT for r in rows)


def test_a_webhook_turned_off_hears_nothing(db):
    hooks(db, ["*"], active=False)
    events.emit(db, "person.updated", {}, now=AT)
    db.commit()
    assert deliveries(db) == []


def test_nothing_is_queued_unless_what_caused_it_is_kept(db):
    hooks(db, ["*"])
    events.emit(db, "person.updated", {}, now=AT)
    db.rollback()
    assert deliveries(db) == []


def test_once_fires_once_whoever_is_listening(db):
    assert events.once(db, "competency.lapsed:4:2:2026-10-11", "competency.lapsed", {}, now=AT)
    db.commit()
    hooks(db, ["*"])
    # a webhook added since isn't told of what was fired before it
    assert not events.once(db, "competency.lapsed:4:2:2026-10-11", "competency.lapsed", {})
    db.commit()
    assert deliveries(db) == []
    seen = db.query(EventSeen).one()
    assert isinstance(seen.event_id, uuid.UUID)


def test_once_names_the_event_it_fired(db):
    hooks(db, ["competency.expiring"])
    events.once(db, "competency.expiring:4:2:2026-11-11", "competency.expiring", {"x": 1}, now=AT)
    db.commit()
    [row] = deliveries(db)
    assert row.payload["event_id"] == str(db.query(EventSeen).one().event_id)


def test_the_catalogue():
    assert events.EVENT_TYPES == ("competency.granted", "competency.revoked",
                                  "competency.expiring", "competency.lapsed", "person.updated")
