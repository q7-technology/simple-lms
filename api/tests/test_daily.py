"""The daily job: reminders at 30, 14 and 0 days to learners with an email,
and a digest of what is expiring and lapsed for each manager on Mondays.
Each is queued once, however often the job runs."""
from datetime import date

import pytest

import yard
from conftest import make_person
from lms.config import get_settings
from lms.models import EventSeen, Outbox, Webhook
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
    assert emails(db) == [("kim@example.com.au", "Forklift licence: 9 days left")]
    on(db, date(2026, 11, 3))   # the 14-day one has gone, so nothing more until the day
    assert len(emails(db)) == 1


def test_the_reminder_says_the_real_days_left_not_the_tier(db, kim):
    on(db, date(2026, 11, 2))
    text = db.query(Outbox).filter(Outbox.key.startswith("reminder")).one().payload["text"]
    assert "Your Forklift licence is good until 11 Nov 2026, 9 days from now." in text


def test_one_day_left_is_tomorrow(db, kim):
    on(db, date(2026, 11, 10))   # missed until the day before: the 14-day one, said as tomorrow
    assert emails(db) == [("kim@example.com.au", "Forklift licence: tomorrow is its last day")]
    text = db.query(Outbox).filter(Outbox.key.startswith("reminder")).one().payload["text"]
    assert "Your Forklift licence is good until the end of tomorrow, 11 Nov 2026." in text


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
                                          "Forklift licence: 29 days left"]


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


def test_the_reminder_days_are_a_setting(db, kim, admin):
    from lms.services import settings

    settings.save(db, {"reminder_days": [7, 0]}, admin)
    on(db, MONDAY, date(2026, 10, 28))     # 30 and 14 days left: no reminder now
    assert emails(db) == []
    on(db, date(2026, 11, 4), date(2026, 11, 5))
    assert emails(db) == [("kim@example.com.au", "Forklift licence: 7 days left")]
    # the key keeps its shape: person, competency, last good day, reminder day
    db.expire_all()
    assert db.query(Outbox).filter(Outbox.key.startswith("reminder")).one().key.endswith(
        ":2026-11-11:7")


def test_a_reminder_day_beyond_30_reminds_while_still_current(db, kim, admin):
    from lms.services import settings

    settings.save(db, {"reminder_days": [60, 0]}, admin)
    on(db, date(2026, 9, 12), date(2026, 9, 20))     # 60 days left, still current
    assert emails(db) == [("kim@example.com.au", "Forklift licence: 60 days left")]


def test_a_key_queued_before_the_change_still_counts(db, kim, admin):
    from lms.services import settings

    on(db, MONDAY)                                          # the 30-day one, as before
    settings.save(db, {"reminder_days": [30, 21, 0]}, admin)
    on(db, date(2026, 10, 15))                              # 27 days left: still the 30
    assert len(emails(db)) == 1


def test_the_web_address_set_here_goes_in_the_email(db, kim, admin):
    from lms.services import settings

    settings.save(db, {"public_url": "https://lms.example.com.au"}, admin)
    on(db, MONDAY)
    text = db.query(Outbox).filter(Outbox.key.startswith("reminder")).one().payload["text"]
    assert "Open Simple LMS: https://lms.example.com.au/learn/" in text


# --- competency.expiring and competency.lapsed -------------------------------

@pytest.fixture
def hook(db):
    db.add(Webhook(name="Simple TMS", url="https://tms.example.com.au/in", secret="whsec_x",
                   events=["competency.expiring", "competency.lapsed"]))
    db.commit()


def told(db) -> list[tuple[str, str, str]]:
    db.expire_all()
    rows = db.query(Outbox).filter_by(kind="webhook").order_by(Outbox.id).all()
    return [(r.payload["event_type"], r.payload["data"]["competency"]["key"],
             r.payload["data"]["expires_on"]) for r in rows]


def test_expiring_then_lapsed_each_once(db, kim, hook):
    on(db, MONDAY, MONDAY, date(2026, 10, 28), date(2026, 11, 11))
    assert told(db) == [("competency.expiring", "forklift-licence", "2026-11-11")]
    on(db, date(2026, 11, 12), date(2026, 11, 13), date(2026, 12, 25))
    assert told(db)[1:] == [("competency.lapsed", "forklift-licence", "2026-11-11")]


def test_what_expiring_says(db, kim, hook):
    on(db, MONDAY)
    [row] = db.query(Outbox).filter_by(kind="webhook").all()
    assert row.payload["data"] == {
        "person": {"code": "LL042", "name": "Kim Lee"},
        "competency": {"key": "forklift-licence", "name": "Forklift licence", "kind": "ticket"},
        "status": "expiring", "granted_on": "2025-01-01", "expires_on": "2026-11-11",
        "days_left": 30}
    assert row.payload["event_id"] == str(db.query(EventSeen).one().event_id)


def test_a_renewal_is_told_afresh(client, db, manager_headers, kim, hook):
    on(db, MONDAY)
    yard.grant(client, manager_headers, "LL042", "forklift-licence", "2026-10-12",
               expires_on="2026-11-30")
    on(db, date(2026, 11, 1))
    assert told(db) == [("competency.expiring", "forklift-licence", "2026-11-11"),
                        ("competency.expiring", "forklift-licence", "2026-11-30")]


def test_a_lapse_the_job_first_sees_late_is_told_as_lapsed_only(db, kim, hook):
    on(db, date(2026, 11, 20))
    assert told(db) == [("competency.lapsed", "forklift-licence", "2026-11-11")]


def test_fired_once_whoever_was_listening(db, kim):
    on(db, MONDAY)
    assert db.query(EventSeen).count() == 1
    db.add(Webhook(name="Late", url="https://late.example.com.au", secret="s", events=["*"]))
    db.commit()
    on(db, MONDAY)
    assert told(db) == []


def test_not_for_a_waiver_nor_someone_deactivated(client, db, manager_headers, kim, hook):
    client.post("/v1/people/LL042/overrides", headers=manager_headers,
                json={"competency": "forklift-licence", "kind": "waive", "note": "office only now"})
    make_person(db, "LL043", "Ash Patel")
    yard.give_roles(client, manager_headers, "LL043", "picker")
    yard.grant(client, manager_headers, "LL043", "site-induction", "2024-09-01")   # lapsed
    client.post("/v1/people/LL043/deactivate", headers=manager_headers)
    on(db, MONDAY)
    assert told(db) == []


def test_it_says_how_many_it_fired(db, kim, hook):
    assert daily.run(db, MONDAY)["events"] == 1
    assert daily.run(db, MONDAY)["events"] == 0
