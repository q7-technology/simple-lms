"""Signing off a practical on the phone: a supervisor, for their own team
(a manager or admin, for anyone), never for themselves (rule 3), ticks every
item and signs; the learner confirms with their signature and their PIN.
The grant is recorded by the supervisor, and the refresher does the rest."""
import pytest

import yard
from checklist import practical
from conftest import bearer, make_person, pin_login

PEOPLE = "/v1/signoffs/people"


@pytest.fixture
def team(client, db, manager_headers, supervisor, learner):
    """Kim is on Sam's team, Pat on nobody's; both drive forklifts, and
    forklift drivers are signed off on the forklift practical."""
    practical(client, manager_headers)
    assert client.post("/v1/roles", headers=manager_headers,
                       json={"key": "forklift-driver", "name": "Forklift driver"}).status_code == 201
    assert client.put("/v1/roles/forklift-driver/requirements", headers=manager_headers,
                      json={"competencies": ["forklift-practical"]}).status_code == 200
    make_person(db, "LL099", "Pat Other", pin="1357")
    for code in ("LL042", "LL099"):
        yard.give_roles(client, manager_headers, code, "forklift-driver")
    return learner


@pytest.fixture
def sam(client, supervisor):
    """Sam on the phone, signed in with his PIN."""
    return bearer(pin_login(client, supervisor.code)["token"])


def test_a_supervisor_signs_off_their_own_team(client, sam, team):
    r = client.get(PEOPLE, headers=sam)
    assert r.status_code == 200, r.text
    assert r.json() == [{"code": "LL042", "name": "Kim Lee", "practicals": [
        {"key": "forklift-practical", "name": "Forklift practical", "status": "missing",
         "expires_on": None}]}]


def test_a_manager_signs_off_anyone_but_themselves(client, db, manager, manager_headers, team):
    make_person(db, "LL100", "Lee Gone").active = False
    db.commit()
    people = client.get(PEOPLE, headers=manager_headers).json()
    assert [p["code"] for p in people] == ["LL042", "LL099", "SV001"]
    assert people[2]["practicals"] == []


def test_a_practical_waived_is_not_to_sign_off(client, sam, manager_headers, team):
    r = client.post("/v1/people/LL042/overrides", headers=manager_headers, json={
        "competency": "forklift-practical", "kind": "waive", "note": "Moved to the office"})
    assert r.status_code == 201
    assert client.get(PEOPLE, headers=sam).json()[0]["practicals"] == []


def test_a_learner_signs_nobody_off(client, learner_headers, team):
    r = client.get(PEOPLE, headers=learner_headers)
    assert r.status_code == 403 and r.json()["detail"] == "you do not have the signoffs:write scope"
