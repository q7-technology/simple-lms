"""A practical's checklist: versions published whole by a manager, never
changed, the newest the one a supervisor ticks."""
import pytest

from checklist import FORKLIFT, ITEMS, practical, published
from conftest import all_at_once, bearer, fresh_client, pin_login


@pytest.fixture
def forklift(client, manager_headers):
    practical(client, manager_headers)


def test_versions_are_numbered_newest_first_with_their_items_in_order(client, manager_headers,
                                                                       forklift):
    one = published(client, manager_headers)
    two = published(client, manager_headers, [*ITEMS, "Signs the pre-start book"],
                    note="the pre-start book")
    assert (one["version"], two["version"]) == (1, 2)
    assert [i["text"] for i in one["items"]] == ITEMS
    assert two["published_by"] == {"code": "MG001", "name": "Mel Grant"}
    r = client.get(f"{FORKLIFT}/versions", headers=manager_headers).json()
    assert [v["version"] for v in r] == [2, 1] and r[0]["note"] == "the pre-start book"
    assert [i["text"] for i in r[0]["items"]][-1] == "Signs the pre-start book"


def test_a_checklist_has_one_to_fifty_things_to_see(client, manager_headers, forklift):
    for items in ([], ["  "], ["x"] * 51, ["x" * 301]):
        r = client.post(f"{FORKLIFT}/versions", headers=manager_headers, json={"items": items})
        assert r.status_code == 422, items


def test_only_a_practical_has_a_checklist(client, manager_headers, forklift):
    r = client.post("/v1/competencies", headers=manager_headers,
                    json={"key": "whs-policy", "name": "WHS policy", "kind": "policy"})
    assert r.status_code == 201
    r = client.post("/v1/practicals/whs-policy/versions", headers=manager_headers,
                    json={"items": ITEMS})
    assert r.status_code == 404 and r.json()["detail"] == "no practical whs-policy"
    assert client.get("/v1/practicals/nothing", headers=manager_headers).status_code == 404


def test_a_learner_or_supervisor_cannot_publish(client, learner_headers, supervisor_headers,
                                                forklift):
    for headers in (learner_headers, supervisor_headers):
        r = client.post(f"{FORKLIFT}/versions", headers=headers, json={"items": ITEMS})
        assert r.status_code == 403


def test_the_checklist_to_tick_now(client, manager_headers, supervisor, forklift):
    sam = bearer(pin_login(client, supervisor.code)["token"])
    r = client.get(FORKLIFT, headers=sam)
    assert r.status_code == 404
    assert r.json()["detail"] == "Forklift practical has no checklist yet"
    published(client, manager_headers)
    published(client, manager_headers, ITEMS[:2])
    out = client.get(FORKLIFT, headers=sam).json()
    assert (out["key"], out["name"], out["version"]["version"]) == (
        "forklift-practical", "Forklift practical", 2)
    assert [i["text"] for i in out["version"]["items"]] == ITEMS[:2]


def test_a_deactivated_practical_gets_no_new_checklist(client, manager_headers, forklift):
    client.post("/v1/competencies/forklift-practical/deactivate", headers=manager_headers)
    r = client.post(f"{FORKLIFT}/versions", headers=manager_headers, json={"items": ITEMS})
    assert r.status_code == 409 and r.json()["code"] == "inactive"


def test_two_published_at_once_are_1_and_2(client, manager_headers, forklift):
    def publish():
        return fresh_client().post(f"{FORKLIFT}/versions", headers=manager_headers,
                                   json={"items": ITEMS}).json()["version"]

    assert sorted(all_at_once(2, publish)) == [1, 2]
