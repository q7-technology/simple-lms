from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from lms.models.base import Base, created_at_column


class Outbox(Base):
    """The queue the worker drains: today, emails. A failed try is tried
    again after 1 min, 5, 30 and 2 h. `key` is unique, so something queued
    twice (a reminder the daily job finds again) is queued once."""

    __tablename__ = "outbox"
    __table_args__ = (
        CheckConstraint("kind in ('email')", name="kind"),
        CheckConstraint("status in ('pending', 'done', 'failed')", name="status"),
        # sent, and when: done_at is set exactly when it is done
        CheckConstraint("(status = 'done') = (done_at is not null)", name="done_at"),
        Index("ix_outbox_due", "status", "next_attempt_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))
    # e.g. reminder:4:2:2026-11-11:30 or digest:2:2026-10-12
    key: Mapped[str] = mapped_column(String(200), unique=True)
    # an email: {"to", "subject", "text"}
    payload: Mapped[dict] = mapped_column(JSONB)
    # pending, done, failed
    status: Mapped[str] = mapped_column(String(16), default="pending", server_default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                      server_default=func.now())
    last_error: Mapped[str | None] = mapped_column(String(500))
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_column()
