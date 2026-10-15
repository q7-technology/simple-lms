"""GET and PUT /v1/settings, for an admin: every setting with where it
comes from, changed a few at a time; and a test email."""
import pytest

from conftest import PIN, bearer, login, make_person, pin_login
from lms.models import Outbox, Setting

URL = "/v1/settings"


def put(client, headers, **changes):
    return client.put(URL, headers=headers, json=changes)


def test_an_admin_sees_every_setting_and_where_it_comes_from(client, admin_headers):
    r = client.get(URL, headers=admin_headers)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["daily_hour"] == {"value": 6, "source": "default"}
    assert out["reminder_days"] == {"value": [30, 14, 0], "source": "default"}
    assert out["quiz_cooldown_tries"] == {"value": 3, "source": "default"}
    assert out["sign_in_pin"] == {"value": True, "source": "default"}
    assert set(out) >= {"timezone", "smtp_host", "smtp_port", "smtp_user", "smtp_from",
                        "smtp_security", "public_url", "quiz_cooldown_minutes",
                        "sign_in_password", "smtp_password"}


def test_the_email_password_is_never_sent_back(client, admin_headers):
    assert client.get(URL, headers=admin_headers).json()["smtp_password"] == {
        "set": False, "source": "default"}
    r = put(client, admin_headers, smtp_password="app password")
    assert r.status_code == 200, r.text
    assert "app password" not in r.text
    assert r.json()["smtp_password"] == {"set": True, "source": "here"}
    # cleared: an empty one, set here
    r = put(client, admin_headers, smtp_password="")
    assert r.json()["smtp_password"] == {"set": False, "source": "here"}


def test_only_an_admin(client, manager_headers, learner_headers):
    for headers in (manager_headers, learner_headers):
        assert client.get(URL, headers=headers).status_code == 403
        assert put(client, headers, daily_hour=7).status_code == 403
        assert client.post(f"{URL}/test-email", headers=headers).status_code == 403
    assert client.get(URL).status_code == 401


def test_a_change_is_kept_with_who_and_when(client, db, admin, admin_headers):
    r = put(client, admin_headers, daily_hour=7, timezone="Australia/Perth",
            reminder_days=[0, 30, 7, 7])
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["daily_hour"] == {"value": 7, "source": "here"}
    assert out["timezone"] == {"value": "Australia/Perth", "source": "here"}
    assert out["reminder_days"]["value"] == [30, 7, 0]
    # left alone
    assert out["smtp_port"]["source"] == "default"
    row = db.get(Setting, "daily_hour")
    assert row.updated_by_id == admin.id and row.updated_at is not None


def test_null_goes_back_to_env_or_the_default(client, admin_headers):
    put(client, admin_headers, daily_hour=7)
    out = put(client, admin_headers, daily_hour=None).json()
    assert out["daily_hour"] == {"value": 6, "source": "default"}


@pytest.mark.parametrize("field,value", [
    ("timezone", "Australia/Ballarat"),
    ("daily_hour", 24),
    ("daily_hour", "6"),
    ("quiz_cooldown_tries", 0),
    ("quiz_cooldown_tries", 21),
    ("reminder_days", []),
    ("reminder_days", [366]),
    ("reminder_days", [1.5]),
    ("smtp_port", 0),
    ("smtp_security", "tls"),
    ("smtp_host", "smtp example"),
    ("smtp_from", "nobody"),
    ("public_url", "lms.example.com.au"),
    ("public_url", "javascript:alert(1)"),
    ("sign_in_pin", "no"),
])
def test_a_bad_value_is_422_on_its_field_and_nothing_is_saved(client, admin_headers, field,
                                                               value):
    r = put(client, admin_headers, **{"quiz_cooldown_minutes": 5, field: value})
    assert r.status_code == 422, r.text
    assert [e["field"] for e in r.json()["errors"]][0].split(".")[0] == field
    assert client.get(URL, headers=admin_headers).json()["quiz_cooldown_minutes"]["value"] == 60


def test_an_unknown_setting_is_422(client, admin_headers):
    r = put(client, admin_headers, database_url="postgresql://elsewhere")
    assert r.status_code == 422
    assert r.json()["errors"][0]["field"] == "database_url"


def test_the_web_address_loses_its_trailing_slash(client, admin_headers):
    out = put(client, admin_headers, public_url="https://lms.example.com.au/").json()
    assert out["public_url"]["value"] == "https://lms.example.com.au"


# --- sign-in methods -------------------------------------------------------

def test_pin_sign_in_switched_off_is_refused(client, admin_headers, learner):
    assert put(client, admin_headers, sign_in_pin=False).status_code == 200
    r = client.post("/v1/auth/pin-login", json={"code": learner.code, "pin": PIN})
    assert r.status_code == 403
    assert r.json()["code"] == "method_off"
    put(client, admin_headers, sign_in_pin=True)
    pin_login(client, learner.code)


def test_password_sign_in_cannot_be_switched_off_while_it_is_an_admins_only_way_in(
        client, admin, admin_headers):
    r = put(client, admin_headers, sign_in_password=False, daily_hour=9)
    assert r.status_code == 409
    assert r.json()["code"] == "last_way_in"
    out = client.get(URL, headers=admin_headers).json()
    assert out["sign_in_password"]["value"] is True
    assert out["daily_hour"]["value"] == 6        # nothing saved
    login(client, admin.email)


def test_password_sign_in_switched_off_is_refused(client, db, admin, monkeypatch):
    """Once another way in exists (Entra, step 5), switching it off sticks."""
    from lms.services import settings

    monkeypatch.setattr(settings, "admin_ways_in", lambda s: ["entra"])
    settings.save(db, {"sign_in_password": False}, admin)
    r = client.post("/v1/auth/login", json={"email": admin.email, "password": "x"})
    assert r.status_code == 403 and r.json()["code"] == "method_off"


def test_the_command_line_works_whatever_is_switched_off(db, admin, capsys):
    from lms import cli
    from lms.services import settings

    settings.save(db, {"sign_in_pin": False}, admin)
    assert cli.main(["clear-setting", "sign_in_pin"]) == 0
    assert "sign_in_pin" in capsys.readouterr().out
    settings.forget()
    assert settings.current().sign_in_pin is True
    assert cli.main(["clear-setting", "no_such_thing"]) == 1


# --- test email ------------------------------------------------------------

def test_a_test_email_is_queued_to_the_admin(client, db, admin_headers, mailbox):
    r = client.post(f"{URL}/test-email", headers=admin_headers)
    assert r.status_code == 202, r.text
    assert r.json()["to"] == "leighton@example.com.au"
    [row] = db.query(Outbox).filter(Outbox.key.startswith("test-email:")).all()
    assert row.payload["to"] == "leighton@example.com.au"
    assert row.payload["subject"] == "Simple LMS: a test email"
    # each press sends one
    client.post(f"{URL}/test-email", headers=admin_headers)
    assert db.query(Outbox).filter(Outbox.key.startswith("test-email:")).count() == 2


def test_no_test_email_without_a_mail_server(client, admin_headers):
    r = client.post(f"{URL}/test-email", headers=admin_headers)
    assert r.status_code == 409 and r.json()["code"] == "no_mail_server"


def test_no_test_email_without_an_address(client, db, mailbox):
    make_person(db, "AD002", "No Email", "admin", password="correct horse battery",
                email="noemail@example.com.au")
    headers = bearer(login(client, "noemail@example.com.au")["token"])
    from lms.models import Person

    p = db.query(Person).filter_by(code="AD002").one()
    p.email = None
    db.commit()
    r = client.post(f"{URL}/test-email", headers=headers)
    assert r.status_code == 409 and r.json()["code"] == "no_email"


def test_the_wait_is_never_negative(client, admin_headers):
    r = put(client, admin_headers, quiz_cooldown_minutes=-1)
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "quiz_cooldown_minutes"


def test_a_problem_is_said_plainly(client, admin_headers):
    r = put(client, admin_headers, timezone="Australia/Ballarat")
    assert r.json()["errors"] == [{"field": "timezone", "message":
                                   "'Australia/Ballarat' is not a time zone, e.g. "
                                   "Australia/Melbourne"}]
