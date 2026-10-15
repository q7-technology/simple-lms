"""Signing in with Microsoft: matched by Entra object id, else the first
time by an email Microsoft has verified, and refused, never added, when
nobody matches. The session token never goes in an address, and a hand-off
works once, soon, and only in the tab that started it."""
import logging
import urllib.parse
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, update

from conftest import bearer
from fake_entra import PUBLIC_URL
from lms.models import EntraSignIn, Person
from lms.services import settings

VERIFIER = "tab-secret-" + "a" * 32


def to_microsoft(client, app: str = "desktop", verifier: str = VERIFIER) -> str:
    r = client.post("/v1/auth/entra/start", json={"app": app, "verifier": verifier})
    assert r.status_code == 200, r.text
    return r.json()["url"]


def back_from_microsoft(client, code: str, state: str, **more) -> tuple[str, dict]:
    """Where the API sends the person, and what is after the #."""
    r = client.get("/v1/auth/entra/callback", params={"code": code, "state": state, **more},
                   follow_redirects=False)
    assert r.status_code == 303, r.text
    assert r.headers["cache-control"] == "no-store"
    page, _, fragment = r.headers["location"].partition("#")
    return page, dict(urllib.parse.parse_qsl(fragment))


def at_microsoft(client, entra, app: str = "desktop", **claims) -> tuple[str, dict]:
    return back_from_microsoft(client, *entra.approve(to_microsoft(client, app), **claims))


def finish(client, code: str, verifier: str = VERIFIER):
    return client.post("/v1/auth/entra/finish", json={"code": code, "verifier": verifier})


def test_matched_by_email_the_first_time_then_by_their_id(client, db, entra, manager):
    page, back = at_microsoft(client, entra, email="Mel@Example.com.au", oid="oid-mel")
    assert page == f"{PUBLIC_URL}/sign-in" and set(back) == {"entra"}
    r = finish(client, back["entra"])
    assert r.status_code == 200, r.text
    me = r.json()["person"]
    assert (me["code"], me["method"], me["idle_seconds"]) == ("MG001", "entra", 12 * 3600)
    assert "records:write" in me["scopes"]
    assert client.get("/v1/auth/me", headers=bearer(r.json()["token"])).status_code == 200
    db.refresh(manager)
    assert manager.entra_oid == "oid-mel" and manager.last_login_at is not None
    # from now on the id is what counts, whatever the email says
    page, back = at_microsoft(client, entra, email="mel.grant@example.com.au", oid="oid-mel")
    assert finish(client, back["entra"]).json()["person"]["code"] == "MG001"


def test_the_learner_app_comes_back_to_its_own_page(client, entra, learner, db):
    learner.email = "kim@example.com.au"
    db.commit()
    url = to_microsoft(client, "learner")
    assert "prompt=login" in url
    page, back = back_from_microsoft(client, *entra.approve(url, email="kim@example.com.au"))
    assert page == f"{PUBLIC_URL}/learn/sign-in"
    me = finish(client, back["entra"]).json()["person"]
    assert (me["code"], me["method"]) == ("LL042", "entra")


def test_the_desktop_lets_them_choose_an_account(client, entra):
    assert "prompt=select_account" in to_microsoft(client, "desktop")


def test_someone_simple_lms_doesnt_know_is_refused_and_not_added(client, db, entra, manager):
    page, back = at_microsoft(client, entra, email="stranger@example.com.au")
    assert back == {"entra_error": "not_matched"}
    assert db.execute(select(func.count()).select_from(Person)).scalar_one() == 1


@pytest.mark.parametrize("claims", [
    {"email": "mel@example.com.au", "xms_edov": None},
    {"email": "mel@example.com.au", "xms_edov": False},
    # a sign-in name is not a checked email
    {"email": None, "preferred_username": "mel@example.com.au"},
])
def test_an_email_microsoft_hasnt_verified_matches_nobody(client, db, entra, manager, claims):
    page, back = at_microsoft(client, entra, **claims)
    assert back == {"entra_error": "not_matched"}
    db.refresh(manager)
    assert manager.entra_oid is None


def test_someone_deactivated_is_refused_either_way(client, db, entra, manager):
    manager.active = False
    db.commit()
    assert at_microsoft(client, entra, email=manager.email)[1] == {"entra_error": "not_matched"}
    db.execute(update(Person).values(entra_oid="oid-mel"))
    db.commit()
    assert at_microsoft(client, entra, oid="oid-mel")[1] == {"entra_error": "not_matched"}


def test_someone_linked_to_one_microsoft_account_keeps_it(client, db, entra, manager):
    manager.entra_oid = "oid-mel"
    db.commit()
    page, back = at_microsoft(client, entra, email=manager.email, oid="oid-someone-else")
    assert back == {"entra_error": "not_matched"}
    db.refresh(manager)
    assert manager.entra_oid == "oid-mel"


def test_the_code_is_swapped_with_the_secret_and_pkce(client, entra, manager):
    url = to_microsoft(client)
    assert "code_challenge=" in url and "client_secret" not in url
    page, back = back_from_microsoft(client, *entra.approve(url, email=manager.email))
    (sent,) = entra.token_requests
    assert sent["grant_type"] == "authorization_code" and sent["client_secret"] == entra.secret
    assert sent["redirect_uri"] == f"{PUBLIC_URL}/v1/auth/entra/callback"
    assert "entra" in back


def test_a_hand_off_works_once(client, entra, manager):
    back = at_microsoft(client, entra, email=manager.email)[1]
    assert finish(client, back["entra"]).status_code == 200
    r = finish(client, back["entra"])
    assert r.status_code == 401
    assert r.json() == {"detail": "that Microsoft sign-in has finished or expired; try again"}


def test_a_hand_off_works_only_in_the_tab_that_started_it(client, entra, manager):
    back = at_microsoft(client, entra, email=manager.email)[1]
    assert finish(client, back["entra"], verifier="someone-elses-tab-" + "b" * 32).status_code == 401
    # and that try used it up
    assert finish(client, back["entra"]).status_code == 401


def test_a_hand_off_lasts_two_minutes(client, db, entra, manager):
    back = at_microsoft(client, entra, email=manager.email)[1]
    db.execute(update(EntraSignIn).values(returned_at=datetime.now(UTC) - timedelta(minutes=3)))
    db.commit()
    assert finish(client, back["entra"]).status_code == 401


def test_each_state_comes_back_once(client, entra, manager):
    code, state = entra.approve(to_microsoft(client), email=manager.email)
    assert "entra" in back_from_microsoft(client, code, state)[1]
    page, back = back_from_microsoft(client, code, state)
    assert (page, back) == (f"{PUBLIC_URL}/sign-in", {"entra_error": "failed"})


def test_a_state_never_given_goes_nowhere(client, entra):
    page, back = back_from_microsoft(client, "a-code", "a-state-we-never-gave")
    assert back == {"entra_error": "failed"}


def test_ten_minutes_at_microsoft_is_too_long(client, db, entra, manager):
    code, state = entra.approve(to_microsoft(client, "learner"), email=manager.email)
    db.execute(update(EntraSignIn).values(created_at=datetime.now(UTC) - timedelta(minutes=11)))
    db.commit()
    assert back_from_microsoft(client, code, state)[1] == {"entra_error": "failed"}


def test_microsoft_saying_no_goes_back_to_the_right_app(client, entra):
    code, state = entra.approve(to_microsoft(client, "learner"))
    r = client.get("/v1/auth/entra/callback", follow_redirects=False, params={
        "state": state, "error": "access_denied", "error_description": "AADSTS65004: declined"})
    assert r.headers["location"] == f"{PUBLIC_URL}/learn/sign-in#entra_error=failed"


@pytest.mark.parametrize("spoil", ["nonce", "code"])
def test_a_token_or_code_that_doesnt_check_out_fails(client, entra, manager, spoil):
    url = to_microsoft(client)
    if spoil == "nonce":
        token = entra.sign(entra.claims(nonce="another-sign-in", email=manager.email))
        code, state = entra.approve(url, token=token)
    else:
        code, state = entra.approve(url, email=manager.email)
        entra.codes.clear()  # Microsoft no longer knows the code
    assert back_from_microsoft(client, code, state)[1] == {"entra_error": "failed"}


def test_microsoft_turned_off_is_refused_at_every_step(client, db, entra, manager):
    url = to_microsoft(client)
    back = at_microsoft(client, entra, email=manager.email)[1]
    settings.save(db, {"sign_in_entra": False}, None)
    r = client.post("/v1/auth/entra/start", json={"app": "desktop", "verifier": VERIFIER})
    assert r.status_code == 403
    assert r.json() == {"detail": "Signing in with Microsoft is switched off here.",
                        "code": "method_off"}
    assert back_from_microsoft(client, *entra.approve(url, email=manager.email))[1] == {
        "entra_error": "method_off"}
    assert finish(client, back["entra"]).json()["code"] == "method_off"


def test_not_set_up_is_off(client):
    r = client.post("/v1/auth/entra/start", json={"app": "desktop", "verifier": VERIFIER})
    assert (r.status_code, r.json()["code"]) == (403, "method_off")


def test_the_tabs_secret_is_long_and_plain(client, entra):
    for verifier in ["short", "has spaces in it and is long enough to pass the length"]:
        r = client.post("/v1/auth/entra/start", json={"app": "desktop", "verifier": verifier})
        assert r.status_code == 422


def test_sign_ins_a_day_old_are_cleared_away(client, db, entra):
    to_microsoft(client)
    db.execute(update(EntraSignIn).values(created_at=datetime.now(UTC) - timedelta(days=2)))
    db.commit()
    to_microsoft(client)
    assert db.execute(select(func.count()).select_from(EntraSignIn)).scalar_one() == 1


def test_what_microsoft_says_is_logged_on_one_line_and_not_too_long(client, entra, caplog):
    code, state = entra.approve(to_microsoft(client))
    caplog.set_level(logging.INFO, logger="lms.entra")
    said = "declined\r\nINFO forged: Mel signed in\x1b[2J\x00" + "x" * 1000
    client.get("/v1/auth/entra/callback", follow_redirects=False, params={
        "state": state, "error": "access_denied\nforged", "error_description": said})
    (line,) = [r.getMessage() for r in caplog.records if r.name == "lms.entra"]
    assert line.startswith("Microsoft sign-in did not finish: access_denied forged declined")
    assert all(ch.isprintable() for ch in line)
    # what Microsoft said, 300 characters of it at most
    assert "x" * 200 in line
    assert len(line) == len("Microsoft sign-in did not finish: access_denied forged ") + 300


@pytest.mark.parametrize("answer", [["a", "list"], {"keys": None}])
def test_keys_that_make_no_sense_are_a_failed_sign_in(client, entra, manager, monkeypatch,
                                                      caplog, answer):
    from lms.services import entra as service

    monkeypatch.setattr(service, "fetch_json", lambda url: answer)
    caplog.set_level(logging.INFO, logger="lms.entra")
    assert at_microsoft(client, entra, email=manager.email)[1] == {"entra_error": "failed"}
    assert any("signing keys" in r.getMessage() for r in caplog.records)


def test_thirty_starts_a_minute_from_one_address_is_enough(client, db, entra):
    for _ in range(30):
        to_microsoft(client)
    r = client.post("/v1/auth/entra/start", json={"app": "desktop", "verifier": VERIFIER})
    assert r.status_code == 429
    assert r.json()["code"] == "too_many_sign_ins"
    assert "retry-after" in r.headers
    assert db.execute(select(func.count()).select_from(EntraSignIn)).scalar_one() == 30
    # a minute on, they may start again
    db.execute(update(EntraSignIn).values(created_at=datetime.now(UTC) - timedelta(minutes=2)))
    db.commit()
    assert to_microsoft(client)


def test_starts_are_counted_by_address(client, db, entra):
    for _ in range(30):
        to_microsoft(client)
    db.execute(update(EntraSignIn).values(client="203.0.113.9"))
    db.commit()
    assert to_microsoft(client)

