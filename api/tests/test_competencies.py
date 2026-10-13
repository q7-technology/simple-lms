INDUCTION = {"key": "Site-Induction", "name": "Site induction", "kind": "module",
             "refresher_months": 24}


def make_competency(client, headers, body=INDUCTION):
    r = client.post("/v1/competencies", headers=headers, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_a_manager_adds_a_competency(client, manager_headers):
    out = make_competency(client, manager_headers)
    assert (out["key"], out["name"], out["kind"]) == ("site-induction", "Site induction", "module")
    assert out["refresher_months"] == 24 and out["active"] is True


def test_four_kinds_only(client, manager_headers):
    r = client.post("/v1/competencies", headers=manager_headers, json={**INDUCTION, "kind": "quiz"})
    assert r.status_code == 422


def test_a_refresher_is_1_to_240_months_or_none(client, manager_headers):
    for months in (0, 241):
        r = client.post("/v1/competencies", headers=manager_headers,
                        json={**INDUCTION, "refresher_months": months})
        assert r.status_code == 422
    out = make_competency(client, manager_headers,
                          {"key": "forklift-licence", "name": "Forklift licence", "kind": "ticket"})
    assert out["refresher_months"] is None


def test_a_key_is_used_once(client, manager_headers):
    make_competency(client, manager_headers)
    r = client.post("/v1/competencies", headers=manager_headers,
                    json={**INDUCTION, "key": "site-induction"})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "key"


def test_a_key_taken_at_the_same_moment_is_still_a_field_error(client, manager_headers,
                                                               beaten_to_it):
    from lms.models import Competency

    beaten_to_it(Competency(key="site-induction", name="Site induction", kind="module"), "key")
    r = client.post("/v1/competencies", headers=manager_headers, json=INDUCTION)
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "key"


def test_a_key_is_letters_digits_and_dashes(client, manager_headers):
    r = client.post("/v1/competencies", headers=manager_headers,
                    json={**INDUCTION, "key": "site induction"})
    assert r.status_code == 422


def test_the_name_and_refresher_change_but_the_kind_stays(client, manager_headers):
    make_competency(client, manager_headers)
    r = client.patch("/v1/competencies/site-induction", headers=manager_headers,
                     json={"name": "Site induction (Ballarat)", "refresher_months": None})
    assert r.status_code == 200
    assert r.json()["name"] == "Site induction (Ballarat)" and r.json()["refresher_months"] is None
    r = client.patch("/v1/competencies/site-induction", headers=manager_headers,
                     json={"kind": "policy"})
    assert r.status_code == 422


def test_list_by_name_and_filter_by_kind(client, manager_headers):
    make_competency(client, manager_headers)
    make_competency(client, manager_headers,
                    {"key": "forklift-licence", "name": "Forklift licence", "kind": "ticket"})
    r = client.get("/v1/competencies", headers=manager_headers).json()
    assert [c["key"] for c in r["items"]] == ["forklift-licence", "site-induction"]
    r = client.get("/v1/competencies?kind=ticket", headers=manager_headers).json()
    assert r["total"] == 1


def test_deactivated_not_deleted(client, manager_headers):
    make_competency(client, manager_headers)
    r = client.post("/v1/competencies/site-induction/deactivate", headers=manager_headers)
    assert r.json()["active"] is False
    assert client.get("/v1/competencies?active=true", headers=manager_headers).json()["total"] == 0
    assert client.post("/v1/competencies/site-induction/reactivate",
                       headers=manager_headers).json()["active"] is True
    assert client.delete("/v1/competencies/site-induction",
                         headers=manager_headers).status_code == 405


def test_a_supervisor_reads_but_does_not_change(client, manager_headers, supervisor_headers):
    make_competency(client, manager_headers)
    assert client.get("/v1/competencies/site-induction", headers=supervisor_headers).status_code == 200
    r = client.patch("/v1/competencies/site-induction", headers=supervisor_headers,
                     json={"name": "x"})
    assert r.status_code == 403


def test_a_learner_cannot_see_the_list(client, learner_headers):
    assert client.get("/v1/competencies", headers=learner_headers).status_code == 403


def test_an_unknown_competency_is_404(client, manager_headers):
    assert client.get("/v1/competencies/nope", headers=manager_headers).status_code == 404


def test_a_ticket_says_whether_its_card_runs_out(client, manager_headers):
    out = make_competency(client, manager_headers,
                          {"key": "forklift-licence", "name": "Forklift licence", "kind": "ticket"})
    assert out["card_expires"] is True
    out = make_competency(client, manager_headers, {"key": "white-card", "name": "White card",
                                                    "kind": "ticket", "card_expires": False})
    assert out["card_expires"] is False
    r = client.patch("/v1/competencies/white-card", headers=manager_headers,
                     json={"card_expires": True})
    assert r.json()["card_expires"] is True
