import pytest

import yard
from conftest import bearer, make_person, pin_login


@pytest.fixture
def team(client, db, manager_headers, supervisor, learner):
    """Kim (forklift operator) and Ash (picker) are on Sam's team; Pat
    (picker) is not on anyone's."""
    yard.build(client, manager_headers)
    make_person(db, "LL043", "Ash Patel", supervisor=supervisor)
    make_person(db, "LL099", "Pat Other")
    yard.give_roles(client, manager_headers, "LL042", "forklift-operator")
    yard.give_roles(client, manager_headers, "LL043", "picker")
    yard.give_roles(client, manager_headers, "LL099", "picker")
    return learner


def cells(matrix: dict) -> dict:
    """{code: {key: status}}"""
    return {p["code"]: {k: c["status"] for k, c in p["cells"].items()} for p in matrix["people"]}


def test_people_down_the_side_and_what_they_need_across_the_top(client, manager_headers, team):
    yard.grant(client, manager_headers, "LL042", "site-induction", "2025-06-01")
    m = client.get("/v1/matrix", headers=manager_headers).json()
    assert m["today"] == "2026-10-12"
    assert [c["key"] for c in m["competencies"]] == ["forklift-licence", "site-induction"]
    # every active person, by name: someone asked for nothing yet shows too
    assert [p["code"] for p in m["people"]] == ["LL043", "LL042", "MG001", "LL099", "SV001"]
    grey = {"forklift-licence": "not_required", "site-induction": "not_required"}
    assert cells(m) == {
        "LL042": {"forklift-licence": "missing", "site-induction": "current"},
        "LL043": {"forklift-licence": "not_required", "site-induction": "missing"},
        "LL099": {"forklift-licence": "not_required", "site-induction": "missing"},
        "MG001": grey,
        "SV001": grey,
    }
    kim = next(p for p in m["people"] if p["code"] == "LL042")
    assert kim["cells"]["site-induction"] == {"status": "current", "granted_on": "2025-06-01",
                                              "expires_on": "2027-06-01"}
    assert kim["supervisor"] == {"code": "SV001", "name": "Sam Vu"}
    assert kim["roles"] == [{"key": "forklift-operator", "name": "Forklift operator"}]


def test_the_matrix_goes_green_amber_and_red_with_the_dates(client, manager_headers, team, today):
    yard.grant(client, manager_headers, "LL042", "forklift-licence", "2025-01-01",
               expires_on="2026-11-01")
    yard.grant(client, manager_headers, "LL042", "site-induction", "2025-06-01")

    def kim():
        return cells(client.get("/v1/matrix", headers=manager_headers).json())["LL042"]

    assert kim() == {"forklift-licence": "expiring", "site-induction": "current"}
    today.set(today.value.replace(year=2027, month=5, day=15))
    assert kim() == {"forklift-licence": "lapsed", "site-induction": "expiring"}


def test_a_waiver_and_an_extra_show_in_the_cells(client, manager_headers, team):
    client.post("/v1/people/LL043/overrides", headers=manager_headers,
                json={"competency": "site-induction", "kind": "waive", "note": "visiting auditor"})
    client.post("/v1/people/LL043/overrides", headers=manager_headers,
                json={"competency": "first-aid", "kind": "extra", "note": "first aid officer"})
    m = client.get("/v1/matrix", headers=manager_headers).json()
    assert [c["key"] for c in m["competencies"]] == ["first-aid", "forklift-licence",
                                                     "site-induction"]
    assert cells(m)["LL043"] == {"first-aid": "missing", "forklift-licence": "not_required",
                                 "site-induction": "waived"}


def test_a_revoke_cancels_the_grant(client, manager_headers, team):
    yard.grant(client, manager_headers, "LL042", "site-induction", "2025-06-01")
    client.post("/v1/people/LL042/records/revoke", headers=manager_headers,
                json={"competency": "site-induction", "note": "ticked for the wrong person"})
    m = client.get("/v1/matrix", headers=manager_headers).json()
    assert cells(m)["LL042"]["site-induction"] == "missing"


def test_a_supervisor_sees_their_own_team(client, supervisor_headers, team):
    m = client.get("/v1/matrix", headers=supervisor_headers).json()
    assert [p["code"] for p in m["people"]] == ["LL043", "LL042"]


def test_filter_by_role_supervisor_and_status(client, manager_headers, team):
    yard.grant(client, manager_headers, "LL042", "site-induction", "2025-06-01")
    yard.grant(client, manager_headers, "LL042", "forklift-licence", "2025-06-01")

    def codes(query: str):
        r = client.get(f"/v1/matrix?{query}", headers=manager_headers)
        assert r.status_code == 200, r.text
        return [p["code"] for p in r.json()["people"]]

    assert codes("role=picker") == ["LL043", "LL099"]
    assert codes("supervisor=sv001") == ["LL043", "LL042"]
    assert codes("status=missing") == ["LL043", "LL099"]
    assert codes("status=current") == ["LL042"]
    assert codes("status=lapsed,expiring") == []
    r = client.get("/v1/matrix?role=picker", headers=manager_headers).json()
    assert [c["key"] for c in r["competencies"]] == ["site-induction"]


def test_a_bad_filter_is_422(client, manager_headers, team):
    assert client.get("/v1/matrix?status=green", headers=manager_headers).status_code == 422
    assert client.get("/v1/matrix?supervisor=NOBODY", headers=manager_headers).status_code == 422


def test_not_required_is_not_a_filter(client, manager_headers, team):
    # a filter on it would match nobody: the columns are what the people shown are asked for
    for query in ("status=not_required", "status=missing,not_required"):
        r = client.get(f"/v1/matrix?{query}", headers=manager_headers)
        assert r.status_code == 422, r.text
        assert "not_required" in r.text
    assert client.get("/v1/matrix.csv?status=not_required",
                      headers=manager_headers).status_code == 422


def test_deactivated_people_and_competencies_drop_out(client, manager_headers, team):
    client.post("/v1/people/LL099/deactivate", headers=manager_headers)
    client.post("/v1/competencies/forklift-licence/deactivate", headers=manager_headers)
    m = client.get("/v1/matrix", headers=manager_headers).json()
    assert [p["code"] for p in m["people"]] == ["LL043", "LL042", "MG001", "SV001"]
    assert [c["key"] for c in m["competencies"]] == ["site-induction"]


def test_a_learner_has_no_matrix(client, learner_headers, team):
    assert client.get("/v1/matrix", headers=learner_headers).status_code == 403


def test_a_supervisor_signed_in_by_pin_has_no_matrix(client, supervisor, team):
    token = pin_login(client, supervisor.code)["token"]
    assert client.get("/v1/matrix", headers=bearer(token)).status_code == 403


def test_my_training_lists_what_i_need_and_not_what_is_waived(client, manager_headers,
                                                              learner_headers, team):
    yard.grant(client, manager_headers, "LL042", "forklift-licence", "2025-01-01",
               expires_on="2026-11-01")
    client.post("/v1/people/LL042/overrides", headers=manager_headers,
                json={"competency": "whs-policy", "kind": "extra", "note": "covers reception"})
    client.post("/v1/people/LL042/overrides", headers=manager_headers,
                json={"competency": "site-induction", "kind": "waive", "note": "inducted at HQ"})
    r = client.get("/v1/people/ll042/training", headers=learner_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["person"] == {"code": "LL042", "name": "Kim Lee"} and body["today"] == "2026-10-12"
    assert [(i["key"], i["status"], i["expires_on"]) for i in body["items"]] == [
        ("forklift-licence", "expiring", "2026-11-01"),
        ("whs-policy", "missing", None),
    ]
    # whether the card has an expiry date is a ticket's question only
    assert [i["card_expires"] for i in body["items"]] == [True, None]


def test_whose_training_who_may_read(client, db, manager_headers, supervisor_headers,
                                     learner_headers, team):
    assert client.get("/v1/people/LL099/training", headers=learner_headers).status_code == 404
    assert client.get("/v1/people/LL043/training", headers=supervisor_headers).status_code == 200
    assert client.get("/v1/people/LL099/training", headers=supervisor_headers).status_code == 404
    assert client.get("/v1/people/LL099/training", headers=manager_headers).status_code == 200
