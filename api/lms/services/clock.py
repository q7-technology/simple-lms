"""Today, where the business is, and now. One place, so tests can move the clock."""
from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from lms.config import get_settings


def today() -> date:
    return datetime.now(ZoneInfo(get_settings().timezone)).date()


def now() -> datetime:
    return datetime.now(UTC)
