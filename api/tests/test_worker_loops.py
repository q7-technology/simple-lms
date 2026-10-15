"""Each kind (email, webhook, print) has a loop of its own in the worker, so
a webhook receiver that hangs holds up no email; and the daily job runs in
one of them only."""
import threading
import time
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from lms import worker
from lms.config import get_settings
from lms.models import Outbox, Webhook
from lms.services import events, outbox, webhooks
from trickler import timed

T0 = datetime(2026, 10, 12, 0, 0, tzinfo=UTC)


def test_email_goes_promptly_while_a_webhook_receiver_hangs(engine, db, mailbox, short,
                                                            trickler, monkeypatch):
    monkeypatch.setattr(get_settings(), "worker_send_deadline_seconds", 5.0)
    t = trickler(every=1.0)   # far slower than the deadline: it hangs
    db.add(Webhook(name="Hangs", url=f"http://127.0.0.1:{t.port}/in", secret="s",
                   events=["*"]))
    db.commit()
    for n in range(3):
        events.emit(db, "competency.granted", {"n": n}, now=T0)
    db.commit()
    stop = threading.Event()
    runner = threading.Thread(target=worker.serve, args=(stop,),
                              kwargs={"make_session": lambda: Session(engine), "poll": 0.05,
                                      "daily": False})
    runner.start()
    try:
        time.sleep(0.3)   # the webhook loop is waiting on the receiver now
        for n in range(3):
            outbox.queue_email(db, f"mail{n}", "kim@example.com.au", f"email {n}", "t")
        db.commit()
        start = time.monotonic()
        while len(mailbox.sent) < 3 and time.monotonic() - start < 3:
            time.sleep(0.05)
        assert len(mailbox.sent) == 3
        assert time.monotonic() - start < 2   # not after the receiver's deadline
    finally:
        stop.set()
        start = time.monotonic()
        runner.join(10)
    assert not runner.is_alive()
    assert time.monotonic() - start < 6   # it stops within a send's deadline


def test_after_a_timeout_a_webhooks_other_rows_wait_for_the_next_pass(db, trickler, short):
    t = trickler(every=1.0)
    slow = Webhook(name="Hangs", url=f"http://127.0.0.1:{t.port}/in", secret="s",
                   events=["competency.granted"])
    db.add(slow)
    db.commit()
    for n in range(3):
        events.emit(db, "competency.granted", {"n": n}, now=T0)
    db.commit()
    with webhooks.client() as http:
        tried, took = timed(lambda: worker.send_due(db, http, now=T0, kinds=("webhook",)))
    assert tried == 1 and took < 3.5
    db.expire_all()
    rows = db.query(Outbox).filter_by(webhook_id=slow.id).order_by(Outbox.id).all()
    assert [r.attempts for r in rows] == [1, 0, 0]


def test_the_daily_job_runs_in_one_loop_only(engine, db, monkeypatch):
    runs = []
    # seven in the morning in Melbourne
    monkeypatch.setattr(worker, "clock", lambda: datetime(2026, 10, 11, 20, 0, tzinfo=UTC))
    monkeypatch.setattr(worker.daily, "run", lambda s, day, now: runs.append(day) or
                        {"reminders": 0, "digests": 0, "events": 0})
    stop = threading.Event()
    runner = threading.Thread(target=worker.serve, args=(stop,),
                              kwargs={"make_session": lambda: Session(engine), "poll": 0.05})
    runner.start()
    time.sleep(0.5)
    stop.set()
    runner.join(10)
    assert not runner.is_alive()
    assert len(runs) == 1
