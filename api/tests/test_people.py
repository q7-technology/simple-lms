import pytest

from conftest import PIN, bearer, pin_login

KIM = {"code": "ll042", "name": "Kim Lee", "pin": PIN}


def make(client, headers, body):
    r = client.post("/v1/people", headers=headers, json=body)
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
def roles(client, manager_headers):
    for key, name in (("forklift-operator", "Forklift operator"), ("picker", "Picker")):
        client.post("/v1/roles", headers=manager_headers, json={"key": key, "name": name})


def test_a_manager_adds_a_learner_whose_pin_is_never_shown(client, manager_headers):
    out = make(client, manager_headers, KIM)
    assert (out["code"], out["name"], out["permission"]) == ("LL042", "Kim Lee", "learner")
    assert out["has_pin"] is True and out["has_password"] is False and out["active"] is True
    assert "pin" not in out and "pin_hash" not in out
    assert pin_login(client, "LL042")["person"]["code"] == "LL042"


def test_with_roles_a_supervisor_and_an_email(client, manager_headers, supervisor, roles):
    out = make(client, manager_headers, {**KIM, "email": "Kim@Example.com", "supervisor": "sv001",
                                         "roles": ["picker", "forklift-operator"]})
    assert out["email"] == "kim@example.com"
    assert out["supervisor"] == {"code": "SV001", "name": "Sam Vu"}
    assert [r["key"] for r in out["roles"]] == ["forklift-operator", "picker"]


def test_a_code_and_an_email_are_used_once(client, manager_headers, manager):
    make(client, manager_headers, KIM)
    r = client.post("/v1/people", headers=manager_headers, json={**KIM, "code": "LL042"})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "code"
    r = client.post("/v1/people", headers=manager_headers,
                    json={"code": "LL043", "name": "Lee", "email": "MEL@example.com.au"})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "email"


def test_a_code_or_email_taken_at_the_same_moment_is_still_a_field_error(client, manager_headers,
                                                                         beaten_to_it):
    from lms.models import Person

    beaten_to_it(Person(code="LL042", name="Kim Lee", permission="learner"), "code")
    r = client.post("/v1/people", headers=manager_headers, json=KIM)
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "code"
    beaten_to_it(Person(code="LL098", name="Ash", permission="learner",
                        email="ash@example.com"), "email")
    r = client.post("/v1/people", headers=manager_headers,
                    json={"code": "LL043", "name": "Lee", "email": "ash@example.com"})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "email"
    make(client, manager_headers, {"code": "LL044", "name": "Jo"})
    beaten_to_it(Person(code="LL099", name="Jo", permission="learner",
                        email="jo@example.com"), "email")
    r = client.patch("/v1/people/LL044", headers=manager_headers,
                     json={"email": "jo@example.com"})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "email"


def test_a_pin_is_four_to_eight_digits(client, manager_headers):
    for pin in ("123", "12a4", "123456789"):
        r = client.post("/v1/people", headers=manager_headers, json={**KIM, "pin": pin})
        assert r.status_code == 422


def test_a_supervisor_must_be_able_to_supervise(client, manager_headers, learner):
    r = client.post("/v1/people", headers=manager_headers,
                    json={"code": "LL050", "name": "Ash", "supervisor": "LL042"})
    assert r.status_code == 422
    assert "give them the supervisor permission" in r.json()["errors"][0]["message"]
    r = client.post("/v1/people", headers=manager_headers,
                    json={"code": "LL050", "name": "Ash", "supervisor": "NOBODY"})
    assert r.status_code == 422


def test_an_unknown_role_is_refused(client, manager_headers):
    r = client.post("/v1/people", headers=manager_headers, json={**KIM, "roles": ["nope"]})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "roles"


def test_edit_name_email_and_supervisor_and_clear_them(client, manager_headers, supervisor):
    make(client, manager_headers, {**KIM, "email": "kim@example.com"})
    r = client.patch("/v1/people/ll042", headers=manager_headers,
                     json={"name": "Kim Lee-Smith", "supervisor": "SV001"})
    assert r.json()["name"] == "Kim Lee-Smith" and r.json()["supervisor"]["code"] == "SV001"
    assert r.json()["email"] == "kim@example.com"
    r = client.patch("/v1/people/LL042", headers=manager_headers,
                     json={"supervisor": None, "email": None})
    assert r.json()["supervisor"] is None and r.json()["email"] is None


def test_nobody_supervises_themselves(client, manager_headers, supervisor):
    r = client.patch("/v1/people/SV001", headers=manager_headers, json={"supervisor": "SV001"})
    assert r.status_code == 422 and "own supervisor" in r.json()["errors"][0]["message"]


def test_roles_are_set_in_full(client, manager_headers, roles):
    make(client, manager_headers, {**KIM, "roles": ["picker"]})
    r = client.put("/v1/people/LL042/roles", headers=manager_headers,
                   json={"roles": ["forklift-operator"]})
    assert [x["key"] for x in r.json()["roles"]] == ["forklift-operator"]
    r = client.put("/v1/people/LL042/roles", headers=manager_headers, json={"roles": []})
    assert r.json()["roles"] == []


def test_list_search_and_filter(client, manager_headers, manager, roles):
    make(client, manager_headers, {**KIM, "roles": ["picker"]})
    make(client, manager_headers, {"code": "LL043", "name": "Ash Patel"})
    names = [p["name"] for p in client.get("/v1/people", headers=manager_headers).json()["items"]]
    assert names == ["Ash Patel", "Kim Lee", "Mel Grant"]
    r = client.get("/v1/people?q=ll04", headers=manager_headers).json()
    assert r["total"] == 2
    r = client.get("/v1/people?role=picker", headers=manager_headers).json()
    assert [p["code"] for p in r["items"]] == ["LL042"]


def test_a_search_for_a_wildcard_matches_it_and_nothing_else(client, manager_headers, manager):
    make(client, manager_headers, KIM)
    make(client, manager_headers, {"code": "LL043", "name": "Ash_Patel 100%"})

    def codes(q):
        r = client.get("/v1/people", params={"q": q}, headers=manager_headers).json()
        return [p["code"] for p in r["items"]]

    assert codes("%") == ["LL043"] and codes("_") == ["LL043"]
    assert codes("\\") == []


def test_deactivated_not_deleted_and_signed_out(client, manager_headers):
    make(client, manager_headers, KIM)
    token = pin_login(client, "LL042")["token"]
    r = client.post("/v1/people/LL042/deactivate", headers=manager_headers)
    assert r.status_code == 200 and r.json()["active"] is False
    assert client.get("/v1/auth/me", headers=bearer(token)).status_code == 401
    assert client.get("/v1/people?active=false", headers=manager_headers).json()["total"] == 1
    assert client.post("/v1/people/LL042/reactivate",
                       headers=manager_headers).json()["active"] is True
    assert client.delete("/v1/people/LL042", headers=manager_headers).status_code == 405


def test_nobody_deactivates_themselves(client, admin_headers):
    r = client.post("/v1/people/AD001/deactivate", headers=admin_headers)
    assert r.status_code == 409 and r.json()["code"] == "self"


def test_a_supervisor_cannot_see_or_change_the_people_list(client, supervisor_headers):
    assert client.get("/v1/people", headers=supervisor_headers).status_code == 403
    assert client.post("/v1/people", headers=supervisor_headers, json=KIM).status_code == 403


def test_an_unknown_person_is_404(client, manager_headers):
    assert client.get("/v1/people/NOBODY", headers=manager_headers).status_code == 404


def test_a_supervisor_keeps_their_permission_while_they_have_a_team(client, manager_headers,
                                                                    learner):
    r = client.patch("/v1/people/SV001", headers=manager_headers, json={"permission": "learner"})
    assert r.status_code == 409 and r.json()["code"] == "has_team"
    r = client.post("/v1/people/SV001/deactivate", headers=manager_headers)
    assert r.status_code == 409 and r.json()["code"] == "has_team"


def test_a_supervisor_whose_team_has_gone_can_be_demoted_or_deactivated(client, manager_headers,
                                                                        learner):
    assert client.patch("/v1/people/SV001", headers=manager_headers,
                        json={"name": "Sam Vu"}).status_code == 200
    client.post("/v1/people/LL042/deactivate", headers=manager_headers)
    r = client.patch("/v1/people/SV001", headers=manager_headers, json={"permission": "learner"})
    assert r.status_code == 200 and r.json()["permission"] == "learner"
    assert client.post("/v1/people/SV001/deactivate", headers=manager_headers).status_code == 200


def test_a_supervisor_with_a_team_can_still_move_up(client, admin_headers, learner):
    r = client.patch("/v1/people/SV001", headers=admin_headers, json={"permission": "manager"})
    assert r.status_code == 200 and r.json()["permission"] == "manager"


def test_nobody_changes_their_own_permission(client, admin_headers):
    r = client.patch("/v1/people/AD001", headers=admin_headers, json={"permission": "learner"})
    assert r.status_code == 409 and r.json()["code"] == "self"
    r = client.patch("/v1/people/AD001", headers=admin_headers, json={"name": "Leighton L"})
    assert r.status_code == 200 and r.json()["permission"] == "admin"


def pin_changes(db, code):
    from sqlalchemy import select

    from lms.models import Person, PinChange

    rows = db.execute(select(PinChange).join(Person, Person.id == PinChange.person_id)
                      .where(Person.code == code).order_by(PinChange.id)).scalars()
    return [db.get(Person, r.changed_by_id).code for r in rows]


def test_every_pin_set_is_kept_with_who_set_it(client, db, manager_headers, admin_headers):
    make(client, manager_headers, KIM)
    make(client, manager_headers, {"code": "LL043", "name": "Lee Park"})
    assert pin_changes(db, "LL042") == ["MG001"] and pin_changes(db, "LL043") == []
    client.post("/v1/people/LL042/pin", headers=admin_headers, json={"pin": "1122"})
    client.post("/v1/people/LL043/pin", headers=manager_headers, json={"pin": "1122"})
    assert pin_changes(db, "LL042") == ["MG001", "AD001"]
    assert pin_changes(db, "LL043") == ["MG001"]
