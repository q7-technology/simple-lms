"""Status is worked out from the requirement, the latest override, the latest
record and today's date. Every case the matrix can show, in one table."""
from datetime import date

import pytest

from lms.services.status import Latest, add_months, expiry, work_out

TODAY = date(2026, 10, 12)
D = date.fromisoformat


def granted(on: str, expires: str | None = None) -> Latest:
    return Latest("granted", D(on), D(expires) if expires else None)


REVOKED = Latest("revoked")

CASES = [
    # (why, by_role, override, latest, refresher_months, status, expires_on)
    ("nothing asks for it", False, None, None, None, "not_required", None),
    ("a record alone does not make it required", False, None, granted("2026-01-01"), None,
     "not_required", None),
    ("a waiver of something not required changes nothing", False, "waive", None, None,
     "not_required", None),
    ("a role asks, nothing recorded", True, None, None, None, "missing", None),
    ("an extra asks, nothing recorded", False, "extra", None, None, "missing", None),
    ("the latest record is a revoke", True, None, REVOKED, 12, "missing", None),
    ("waived, with nothing recorded", True, "waive", None, None, "waived", None),
    ("waived beats a lapsed record", True, "waive", granted("2020-01-01", "2021-01-01"), None,
     "waived", None),
    ("granted, no expiry and no refresher: never runs out", True, None,
     granted("2019-05-01"), None, "current", None),
    ("an extra, granted and current", False, "extra", granted("2026-01-01", "2027-01-01"), None,
     "current", "2027-01-01"),
    ("card date 31 days away", True, None, granted("2025-01-01", "2026-11-12"), None,
     "current", "2026-11-12"),
    ("card date 30 days away", True, None, granted("2025-01-01", "2026-11-11"), None,
     "expiring", "2026-11-11"),
    ("card date is today: still good today", True, None, granted("2025-01-01", "2026-10-12"),
     None, "expiring", "2026-10-12"),
    ("card date was yesterday", True, None, granted("2025-01-01", "2026-10-11"), None,
     "lapsed", "2026-10-11"),
    ("24-month refresher, due tomorrow", True, None, granted("2024-10-13"), 24, "expiring",
     "2026-10-13"),
    ("24-month refresher, due yesterday", True, None, granted("2024-10-11"), 24, "lapsed",
     "2026-10-11"),
    ("12-month refresher, done six months ago", True, None, granted("2026-04-12"), 12,
     "current", "2027-04-12"),
    ("the record's own date beats the refresher", True, None,
     granted("2020-01-01", "2027-06-30"), 12, "current", "2027-06-30"),
]


@pytest.mark.parametrize("why,by_role,override,latest,months,status,expires",
                         CASES, ids=[c[0] for c in CASES])
def test_status(why, by_role, override, latest, months, status, expires):
    s = work_out(by_role=by_role, override=override, latest=latest, refresher_months=months,
                 today=TODAY)
    assert s.status == status
    assert s.expires_on == (D(expires) if expires else None)
    if status in ("current", "expiring", "lapsed"):
        assert s.granted_on == latest.granted_on


@pytest.mark.parametrize("start,months,end", [
    ("2026-01-15", 1, "2026-02-15"),
    ("2026-11-15", 2, "2027-01-15"),
    ("2024-01-31", 1, "2024-02-29"),   # a leap year
    ("2023-01-31", 1, "2023-02-28"),
    ("2024-02-29", 12, "2025-02-28"),
    ("2026-10-12", 240, "2046-10-12"),
])
def test_months_are_added_as_a_calendar_does(start, months, end):
    assert add_months(D(start), months) == D(end)


def test_expiry_is_the_record_then_the_refresher_then_never():
    assert expiry(D("2026-01-01"), D("2026-06-30"), 12) == D("2026-06-30")
    assert expiry(D("2026-01-01"), None, 12) == D("2027-01-01")
    assert expiry(D("2026-01-01"), None, None) is None


def signed(version: int | None) -> Latest:
    return Latest("granted", D("2026-03-01"), None, version)


@pytest.mark.parametrize("why,latest,current,status", [
    ("no version published yet: any grant counts", signed(None), None, "current"),
    ("signed the version that is current", signed(7), 7, "current"),
    ("signed an older version", signed(3), 7, "missing"),
    ("recorded before there were versions", signed(None), 7, "missing"),
    ("a revoke is still a revoke", REVOKED, 7, "missing"),
])
def test_a_new_policy_version_needs_a_new_signature(why, latest, current, status):
    s = work_out(by_role=True, override=None, latest=latest, refresher_months=None,
                 today=TODAY, current_version=current)
    assert s.status == status, why
