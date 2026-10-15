"""Signing off a practical on the phone: a supervisor, for their own team
(a manager or admin, for anyone), never for themselves (rule 3), ticks every
item and signs; the learner confirms with their signature and their PIN.
The grant is recorded by the supervisor, and the refresher does the rest."""
from datetime import date

import pytest

import yard
from checklist import FORKLIFT, ITEMS, practical, published
from conftest import PIN, all_at_once, bearer, fresh_client, make_person, pin_login
from files import JPEG, PNG, sent

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


def signed(client, headers, purpose="signature"):
    """A finger signature (or a photo) sent from the phone."""
    if purpose == "signoff-photo":
        return sent(client, headers, purpose, JPEG)
    return sent(client, headers, purpose, PNG, "image/png")


def body(client, headers, version=1, ticked=None, pin=PIN, **more) -> dict:
    """Every item on the newest checklist ticked, both signatures, the learner's PIN."""
    if ticked is None:
        ticked = [i["id"] for i in client.get(FORKLIFT, headers=headers).json()["version"]["items"]]
    return {"competency": "forklift-practical", "version": version, "ticked": ticked,
            "supervisor_signature": signed(client, headers),
            "learner_signature": signed(client, headers), "learner_pin": pin, **more}


def sign_off(client, headers, code="LL042", **more):
    return client.post(f"/v1/people/{code}/signoffs", headers=headers,
                       json=body(client, headers, **more))


@pytest.fixture
def checklist(client, manager_headers, team):
    return published(client, manager_headers)


def forklift(client, headers, code="LL042"):
    items = client.get(f"/v1/people/{code}/training", headers=headers).json()["items"]
    return next(i for i in items if i["key"] == "forklift-practical")


def test_signed_off_it_is_current_until_the_refresher(client, sam, learner_headers,
                                                       manager_headers, checklist):
    r = sign_off(client, sam, note="Smooth on the ramp", photo=signed(client, sam, "signoff-photo"))
    assert r.status_code == 201, r.text
    out = r.json()
    assert (out["kind"], out["granted_on"], out["expires_on"]) == ("granted", "2026-10-12", None)
    assert out["recorded_by"] == {"code": "SV001", "name": "Sam Vu"}
    s = out["signoff"]
    assert (s["version"], s["ticked"], s["note"]) == (1, ITEMS, "Smooth on the ramp")
    assert s["photo"] and s["supervisor_signature"] != s["learner_signature"]
    item = forklift(client, learner_headers)
    assert (item["status"], item["expires_on"]) == ("current", "2027-10-12")
    m = client.get("/v1/matrix", headers=manager_headers).json()
    assert next(p for p in m["people"] if p["code"] == "LL042")["cells"]["forklift-practical"][
        "status"] == "current"
    # Kim sees it in her history, photo and signatures too
    record = client.get("/v1/people/LL042/records", headers=learner_headers).json()[0]
    assert record["signoff"] == s
    for upload in (s["photo"], s["supervisor_signature"], s["learner_signature"]):
        assert client.get(f"/v1/uploads/{upload}", headers=learner_headers).status_code == 200


def test_the_refresher_brings_it_round_again(client, sam, learner_headers, checklist, today):
    sign_off(client, sam)
    today.set(date(2027, 9, 20))
    assert forklift(client, learner_headers)["status"] == "expiring"
    today.set(date(2027, 10, 13))
    assert forklift(client, learner_headers)["status"] == "lapsed"
    assert sign_off(client, sam).status_code == 201
    assert forklift(client, learner_headers)["expires_on"] == "2028-10-13"


def test_nobody_signs_off_their_own(client, manager_headers, checklist):
    r = sign_off(client, manager_headers, "MG001")
    assert r.status_code == 403 and r.json() == {
        "detail": "nobody signs off their own practical: ask your supervisor",
        "code": "own_signoff"}


def test_a_supervisor_signs_off_their_own_team_only(client, sam, manager_headers, checklist):
    r = sign_off(client, sam, "LL099", pin="1357")
    assert r.status_code == 404 and r.json()["detail"] == "no person LL099"
    assert sign_off(client, manager_headers, "LL099", pin="1357").status_code == 201


def test_every_item_is_ticked(client, sam, manager_headers, checklist):
    ids = [i["id"] for i in checklist["items"]]
    for ticked in (ids[:2], [*ids, ids[0]], [*ids[:2], 999_999]):
        r = sign_off(client, sam, ticked=ticked)
        assert r.status_code == 422 and r.json()["errors"] == [
            {"field": "ticked", "message": "tick all 3 items on the checklist"}]
    assert sign_off(client, sam, ticked=list(reversed(ids))).status_code == 201


def test_the_checklist_changed_meanwhile(client, sam, manager_headers, checklist):
    ids = [i["id"] for i in checklist["items"]]
    published(client, manager_headers, ITEMS[:2])
    r = sign_off(client, sam, ticked=ids)
    assert r.status_code == 409 and r.json() == {
        "detail": "version 2 is the checklist now: tick it again", "code": "new_version"}


def test_the_learner_confirms_with_their_own_pin(client, db, sam, learner, learner_headers,
                                                 checklist):
    # not a PIN at all: refused before it is checked, so it costs no try
    r = sign_off(client, sam, pin="12ab")
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "learner_pin"
    r = sign_off(client, sam, pin="1357")
    assert r.status_code == 422 and r.json()["errors"] == [
        {"field": "learner_pin", "message": "that isn't Kim Lee's PIN: try again"}]
    assert forklift(client, learner_headers)["status"] == "missing"
    db.refresh(learner)
    assert learner.pin_failed_attempts == 1
    assert sign_off(client, sam).status_code == 201
    db.refresh(learner)
    assert learner.pin_failed_attempts == 0


def test_five_wrong_pins_lock_it_as_signing_in_would(client, db, sam, learner, checklist):
    for _ in range(4):
        assert sign_off(client, sam, pin="0000").status_code == 422
    r = sign_off(client, sam, pin="0000")
    assert r.json()["errors"][0]["message"] == (
        "wrong PIN 5 times: Kim Lee's PIN is locked until a manager resets it")
    r = sign_off(client, sam)
    assert r.json()["errors"][0]["message"] == (
        "Kim Lee's PIN is locked after too many wrong tries: a manager resets it")
    r = client.post("/v1/auth/pin-login", json={"code": "LL042", "pin": PIN})
    assert r.status_code == 401 and r.json()["code"] == "locked"


def test_wrong_pins_sent_all_at_once_still_lock_after_five(client, db, sam, learner, checklist):
    bodies = [body(client, sam, pin="0000") for _ in range(8)]

    def guess():
        r = fresh_client().post("/v1/people/LL042/signoffs", headers=sam, json=bodies.pop())
        return r.json()["errors"][0]["message"]

    messages = all_at_once(8, guess)
    assert messages.count("that isn't Kim Lee's PIN: try again") == 4
    db.refresh(learner)
    assert learner.pin_locked is True


def test_a_learner_with_no_pin_cant_confirm(client, db, sam, learner, checklist):
    learner.pin_hash = None
    db.commit()
    r = sign_off(client, sam)
    assert r.status_code == 422 and r.json()["errors"] == [{
        "field": "learner_pin",
        "message": "Kim Lee has no PIN yet: a manager sets one on People, then sign off again"}]


def test_the_signatures_and_photo_are_the_supervisors_own_and_used_once(
        client, sam, learner_headers, checklist):
    ink = signed(client, sam)
    r = sign_off(client, sam, supervisor_signature=ink, learner_signature=ink)
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "learner_signature"
    kims = signed(client, learner_headers)
    r = sign_off(client, sam, supervisor_signature=kims)
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "supervisor_signature"
    r = sign_off(client, sam, photo=signed(client, sam))
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "photo"
    photo = signed(client, sam, "signoff-photo")
    first = sign_off(client, sam, photo=photo).json()["signoff"]
    for more in ({"photo": photo}, {"supervisor_signature": first["supervisor_signature"]},
                 {"learner_signature": first["learner_signature"]},
                 {"learner_signature": first["supervisor_signature"]}):
        r = sign_off(client, sam, **more)
        assert r.status_code == 422, more
        assert "already on" in r.json()["errors"][0]["message"]


def test_only_a_practical_with_a_checklist_is_signed_off(client, sam, manager_headers, team):
    r = sign_off(client, sam, ticked=[], competency="nothing")
    assert r.status_code == 404 and r.json()["detail"] == "no competency nothing"
    r = sign_off(client, sam, ticked=[])
    assert r.status_code == 404 and r.json()["detail"] == "Forklift practical has no checklist yet"
    client.post("/v1/competencies", headers=manager_headers,
                json={"key": "whs-policy", "name": "WHS policy", "kind": "policy"})
    r = sign_off(client, sam, ticked=[], competency="whs-policy")
    assert r.status_code == 422 and r.json()["errors"] == [
        {"field": "competency", "message": "whs-policy is not a practical"}]


def test_not_for_a_deactivated_practical_or_person(client, db, sam, manager_headers, learner,
                                                   checklist):
    client.post("/v1/competencies/forklift-practical/deactivate", headers=manager_headers)
    r = sign_off(client, sam)
    assert r.status_code == 409 and r.json()["code"] == "inactive"
    client.post("/v1/competencies/forklift-practical/reactivate", headers=manager_headers)
    learner.active = False
    db.commit()
    r = sign_off(client, sam)
    assert r.status_code == 409 and r.json()["detail"] == "LL042 is deactivated"


def test_a_signoff_put_right_by_a_revoke(client, sam, manager_headers, learner_headers,
                                         checklist):
    sign_off(client, sam)
    r = client.post("/v1/people/LL042/records/revoke", headers=manager_headers,
                    json={"competency": "forklift-practical", "note": "Signed off the wrong Kim"})
    assert r.status_code == 201
    assert forklift(client, learner_headers)["status"] == "missing"
