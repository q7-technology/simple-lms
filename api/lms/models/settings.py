from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from lms.models.base import Base


class Setting(Base):
    """A setting changed on the Settings screen: mutable config, not the
    training record, so changed in place. Without a row the value comes
    from .env, or the default (lms/services/settings.py)."""

    __tablename__ = "setting"

    # e.g. daily_hour, smtp_host
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB)
    # who changed it last; null when it was the lms command line
    updated_by_id: Mapped[int | None] = mapped_column(ForeignKey("person.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                 server_default=func.now())
