"""Drains the outbox (emails, events for the webhooks, and print jobs for
Platen) and runs the daily job. Run as `python -m lms.worker`.

A failed try is tried again after 1 min, 5, 30 and 2 h. The try after the
2 h wait is the last: if it fails too, the row is `failed` and stays, with
its last error, for someone to look at.

Each kind takes its turn, a row at a time, so a Monday's pile of reminders
doesn't hold up an event another system is waiting on, nor the other way
round; and a row that fails waits for its next try without holding up the
rows after it.

The daily job runs once a day from the daily hour in the time zone (both
in Settings, or .env), and again whenever the worker starts after that
hour: each email it queues has its own key, and each event it fires is
fired once, so running it twice sends nothing twice.
"""
from __future__ import annotations

import logging
import time
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


def _claim(session: Session, kind: str, now: datetime) -> Outbox | None:
    """The next row of this kind that is due, locked so a second worker
    passes it by. One row per transaction, so a slow mail server or
    receiver holds up only that row."""
    return session.execute(
        select(Outbox)
        .where(Outbox.kind == kind, Outbox.status == "pending", Outbox.next_attempt_at <= now)
        .order_by(Outbox.next_attempt_at, Outbox.id)
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


def _send_one(session: Session, kind: str, clients: Clients, now: datetime | None) -> bool:
    """Send the next row of this kind that is due, if there is one."""
    row = _claim(session, kind, now or clock())
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
    while kinds:
        for kind in list(kinds):
            if tried[kind] < limit and _send_one(session, kind, clients, now):
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


def run_once(session: Session, today: Daily, now: datetime | None = None,
             http: httpx.Client | None = None, print_http: httpx.Client | None = None) -> int:
    """The daily job if it is due, then whatever is due in the outbox.
    Returns how many rows were tried."""
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


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
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
    today = Daily()
    # events only to public addresses (unless LMS_WEBHOOK_ALLOW_PRIVATE);
    # Platen wherever its address in Settings says
    with webhooks.client() as http, printing.client() as print_http:
        while True:
            try:
                with make_session() as session:
                    done = run_once(session, today, http=http, print_http=print_http)
            except Exception:  # keep the loop alive; log and back off
                log.exception("worker loop error")
                done = 0
            if done == 0:
                time.sleep(poll)


if __name__ == "__main__":
    main()
