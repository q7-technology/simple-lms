"""Drains the outbox (emails, for now) and runs the daily job. Run as
`python -m lms.worker`.

A failed try is tried again after 1 min, 5, 30 and 2 h. The try after the
2 h wait is the last: if it fails too, the row is `failed` and stays, with
its last error, for someone to look at.

The daily job runs once a day from the daily hour in the time zone (both
in Settings, or .env), and again whenever the worker starts after that hour: each email it queues has
its own key, so running it twice sends nothing twice.
"""
from __future__ import annotations

import logging
import time
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from lms.config import get_settings
from lms.db import get_sessionmaker
from lms.models import Outbox
from lms.services import daily, mail, settings

log = logging.getLogger("lms.worker")

BACKOFF = (60, 300, 1800, 7200)
# after the daily job fails, how long before it is tried again
DAILY_RETRY = timedelta(minutes=5)


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


def _claim(session: Session, now: datetime) -> Outbox | None:
    """The next row due, locked so a second worker passes it by. One row per
    transaction, so a slow mail server holds up only that row."""
    return session.execute(
        select(Outbox)
        .where(Outbox.status == "pending", Outbox.next_attempt_at <= now)
        .order_by(Outbox.next_attempt_at, Outbox.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    ).scalar_one_or_none()


def _send_one(session: Session, now: datetime | None) -> bool:
    row = _claim(session, now or clock())
    if row is None:
        return False
    try:
        error = mail.send(row.payload)
    except Exception as e:  # a bad row (or password) must not stop the rows after it
        error = f"{type(e).__name__}: {e}"
    # after the answer, not before: a slow server would date it in the past
    answered = now or clock()
    row.attempts += 1
    if error is None:
        # At least once: a crash between the send and the commit sends this
        # email again next time, which is fine for reminders.
        row.status = "done"
        row.done_at = answered
        row.last_error = None
        log.info("email %s sent", row.key)
    else:
        retry_later(row, answered, error)
        log.warning("email %s try %d failed%s: %s", row.key, row.attempts,
                    "; given up" if row.status == "failed" else "", error)
    session.commit()
    return True


def send_emails(session: Session, now: datetime | None = None, limit: int = 50) -> int:
    """Send every email that is due. Returns how many were tried."""
    if not mail.set_up():
        return 0    # they wait, untried, until SMTP is set up
    tried = 0
    while tried < limit and _send_one(session, now):
        tried += 1
    return tried


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


def run_once(session: Session, today: Daily, now: datetime | None = None) -> int:
    """The daily job if it is due, then the emails. Returns how many emails
    were tried."""
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
            log.info("daily job for %s: %d reminders, %d digests queued", day,
                     queued["reminders"], queued["digests"])
    return send_emails(session, now)


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
    s = settings.current()
    log.info("worker started, polling every %ss; daily job from %02d:00 %s", poll,
             s.daily_hour, s.timezone)
    today = Daily()
    while True:
        try:
            with make_session() as session:
                done = run_once(session, today)
        except Exception:  # keep the loop alive; log and back off
            log.exception("worker loop error")
            done = 0
        if done == 0:
            time.sleep(poll)


if __name__ == "__main__":
    main()
