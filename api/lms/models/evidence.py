from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint,
    Uuid, text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from lms.models.base import Base, created_at_column
from lms.models.catalogue import Competency
from lms.models.people import Person


class Upload(Base):
    """A file someone sent: a ticket's photo or PDF, a signature, a module
    page's picture, PDF or video, or a sign-off's photo. Kept on disk under
    LMS_UPLOAD_DIR, named by its random id; served only through the API to
    people who may see it. Append-only: a trigger refuses UPDATE and DELETE,
    since records, tickets, pages and sign-offs point at it."""

    __tablename__ = "upload"
    __table_args__ = (CheckConstraint("purpose in ('ticket', 'signature', 'page-image', "
                                      "'page-pdf', 'page-video', 'signoff-photo')",
                                      name="purpose"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    # whose it is: the person who sent it
    person_id: Mapped[int] = mapped_column(ForeignKey("person.id"), index=True)
    purpose: Mapped[str] = mapped_column(String(16))
    # worked out from its first bytes, never from what the request said
    content_type: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    # under LMS_UPLOAD_DIR, e.g. 3f/3f2a….jpg
    path: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = created_at_column()


class PolicyVersion(Base):
    """One version of a policy's text. Append-only: what someone signed never
    changes under them. The newest version is the one to sign."""

    __tablename__ = "policy_version"
    __table_args__ = (
        UniqueConstraint("competency_id", "version"),
        CheckConstraint("version >= 1", name="version"),
        CheckConstraint("length(trim(body)) > 0", name="body"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    competency_id: Mapped[int] = mapped_column(ForeignKey("competency.id"), index=True)
    # 1, 2, 3 … for each policy
    version: Mapped[int] = mapped_column(Integer)
    body: Mapped[str] = mapped_column(Text)
    # what changed, for the people asked to sign again
    note: Mapped[str | None] = mapped_column(String(500))
    published_by_id: Mapped[int] = mapped_column(ForeignKey("person.id"))
    created_at: Mapped[datetime] = created_at_column()

    competency: Mapped[Competency] = relationship()
    published_by: Mapped[Person] = relationship()


class TicketSubmission(Base):
    """A ticket or licence a person sent in, waiting for a manager's check.
    Decided once: a trigger lets a pending ticket be approved or rejected and
    refuses every other change, and every delete."""

    __tablename__ = "ticket_submission"
    __table_args__ = (
        CheckConstraint("status in ('pending', 'approved', 'rejected')", name="status"),
        # a reason when rejected, and only then
        CheckConstraint("case when status = 'rejected' then coalesce(length(trim(reason)), 0) > 0"
                        " else reason is null end",
                        name="reason"),
        # pending has no decider and no date; approved and rejected have both
        CheckConstraint("(status = 'pending') = (decided_by_id is null)"
                        " and (status = 'pending') = (decided_at is null)",
                        name="decided"),
        CheckConstraint("length(trim(number)) > 0", name="number"),
        # a photo is one side of one ticket: never both sides, never on two
        # tickets. A front on one ticket as the back of another isn't a rule
        # a unique index can say; uploads.on_a_ticket() checks that one.
        CheckConstraint("front_upload_id <> back_upload_id", name="two_sides"),
        Index("uq_ticket_submission_front_upload_id", "front_upload_id", unique=True),
        Index("uq_ticket_submission_back_upload_id", "back_upload_id", unique=True,
              postgresql_where=text("back_upload_id is not null")),
        # one waiting at a time for a person and a ticket
        Index("uq_ticket_submission_waiting", "person_id", "competency_id", unique=True,
              postgresql_where=text("status = 'pending'")),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("person.id"), index=True)
    competency_id: Mapped[int] = mapped_column(ForeignKey("competency.id"), index=True)
    # the number on the card
    number: Mapped[str] = mapped_column(String(64))
    # the card's last good day; none for a card that never runs out
    expires_on: Mapped[date | None] = mapped_column(Date)
    front_upload_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("upload.id"))
    back_upload_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("upload.id"))
    # pending, approved, rejected
    status: Mapped[str] = mapped_column(String(16), default="pending")
    reason: Mapped[str | None] = mapped_column(String(500))
    decided_by_id: Mapped[int | None] = mapped_column(ForeignKey("person.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_column()

    person: Mapped[Person] = relationship(foreign_keys=[person_id])
    competency: Mapped[Competency] = relationship()
    decided_by: Mapped[Person | None] = relationship(foreign_keys=[decided_by_id])
