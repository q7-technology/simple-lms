"""Practicals: a checklist a supervisor ticks while they watch, in
versions. The newest version is the one signed off now."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session as Db

from lms.models import Competency, PracticalVersion


def newest(db: Db, practical: Competency) -> PracticalVersion | None:
    return db.execute(select(PracticalVersion)
                      .where(PracticalVersion.competency_id == practical.id)
                      .order_by(PracticalVersion.version.desc()).limit(1)).scalar_one_or_none()
