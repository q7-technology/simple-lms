"""The daily job: reminders at 30, 14 and 0 days to learners with an email,
and a digest of what is expiring and lapsed for each manager on Mondays.
Each is queued once, however often the job runs."""
from datetime import date

import pytest

import yard
from conftest import make_person
from lms.config import get_settings
from lms.models import Outbox
from lms.services import daily

MONDAY = date(2026, 10, 12)


@pytest.fixture
def kim(client, db, manager_headers, learner):
    """Kim has an email; her forklift licence is good until 11 Nov 2026,
    30 days after the Monday the tests start on."""
    yard.build(client, manager_headers)
    learner.email = "kim@example.com.au"
    db.commit()
    yard.give_roles(client, manager_headers, "LL042", "forklift-operator")
    yard.grant(client, manager_headers, "LL042", "forklift-licence", "2025-01-01",
               expires_on="2026-11-11")
    yard.grant(client, manager_headers, "LL042", "site-induction", "2026-01-01")
    return learner


def emails(db, prefix="reminder"):
    db.expire_all()
    rows = db.query(Outbox).filter(Outbox.key.startswith(prefix)).order_by(Outbox.id).all()
    return [(r.payload["to"], r.payload["subject"]) for r in rows]


def on(db, *days):
    for d in days:
        daily.run(db, d)


def test_reminders_at_30_14_and_0_days_each_once(db, kim):
    on(db, date(2026, 10, 12), date(2026, 10, 12), date(2026, 10, 20))
    assert emails(db) == [("kim@example.com.au", "Forklift licence: 30 days left")]
    on(db, date(2026, 10, 28), date(2026, 11, 5))
    assert emails(db)[1:] == [("kim@example.com.au", "Forklift licence: 14 days left")]
    on(db, date(2026, 11, 11), date(2026, 11, 12), date(2026, 12, 1))
    assert emails(db)[2:] == [("kim@example.com.au", "Forklift licence: today is its last day")]


def test_a_day_the_worker_missed_still_gets_the_reminder_it_owed(db, kim):
    on(db, date(2026, 11, 2))   # 9 days left: the 14-day one, not the 30
    assert emails(db) == [("kim@example.com.au", "Forklift licence: 14 days left")]


def test_what_the_reminder_says(db, kim, monkeypatch):
    monkeypatch.setattr(get_settings(), "public_url", "https://lms.example.com.au")
    on(db, MONDAY)
    text = db.query(Outbox).filter(Outbox.key.startswith("reminder")).one().payload["text"]
    assert text.startswith("Hi Kim Lee,\n\nYour Forklift licence is good until 11 Nov 2026, "
                           "30 days from now.")
    assert "Open Simple LMS: https://lms.example.com.au/learn/" in text


def test_no_email_no_reminder(db, kim):
    kim.email = None
    db.commit()
    on(db, MONDAY)
    assert emails(db) == []


def test_a_renewed_ticket_is_reminded_afresh(client, db, manager_headers, kim):
    on(db, MONDAY)
    yard.grant(client, manager_headers, "LL042", "forklift-licence", "2026-10-12",
               expires_on="2026-11-30")
    on(db, date(2026, 11, 1))
    assert [s for _, s in emails(db)] == ["Forklift licence: 30 days left",
                                          "Forklift licence: 30 days left"]


def test_a_waived_one_is_not_reminded(client, db, manager_headers, kim):
    client.post("/v1/people/LL042/overrides", headers=manager_headers,
                json={"competency": "forklift-licence", "kind": "waive", "note": "office only now"})
    on(db, MONDAY)
    assert emails(db) == []


def test_managers_get_a_digest_on_mondays(client, db, manager_headers, kim):
    make_person(db, "LL043", "Ash Patel", email="ash@example.com.au")
    yard.give_roles(client, manager_headers, "LL043", "picker")
    yard.grant(client, manager_headers, "LL043", "site-induction", "2024-09-01")   # lapsed
    on(db, MONDAY, MONDAY)
    assert emails(db, "digest") == [("mel@example.com.au", "Training this week: 1 lapsed, 1 expiring")]
    text = db.query(Outbox).filter(Outbox.key.startswith("digest")).one().payload["text"]
    assert "Lapsed:\n- Ash Patel (LL043): Site induction, ran out after 1 Sep 2026" in text
    assert ("Expiring in the next 30 days:\n- Kim Lee (LL042): Forklift licence, good until "
            "11 Nov 2026") in text
    on(db, date(2026, 10, 13))   # a Tuesday
    assert len(emails(db, "digest")) == 1
    on(db, date(2026, 10, 19))   # the next Monday
    assert len(emails(db, "digest")) == 2


def test_no_digest_when_nothing_is_due(db, manager):
    on(db, MONDAY)
    assert emails(db, "digest") == []


def test_reminder_days():
    assert [daily.reminder_for(d) for d in (30, 29, 15, 14, 1, 0)] == [30, 30, 30, 14, 14, 0]
