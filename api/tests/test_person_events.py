"""person.updated: fired whenever what another system keeps about a person
changes: added, details, roles, deactivated or back. Never a PIN or a
password."""
import pytest

import yard
from conftest import make_person
from lms.models import Outbox, Webhook


@pytest.fixture
def hook(db):
    db.add(Webhook(name="Simple TMS", url="https://tms.example.com.au/in", secret="whsec_x",
                   events=["person.updated"]))
    db.commit()


def fired(db) -> list[dict]:
    db.expire_all()
    return [r.payload["data"]["person"] for r in
            db.query(Outbox).filter_by(kind="webhook").order_by(Outbox.id)]


def test_added(client, db, manager_headers, supervisor, hook):
    yard.build(client, manager_headers)
    r = client.post("/v1/people", headers=manager_headers,
                    json={"code": "ll042", "name": "Kim Lee", "email": "Kim@Example.com.au",
                          "supervisor": "SV001", "roles": ["picker"], "pin": "2468"})
    assert r.status_code == 201
    assert fired(db) == [{"code": "LL042", "name": "Kim Lee", "email": "kim@example.com.au",
                          "permission": "learner", "active": True,
                          "supervisor": {"code": "SV001", "name": "Sam Vu"},
                          "roles": [{"key": "picker", "name": "Picker"}]}]


def test_details_and_roles_changed(client, db, manager_headers, learner, hook):
    yard.build(client, manager_headers)
    client.patch("/v1/people/LL042", headers=manager_headers,
                 json={"name": "Kim Lee-Park", "supervisor": None})
    yard.give_roles(client, manager_headers, "LL042", "forklift-operator", "picker")
    first, second = fired(db)
    assert (first["name"], first["supervisor"], first["roles"]) == ("Kim Lee-Park", None, [])
    assert [r["key"] for r in second["roles"]] == ["forklift-operator", "picker"]


def test_deactivated_and_back(client, db, manager_headers, learner, hook):
    client.post("/v1/people/LL042/deactivate", headers=manager_headers)
    client.post("/v1/people/LL042/reactivate", headers=manager_headers)
    assert [p["active"] for p in fired(db)] == [False, True]


def test_not_for_a_pin_or_a_password(client, db, manager_headers, learner, hook):
    client.post("/v1/people/LL042/pin", headers=manager_headers, json={"pin": "1357"})
    client.post("/v1/people/LL042/password", headers=manager_headers,
                json={"password": "a long new password"})
    assert fired(db) == []


def test_not_for_what_is_refused(client, db, manager_headers, hook):
    make_person(db, "AD002", "Ada Admin", "admin")
    r = client.patch("/v1/people/AD002", headers=manager_headers, json={"name": "Ada"})
    assert r.status_code == 403
    r = client.post("/v1/people", headers=manager_headers,
                    json={"code": "AD002", "name": "Someone else"})
    assert r.status_code == 422
    assert fired(db) == []
