"""The quiz: marked on the server, every attempt kept, a pass a grant of
the learner's own (the one thing anybody earns alone), and the refresher
saying when it runs out. Try again after a fail."""
from datetime import date

import pytest

import yard
from conftest import bearer, make_person, pin_login
from course import INDUCTION, QUESTIONS, RIGHT, published

ATTEMPTS = f"{INDUCTION}/attempts"


@pytest.fixture
def kim(client, manager_headers, learner):
    """Kim is a picker: pickers do the site induction, refreshed every 24 months."""
    yard.build(client, manager_headers)
    yard.give_roles(client, manager_headers, "LL042", "picker")
    return learner


def take(client, headers, answers=RIGHT, version=1):
    return client.post(ATTEMPTS, headers=headers, json={"version": version, "answers": answers})


def induction(client, headers, code="LL042"):
    items = client.get(f"/v1/people/{code}/training", headers=headers).json()["items"]
    return next(i for i in items if i["key"] == "site-induction")


def test_a_pass_makes_it_current_until_the_refresher(client, manager_headers, learner_headers,
                                                      kim):
    published(client, manager_headers)
    r = take(client, learner_headers)
    assert r.status_code == 201, r.text
    out = r.json()
    assert (out["score"], out["correct"], out["total"], out["pass_mark"], out["passed"]) == (
        100, 2, 2, 80, True)
    item = induction(client, learner_headers)
    assert (item["status"], item["granted_on"], item["expires_on"]) == (
        "current", "2026-10-12", "2028-10-12")
    m = client.get("/v1/matrix", headers=manager_headers).json()
    assert next(p for p in m["people"] if p["code"] == "LL042")["cells"]["site-induction"][
        "status"] == "current"


def test_a_pass_is_recorded_as_the_learners_own(client, manager_headers, learner_headers, kim):
    published(client, manager_headers)
    take(client, learner_headers)
    record = client.get("/v1/people/LL042/records", headers=learner_headers).json()[0]
    assert record["recorded_by"] == {"code": "LL042", "name": "Kim Lee"}
    assert record["quiz"] == {"version": 1, "score": 100, "pass_mark": 80}
    assert record["expires_on"] is None  # worked out from the refresher, never stored


def test_a_fail_is_kept_and_grants_nothing(client, manager_headers, learner_headers, kim):
    published(client, manager_headers)
    out = take(client, learner_headers, answers=[0, 2]).json()
    assert (out["score"], out["passed"]) == (50, False)
    assert induction(client, learner_headers)["status"] == "missing"
    assert client.get("/v1/people/LL042/records", headers=learner_headers).json() == []


def test_try_again_after_a_fail_and_every_attempt_is_kept(client, manager_headers,
                                                          learner_headers, kim):
    published(client, manager_headers)
    take(client, learner_headers, answers=[1, 0])
    take(client, learner_headers, answers=[0, 2])
    assert take(client, learner_headers).json()["passed"] is True
    attempts = client.get("/v1/people/LL042/attempts", headers=learner_headers).json()
    assert [(a["score"], a["passed"]) for a in attempts] == [(100, True), (50, False), (0, False)]
    assert attempts[0]["competency"] == {"key": "site-induction", "name": "Site induction",
                                         "kind": "module"}
    for key, n in (("site-induction", 3), ("first-aid", 0)):
        r = client.get("/v1/people/LL042/attempts", headers=learner_headers,
                       params={"competency": key})
        assert len(r.json()) == n
    assert induction(client, learner_headers)["status"] == "current"


@pytest.mark.parametrize("pass_mark, passed", [(67, False), (66, True)])
def test_the_score_is_rounded_down_and_the_pass_mark_is_the_least_that_passes(
        client, manager_headers, learner_headers, kim, pass_mark, passed):
    three = [*QUESTIONS, {"prompt": "Who signs you in?", "options": ["Security", "Nobody"],
                          "correct": 0}]
    published(client, manager_headers, questions=three, pass_mark=pass_mark)
    out = take(client, learner_headers, answers=[0, 1, 1]).json()
    assert (out["score"], out["passed"]) == (66, passed)


@pytest.mark.parametrize("answers, field, message", [
    ([0], "answers", "answer all 2 questions"),
    ([0, 1, 0], "answers", "answer all 2 questions"),
    ([0, 3], "answers.1", "choose one of the answers"),
    ([-1, 1], "answers.0", "choose one of the answers"),
])
def test_every_question_gets_one_of_its_answers(client, manager_headers, learner_headers, kim,
                                                answers, field, message):
    published(client, manager_headers)
    r = take(client, learner_headers, answers=answers)
    assert r.status_code == 422 and r.json()["errors"] == [{"field": field, "message": message}]
    assert client.get("/v1/people/LL042/attempts", headers=learner_headers).json() == []


def test_the_quiz_is_the_version_they_read(client, manager_headers, learner_headers, kim):
    published(client, manager_headers)
    published(client, manager_headers)
    r = take(client, learner_headers, version=1)
    assert r.status_code == 409 and r.json()["code"] == "new_version"
    assert take(client, learner_headers, version=2).json()["version"] == 2


def test_a_pass_starts_the_module_from_the_top_next_time(client, manager_headers,
                                                         learner_headers, kim):
    published(client, manager_headers)
    client.put(f"{INDUCTION}/progress", headers=learner_headers, json={"version": 1, "page": 5})
    take(client, learner_headers, answers=[1, 1])
    assert client.get(INDUCTION, headers=learner_headers).json()["resume_at"] == 5
    take(client, learner_headers)
    assert client.get(INDUCTION, headers=learner_headers).json()["resume_at"] == 0


def test_the_refresher_runs_it_out_and_taking_it_again_renews_it(client, manager_headers,
                                                                 learner_headers, kim, today):
    published(client, manager_headers)
    take(client, learner_headers)
    today.set(date(2028, 9, 20))
    assert induction(client, learner_headers)["status"] == "expiring"
    today.set(date(2028, 10, 13))
    assert induction(client, learner_headers)["status"] == "lapsed"
    take(client, learner_headers)
    item = induction(client, learner_headers)
    assert (item["status"], item["expires_on"]) == ("current", "2030-10-13")


def test_a_new_version_asks_nobody_to_take_it_again(client, manager_headers, learner_headers,
                                                    kim):
    published(client, manager_headers)
    take(client, learner_headers)
    published(client, manager_headers)
    assert induction(client, learner_headers)["status"] == "current"


def test_nobody_takes_it_for_someone_else(client, manager_headers, kim):
    published(client, manager_headers)
    r = client.post(ATTEMPTS, headers=manager_headers,
                    json={"version": 1, "answers": RIGHT, "person": "LL042"})
    assert r.status_code == 422


def test_attempts_are_seen_by_who_may_see_the_person(client, db, manager_headers,
                                                     learner_headers, supervisor_headers, kim):
    published(client, manager_headers)
    take(client, learner_headers, answers=[1, 1])
    seen = client.get("/v1/people/LL042/attempts", headers=supervisor_headers).json()
    assert [(a["score"], a["passed"]) for a in seen] == [(50, False)]
    make_person(db, "LL099", "Pat Other", pin="1357")
    pat = bearer(pin_login(client, "LL099", "1357")["token"])
    assert client.get("/v1/people/LL042/attempts", headers=pat).status_code == 404


def test_a_deactivated_module_is_not_taken(client, manager_headers, learner_headers, kim):
    published(client, manager_headers)
    client.post("/v1/competencies/site-induction/deactivate", headers=manager_headers)
    r = take(client, learner_headers)
    assert r.status_code == 409 and r.json()["code"] == "inactive"
