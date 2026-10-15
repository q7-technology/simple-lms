"""Microsoft is a third way of signing in, switched in Settings and offered
only once it is set up. Password and Microsoft are never both off, and an
admin can't switch off the way they signed in; `lms clear-setting` is the
way back in."""
import pytest

from conftest import PASSWORD, bearer, login
from lms import cli
from lms.services import sessions, settings

URL = "/v1/settings"


@pytest.fixture
def set_up(monkeypatch):
    """LMS_ENTRA_* and LMS_PUBLIC_URL in .env."""
    from lms.config import get_settings

    env = get_settings()
    monkeypatch.setattr(env, "entra_tenant_id", "6f1c2a4e-7b3d-4e8f-9a01-2b3c4d5e6f70")
    monkeypatch.setattr(env, "entra_client_id", "0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d")
    monkeypatch.setattr(env, "entra_client_secret", "s3cret")
    monkeypatch.setattr(env, "public_url", "https://lms.example.com.au")


@pytest.fixture
def admin_by_entra(db, admin):
    """The admin, signed in with Microsoft."""
    token = sessions.start(db, admin, "entra")
    db.commit()
    return bearer(token)


def put(client, headers, **changes):
    return client.put(URL, headers=headers, json=changes)


def test_a_sign_in_page_is_told_what_to_offer(client):
    assert client.get("/v1/auth/methods").json() == {"pin": True, "password": True,
                                                      "entra": False}


def test_microsoft_is_offered_once_it_is_set_up(client, set_up):
    assert client.get("/v1/auth/methods").json() == {"pin": True, "password": True,
                                                      "entra": True}


def test_microsoft_needs_a_web_address_to_send_people_back_to(client, db, set_up, admin):
    settings.save(db, {"public_url": ""}, admin)
    assert client.get("/v1/auth/methods").json()["entra"] is False


def test_an_admin_sees_the_switch_and_whether_it_is_set_up(client, admin_headers):
    out = client.get(URL, headers=admin_headers).json()
    assert out["sign_in_entra"] == {"value": True, "source": "default", "set_up": False}


def test_switched_off_it_is_not_offered(client, admin_headers, set_up):
    r = put(client, admin_headers, sign_in_entra=False)
    assert r.status_code == 200, r.text
    assert r.json()["sign_in_entra"] == {"value": False, "source": "here", "set_up": True}
    assert client.get("/v1/auth/methods").json()["entra"] is False


def test_passwords_go_off_from_a_microsoft_session(client, admin, admin_by_entra, set_up):
    r = put(client, admin_by_entra, sign_in_password=False)
    assert r.status_code == 200, r.text
    r = client.post("/v1/auth/login", json={"email": admin.email, "password": PASSWORD})
    assert (r.status_code, r.json()["code"]) == (403, "method_off")
    assert client.get("/v1/auth/methods").json() == {"pin": True, "password": False,
                                                      "entra": True}


def test_nobody_switches_off_the_way_they_signed_in(client, admin_headers, admin_by_entra,
                                                     set_up):
    r = put(client, admin_headers, sign_in_password=False)
    assert r.status_code == 409
    assert r.json() == {"detail": "You signed in with an email and password: sign in another "
                                  "way before switching it off.", "code": "own_method"}
    r = put(client, admin_by_entra, sign_in_entra=False)
    assert (r.status_code, r.json()["code"]) == (409, "own_method")


def test_password_and_microsoft_are_never_both_off(client, admin_by_entra, set_up):
    r = put(client, admin_by_entra, sign_in_password=False, sign_in_entra=False)
    assert (r.status_code, r.json()["code"]) == (409, "last_way_in")


def test_microsoft_not_set_up_is_no_way_in(client, admin_by_entra):
    r = put(client, admin_by_entra, sign_in_password=False)
    assert (r.status_code, r.json()["code"]) == (409, "last_way_in")


def test_the_command_line_is_the_way_back_in(client, db, admin, set_up, capsys):
    settings.save(db, {"sign_in_password": False}, admin)
    assert client.post("/v1/auth/login", json={"email": admin.email,
                                               "password": PASSWORD}).status_code == 403
    assert cli.main(["clear-setting", "sign_in_password"]) == 0
    settings.forget()
    assert login(client, admin.email)["token"]
