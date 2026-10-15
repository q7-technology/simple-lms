from datetime import UTC, datetime, timedelta

import pytest

from conftest import make_person
from lms.services import access, sessions


def test_a_password_hash_checks_the_password_and_nothing_else():
    stored = access.hash_password("correct horse battery")
    assert stored.startswith("pbkdf2_sha256$")
    assert access.verify_password("correct horse battery", stored)
    assert not access.verify_password("Correct horse battery", stored)
    assert not access.verify_password("anything", None)
    assert not access.verify_password("anything", access.DUMMY_HASH)


@pytest.mark.parametrize("stored", [
    "pbkdf2_sha256$600000$not-hex$" + "0" * 64,
    "pbkdf2_sha256$many$" + "0" * 32 + "$" + "0" * 64,
    "pbkdf2_sha256$-5$" + "0" * 32 + "$" + "0" * 64,
    "pbkdf2_sha256$600000$" + "0" * 32 + "$",
    "not a hash",
])
def test_a_damaged_hash_is_a_wrong_password_not_a_crash(stored):
    assert access.verify_password("anything", stored) is False


@pytest.fixture
def kim(db):
    return make_person(db, "LL042", "Kim Lee")


NOW = datetime(2026, 10, 12, 9, 0, tzinfo=UTC)


def test_the_token_is_kept_only_as_its_hash(db, kim):
    raw = sessions.start(db, kim, "pin", now=NOW)
    assert raw.startswith("lms_s.")
    row = sessions.find(db, raw, now=NOW)
    assert row.person_id == kim.id and row.method == "pin"
    assert raw not in row.token_hash and len(row.token_hash) == 64


def test_a_pin_session_ends_after_15_minutes_idle(db, kim):
    raw = sessions.start(db, kim, "pin", now=NOW)
    assert sessions.find(db, raw, now=NOW + timedelta(minutes=14)) is not None
    # that use counted: 14 more minutes from there is still fine
    assert sessions.find(db, raw, now=NOW + timedelta(minutes=28)) is not None
    assert sessions.find(db, raw, now=NOW + timedelta(minutes=44)) is None


def test_a_password_session_ends_after_12_hours_idle(db, kim):
    raw = sessions.start(db, kim, "password", now=NOW)
    assert sessions.find(db, raw, now=NOW + timedelta(hours=11)) is not None
    assert sessions.find(db, raw, now=NOW + timedelta(hours=23, minutes=1)) is None


def test_a_busy_pin_session_still_ends_after_12_hours(db, kim):
    raw = sessions.start(db, kim, "pin", now=NOW)
    t = NOW
    while t < NOW + timedelta(hours=12):
        assert sessions.find(db, raw, now=t) is not None
        t += timedelta(minutes=10)
    assert sessions.find(db, raw, now=t) is None


def test_ending_one_session_or_all_of_them(db, kim):
    a = sessions.start(db, kim, "pin", now=NOW)
    b = sessions.start(db, kim, "password", now=NOW)
    c = sessions.start(db, kim, "pin", now=NOW)
    sessions.end(db, a)
    assert sessions.find(db, a, now=NOW) is None
    sessions.end_all(db, kim, "pin")
    assert sessions.find(db, c, now=NOW) is None
    assert sessions.find(db, b, now=NOW) is not None
    sessions.end_all(db, kim)
    assert sessions.find(db, b, now=NOW) is None


def test_someone_elses_token_is_nothing(db):
    assert sessions.find(db, "tms_s.abc.def", now=NOW) is None
    assert sessions.find(db, "lms_s.never-issued", now=NOW) is None


def test_a_pin_session_does_its_own_training_and_signs_off_practicals():
    assert sessions.scopes_for("learner", "pin") == ["training:read", "training:write"]
    for permission in ("supervisor", "manager", "admin"):
        assert sessions.scopes_for(permission, "pin") == [
            "training:read", "training:write", "signoffs:write"]
    assert sessions.scopes_for("admin", "password") == ["*"]
    assert sessions.scopes_for("learner", "password") == ["training:read", "training:write"]
    for permission in ("supervisor", "manager"):
        assert "signoffs:write" in sessions.scopes_for(permission, "password")
