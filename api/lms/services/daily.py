"""The daily job, run by the worker each morning: a reminder to each
learner with an email when something of theirs has 30, 14 or 0 days left,
and on Mondays a digest of what is expiring and lapsed for each manager.
Status comes from status.py, as everywhere (rule 2). Each email has its
own key in the outbox, so running the job again sends nothing twice."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session as Db

from lms.config import get_settings
from lms.models import Person
from lms.services import outbox, standing

# days left on the last good day's count: 30, 14, and the day itself
REMINDER_DAYS = (30, 14, 0)
MONDAY = 0
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def formatted(d: date) -> str:
    """1 Nov 2026, day first as Australians write it."""
    return f"{d.day} {MONTHS[d.month - 1]} {d.year}"


def reminder_for(days_left: int) -> int:
    """Which reminder is due: the nearest of 30, 14 and 0 not yet passed, so a
    day the worker missed still gets the one it was owed."""
    return min(t for t in REMINDER_DAYS if t >= days_left)


@dataclass
class Item:
    person: Person
    name: str
    status: str
    expires_on: date


def _where_to(path: str) -> str:
    url = get_settings().public_url
    return f"\n\nOpen Simple LMS: {url}{path}" if url else ""


def reminder(person: Person, name: str, expires_on: date, days: int) -> tuple[str, str]:
    if days == 0:
        subject = f"{name}: today is its last day"
        when = f"Your {name} is good until the end of today, {formatted(expires_on)}."
    else:
        subject = f"{name}: {days} days left"
        when = f"Your {name} is good until {formatted(expires_on)}, {days} days from now."
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


def run(db: Db, today: date, now: datetime | None = None) -> dict[str, int]:
    """Queue today's reminders and (on a Monday) the digests. Returns how
    many were queued now; anything an earlier run queued is not queued again."""
    queued = {"reminders": 0, "digests": 0}
    people = db.execute(select(Person).where(Person.active.is_(True))
                        .order_by(Person.name, Person.code)).scalars().all()
    st = standing.load(db, [p.id for p in people], today)
    items: list[Item] = []
    for p in people:
        for c in sorted(st.asked_for(p.id), key=lambda c: st.competencies[c].name):
            s = st.status(p.id, c)
            if s.status not in ("expiring", "lapsed"):
                continue
            name = st.competencies[c].name
            items.append(Item(p, name, s.status, s.expires_on))
            if s.status == "expiring" and p.email:
                days = reminder_for((s.expires_on - today).days)
                subject, text = reminder(p, name, s.expires_on, days)
                key = f"reminder:{p.id}:{c}:{s.expires_on.isoformat()}:{days}"
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
