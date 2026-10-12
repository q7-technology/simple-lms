from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from lms.models.base import Base, created_at_column
from lms.models.catalogue import Competency
from lms.models.people import Person


class PersonOverride(Base):
    """An extra (required for this person alone), a waiver (not required, for
    a reason) or a clear (back to what their roles say). Append-only: the
    latest row for a person and competency is the one that counts."""

    __tablename__ = "person_override"
    __table_args__ = (
        CheckConstraint("kind in ('extra', 'waive', 'clear')", name="kind"),
        CheckConstraint("length(trim(note)) > 0", name="note"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("person.id"), index=True)
    competency_id: Mapped[int] = mapped_column(ForeignKey("competency.id"), index=True)
    kind: Mapped[str] = mapped_column(String(8))
    note: Mapped[str] = mapped_column(String(500))
    recorded_by_id: Mapped[int] = mapped_column(ForeignKey("person.id"))
    created_at: Mapped[datetime] = created_at_column()

    competency: Mapped[Competency] = relationship()
    recorded_by: Mapped[Person] = relationship(foreign_keys=[recorded_by_id])


class CompetencyRecord(Base):
    """The training record. Append-only: a trigger refuses UPDATE and DELETE.
    The latest row for a person and competency is the one that counts; a
    mistake is put right by a new row, a grant with the right dates or a
    revoke with a note."""

    __tablename__ = "competency_record"
    __table_args__ = (
        CheckConstraint("kind in ('granted', 'revoked')", name="kind"),
        CheckConstraint("kind = 'revoked' or granted_on is not null", name="granted_on"),
        CheckConstraint("kind = 'granted' or length(trim(note)) > 0", name="revoke_note"),
        CheckConstraint("expires_on > granted_on", name="expires_after_granted"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("person.id"), index=True)
    competency_id: Mapped[int] = mapped_column(ForeignKey("competency.id"), index=True)
    kind: Mapped[str] = mapped_column(String(8))
    granted_on: Mapped[date | None] = mapped_column(Date)
    # the last day it is good for, when the record says (a ticket's card);
    # otherwise worked out from the competency's refresher
    expires_on: Mapped[date | None] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(String(500))
    recorded_by_id: Mapped[int] = mapped_column(ForeignKey("person.id"))
    created_at: Mapped[datetime] = created_at_column()

    competency: Mapped[Competency] = relationship()
    recorded_by: Mapped[Person] = relationship(foreign_keys=[recorded_by_id])
