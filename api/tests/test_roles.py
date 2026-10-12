import pytest

from test_competencies import make_competency


@pytest.fixture
def catalogue(client, manager_headers):
    make_competency(client, manager_headers,
                    {"key": "site-induction", "name": "Site induction", "kind": "module"})
    make_competency(client, manager_headers,
                    {"key": "forklift-licence", "name": "Forklift licence", "kind": "ticket"})
    r = client.post("/v1/roles", headers=manager_headers,
                    json={"key": "Forklift-Operator", "name": "Forklift operator"})
    assert r.status_code == 201, r.text
    return r.json()


def test_a_manager_adds_a_role(catalogue):
    assert catalogue["key"] == "forklift-operator"
    assert catalogue["competencies"] == [] and catalogue["people"] == 0


def test_a_role_key_is_used_once(client, manager_headers, catalogue):
    r = client.post("/v1/roles", headers=manager_headers,
                    json={"key": "forklift-operator", "name": "Again"})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "key"


def test_requirements_are_set_in_full(client, manager_headers, catalogue):
    r = client.put("/v1/roles/forklift-operator/requirements", headers=manager_headers,
                   json={"competencies": ["site-induction", "forklift-licence", "site-induction"]})
    assert r.status_code == 200
    assert [c["key"] for c in r.json()["competencies"]] == ["forklift-licence", "site-induction"]
    r = client.put("/v1/roles/forklift-operator/requirements", headers=manager_headers,
                   json={"competencies": ["site-induction"]})
    assert [c["key"] for c in r.json()["competencies"]] == ["site-induction"]


def test_an_unknown_or_deactivated_competency_is_refused(client, manager_headers, catalogue):
    r = client.put("/v1/roles/forklift-operator/requirements", headers=manager_headers,
                   json={"competencies": ["nope"]})
    assert r.status_code == 422 and "no competency nope" in r.json()["errors"][0]["message"]
    client.post("/v1/competencies/forklift-licence/deactivate", headers=manager_headers)
    r = client.put("/v1/roles/forklift-operator/requirements", headers=manager_headers,
                   json={"competencies": ["forklift-licence"]})
    assert r.status_code == 422 and "deactivated" in r.json()["errors"][0]["message"]


def test_a_role_keeps_a_competency_deactivated_since(client, manager_headers, catalogue):
    client.put("/v1/roles/forklift-operator/requirements", headers=manager_headers,
               json={"competencies": ["forklift-licence"]})
    client.post("/v1/competencies/forklift-licence/deactivate", headers=manager_headers)
    role = client.get("/v1/roles/forklift-operator", headers=manager_headers).json()
    r = client.put("/v1/roles/forklift-operator/requirements", headers=manager_headers,
                   json={"competencies": [c["key"] for c in role["competencies"]]})
    assert r.status_code == 200, r.text
    assert [c["key"] for c in r.json()["competencies"]] == ["forklift-licence"]
    client.post("/v1/competencies/site-induction/deactivate", headers=manager_headers)
    r = client.put("/v1/roles/forklift-operator/requirements", headers=manager_headers,
                   json={"competencies": ["forklift-licence", "site-induction"]})
    assert r.status_code == 422
    assert "site-induction is deactivated" in r.json()["errors"][0]["message"]


def test_rename_and_list(client, manager_headers, supervisor_headers, catalogue):
    r = client.patch("/v1/roles/forklift-operator", headers=manager_headers,
                     json={"name": "Forklift operator (LF)"})
    assert r.json()["name"] == "Forklift operator (LF)"
    r = client.get("/v1/roles", headers=supervisor_headers)
    assert r.status_code == 200 and r.json()["total"] == 1
    assert client.post("/v1/roles", headers=supervisor_headers,
                       json={"key": "x", "name": "X"}).status_code == 403


def test_an_unknown_role_is_404(client, manager_headers):
    assert client.get("/v1/roles/nope", headers=manager_headers).status_code == 404
