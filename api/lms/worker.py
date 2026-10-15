"""Drains the outbox (emails, events for the webhooks, and print jobs for
Platen) and runs the daily job. Run as `python -m lms.worker`.

A failed try is tried again after 1 min, 5, 30 and 2 h. The try after the
2 h wait is the last: if it fails too, the row is `failed` and stays, with
its last error, for someone to look at.

Each kind (email, webhook, print) has a loop and a thread of its own, each
claiming its own rows, so a Monday's pile of reminders doesn't hold up an
event another system is waiting on, nor a receiver that hangs the emails;
and a row that fails waits for its next try without holding up the rows
after it. Every send is done within the deadline (LMS_WORKER_SEND_DEADLINE_
SECONDS), and after a webhook gives no answer in time its other events wait
for the next pass, so one dead receiver costs the others one deadline a
pass, not one each.

The daily job runs in the main thread, once a day from the daily hour in
the time zone (both in Settings, or .env), and again whenever the worker
starts after that hour: each email it queues has its own key, and each
event it fires is fired once, so running it twice sends nothing twice.

SIGTERM or SIGINT stops it: each loop finishes the send it is on (within
the deadline) and the worker exits.
"""
from __future__ import annotations

import logging
import signal
import threading
import time
from collections.abc import Callable, Collection
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from lms.config import get_settings
from lms.db import get_sessionmaker
from lms.models import Outbox
from lms.services import daily, mail, printing, settings, webhooks
from lms.services.outbox import GiveUp

log = logging.getLogger("lms.worker")

BACKOFF = (60, 300, 1800, 7200)
# after the daily job fails, how long before it is tried again
DAILY_RETRY = timedelta(minutes=5)
# what the outbox holds, in the order each takes its turn
KINDS = ("email", "webhook", "print")


def clock() -> datetime:
    return datetime.now(UTC)


def retry_later(row: Outbox, now: datetime, error: str) -> None:
    """After a failed try: wait the next step of the backoff, or give up once
    the try after the last wait has failed. attempts has counted this try."""
    row.last_error = error[:500]
    if row.attempts > len(BACKOFF):
        row.status = "failed"
    else:
        row.next_attempt_at = now + timedelta(seconds=BACKOFF[row.attempts - 1])


def _claim(session: Session, kind: str, now: datetime,
           passed_by: Collection[int] = ()) -> Outbox | None:
    """The next row of this kind that is due, locked so a second worker (or
    loop) passes it by, and not for a webhook `passed_by` this pass. One row
    per transaction, so a slow mail server or receiver holds up only that
    row."""
    query = select(Outbox).where(Outbox.kind == kind, Outbox.status == "pending",
                                 Outbox.next_attempt_at <= now)
    if passed_by:
        query = query.where(Outbox.webhook_id.not_in(passed_by))
    return session.execute(
        query.order_by(Outbox.next_attempt_at, Outbox.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    ).scalar_one_or_none()


def _ready(kind: str) -> bool:
    """Emails wait, untried, until SMTP is set up, and print jobs until
    Platen is; events always go."""
    if kind == "email":
        return mail.set_up()
    if kind == "print":
        return printing.set_up()
    return True


# the client each kind posts with (none for an email)
Clients = dict[str, "httpx.Client | None"]


def _send(kind: str, clients: Clients, row: Outbox) -> str | None:
    if kind == "email":
        return mail.send(row.payload)
    if kind == "print":
        return printing.send(clients["print"], row)
    return webhooks.deliver(clients["webhook"], row)


def _send_one(session: Session, kind: str, clients: Clients, now: datetime | None,
              passed_by: set[int]) -> bool:
    """Send the next row of this kind that is due, if there is one. A
    webhook that gives no answer in time goes into `passed_by`."""
    row = _claim(session, kind, now or clock(), passed_by)
    if row is None:
        return False
    give_up = False
    try:
        error = _send(kind, clients, row)
    except GiveUp as e:
        error, give_up = str(e), True
    except Exception as e:  # a bad row (or password) must not stop the rows after it
        error = f"{type(e).__name__}: {e}"
    # after the answer, not before: a slow server would date it in the past
    answered = now or clock()
    if isinstance(error, webhooks.TimedOut):
        passed_by.add(row.webhook_id)
    row.attempts += 1
    if error is None:
        # At least once: a crash between the send and the commit sends it
        # again next time. Reminders don't mind; a receiver goes by event_id.
        row.status = "done"
        row.done_at = answered
        row.last_error = None
        log.info("%s %s sent", kind, row.key)
    elif give_up:
        row.status = "failed"
        row.last_error = error[:500]
        log.warning("%s %s given up: %s", kind, row.key, error)
    else:
        retry_later(row, answered, error)
        log.warning("%s %s try %d failed%s: %s", kind, row.key, row.attempts,
                    "; given up" if row.status == "failed" else "", error)
    session.commit()
    return True


def _drain(session: Session, clients: Clients, now: datetime | None, limit: int,
           kinds: list[str]) -> int:
    tried = dict.fromkeys(kinds, 0)
    passed_by: set[int] = set()   # webhooks that gave no answer in time, this pass
    while kinds:
        for kind in list(kinds):
            if tried[kind] < limit and _send_one(session, kind, clients, now, passed_by):
                tried[kind] += 1
            else:
                kinds.remove(kind)
    return sum(tried.values())


def send_due(session: Session, http: httpx.Client | None = None, now: datetime | None = None,
             limit: int = 50, kinds: tuple[str, ...] = KINDS,
             print_http: httpx.Client | None = None) -> int:
    """Send what is due, a row of each kind in turn, up to `limit` of each.
    `http` posts the events (and the print jobs, unless `print_http` is
    given); without one, the guarded webhook client and Platen's own are
    made for this pass. Returns how many were tried."""
    ready = [k for k in kinds if _ready(k)]
    if http is None and any(k != "email" for k in ready):
        with webhooks.client() as hooks, printing.client() as platen:
            return _drain(session, {"webhook": hooks, "print": platen}, now, limit, ready)
    return _drain(session, {"webhook": http, "print": print_http or http}, now, limit, ready)


def send_emails(session: Session, now: datetime | None = None, limit: int = 50) -> int:
    """Send every email that is due, and nothing else. Returns how many were tried."""
    return send_due(session, None, now, limit, kinds=("email",))


class Daily:
    """Remembers the last day the daily job ran in this worker."""

    def __init__(self) -> None:
        self.last: date | None = None
        self.not_before: datetime | None = None   # set when it last failed

    def due(self, now: datetime) -> date | None:
        """Today in the time zone, if the job is due: past the daily hour,
        not yet run today, and not failed in the last few minutes. Both are
        read each time, so a change in Settings needs no restart."""
        s = settings.current()
        local = now.astimezone(ZoneInfo(s.timezone))
        if local.hour < s.daily_hour or local.date() == self.last:
            return None
        if self.not_before is not None and now < self.not_before:
            return None
        return local.date()


def run_daily(session: Session, today: Daily, now: datetime | None = None) -> None:
    """The daily job, if it is due."""
    day = today.due(now or clock())
    if day is not None:
        try:
            queued = daily.run(session, day, now)
        except Exception:  # the emails already queued still go
            log.exception("daily job for %s failed; trying again in %s", day, DAILY_RETRY)
            # set first: a dead connection can make the rollback raise as well
            today.not_before = (now or clock()) + DAILY_RETRY
            session.rollback()
        else:
            today.last = day
            today.not_before = None
            log.info("daily job for %s: %d reminders, %d digests, %d events queued", day,
                     queued["reminders"], queued["digests"], queued["events"])


def run_once(session: Session, today: Daily, now: datetime | None = None,
             http: httpx.Client | None = None, print_http: httpx.Client | None = None) -> int:
    """The daily job if it is due, then whatever is due in the outbox, in
    one pass. Returns how many rows were tried."""
    run_daily(session, today, now)
    return send_due(session, http, now, print_http=print_http)


def wait_for_schema(session: Session, timeout: float = 120, poll: float = 2) -> None:
    """Block until the api container has run the migrations."""
    from sqlalchemy.exc import ProgrammingError

    deadline = time.monotonic() + timeout
    while True:
        try:
            session.execute(select(Outbox.id).limit(1))
            return
        except ProgrammingError:
            session.rollback()
            if time.monotonic() >= deadline:
                raise TimeoutError("outbox never appeared; did the migrations run?")
            log.info("waiting for migrations")
            time.sleep(poll)


MakeSession = Callable[[], Session]


def _loop(kind: str, stop: threading.Event, make_session: MakeSession, poll: float) -> None:
    """Send this kind until told to stop, with a client of its own."""
    with webhooks.client() as hooks, printing.client() as platen:
        clients: Clients = {"webhook": hooks, "print": platen}
        while not stop.is_set():
            try:
                with make_session() as session:
                    ready = [kind] if _ready(kind) else []
                    done = _drain(session, clients, None, 50, ready)
            except Exception:  # keep the loop alive; log and back off
                log.exception("%s loop error", kind)
                done = 0
            if done == 0:
                stop.wait(poll)


def serve(stop: threading.Event, make_session: MakeSession | None = None,
          poll: float | None = None, daily: bool = True) -> None:
    """A loop per kind, each in its own thread, and the daily job (unless
    `daily` is False) in this one, until `stop` is set; then wait for the
    loops to finish what they are sending."""
    make_session = make_session or get_sessionmaker()
    poll = get_settings().worker_poll_seconds if poll is None else poll
    loops = [threading.Thread(target=_loop, args=(kind, stop, make_session, poll),
                              name=f"worker-{kind}") for kind in KINDS]
    for t in loops:
        t.start()
    today = Daily()
    try:
        while not stop.is_set():
            if daily:
                try:
                    with make_session() as session:
                        run_daily(session, today)
                except Exception:
                    log.exception("daily loop error")
            stop.wait(poll)
    finally:
        stop.set()
        for t in loops:
            t.join()


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(threadName)s %(message)s")
    poll = get_settings().worker_poll_seconds
    make_session = get_sessionmaker()
    with make_session() as session:
        wait_for_schema(session)
    if not mail.set_up():
        log.warning("no email server (Settings, or LMS_SMTP_HOST and LMS_SMTP_FROM): emails "
                    "wait in the outbox until one is set")
    if get_settings().webhook_allow_private:
        log.warning("LMS_WEBHOOK_ALLOW_PRIVATE is set: webhooks may go to addresses on this "
                    "machine and the local network")
    s = settings.current()
    log.info("worker started, polling every %ss; daily job from %02d:00 %s", poll,
             s.daily_hour, s.timezone)
    stop = threading.Event()

    def stopping(signum, frame):
        log.info("stopping: finishing what is being sent")
        stop.set()

    signal.signal(signal.SIGTERM, stopping)
    signal.signal(signal.SIGINT, stopping)
    serve(stop, make_session, poll)
    log.info("worker stopped")


if __name__ == "__main__":
    main()
