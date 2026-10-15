"""A module as the learner takes it: the newest published version, its
pages and its questions without the right answers, and how far they have
read kept on the server."""
import pytest

import yard
from conftest import bearer, pin_login
from course import INDUCTION, published, save, written
from files import MP4


@pytest.fixture
def kim(client, manager_headers, learner):
    """Kim is a picker: pickers do the site induction."""
    yard.build(client, manager_headers)
    yard.give_roles(client, manager_headers, "LL042", "picker")
    return learner


def test_nothing_to_take_until_it_is_published(client, manager_headers, learner_headers, kim):
    written(client, manager_headers)
    r = client.get(INDUCTION, headers=learner_headers)
    assert r.status_code == 404 and r.json()["detail"] == "Site induction has nothing to take yet"


def test_the_learner_gets_the_newest_published_version_without_the_answers(
        client, manager_headers, learner_headers, kim):
    published(client, manager_headers)
    # version 2 is being written: nobody takes it until it is published
    client.post(f"{INDUCTION}/draft", headers=manager_headers)
    save(client, manager_headers, pages=[{"kind": "text", "title": "New", "body": "New."}])
    out = client.get(INDUCTION, headers=learner_headers).json()
    assert (out["key"], out["name"], out["resume_at"]) == ("site-induction", "Site induction", 0)
    v = out["version"]
    assert (v["version"], v["pass_mark"], len(v["pages"])) == (1, 80, 5)
    assert v["questions"] == [
        {"prompt": "Where do you sign in?", "options": ["The gatehouse", "The canteen"]},
        {"prompt": "What do you wear on the floor?", "options": ["Thongs", "Your PPE", "Anything"]},
    ]
    assert "correct" not in str(out)


def test_the_learners_links_open_the_files(client, manager_headers, learner_headers, kim):
    published(client, manager_headers)
    video = client.get(INDUCTION, headers=learner_headers).json()["version"]["pages"][3]
    r = client.get(video["file"]["link"])
    assert r.status_code == 200 and r.content == MP4


def test_where_they_left_off_is_kept(client, manager_headers, learner_headers, learner, kim):
    published(client, manager_headers)
    r = client.put(f"{INDUCTION}/progress", headers=learner_headers, json={"version": 1, "page": 3})
    assert r.status_code == 204
    assert client.get(INDUCTION, headers=learner_headers).json()["resume_at"] == 3
    # on another device, the same place
    tablet = bearer(pin_login(client, learner.code)["token"])
    assert client.get(INDUCTION, headers=tablet).json()["resume_at"] == 3
    # one past the last page is the quiz
    client.put(f"{INDUCTION}/progress", headers=tablet, json={"version": 1, "page": 5})
    assert client.get(INDUCTION, headers=learner_headers).json()["resume_at"] == 5


def test_each_person_has_their_own_place(client, manager_headers, learner_headers,
                                         supervisor_headers, kim):
    published(client, manager_headers)
    client.put(f"{INDUCTION}/progress", headers=learner_headers, json={"version": 1, "page": 3})
    assert client.get(INDUCTION, headers=supervisor_headers).json()["resume_at"] == 0


def test_a_new_version_starts_from_the_top(client, manager_headers, learner_headers, kim):
    published(client, manager_headers)
    client.put(f"{INDUCTION}/progress", headers=learner_headers, json={"version": 1, "page": 3})
    published(client, manager_headers)
    assert client.get(INDUCTION, headers=learner_headers).json()["resume_at"] == 0
    r = client.put(f"{INDUCTION}/progress", headers=learner_headers,
                   json={"version": 1, "page": 4})
    assert r.status_code == 409 and r.json()["code"] == "new_version"


def test_the_place_is_within_the_module(client, manager_headers, learner_headers, kim):
    published(client, manager_headers)
    r = client.put(f"{INDUCTION}/progress", headers=learner_headers,
                   json={"version": 1, "page": 6})
    assert r.status_code == 422 and r.json()["errors"] == [
        {"field": "page", "message": "this version has 5 pages, then the quiz"}]


def test_a_deactivated_module_is_not_read_or_kept(client, manager_headers, learner_headers, kim):
    published(client, manager_headers)
    client.put(f"{INDUCTION}/progress", headers=learner_headers, json={"version": 1, "page": 2})
    client.post("/v1/competencies/site-induction/deactivate", headers=manager_headers)
    r = client.get(INDUCTION, headers=learner_headers)
    assert r.status_code == 409 and r.json()["code"] == "inactive"
    r = client.put(f"{INDUCTION}/progress", headers=learner_headers, json={"version": 1, "page": 3})
    assert r.status_code == 409 and r.json()["code"] == "inactive"
    # its editors still see its versions
    assert client.get(f"{INDUCTION}/versions", headers=manager_headers).status_code == 200
    # and back in use, the learner carries on where they were
    client.post("/v1/competencies/site-induction/reactivate", headers=manager_headers)
    assert client.get(INDUCTION, headers=learner_headers).json()["resume_at"] == 2
