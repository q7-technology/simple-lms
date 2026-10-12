"""Where a group of people stand. For now, the newest rows."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session as Db


def latest_rows(db: Db, model, person_ids: list[int]):
    """The newest row per person and competency: the one that counts."""
    newest = (select(func.max(model.id)).where(model.person_id.in_(person_ids))
              .group_by(model.person_id, model.competency_id))
    return db.execute(select(model).where(model.id.in_(newest))).scalars().all()
