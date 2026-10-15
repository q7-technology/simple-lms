"""Practicals: a checklist a supervisor ticks while they watch, in
versions. The newest version is the one signed off now. Who signs off whom
is said here and nowhere else."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session as Db

from lms.models import Competency, Person, PracticalVersion

# who signs off anyone, not only their own team
ANYONE = ("manager", "admin")


def newest(db: Db, practical: Competency) -> PracticalVersion | None:
    return db.execute(select(PracticalVersion)
                      .where(PracticalVersion.competency_id == practical.id)
                      .order_by(PracticalVersion.version.desc()).limit(1)).scalar_one_or_none()


def may_sign_off(signer: Person, learner: Person) -> bool:
    """A supervisor signs off their own team (the people whose supervisor
    they are); a manager or admin, anyone. Nobody signs off themselves
    (rule 3)."""
    if learner.id == signer.id:
        return False
    return signer.permission in ANYONE or (signer.permission == "supervisor"
                                           and learner.supervisor_id == signer.id)
