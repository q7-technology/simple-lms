import pytest

import yard
from conftest import bearer, login, make_person


@pytest.fixture
def kim(client, manager_headers, learner):
    yard.build(client, manager_headers)
    yard.give_roles(client, manager_headers, "LL042", "forklift-operator")
    return learner


def test_a_manager_records_a_completion_by_hand(client, manager_headers, kim):
    out = yard.grant(client, manager_headers, "LL042", "forklift-licence", "2026-03-01",
                     expires_on="2031-03-01", note="LF 0012345, sighted")
    assert out["kind"] == "granted" and out["competency"]["key"] == "forklift-licence"
    assert (out["granted_on"], out["expires_on"]) == ("2026-03-01", "2031-03-01")
    assert out["recorded_by"] == {"code": "MG001", "name": "Mel Grant"}


def test_nobody_records_their_own(client, db, manager_headers, manager, kim):
    r = client.post("/v1/people/MG001/records", headers=manager_headers,
                    json={"competency": "site-induction", "granted_on": "2026-10-01"})
    assert r.status_code == 403 and r.json()["code"] == "own_record"


def test_not_even_an_admin(client, admin_headers, kim):
    r = client.post("/v1/people/AD001/records", headers=admin_headers,
                    json={"competency": "site-induction", "granted_on": "2026-10-01"})
    assert r.status_code == 403


def test_dates_must_make_sense(client, manager_headers, kim):
    def post(**body):
        return client.post("/v1/people/LL042/records", headers=manager_headers,
                           json={"competency": "forklift-licence", **body})

    r = post(granted_on="2026-10-13")
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "granted_on"
    r = post(granted_on="2026-03-01", expires_on="2026-03-01")
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "expires_on"
    assert post(granted_on="2026-10-12").status_code == 201


def test_not_for_a_deactivated_competency_or_person(client, manager_headers, kim):
    client.post("/v1/competencies/whs-policy/deactivate", headers=manager_headers)
    r = client.post("/v1/people/LL042/records", headers=manager_headers,
                    json={"competency": "whs-policy", "granted_on": "2026-10-01"})
    assert r.status_code == 422
    client.post("/v1/people/LL042/deactivate", headers=manager_headers)
    r = client.post("/v1/people/LL042/records", headers=manager_headers,
                    json={"competency": "site-induction", "granted_on": "2026-10-01"})
    assert r.status_code == 409 and r.json()["code"] == "inactive"


def test_revoke_needs_a_note_and_a_grant_to_cancel(client, manager_headers, kim):
    def revoke(note="wrong person ticked"):
        return client.post("/v1/people/LL042/records/revoke", headers=manager_headers,
                           json={"competency": "site-induction", "note": note})

    assert revoke().status_code == 409 and revoke().json()["code"] == "nothing_to_revoke"
    yard.grant(client, manager_headers, "LL042", "site-induction", "2026-09-01")
    assert revoke(note="").status_code == 422
    out = revoke().json()
    assert out["kind"] == "revoked" and out["granted_on"] is None
    assert revoke().status_code == 409


def test_history_is_newest_first(client, manager_headers, kim):
    yard.grant(client, manager_headers, "LL042", "site-induction", "2025-01-10")
    yard.grant(client, manager_headers, "LL042", "forklift-licence", "2026-03-01")
    yard.grant(client, manager_headers, "LL042", "site-induction", "2024-11-02",
               note="date was wrong: induction was in 2024")
    r = client.get("/v1/people/LL042/records?competency=site-induction", headers=manager_headers)
    assert [x["granted_on"] for x in r.json()] == ["2024-11-02", "2025-01-10"]
    assert len(client.get("/v1/people/LL042/records", headers=manager_headers).json()) == 3


def test_who_sees_whose_history(client, db, manager_headers, supervisor_headers, learner_headers,
                                kim):
    yard.grant(client, manager_headers, "LL042", "site-induction", "2026-09-01")
    other = make_person(db, "LL099", "Pat Other", pin="1357")
    path = "/v1/people/LL042/records"
    assert client.get(path, headers=learner_headers).status_code == 200      # their own
    assert client.get(path, headers=supervisor_headers).status_code == 200   # their team
    pat = client.post("/v1/auth/pin-login", json={"code": other.code, "pin": "1357"}).json()
    assert client.get(path, headers=bearer(pat["token"])).status_code == 404
    # a supervisor sees their team only
    assert client.get("/v1/people/LL099/records", headers=supervisor_headers).status_code == 404


def test_a_supervisor_or_learner_cannot_record(client, supervisor_headers, learner_headers, kim):
    for headers in (supervisor_headers, learner_headers):
        r = client.post("/v1/people/LL042/records", headers=headers,
                        json={"competency": "site-induction", "granted_on": "2026-10-01"})
        assert r.status_code == 403
