"""Webhooks, their deliveries, API keys and the events the daily job has
fired: what the database itself holds to."""
import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from conftest import make_person
from lms.models import ApiKey, EventSeen, Outbox, Webhook


def hook(**more) -> Webhook:
    return Webhook(**{"name": "Simple TMS", "url": "https://tms.example.com.au/lms-events",
                      "secret": "whsec_x", "events": ["*"], **more})


@pytest.mark.parametrize("row, constraint", [
    ({"url": "ftp://tms.example.com.au"}, "ck_webhook_url"),
    ({"url": "tms.example.com.au/lms-events"}, "ck_webhook_url"),
    ({"events": []}, "ck_webhook_events"),
])
def test_a_webhook_has_a_web_address_and_wants_something(db, row, constraint):
    db.add(hook(**row))
    with pytest.raises(IntegrityError, match=constraint):
        db.commit()


def test_two_webhooks_have_two_names(db):
    db.add(hook())
    db.commit()
    db.add(hook(url="https://other.example.com.au"))
    with pytest.raises(IntegrityError, match="uq_webhook_name"):
        db.commit()


def test_a_delivery_names_its_webhook_and_an_email_names_none(db):
    w = hook()
    db.add(w)
    db.commit()
    db.add(Outbox(kind="webhook", key="event:1", payload={}))
    with pytest.raises(IntegrityError, match="ck_outbox_webhook"):
        db.commit()
    db.rollback()
    db.add(Outbox(kind="email", key="email:1", payload={}, webhook_id=w.id))
    with pytest.raises(IntegrityError, match="ck_outbox_webhook"):
        db.commit()
    db.rollback()
    db.add_all([Outbox(kind="webhook", key="event:2", payload={}, webhook_id=w.id),
                Outbox(kind="print", key="print:1", payload={})])
    db.commit()


def test_the_outbox_holds_emails_deliveries_and_print_jobs_only(db):
    db.add(Outbox(kind="sms", key="sms:1", payload={}))
    with pytest.raises(IntegrityError, match="ck_outbox_kind"):
        db.commit()


def test_an_event_is_seen_once(db):
    db.add(EventSeen(key="competency.lapsed:4:2:2026-10-11", event_id=uuid.uuid4()))
    db.commit()
    db.add(EventSeen(key="competency.lapsed:4:2:2026-10-11", event_id=uuid.uuid4()))
    with pytest.raises(IntegrityError, match="pk_event_seen"):
        db.commit()


def test_an_api_key_is_given_a_scope(db):
    admin = make_person(db, "AD001", "Leighton Lauton", "admin")
    db.add(ApiKey(name="Simple TMS", key_hash="0" * 64, prefix="lms_k.abcd", scopes=[],
                  created_by_id=admin.id))
    with pytest.raises(IntegrityError, match="ck_api_key_scopes"):
        db.commit()
