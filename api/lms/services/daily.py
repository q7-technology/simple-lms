"""The daily job, run by the worker each morning: a reminder to each
learner with an email when something of theirs reaches a reminder day
(Settings; 30, 14 and 0 days left unless changed), on Mondays a digest of
what is expiring and lapsed for each manager, and competency.expiring and
competency.lapsed for the webhooks. Status comes from status.py, as
everywhere (rule 2). Each email has its own key in the outbox and each
event is fired once, so running the job again sends nothing twice."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session as Db

from lms.models import Competency, Person
from lms.services import events, outbox, settings, standing
from lms.services.status import Status

# days left on the last good day's count, unless Settings says otherwise:
# 30, 14, and the day itself
REMINDER_DAYS = (30, 14, 0)
MONDAY = 0
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def formatted(d: date) -> str:
    """1 Nov 2026, day first as Australians write it."""
    return f"{d.day} {MONTHS[d.month - 1]} {d.year}"


def reminder_for(days_left: int, days: tuple[int, ...] = REMINDER_DAYS) -> int | None:
    """Which reminder is due: the nearest reminder day not yet passed, so a
    day the worker missed still gets the one it was owed. None before the
    first of them."""
    return min((t for t in days if t >= days_left), default=None)


@dataclass
class Item:
    person: Person
    name: str
    status: str
    expires_on: date


def _where_to(path: str) -> str:
    url = settings.current().public_url
    return f"\n\nOpen Simple LMS: {url}{path}" if url else ""


def reminder(person: Person, name: str, expires_on: date, days_left: int) -> tuple[str, str]:
    """Said with the real days left, whichever reminder day is being sent."""
    if days_left == 0:
        subject = f"{name}: today is its last day"
        when = f"Your {name} is good until the end of today, {formatted(expires_on)}."
    elif days_left == 1:
        subject = f"{name}: tomorrow is its last day"
        when = f"Your {name} is good until the end of tomorrow, {formatted(expires_on)}."
    else:
        subject = f"{name}: {days_left} days left"
        when = f"Your {name} is good until {formatted(expires_on)}, {days_left} days from now."
    text = (f"Hi {person.name},\n\n{when} Renew it before then, and it will show in "
            f"My training.{_where_to('/learn/')}\n\nIf you have already done it, ask your "
            "supervisor to check it is recorded.\n\nSimple LMS")
    return subject, text


def digest(manager: Person, items: list[Item]) -> tuple[str, str]:
    lapsed = [i for i in items if i.status == "lapsed"]
    expiring = [i for i in items if i.status == "expiring"]
    subject = f"Training this week: {len(lapsed)} lapsed, {len(expiring)} expiring"
    lines = [f"Hi {manager.name},", ""]
    if lapsed:
        lines += ["Lapsed:"] + [f"- {i.person.name} ({i.person.code}): {i.name}, ran out after "
                                f"{formatted(i.expires_on)}" for i in lapsed] + [""]
    if expiring:
        lines += ["Expiring in the next 30 days:"] + [
            f"- {i.person.name} ({i.person.code}): {i.name}, good until {formatted(i.expires_on)}"
            for i in expiring] + [""]
    text = "\n".join(lines).rstrip() + _where_to("/") + "\n\nSimple LMS"
    return subject, text


def fire(db: Db, p: Person, c: Competency, s: Status, today: date,
         now: datetime | None) -> bool:
    """competency.expiring or competency.lapsed, once for each last good day:
    the first day the job finds it so. A renewal has a new last good day, so
    it is told afresh when it comes round. True when it fired now."""
    data = {"person": events.person_ref(p), "competency": events.competency_ref(c),
            "status": s.status, "granted_on": s.granted_on.isoformat(),
            "expires_on": s.expires_on.isoformat()}
    if s.status == "expiring":
        data["days_left"] = (s.expires_on - today).days
    event_type = f"competency.{s.status}"
    key = f"{event_type}:{p.id}:{c.id}:{s.expires_on.isoformat()}"
    return events.once(db, key, event_type, data, now)


def run(db: Db, today: date, now: datetime | None = None) -> dict[str, int]:
    """Queue today's reminders, (on a Monday) the digests, and the expiring
    and lapsed events. Returns how many were queued now; anything an earlier
    run queued is not queued again."""
    queued = {"reminders": 0, "digests": 0, "events": 0}
    days = settings.current().reminder_days
    people = db.execute(select(Person).where(Person.active.is_(True))
                        .order_by(Person.name, Person.code)).scalars().all()
    st = standing.load(db, [p.id for p in people], today)
    items: list[Item] = []
    for p in people:
        for c in sorted(st.asked_for(p.id), key=lambda c: st.competencies[c].name):
            s = st.status(p.id, c)
            name = st.competencies[c].name
            if s.status in ("expiring", "lapsed"):
                items.append(Item(p, name, s.status, s.expires_on))
                queued["events"] += fire(db, p, st.competencies[c], s, today, now)
            # a reminder day may be further off than "expiring" (30 days)
            if s.status in ("current", "expiring") and s.expires_on is not None and p.email:
                days_left = (s.expires_on - today).days
                tier = reminder_for(days_left, days)
                if tier is None:
                    continue
                subject, text = reminder(p, name, s.expires_on, days_left)
                key = f"reminder:{p.id}:{c}:{s.expires_on.isoformat()}:{tier}"
                queued["reminders"] += outbox.queue_email(db, key, p.email, subject, text, now)
    if today.weekday() == MONDAY and items:
        items.sort(key=lambda i: (i.expires_on, i.person.name, i.name))
        for m in people:
            if m.permission in ("manager", "admin") and m.email:
                subject, text = digest(m, items)
                key = f"digest:{m.id}:{today.isoformat()}"
                queued["digests"] += outbox.queue_email(db, key, m.email, subject, text, now)
    db.commit()
    return queued
