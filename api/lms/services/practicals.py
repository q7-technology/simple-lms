"""Practicals: a checklist a supervisor ticks while they watch, in
versions. The newest version is the one signed off now. Who signs off whom
is said here and nowhere else."""
from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import exists, select
from sqlalchemy.orm import Session as Db

from lms.models import Competency, Person, PinChange, PracticalVersion, Signoff
from lms.services import clock

# who signs off anyone, not only their own team
ANYONE = ("manager", "admin")
# whoever set a learner's PIN this recently doesn't sign them off
PIN_SET_WITHIN = timedelta(days=7)


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


def photo_used(db: Db, upload_id: uuid.UUID) -> bool:
    """A photo goes on one sign-off only. Its sender is locked while it is
    used, so two at once can't both find it unused."""
    return db.execute(select(exists().where(Signoff.photo_upload_id == upload_id))).scalar()


def last_pin_change(db: Db, learner: Person) -> PinChange | None:
    """When the learner's PIN was last set, and by whom; None if it was set
    before PIN changes were kept, or never."""
    return db.execute(select(PinChange).where(PinChange.person_id == learner.id)
                      .order_by(PinChange.created_at.desc(), PinChange.id.desc())
                      .limit(1)).scalar_one_or_none()


def set_their_pin(db: Db, signer: Person, learner: Person) -> bool:
    """Whoever set the learner's PIN in the last week knows it: the learner
    typing it on their phone says nothing, so someone else signs them off.
    Learners don't set their own PIN, so it is whoever set it last."""
    return db.execute(select(exists().where(
        PinChange.person_id == learner.id, PinChange.changed_by_id == signer.id,
        PinChange.created_at > clock.now() - PIN_SET_WITHIN))).scalar()
