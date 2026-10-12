import pytest

import yard


@pytest.fixture
def kim(client, manager_headers, learner):
    yard.build(client, manager_headers)
    yard.give_roles(client, manager_headers, "LL042", "picker")
    return learner


def override(client, headers, kind, competency="first-aid", note="covers the night shift"):
    return client.post("/v1/people/LL042/overrides", headers=headers,
                       json={"competency": competency, "kind": kind, "note": note})


def test_an_extra_with_a_note(client, manager_headers, kim):
    r = override(client, manager_headers, "extra")
    assert r.status_code == 201
    assert r.json()["kind"] == "extra" and r.json()["recorded_by"]["code"] == "MG001"
    now = client.get("/v1/people/LL042/overrides", headers=manager_headers).json()
    assert [(o["competency"]["key"], o["kind"]) for o in now] == [("first-aid", "extra")]


def test_a_note_is_required(client, manager_headers, kim):
    assert override(client, manager_headers, "waive", note="   ").status_code == 422


def test_the_latest_counts_and_a_clear_puts_it_back(client, manager_headers, kim):
    override(client, manager_headers, "extra")
    override(client, manager_headers, "waive", note="first aid officer on site already")
    now = client.get("/v1/people/LL042/overrides", headers=manager_headers).json()
    assert [o["kind"] for o in now] == ["waive"]
    assert override(client, manager_headers, "clear", note="back to the role").status_code == 201
    assert client.get("/v1/people/LL042/overrides", headers=manager_headers).json() == []


def test_nothing_to_clear_is_409(client, manager_headers, kim):
    r = override(client, manager_headers, "clear")
    assert r.status_code == 409 and r.json()["code"] == "nothing_to_clear"


def test_a_supervisor_cannot_waive(client, supervisor_headers, kim):
    assert override(client, supervisor_headers, "waive").status_code == 403


def test_an_unknown_competency_is_404(client, manager_headers, kim):
    assert override(client, manager_headers, "extra", competency="nope").status_code == 404
