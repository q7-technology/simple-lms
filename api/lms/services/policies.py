"""Policies: the newest version is the one to sign, and a signature names
the person as Simple LMS has them."""
from __future__ import annotations

import uuid

from sqlalchemy import exists, select
from sqlalchemy.orm import Session as Db

from lms.models import Competency, CompetencyRecord, PolicyVersion


def newest(db: Db, competency: Competency) -> PolicyVersion | None:
    return db.execute(select(PolicyVersion).where(PolicyVersion.competency_id == competency.id)
                      .order_by(PolicyVersion.id.desc()).limit(1)).scalar_one_or_none()


def same_name(typed: str, name: str) -> bool:
    """'kim  lee' is Kim Lee: case and spacing aside, the name on their record."""
    return " ".join(typed.split()).casefold() == " ".join(name.split()).casefold()


def signature_used(db: Db, upload_id: uuid.UUID) -> bool:
    """A drawn signature goes on one record only: it can't be put on another
    version later. The signer's row is locked while they sign, so two at once
    can't both find it unused."""
    return db.execute(select(exists().where(
        CompetencyRecord.signature_upload_id == upload_id))).scalar()
