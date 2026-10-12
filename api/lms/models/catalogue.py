from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from lms.models.base import Base, created_at_column

KINDS = ("module", "practical", "ticket", "policy")


class Role(Base):
    """A job, e.g. forklift-operator, and the competencies it requires."""

    __tablename__ = "role"
    __table_args__ = (CheckConstraint("key = lower(key)", name="key_lower"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = created_at_column()

    competencies: Mapped[list[Competency]] = relationship(
        secondary="role_requirement", order_by="Competency.name")


class PersonRole(Base):
    __tablename__ = "person_role"

    person_id: Mapped[int] = mapped_column(ForeignKey("person.id"), primary_key=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("role.id"), primary_key=True, index=True)
    created_at: Mapped[datetime] = created_at_column()


class Competency(Base):
    """Anything a person can be current for. Deactivated, never deleted: its
    records stay."""

    __tablename__ = "competency"
    __table_args__ = (
        CheckConstraint("key = lower(key)", name="key_lower"),
        CheckConstraint("kind in ('module', 'practical', 'ticket', 'policy')", name="kind"),
        CheckConstraint("refresher_months between 1 and 240", name="refresher_months"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    # module, practical, ticket, policy: how it is earned (by hand in step 1)
    kind: Mapped[str] = mapped_column(String(16))
    # a refresher after this many months; none means it never runs out unless
    # the record itself says when (a ticket's card)
    refresher_months: Mapped[int | None] = mapped_column(Integer)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = created_at_column()


class RoleRequirement(Base):
    __tablename__ = "role_requirement"

    role_id: Mapped[int] = mapped_column(ForeignKey("role.id"), primary_key=True)
    competency_id: Mapped[int] = mapped_column(ForeignKey("competency.id"), primary_key=True,
                                               index=True)
    created_at: Mapped[datetime] = created_at_column()
