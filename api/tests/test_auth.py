from datetime import UTC, datetime, timedelta

from sqlalchemy import update

from conftest import PASSWORD, PIN, all_at_once, bearer, fresh_client, login, pin_login
from lms.models import Session


def test_email_and_password_give_a_session_that_says_who_you_are(client, manager):
    out = login(client, "Mel@Example.com.au ")
    assert out["token"].startswith("lms_s.")
    assert out["person"]["code"] == "MG001" and out["person"]["method"] == "password"
    me = client.get("/v1/auth/me", headers=bearer(out["token"])).json()
    assert me["permission"] == "manager"
    assert "records:write" in me["scopes"] and me["idle_seconds"] == 12 * 3600


def test_code_and_pin_give_a_learner_session(client, learner):
    out = pin_login(client, " ll042")
    me = client.get("/v1/auth/me", headers=bearer(out["token"])).json()
    assert (me["code"], me["method"], me["scopes"]) == ("LL042", "pin", ["training:read", "training:write"])
    assert me["idle_seconds"] == 15 * 60


def test_a_supervisor_signed_in_by_pin_only_does_their_own_training(client, supervisor):
    by_pin = pin_login(client, supervisor.code)["person"]
    assert (by_pin["permission"], by_pin["scopes"]) == ("supervisor", ["training:read", "training:write"])
    by_password = login(client, supervisor.email)["person"]
    assert "matrix:read" in by_password["scopes"]


def test_a_wrong_password_and_an_unknown_email_look_alike(client, manager):
    wrong = client.post("/v1/auth/login", json={"email": manager.email, "password": "nope"})
    unknown = client.post("/v1/auth/login", json={"email": "who@example.com", "password": "nope"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json() == {"detail": "wrong email or password",
                                              "code": "wrong_password"}


def test_someone_without_a_password_cannot_use_one(client, learner):
    r = client.post("/v1/auth/login", json={"email": "kim@example.com", "password": PASSWORD})
    assert r.status_code == 401 and r.json()["code"] == "wrong_password"


def test_five_wrong_passwords_lock_it_for_15_minutes(client, db, manager):
    for _ in range(4):
        client.post("/v1/auth/login", json={"email": manager.email, "password": "nope"})
    r = client.post("/v1/auth/login", json={"email": manager.email, "password": "nope"})
    assert r.status_code == 401 and r.json()["code"] == "locked"
    r = client.post("/v1/auth/login", json={"email": manager.email, "password": PASSWORD})
    assert r.json()["code"] == "locked"
    # 15 minutes on, the right password works
    manager.password_locked_until = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    assert login(client, manager.email)["token"]


def test_five_wrong_pins_lock_the_pin_until_a_manager_resets_it(client, db, learner):
    for _ in range(4):
        r = client.post("/v1/auth/pin-login", json={"code": "LL042", "pin": "0000"})
        assert r.status_code == 401 and r.json()["code"] == "wrong_pin"
    r = client.post("/v1/auth/pin-login", json={"code": "LL042", "pin": "0000"})
    assert r.json()["code"] == "locked"
    r = client.post("/v1/auth/pin-login", json={"code": "LL042", "pin": PIN})
    assert r.status_code == 401 and r.json()["code"] == "locked"
    db.refresh(learner)
    assert learner.pin_locked is True


def test_an_unknown_code_looks_like_a_wrong_pin(client, learner):
    r = client.post("/v1/auth/pin-login", json={"code": "NOBODY", "pin": PIN})
    assert r.status_code == 401 and r.json() == {"detail": "wrong code or PIN",
                                                 "code": "wrong_pin"}


def test_a_right_pin_clears_the_count(client, db, learner):
    client.post("/v1/auth/pin-login", json={"code": "LL042", "pin": "0000"})
    pin_login(client, "LL042")
    db.refresh(learner)
    assert learner.pin_failed_attempts == 0


def test_wrong_pins_sent_all_at_once_still_lock_after_five(client, db, learner):
    def guess():
        return fresh_client().post("/v1/auth/pin-login",
                                   json={"code": "LL042", "pin": "0000"}).json()["code"]

    codes = all_at_once(8, guess)
    assert codes.count("wrong_pin") == 4 and codes.count("locked") == 4


def test_signing_out_ends_the_session(client, learner):
    token = pin_login(client, "LL042")["token"]
    assert client.post("/v1/auth/logout", headers=bearer(token)).status_code == 204
    assert client.get("/v1/auth/me", headers=bearer(token)).status_code == 401
    # again, or with nothing at all, is still fine
    assert client.post("/v1/auth/logout", headers=bearer(token)).status_code == 204
    assert client.post("/v1/auth/logout").status_code == 204


def test_15_minutes_idle_ends_a_pin_session(client, db, learner):
    token = pin_login(client, "LL042")["token"]
    db.execute(update(Session).values(last_seen_at=datetime.now(UTC) - timedelta(minutes=16)))
    db.commit()
    assert client.get("/v1/auth/me", headers=bearer(token)).status_code == 401


def test_no_token_or_a_bad_one_is_401(client):
    assert client.get("/v1/auth/me").status_code == 401
    assert client.get("/v1/auth/me", headers=bearer("lms_s.forged")).status_code == 401
    assert client.get("/v1/auth/me", headers=bearer("tms_s.someone-elses")).status_code == 401


def test_a_deactivated_person_loses_their_session(client, db, learner):
    token = pin_login(client, "LL042")["token"]
    learner.active = False
    db.commit()
    assert client.get("/v1/auth/me", headers=bearer(token)).status_code == 401
    r = client.post("/v1/auth/pin-login", json={"code": "LL042", "pin": PIN})
    assert r.json()["code"] == "wrong_pin"
