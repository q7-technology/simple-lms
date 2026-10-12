"""A person's status for one competency, worked out from what their roles
require, their latest override and latest record, and today's date. Never
stored, so it cannot drift (rule 2)."""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date

EXPIRING_DAYS = 30
STATUSES = ("current", "expiring", "lapsed", "missing", "waived", "not_required")


@dataclass(frozen=True, slots=True)
class Latest:
    """The latest record for a person and competency."""

    kind: str  # granted | revoked
    granted_on: date | None = None
    expires_on: date | None = None


@dataclass(frozen=True, slots=True)
class Status:
    status: str
    granted_on: date | None = None
    expires_on: date | None = None


def add_months(d: date, months: int) -> date:
    """31 January plus a month is the last day of February."""
    years, month0 = divmod(d.month - 1 + months, 12)
    year, month = d.year + years, month0 + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def expiry(granted_on: date, expires_on: date | None, refresher_months: int | None) -> date | None:
    """The last day a grant is good for: the record's own date if it has one
    (a ticket's card), else the refresher after the grant, else never."""
    if expires_on is not None:
        return expires_on
    if refresher_months:
        return add_months(granted_on, refresher_months)
    return None


def work_out(*, by_role: bool, override: str | None, latest: Latest | None,
             refresher_months: int | None, today: date) -> Status:
    """Required is roles plus extras, less waivers. `override` is the latest
    override's kind: extra, waive, or None (none, or cleared)."""
    if not (by_role or override == "extra"):
        return Status("not_required")
    if override == "waive":
        return Status("waived")
    if latest is None or latest.kind != "granted" or latest.granted_on is None:
        return Status("missing")
    ends = expiry(latest.granted_on, latest.expires_on, refresher_months)
    if ends is None:
        return Status("current", latest.granted_on, None)
    if today > ends:
        return Status("lapsed", latest.granted_on, ends)
    if (ends - today).days <= EXPIRING_DAYS:
        return Status("expiring", latest.granted_on, ends)
    return Status("current", latest.granted_on, ends)
