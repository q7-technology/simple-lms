from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Index, Integer, String, UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from lms.models.base import Base, created_at_column
from lms.models.catalogue import Competency
from lms.models.people import Person


class PracticalVersion(Base):
    """One version of a practical's checklist: the items a supervisor ticks
    while they watch. Append-only, items and all (triggers say so): a
    sign-off names its version, so what was ticked never changes under it.
    The newest version is the one signed off now."""

    __tablename__ = "practical_version"
    __table_args__ = (
        UniqueConstraint("competency_id", "version"),
        # what a sign-off names as its practical and version agree
        UniqueConstraint("id", "competency_id"),
        CheckConstraint("version >= 1", name="version"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    competency_id: Mapped[int] = mapped_column(ForeignKey("competency.id"), index=True)
    # 1, 2, 3 … for each practical
    version: Mapped[int] = mapped_column(Integer)
    # what changed, for the supervisors
    note: Mapped[str | None] = mapped_column(String(500))
    published_by_id: Mapped[int] = mapped_column(ForeignKey("person.id"))
    created_at: Mapped[datetime] = created_at_column()

    competency: Mapped[Competency] = relationship()
    published_by: Mapped[Person] = relationship()
    items: Mapped[list[PracticalItem]] = relationship(order_by="PracticalItem.position")


class PracticalItem(Base):
    """One thing to see the learner do, e.g. "Checks the forks and chains".
    Written with its version and never after (a trigger says so)."""

    __tablename__ = "practical_item"
    __table_args__ = (
        UniqueConstraint("practical_version_id", "position"),
        # what a ticked item names as its version agrees
        UniqueConstraint("id", "practical_version_id"),
        CheckConstraint("position >= 0", name="position"),
        CheckConstraint("length(trim(text)) > 0", name="text"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    practical_version_id: Mapped[int] = mapped_column(ForeignKey("practical_version.id"),
                                                      index=True)
    # 0, 1, 2 …: the order they are ticked in
    position: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(String(300))


class Signoff(Base):
    """A supervisor watched a learner do a practical, ticked every item on
    its checklist and signed; the learner signed on the same device to
    confirm. Append-only (rule 1), and never by the learner themselves
    (rule 3). Its grant is in the training record, recorded by the
    supervisor."""

    __tablename__ = "signoff"
    __table_args__ = (
        # a version of this practical
        ForeignKeyConstraint(["practical_version_id", "competency_id"],
                             ["practical_version.id", "practical_version.competency_id"]),
        # what a ticked item names as its sign-off's version agrees
        UniqueConstraint("id", "practical_version_id"),
        # nobody signs off their own practical
        CheckConstraint("supervisor_id <> person_id", name="not_own"),
        CheckConstraint("supervisor_signature_upload_id <> learner_signature_upload_id",
                        name="two_signatures"),
        CheckConstraint("note is null or length(trim(note)) > 0", name="note"),
        CheckConstraint("(learner_pin_set_at is null) = (learner_pin_set_by_id is null)",
                        name="learner_pin_set"),
        # a photo or a signature goes on one sign-off only
        Index("uq_signoff_photo_upload_id", "photo_upload_id", unique=True,
              postgresql_where=text("photo_upload_id is not null")),
        Index("uq_signoff_supervisor_signature_upload_id", "supervisor_signature_upload_id",
              unique=True),
        Index("uq_signoff_learner_signature_upload_id", "learner_signature_upload_id",
              unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # the learner
    person_id: Mapped[int] = mapped_column(ForeignKey("person.id"), index=True)
    competency_id: Mapped[int] = mapped_column(ForeignKey("competency.id"), index=True)
    # the checklist ticked, whose items never change
    practical_version_id: Mapped[int] = mapped_column(Integer)
    # who watched and signed it off
    supervisor_id: Mapped[int] = mapped_column(ForeignKey("person.id"))
    note: Mapped[str | None] = mapped_column(String(500))
    photo_upload_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("upload.id"))
    supervisor_signature_upload_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("upload.id"))
    # the learner's own, drawn on the supervisor's device once their PIN said it was them
    learner_signature_upload_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("upload.id"))
    # when the learner's PIN was last set, and by whom, as it was at the
    # sign-off: whoever set it knew it. Unknown for a PIN set before PIN
    # changes were kept.
    learner_pin_set_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    learner_pin_set_by_id: Mapped[int | None] = mapped_column(ForeignKey("person.id"))
    created_at: Mapped[datetime] = created_at_column()

    competency: Mapped[Competency] = relationship()
    practical_version: Mapped[PracticalVersion] = relationship(
        primaryjoin="PracticalVersion.id == Signoff.practical_version_id",
        foreign_keys=[practical_version_id])
    supervisor: Mapped[Person] = relationship(foreign_keys=[supervisor_id])
    learner_pin_set_by: Mapped[Person | None] = relationship(foreign_keys=[learner_pin_set_by_id])
    ticked: Mapped[list[SignoffItem]] = relationship(
        primaryjoin="Signoff.id == SignoffItem.signoff_id", foreign_keys="SignoffItem.signoff_id",
        order_by="SignoffItem.practical_item_id")


class SignoffItem(Base):
    """An item ticked on a sign-off: one of its version's own (the foreign
    keys say so). Written with its sign-off and never after."""

    __tablename__ = "signoff_item"
    __table_args__ = (
        ForeignKeyConstraint(["signoff_id", "practical_version_id"],
                             ["signoff.id", "signoff.practical_version_id"]),
        ForeignKeyConstraint(["practical_item_id", "practical_version_id"],
                             ["practical_item.id", "practical_item.practical_version_id"]),
    )

    signoff_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    practical_item_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    practical_version_id: Mapped[int] = mapped_column(Integer)

    item: Mapped[PracticalItem] = relationship(
        primaryjoin="PracticalItem.id == SignoffItem.practical_item_id",
        foreign_keys=[practical_item_id])
