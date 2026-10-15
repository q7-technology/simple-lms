"""Modules: versions of pages and a quiz. A draft is edited freely;
publishing freezes it. People take the newest published version."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session as Db

from lms.models import Competency, ModulePage, ModuleVersion, QuizQuestion


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
