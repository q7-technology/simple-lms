"""Settings: the value set here wins, then .env, then the default. One
reader, lms/services/settings.py, which every process asks, so a change
takes effect without a restart."""
from lms.config import get_settings
from lms.models import Setting
from lms.services import settings


def test_the_defaults_when_nothing_is_set(db):
    s = settings.current()
    assert s.quiz_cooldown_tries == 3
    assert s.quiz_cooldown_minutes == 60
    assert s.reminder_days == (30, 14, 0)
    assert s.daily_hour == 6
    assert s.timezone == "Australia/Melbourne"
    assert s.sign_in_pin is True and s.sign_in_password is True
    assert settings.source("daily_hour") == "default"


def test_env_wins_over_the_default(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "public_url", "https://env.example.com.au")
    assert settings.current().public_url == "https://env.example.com.au"
    assert settings.source("public_url") == "env"


def test_a_value_set_here_wins_over_env(db, monkeypatch, admin):
    monkeypatch.setattr(get_settings(), "public_url", "https://env.example.com.au")
    settings.save(db, {"public_url": "https://lms.example.com.au"}, admin)
    assert settings.current().public_url == "https://lms.example.com.au"
    assert settings.source("public_url") == "here"
    row = db.get(Setting, "public_url")
    assert row.value == "https://lms.example.com.au" and row.updated_by_id == admin.id


def test_null_goes_back_to_env_or_the_default(db, admin):
    settings.save(db, {"daily_hour": 9}, admin)
    assert settings.current().daily_hour == 9
    settings.save(db, {"daily_hour": None}, admin)
    assert settings.current().daily_hour == 6
    assert db.get(Setting, "daily_hour") is None


def test_another_process_sees_a_change_within_seconds(db, engine, monkeypatch):
    from sqlalchemy.orm import Session

    now = [1000.0]
    monkeypatch.setattr(settings, "monotonic", lambda: now[0])
    assert settings.current().daily_hour == 6
    with Session(engine) as other:   # the API, say, while this is the worker
        other.add(Setting(key="daily_hour", value=8))
        other.commit()
    assert settings.current().daily_hour == 6     # kept a moment
    now[0] += settings.KEEP_SECONDS + 0.1
    assert settings.current().daily_hour == 8


def test_an_env_value_that_is_the_default_says_default(db, monkeypatch):
    """Compose passes every LMS_ variable, empty or at its default, when
    .env leaves it out: that is not something .env chose."""
    monkeypatch.setenv("LMS_SMTP_HOST", "")
    monkeypatch.setenv("LMS_DAILY_HOUR", "6")
    monkeypatch.setenv("LMS_SMTP_PORT", "2525")
    from lms.config import Settings

    monkeypatch.setattr(settings, "get_settings", lambda: Settings())
    assert settings.source("smtp_host") == "default"
    assert settings.source("daily_hour") == "default"
    assert settings.source("smtp_port") == "env"
