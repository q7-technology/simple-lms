"""Modules: versions of pages and a quiz. A draft is edited freely;
publishing freezes it. People take the newest published version."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session as Db

from lms.config import get_settings
from lms.models import Competency, ModulePage, ModuleVersion, QuizAttempt, QuizQuestion
from lms.services import clock

# this many goes in a row that didn't pass, and the learner waits
TRIES = 3


def newest(db: Db, module: Competency) -> ModuleVersion | None:
    """The version people take now."""
    return db.execute(select(ModuleVersion).where(ModuleVersion.competency_id == module.id,
                                                  ModuleVersion.published_at.is_not(None))
                      .order_by(ModuleVersion.version.desc()).limit(1)).scalar_one_or_none()


def draft(db: Db, module: Competency) -> ModuleVersion | None:
    return db.execute(select(ModuleVersion).where(ModuleVersion.competency_id == module.id,
                                                  ModuleVersion.published_at.is_(None))
                      ).scalar_one_or_none()


def start_draft(db: Db, module: Competency) -> ModuleVersion:
    """The next version, a copy of the newest published one (or empty):
    changed without touching what people have taken."""
    last = db.execute(select(func.max(ModuleVersion.version))
                      .where(ModuleVersion.competency_id == module.id)).scalar() or 0
    base = newest(db, module)
    v = ModuleVersion(competency=module, version=last + 1,
                      pass_mark=base.pass_mark if base else 80)
    db.add(v)
    db.flush()
    for p in base.pages if base else []:
        db.add(ModulePage(module_version_id=v.id, position=p.position, kind=p.kind,
                          title=p.title, body=p.body, upload_id=p.upload_id, url=p.url))
    for q in base.questions if base else []:
        db.add(QuizQuestion(module_version_id=v.id, position=q.position, prompt=q.prompt,
                            options=list(q.options), correct=q.correct))
    db.flush()
    db.expire(v, ["pages", "questions"])
    return v


def score(correct: int, total: int) -> int:
    """Out of 100, rounded down: 2 of 3 is 66, never a pass mark of 67."""
    return correct * 100 // total


def retry_at(db: Db, person_id: int, module: Competency) -> datetime | None:
    """When the person may next try the module's quiz, if they must wait:
    their last three goes at it (any version) didn't pass, and the wait
    (LMS_QUIZ_COOLDOWN_MINUTES) runs from the last of them. A pass starts
    the count again. Worked out from the attempts, never stored."""
    minutes = get_settings().quiz_cooldown_minutes
    if minutes <= 0:
        return None
    last = db.execute(select(QuizAttempt.passed, QuizAttempt.created_at)
                      .where(QuizAttempt.person_id == person_id,
                             QuizAttempt.competency_id == module.id)
                      .order_by(QuizAttempt.created_at.desc(), QuizAttempt.id.desc())
                      .limit(TRIES)).all()
    if len(last) < TRIES or any(passed for passed, _ in last):
        return None
    until = last[0].created_at + timedelta(minutes=minutes)
    return until if until > clock.now() else None


def said_at(when: datetime, now: datetime) -> str:
    """A time as people say it where the business is: 2:15 pm, and the day
    too when it isn't today, 1:00 am on Fri 16 Oct."""
    zone = ZoneInfo(get_settings().timezone)
    local, today = when.astimezone(zone), now.astimezone(zone).date()
    out = f"{local.hour % 12 or 12}:{local:%M} {'am' if local.hour < 12 else 'pm'}"
    if local.date() != today:
        out += f" on {local:%a} {local.day} {local:%b}"
    return out
