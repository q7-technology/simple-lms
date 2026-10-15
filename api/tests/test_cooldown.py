"""Three tries in a row that didn't pass, and the learner waits
LMS_QUIZ_COOLDOWN_MINUTES before the next go, worked out from the attempts
themselves. A pass in between starts the count again; 0 turns it off."""
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

import yard
from conftest import bearer, make_person, pin_login
from course import INDUCTION, RIGHT, published

ATTEMPTS = f"{INDUCTION}/attempts"
WRONG = [1, 0]


@pytest.fixture
def kim(client, manager_headers, learner):
    yard.build(client, manager_headers)
    yard.give_roles(client, manager_headers, "LL042", "picker")
    published(client, manager_headers)
    return learner


@pytest.fixture
def later(monkeypatch):
    """The API's now, moved on by later(minutes) from the real one."""
    from lms.services import clock

    real = clock.now

    def move(minutes: float):
        monkeypatch.setattr(clock, "now", lambda: real() + timedelta(minutes=minutes))

    return move


@pytest.fixture
def cooldown(monkeypatch):
    from lms.config import get_settings

    return lambda minutes: monkeypatch.setattr(get_settings(), "quiz_cooldown_minutes", minutes)


def take(client, headers, answers=RIGHT, version=1):
    return client.post(ATTEMPTS, headers=headers, json={"version": version, "answers": answers})


def attempts(client, headers):
    return client.get("/v1/people/LL042/attempts", headers=headers).json()


def three_fails(client, headers):
    for _ in range(3):
        assert take(client, headers, answers=WRONG).status_code == 201


def test_the_wait_defaults_to_an_hour():
    from lms.config import Settings

    assert Settings().quiz_cooldown_minutes == 60


def test_the_wait_is_never_negative(monkeypatch):
    from pydantic import ValidationError

    from lms.config import Settings

    monkeypatch.setenv("LMS_QUIZ_COOLDOWN_MINUTES", "-1")
    with pytest.raises(ValidationError):
        Settings()


def test_two_fails_then_a_third_and_the_next_go_waits(client, learner_headers, kim):
    take(client, learner_headers, answers=WRONG)
    take(client, learner_headers, answers=WRONG)
    # two in a row: still free to try
    assert client.get(INDUCTION, headers=learner_headers).json()["retry_at"] is None
    assert take(client, learner_headers, answers=WRONG).status_code == 201
    third = datetime.fromisoformat(attempts(client, learner_headers)[0]["created_at"])
    r = take(client, learner_headers)
    assert r.status_code == 429, r.text
    out = r.json()
    retry_at = datetime.fromisoformat(out["retry_at"])
    assert retry_at == third + timedelta(minutes=60)
    local = retry_at.astimezone(ZoneInfo("Australia/Melbourne"))
    clock = f"{local.hour % 12 or 12}:{local:%M} {'am' if local.hour < 12 else 'pm'}"
    assert out["code"] == "cooldown"
    assert out["detail"] == f"Three tries in a row didn't pass: try again after {clock}"
    assert r.headers["Retry-After"].isdigit()
    # nothing was kept of the refused go
    assert len(attempts(client, learner_headers)) == 3


def test_after_the_wait_they_try_again(client, learner_headers, kim, later):
    three_fails(client, learner_headers)
    later(59)
    assert take(client, learner_headers).status_code == 429
    later(61)
    r = take(client, learner_headers)
    assert r.status_code == 201 and r.json()["passed"] is True
    assert client.get(INDUCTION, headers=learner_headers).json()["retry_at"] is None


def failed_earlier(db, person, minutes_ago: int, n: int = 3):
    """n goes that didn't pass, kept `minutes_ago` minutes back."""
    from sqlalchemy import select

    from lms.models import Competency, QuizAttempt
    from lms.services.modules import newest

    c = db.execute(select(Competency).where(Competency.key == "site-induction")).scalar_one()
    v = newest(db, c)
    at = datetime.now(UTC) - timedelta(minutes=minutes_ago)
    for i in range(n):
        db.add(QuizAttempt(person_id=person.id, competency_id=c.id, module_version_id=v.id,
                           answers=WRONG, correct=0, total=2, score=0, passed=False,
                           created_at=at + timedelta(seconds=i)))
    db.commit()


def test_a_fail_after_the_wait_waits_again(client, db, learner_headers, kim):
    failed_earlier(db, kim, minutes_ago=61)
    assert client.get(INDUCTION, headers=learner_headers).json()["retry_at"] is None
    assert take(client, learner_headers, answers=WRONG).status_code == 201
    assert take(client, learner_headers).status_code == 429


def test_a_pass_in_between_starts_the_count_again(client, learner_headers, kim):
    take(client, learner_headers, answers=WRONG)
    take(client, learner_headers, answers=WRONG)
    assert take(client, learner_headers).json()["passed"] is True
    take(client, learner_headers, answers=WRONG)
    take(client, learner_headers, answers=WRONG)
    assert take(client, learner_headers, answers=WRONG).status_code == 201
    assert take(client, learner_headers).status_code == 429


def test_the_fails_count_across_versions(client, manager_headers, learner_headers, kim):
    take(client, learner_headers, answers=WRONG)
    take(client, learner_headers, answers=WRONG)
    published(client, manager_headers)
    take(client, learner_headers, answers=WRONG, version=2)
    assert take(client, learner_headers, version=2).status_code == 429


def test_each_person_and_module_counts_alone(client, db, learner_headers, kim):
    three_fails(client, learner_headers)
    make_person(db, "LL099", "Pat Other", pin="1357")
    pat = bearer(pin_login(client, "LL099", "1357")["token"])
    assert take(client, pat).status_code == 201
    assert client.get(INDUCTION, headers=pat).json()["retry_at"] is None


def test_no_wait_when_the_setting_is_0(client, learner_headers, kim, cooldown):
    cooldown(0)
    three_fails(client, learner_headers)
    assert client.get(INDUCTION, headers=learner_headers).json()["retry_at"] is None
    assert take(client, learner_headers, answers=WRONG).status_code == 201
    assert take(client, learner_headers).status_code == 201


def test_the_wait_is_the_setting(client, learner_headers, kim, cooldown, later):
    cooldown(1440)
    three_fails(client, learner_headers)
    later(61)
    assert take(client, learner_headers).status_code == 429
    later(1441)
    assert take(client, learner_headers).status_code == 201


def test_the_module_says_when_they_can_try_again(client, learner_headers, kim, later):
    assert client.get(INDUCTION, headers=learner_headers).json()["retry_at"] is None
    three_fails(client, learner_headers)
    third = datetime.fromisoformat(attempts(client, learner_headers)[0]["created_at"])
    out = client.get(INDUCTION, headers=learner_headers).json()
    assert datetime.fromisoformat(out["retry_at"]) == third + timedelta(minutes=60)
    later(61)
    assert client.get(INDUCTION, headers=learner_headers).json()["retry_at"] is None


def test_the_time_is_said_in_the_business_timezone():
    from lms.services.modules import said_at

    when = datetime(2026, 10, 15, 3, 15, tzinfo=UTC)  # 2:15 pm in Melbourne (AEDT)
    assert said_at(when, when) == "2:15 pm"
    assert said_at(datetime(2026, 10, 15, 12, 5, tzinfo=UTC), when) == "11:05 pm"
    # another day: the day too
    assert said_at(datetime(2026, 10, 15, 14, 0, tzinfo=UTC), when) == "1:00 am on Fri 16 Oct"


@pytest.fixture
def setting(db, admin):
    from lms.services import settings

    return lambda **changes: settings.save(db, changes, admin)


def test_the_tries_before_the_wait_are_a_setting(client, learner_headers, kim, setting):
    setting(quiz_cooldown_tries=2)
    take(client, learner_headers, answers=WRONG)
    assert take(client, learner_headers, answers=WRONG).status_code == 201
    r = take(client, learner_headers)
    assert r.status_code == 429
    assert r.json()["detail"].startswith("Two tries in a row didn't pass")


def test_the_wait_set_here_wins(client, learner_headers, kim, setting, later):
    setting(quiz_cooldown_minutes=5)
    three_fails(client, learner_headers)
    later(6)
    assert take(client, learner_headers).status_code == 201


def test_the_time_is_said_in_the_zone_set_here(db, admin):
    from lms.services import settings
    from lms.services.modules import said_at

    settings.save(db, {"timezone": "Australia/Perth"}, admin)
    when = datetime(2026, 10, 15, 3, 15, tzinfo=UTC)  # 11:15 am in Perth
    assert said_at(when, when) == "11:15 am"


def test_today_is_in_the_zone_set_here(db, admin, monkeypatch):
    from lms.services import clock, settings

    monkeypatch.undo()   # the real clock.today, not the tests' fixed day
    settings.save(db, {"timezone": "Pacific/Kiritimati"}, admin)   # UTC+14
    late = datetime(2026, 10, 15, 11, 0, tzinfo=UTC)
    monkeypatch.setattr(clock, "datetime", type("D", (datetime,), {
        "now": staticmethod(lambda tz=None: late.astimezone(tz))}))
    assert clock.today() == date(2026, 10, 16)
