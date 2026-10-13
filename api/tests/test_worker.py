"""The worker sends each email in the outbox, retrying after 1 min, 5, 30
and 2 h, and runs the daily job once a day from LMS_DAILY_HOUR."""
import smtplib
from datetime import UTC, date, datetime, timedelta

import pytest

from conftest import all_at_once
from lms import worker
from lms.config import get_settings
from lms.models import Outbox
from lms.services import outbox

T0 = datetime(2026, 10, 12, 0, 0, tzinfo=UTC)


def queued(db, key="hello", to="kim@example.com.au"):
    outbox.queue_email(db, key, to, "Forklift licence: 30 days left", "Hi Kim", now=T0)
    db.commit()


def row(db, key="hello") -> Outbox:
    db.expire_all()
    return db.query(Outbox).filter_by(key=key).one()


def test_an_email_is_sent_once(db, mailbox):
    queued(db)
    assert worker.send_emails(db, now=T0) == 1
    [msg] = mailbox.sent
    assert (msg["To"], msg["From"], msg["Subject"]) == (
        "kim@example.com.au", "Simple LMS <lms@example.com.au>", "Forklift licence: 30 days left")
    assert msg.get_content().strip() == "Hi Kim"
    assert (row(db).status, row(db).attempts) == ("done", 1)
    assert worker.send_emails(db, now=T0 + timedelta(hours=1)) == 0


def test_the_same_key_is_queued_once(db):
    assert outbox.queue_email(db, "k", "a@example.com.au", "s", "t") is True
    assert outbox.queue_email(db, "k", "a@example.com.au", "s", "t") is False
    db.commit()
    assert db.query(Outbox).count() == 1


def test_emails_wait_until_smtp_is_set_up(db):
    queued(db)
    assert worker.send_emails(db, now=T0) == 0
    assert (row(db).status, row(db).attempts) == ("pending", 0)


def test_it_signs_in_to_the_mail_server_when_told_to(db, mailbox, monkeypatch):
    monkeypatch.setattr(get_settings(), "smtp_user", "lms")
    monkeypatch.setattr(get_settings(), "smtp_password", "app password")
    queued(db)
    worker.send_emails(db, now=T0)
    assert mailbox.logins == [("lms", "app password")]


def test_a_failure_is_tried_again_after_1_5_30_and_120_minutes(db, mailbox):
    queued(db)
    mailbox.refuse = smtplib.SMTPServerDisconnected("Connection unexpectedly closed")
    now = T0
    for wait in (60, 300, 1800, 7200):
        assert worker.send_emails(db, now=now) == 1
        r = row(db)
        assert r.status == "pending" and r.next_attempt_at == now + timedelta(seconds=wait)
        assert r.last_error == "SMTPServerDisconnected: Connection unexpectedly closed"
        # not before its time
        assert worker.send_emails(db, now=now + timedelta(seconds=wait - 1)) == 0
        now += timedelta(seconds=wait)
    worker.send_emails(db, now=now)
    assert (row(db).status, row(db).attempts) == ("failed", 5)
    assert worker.send_emails(db, now=now + timedelta(days=1)) == 0


def test_a_mail_server_that_cannot_be_reached_is_a_failure_not_a_crash(db, mailbox):
    queued(db)
    mailbox.refuse = ConnectionRefusedError(61, "Connection refused")
    worker.send_emails(db, now=T0)
    assert row(db).last_error.startswith("ConnectionRefusedError")


def test_it_comes_good_on_a_later_try(db, mailbox):
    queued(db)
    mailbox.refuse = smtplib.SMTPDataError(451, b"try again later")
    worker.send_emails(db, now=T0)
    mailbox.refuse = None
    worker.send_emails(db, now=T0 + timedelta(minutes=1))
    assert (row(db).status, row(db).attempts, row(db).last_error) == ("done", 2, None)
    assert len(mailbox.sent) == 1


def test_two_workers_at_once_send_each_email_once(db, engine, mailbox):
    from sqlalchemy.orm import Session

    for n in range(6):
        queued(db, key=f"k{n}")

    def one_worker():
        with Session(engine) as s:
            return worker.send_emails(s, now=T0)

    assert sum(all_at_once(2, one_worker)) == 6
    assert len(mailbox.sent) == 6


@pytest.mark.parametrize("utc,due", [
    # 6 am in Melbourne (AEDT, UTC+11) is 7 pm UTC the day before
    (datetime(2026, 10, 11, 18, 59, tzinfo=UTC), None),
    (datetime(2026, 10, 11, 19, 0, tzinfo=UTC), date(2026, 10, 12)),
    (datetime(2026, 10, 12, 12, 59, tzinfo=UTC), date(2026, 10, 12)),
    # just past midnight in Melbourne: a new day, but before six
    (datetime(2026, 10, 12, 13, 30, tzinfo=UTC), None),
])
def test_the_daily_job_is_due_from_six_in_the_morning_where_the_business_is(utc, due):
    assert worker.Daily().due(utc) == due


def test_the_daily_job_runs_once_a_day(db, monkeypatch):
    runs = []
    monkeypatch.setattr(worker.daily, "run", lambda s, day, now: runs.append(day) or
                        {"reminders": 0, "digests": 0})
    today = worker.Daily()
    morning = datetime(2026, 10, 11, 20, 0, tzinfo=UTC)
    worker.run_once(db, today, now=morning)
    worker.run_once(db, today, now=morning + timedelta(hours=3))
    worker.run_once(db, today, now=morning + timedelta(days=1))
    assert runs == [date(2026, 10, 12), date(2026, 10, 13)]


def test_run_once_queues_the_days_emails_then_sends_them(client, db, mailbox, manager_headers,
                                                         learner):
    import yard

    yard.build(client, manager_headers)
    learner.email = "kim@example.com.au"
    db.commit()
    yard.give_roles(client, manager_headers, "LL042", "forklift-operator")
    yard.grant(client, manager_headers, "LL042", "forklift-licence", "2025-01-01",
               expires_on="2026-11-11")
    assert worker.run_once(db, worker.Daily(), now=datetime(2026, 10, 11, 20, 0, tzinfo=UTC)) >= 1
    assert "Forklift licence: 30 days left" in [m["Subject"] for m in mailbox.sent]


def test_the_connection_is_encrypted_as_the_settings_say(monkeypatch):
    from lms.config import Settings
    from lms.services import mail

    made = []

    class SMTP:
        def __init__(self, host, port, timeout, context=None):
            made.append((type(self).__name__, host, port))

        def starttls(self, context):
            made.append("starttls")

    class SMTP_SSL(SMTP):
        pass

    monkeypatch.setattr(mail.smtplib, "SMTP", SMTP)
    monkeypatch.setattr(mail.smtplib, "SMTP_SSL", SMTP_SSL)
    mail.connect(Settings(smtp_host="mail.example.com.au"))
    mail.connect(Settings(smtp_host="mail.example.com.au", smtp_port=465, smtp_security="ssl"))
    mail.connect(Settings(smtp_host="relay", smtp_port=25, smtp_security="none"))
    assert made == [("SMTP", "mail.example.com.au", 587), "starttls",
                    ("SMTP_SSL", "mail.example.com.au", 465), ("SMTP", "relay", 25)]
