"""The competency API: is this person current for what they need, or for
this one competency? For another system with an API key, and for the
people who may see the person."""
import pytest

import yard
from conftest import bearer, make_person
from lms.models import ApiKey


@pytest.fixture
def key(client, admin_headers) -> dict:
    r = client.post("/v1/api-keys", headers=admin_headers,
                    json={"name": "Simple TMS", "scopes": ["competencies:read"]})
    return bearer(r.json()["key"])


@pytest.fixture
def kim(client, manager_headers, learner):
    """Kim is a forklift operator: the induction current, the licence
    expiring, and first aid (not asked of her) done anyway."""
    yard.build(client, manager_headers)
    yard.give_roles(client, manager_headers, "LL042", "forklift-operator")
    yard.grant(client, manager_headers, "LL042", "site-induction", "2026-01-01")
    yard.grant(client, manager_headers, "LL042", "forklift-licence", "2025-01-01",
               expires_on="2026-11-11")
    yard.grant(client, manager_headers, "LL042", "first-aid", "2026-01-01")
    return learner


def test_everything_they_are_asked_for(client, key, kim):
    r = client.get("/v1/people/ll042/competencies", headers=key)
    assert r.status_code == 200, r.text
    assert r.json() == {
        "person": {"code": "LL042", "name": "Kim Lee", "active": True},
        "today": "2026-10-12",
        "competencies": [
            {"key": "forklift-licence", "name": "Forklift licence", "kind": "ticket",
             "status": "expiring", "granted_on": "2025-01-01", "expires_on": "2026-11-11"},
            {"key": "site-induction", "name": "Site induction", "kind": "module",
             "status": "current", "granted_on": "2026-01-01", "expires_on": "2028-01-01"},
        ]}


def test_one_competency(client, key, kim):
    r = client.get("/v1/people/LL042/competencies/Forklift-Licence", headers=key)
    assert r.status_code == 200
    assert r.json() == {"person": {"code": "LL042", "name": "Kim Lee", "active": True},
                        "today": "2026-10-12", "key": "forklift-licence",
                        "name": "Forklift licence", "kind": "ticket", "status": "expiring",
                        "granted_on": "2025-01-01", "expires_on": "2026-11-11"}


def test_one_not_asked_of_them_or_deactivated_is_not_required(client, manager_headers, key, kim):
    r = client.get("/v1/people/LL042/competencies/first-aid", headers=key).json()
    assert (r["status"], r["expires_on"]) == ("not_required", None)
    client.post("/v1/competencies/forklift-licence/deactivate", headers=manager_headers)
    r = client.get("/v1/people/LL042/competencies/forklift-licence", headers=key).json()
    assert r["status"] == "not_required"


def test_someone_who_has_left_says_so(client, manager_headers, key, kim):
    client.post("/v1/people/LL042/deactivate", headers=manager_headers)
    r = client.get("/v1/people/LL042/competencies/site-induction", headers=key).json()
    assert (r["person"]["active"], r["status"]) == (False, "current")


def test_who_or_what_is_not_there(client, key, kim):
    assert client.get("/v1/people/ZZ999/competencies", headers=key).status_code == 404
    assert client.get("/v1/people/LL042/competencies/juggling", headers=key).status_code == 404


def test_a_revoked_key_is_refused(client, db, admin_headers, key, kim):
    k = db.query(ApiKey).one()
    client.post(f"/v1/api-keys/{k.id}/revoke", headers=admin_headers)
    assert client.get("/v1/people/LL042/competencies", headers=key).status_code == 401


def test_a_person_sees_it_for_whom_they_may_see(client, db, manager_headers, supervisor_headers,
                                                learner_headers, kim):
    make_person(db, "LL043", "Ash Patel")
    assert client.get("/v1/people/LL043/competencies", headers=manager_headers).status_code == 200
    # Sam supervises Kim, not Ash
    assert client.get("/v1/people/LL042/competencies",
                      headers=supervisor_headers).status_code == 200
    assert client.get("/v1/people/LL043/competencies",
                      headers=supervisor_headers).status_code == 404
    # a learner's own is My training: /v1/people/{code}/training
    r = client.get("/v1/people/LL042/competencies", headers=learner_headers)
    assert r.status_code == 403
