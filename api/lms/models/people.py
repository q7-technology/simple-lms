from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from lms.models.base import Base, created_at_column

PERMISSIONS = ("learner", "supervisor", "manager", "admin")


class Person(Base):
    """Everyone: learners, supervisors, managers and admins. One record serves
    every way of signing in. Deactivated, never deleted."""

    __tablename__ = "person"
    __table_args__ = (
        CheckConstraint("code = upper(code)", name="code_upper"),
        CheckConstraint("email = lower(email)", name="email_lower"),
        CheckConstraint("permission in ('learner', 'supervisor', 'manager', 'admin')",
                        name="permission"),
        CheckConstraint("supervisor_id <> id", name="not_own_supervisor"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # e.g. LL042: kept upper case, matched however it is typed
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str | None] = mapped_column(String(254), unique=True)
    # their Microsoft Entra object id (oid), kept the first time they sign in
    # with Microsoft and matched from then on
    entra_oid: Mapped[str | None] = mapped_column(String(64), unique=True)
    # learner, supervisor, manager, admin: what they may do, not what they need
    permission: Mapped[str] = mapped_column(String(16), default="learner")
    supervisor_id: Mapped[int | None] = mapped_column(ForeignKey("person.id"), index=True)

    pin_hash: Mapped[str | None] = mapped_column(String(200))
    pin_failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    # five wrong PINs: locked until a manager sets a new one
    pin_locked: Mapped[bool] = mapped_column(Boolean, default=False)
    password_hash: Mapped[str | None] = mapped_column(String(200))
    password_failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    password_locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = created_at_column()
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    supervisor: Mapped[Person | None] = relationship(remote_side=[id])
    roles: Mapped[list[Role]] = relationship(secondary="person_role", order_by="Role.name")


class Session(Base):
    """One signed-in device. Only the token's hash is kept. It ends after
    idle_seconds without a request: 15 minutes for a PIN, or Microsoft in the
    learner app; 12 hours for a password, or Microsoft on the desktop."""

    __tablename__ = "session"
    __table_args__ = (CheckConstraint("method in ('password', 'pin', 'entra')", name="method"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("person.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    method: Mapped[str] = mapped_column(String(8))
    created_at: Mapped[datetime] = created_at_column()
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    idle_seconds: Mapped[int] = mapped_column(Integer)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
