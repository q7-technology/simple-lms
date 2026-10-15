"""Simple LMS's outward links: the webhooks that hear its events, the API
keys other systems read it with, and the events the daily job has fired."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, String, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from lms.models.base import Base, created_at_column
from lms.models.people import Person


class Webhook(Base):
    """Somewhere Simple LMS sends its events: a web address, the secret each
    body is signed with, and the events it wants (`*` for all). Turned off,
    never deleted: its deliveries name it."""

    __tablename__ = "webhook"
    __table_args__ = (
        CheckConstraint("url ~ '^https?://[^[:space:]]+$'", name="url"),
        CheckConstraint("jsonb_typeof(events) = 'array' and jsonb_array_length(events) > 0",
                        name="events"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    url: Mapped[str] = mapped_column(String(500))
    # kept as it is, since the worker signs with it; shown once, when it is made
    secret: Mapped[str] = mapped_column(String(100))
    # event types, e.g. ["competency.granted", "competency.revoked"], or ["*"]
    events: Mapped[list] = mapped_column(JSONB)
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = created_at_column()


class ApiKey(Base):
    """A key for a system, not a person: Simple TMS reading who is current,
    say. Only its SHA-256 is kept; the key is shown once, when it is made.
    Revoked, never deleted."""

    __tablename__ = "api_key"
    __table_args__ = (
        CheckConstraint("jsonb_typeof(scopes) = 'array' and jsonb_array_length(scopes) > 0",
                        name="scopes"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    # the key's first characters, so a person can tell which one it is
    prefix: Mapped[str] = mapped_column(String(16))
    scopes: Mapped[list] = mapped_column(JSONB)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("person.id"))
    created_at: Mapped[datetime] = created_at_column()
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_by: Mapped[Person] = relationship()


class EventSeen(Base):
    """An event the daily job has fired, by what it was about: the expiring
    or lapsed of one person's competency, to one last good day. It fires
    once (rule 2), whoever was listening then."""

    __tablename__ = "event_seen"

    # e.g. competency.expiring:4:2:2026-11-11 (person, competency, last good day)
    key: Mapped[str] = mapped_column(String(200), primary_key=True)
    event_id: Mapped[uuid.UUID] = mapped_column(Uuid, unique=True)
    created_at: Mapped[datetime] = created_at_column()
