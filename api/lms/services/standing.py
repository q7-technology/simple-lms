"""Where a group of people stand: what each is asked for and their status
for it, loaded in a handful of queries for the matrix and the to-do list."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session as Db

from lms.models import Competency, CompetencyRecord, PersonOverride, PersonRole, RoleRequirement
from lms.services.status import Latest, Status, work_out


@dataclass
class Standing:
    today: date
    competencies: dict[int, Competency]  # active ones only
    by_role: set[tuple[int, int]]
    overrides: dict[tuple[int, int], str]
    records: dict[tuple[int, int], CompetencyRecord]

    def asked_for(self, person_id: int) -> set[int]:
        """Competencies their roles or an extra ask for, waived or not."""
        keys = {c for (p, c) in self.by_role if p == person_id}
        keys |= {c for (p, c), kind in self.overrides.items() if p == person_id and kind == "extra"}
        return {c for c in keys if c in self.competencies}

    def status(self, person_id: int, competency_id: int) -> Status:
        record = self.records.get((person_id, competency_id))
        latest = None if record is None else Latest(record.kind, record.granted_on,
                                                    record.expires_on)
        override = self.overrides.get((person_id, competency_id))
        return work_out(
            by_role=(person_id, competency_id) in self.by_role,
            override=None if override == "clear" else override,
            latest=latest,
            refresher_months=self.competencies[competency_id].refresher_months,
            today=self.today,
        )


def latest_rows(db: Db, model, person_ids: list[int]):
    """The newest row per person and competency: the one that counts."""
    newest = (select(func.max(model.id)).where(model.person_id.in_(person_ids))
              .group_by(model.person_id, model.competency_id))
    return db.execute(select(model).where(model.id.in_(newest))).scalars().all()


def load(db: Db, person_ids: list[int], today: date) -> Standing:
    if not person_ids:
        return Standing(today, {}, set(), {}, {})
    competencies = {c.id: c for c in db.execute(
        select(Competency).where(Competency.active.is_(True))).scalars()}
    by_role = {(p, c) for p, c in db.execute(
        select(PersonRole.person_id, RoleRequirement.competency_id)
        .join(RoleRequirement, RoleRequirement.role_id == PersonRole.role_id)
        .where(PersonRole.person_id.in_(person_ids)))}
    overrides = {(o.person_id, o.competency_id): o.kind
                 for o in latest_rows(db, PersonOverride, person_ids)}
    records = {(r.person_id, r.competency_id): r for r in latest_rows(db, CompetencyRecord, person_ids)}
    return Standing(today, competencies, by_role, overrides, records)
