from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from lms.models.base import Base, created_at_column
from lms.models.catalogue import Competency
from lms.models.evidence import PolicyVersion
from lms.models.modules import QuizAttempt
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
        CheckConstraint("signature_upload_id is null or "
                        "(policy_version_id is not null and signed_name is not null)",
                        name="signature"),
        # a drawn signature goes on one record only
        Index("uq_competency_record_signature_upload_id", "signature_upload_id", unique=True,
              postgresql_where=text("signature_upload_id is not null")),
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
    # a policy: the version this grant is for (signed in the learner app, or
    # on paper and recorded by hand). A newer version needs a new grant.
    policy_version_id: Mapped[int | None] = mapped_column(ForeignKey("policy_version.id"))
    # signed in the learner app: the name they typed and their finger signature
    signed_name: Mapped[str | None] = mapped_column(String(120))
    signature_upload_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("upload.id"))
    # a ticket a manager verified: the submission it came from
    ticket_submission_id: Mapped[int | None] = mapped_column(ForeignKey("ticket_submission.id"),
                                                             unique=True)
    # a module passed: the quiz attempt that passed it
    quiz_attempt_id: Mapped[int | None] = mapped_column(ForeignKey("quiz_attempt.id"), unique=True)
    created_at: Mapped[datetime] = created_at_column()

    competency: Mapped[Competency] = relationship()
    recorded_by: Mapped[Person] = relationship(foreign_keys=[recorded_by_id])
    policy_version: Mapped[PolicyVersion | None] = relationship()
    quiz_attempt: Mapped[QuizAttempt | None] = relationship()
