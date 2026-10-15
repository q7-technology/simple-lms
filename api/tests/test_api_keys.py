"""API keys: for other systems, not people. An admin makes one with the
scopes it needs, sees it once, and revokes it; only its hash is kept."""
import hashlib
from datetime import UTC, datetime, timedelta

import pytest

from conftest import bearer
from lms.models import ApiKey
from lms.services import api_keys

TMS = {"name": "Simple TMS", "scopes": ["competencies:read"]}


@pytest.fixture
def made(client, admin_headers):
    r = client.post("/v1/api-keys", headers=admin_headers, json=TMS)
    assert r.status_code == 201, r.text
    return r.json()


def test_made_and_shown_once_and_only_its_hash_kept(client, db, admin_headers, made):
    assert made["key"].startswith("lms_k.") and len(made["key"]) > 40
    assert made["prefix"] == made["key"][:10]
    assert (made["name"], made["scopes"], made["revoked_at"], made["last_used_at"]) == (
        "Simple TMS", ["competencies:read"], None, None)
    assert made["created_by"] == {"code": "AD001", "name": "Leighton Lauton"}
    row = db.query(ApiKey).one()
    assert row.key_hash == hashlib.sha256(made["key"].encode()).hexdigest()
    listed = client.get("/v1/api-keys", headers=admin_headers).json()
    assert [k["name"] for k in listed] == ["Simple TMS"] and "key" not in listed[0]


@pytest.mark.parametrize("body, field", [
    ({"scopes": ["people:write"]}, "scopes.0"),
    ({"scopes": []}, "scopes"),
    ({"name": ""}, "name"),
])
def test_what_is_wrong_is_said(client, admin_headers, body, field):
    r = client.post("/v1/api-keys", headers=admin_headers, json={**TMS, **body})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == field


def test_two_cannot_share_a_name(client, admin_headers, made):
    r = client.post("/v1/api-keys", headers=admin_headers, json=TMS)
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "name"


def test_only_an_admin(client, manager_headers):
    assert client.get("/v1/api-keys", headers=manager_headers).status_code == 403
    assert client.post("/v1/api-keys", headers=manager_headers, json=TMS).status_code == 403


def test_a_key_opens_nothing_a_person_does(client, made):
    for path in ("/v1/auth/me", "/v1/people", "/v1/matrix", "/v1/webhooks"):
        r = client.get(path, headers=bearer(made["key"]))
        assert r.status_code == 403 and r.json()["code"] == "key_not_allowed", path


def test_a_key_that_is_not_ours_is_refused(client):
    r = client.get("/v1/people", headers=bearer("lms_k.not-a-real-one"))
    assert r.status_code == 401


def test_revoked_once_and_it_stops_working(client, db, admin_headers, made):
    r = client.post(f"/v1/api-keys/{made['id']}/revoke", headers=admin_headers)
    assert r.status_code == 200 and r.json()["revoked_at"] is not None
    assert api_keys.find(db, made["key"]) is None
    r = client.post(f"/v1/api-keys/{made['id']}/revoke", headers=admin_headers)
    assert r.status_code == 409 and r.json()["code"] == "revoked"
    assert client.post("/v1/api-keys/999/revoke", headers=admin_headers).status_code == 404


def test_when_it_was_last_used_is_noted_once_a_minute(db, made):
    t0 = datetime(2026, 10, 12, 1, 0, tzinfo=UTC)
    assert api_keys.find(db, made["key"], now=t0).last_used_at == t0
    assert api_keys.find(db, made["key"], now=t0 + timedelta(seconds=30)).last_used_at == t0
    later = t0 + timedelta(minutes=1)
    assert api_keys.find(db, made["key"], now=later).last_used_at == later


# the competency API, the one door a key opens (and only with its scope)
KEY_DOOR = {"/v1/people/{code}/competencies", "/v1/people/{code}/competencies/{key}"}
# what answers without a session, and so is never asked about a key: signing
# in and out, the health check, and a media link (signed in its query)
OPEN_WITHOUT_A_SESSION = {
    ("GET", "/v1/health"), ("GET", "/v1/auth/methods"), ("POST", "/v1/auth/login"),
    ("POST", "/v1/auth/pin-login"), ("POST", "/v1/auth/logout"),
    ("POST", "/v1/auth/entra/start"), ("POST", "/v1/auth/entra/finish"),
    ("GET", "/v1/media/{upload_id}"),
}


def test_no_route_but_the_competency_api_takes_a_key(client, made):
    """Every route that wants a session refuses a key, whatever it is."""
    import re

    from lms.api.app import app

    checked, open_ = 0, set()
    for template, operations in app.openapi()["paths"].items():
        if template in KEY_DOOR:
            continue
        path = re.sub(r"\{[^}]+\}", "1", template)
        for method in operations:
            if client.request(method, path).status_code != 401:
                open_.add((method.upper(), template))
                continue
            r = client.request(method, path, headers=bearer(made["key"]))
            assert (r.status_code, r.json()["code"]) == (403, "key_not_allowed"), (method, path)
            checked += 1
    # the only routes open without a session, so a new one can't slip by
    assert open_ == OPEN_WITHOUT_A_SESSION
    assert checked > 50

