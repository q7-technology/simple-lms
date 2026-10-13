"""Tickets: sent in by the person with photos, a number and the card's
expiry; checked by a manager who is not them, and approved (a grant good
until the card's date) or sent back with a reason."""
import pytest

import yard
from conftest import all_at_once, bearer, fresh_client, login, make_person
from files import JPEG, PDF, PNG, sent


@pytest.fixture
def kim(client, manager_headers, learner):
    """Kim is a forklift operator: a site induction and a forklift licence."""
    yard.build(client, manager_headers)
    yard.give_roles(client, manager_headers, "LL042", "forklift-operator")
    return learner


def send_in(client, headers, competency="forklift-licence", number="LF0012345",
            expires_on="2031-03-01", back=True, **more):
    body = {"competency": competency, "number": number, "expires_on": expires_on,
            "front": sent(client, headers), **more}
    if back:
        body["back"] = sent(client, headers, data=PNG, content_type="image/png")
    return client.post("/v1/tickets", headers=headers, json=body)


def forklift(client, headers, code="LL042"):
    items = client.get(f"/v1/people/{code}/training", headers=headers).json()["items"]
    return next(i for i in items if i["key"] == "forklift-licence")


def test_a_learner_sends_in_a_ticket_and_it_waits(client, manager_headers, learner_headers, kim):
    r = send_in(client, learner_headers)
    assert r.status_code == 201, r.text
    out = r.json()
    assert (out["status"], out["number"], out["expires_on"]) == ("pending", "LF0012345",
                                                                 "2031-03-01")
    assert out["person"] == {"code": "LL042", "name": "Kim Lee"} and out["back"]
    item = forklift(client, learner_headers)
    assert (item["status"], item["waiting"], item["card_expires"]) == ("missing", True, True)


def test_one_waiting_at_a_time(client, learner_headers, kim):
    send_in(client, learner_headers)
    r = send_in(client, learner_headers)
    assert r.status_code == 409 and r.json()["code"] == "already_waiting"


def test_the_back_is_optional_and_a_pdf_will_do(client, learner_headers, kim):
    front = sent(client, learner_headers, data=PDF, content_type="application/pdf")
    r = client.post("/v1/tickets", headers=learner_headers,
                    json={"competency": "forklift-licence", "number": "LF1", "front": front,
                          "expires_on": "2031-03-01"})
    assert r.status_code == 201 and r.json()["back"] is None


def test_the_card_date_is_asked_for_when_the_card_has_one(client, manager_headers,
                                                          learner_headers, kim):
    def field(r):
        assert r.status_code == 422, r.text
        return r.json()["errors"][0]

    assert field(send_in(client, learner_headers, expires_on=None)) == {
        "field": "expires_on", "message": "this card has an expiry date: type it in"}
    # the last good day must still be ahead
    assert field(send_in(client, learner_headers, expires_on="2026-10-12"))["message"] == \
        "this card has run out: send the new one"
    client.post("/v1/competencies", headers=manager_headers,
                json={"key": "white-card", "name": "White card", "kind": "ticket",
                      "card_expires": False})
    client.post("/v1/people/LL042/overrides", headers=manager_headers,
                json={"competency": "white-card", "kind": "extra", "note": "on the building site"})
    assert field(send_in(client, learner_headers, "white-card"))["field"] == "expires_on"
    assert send_in(client, learner_headers, "white-card", expires_on=None).status_code == 201


def test_only_a_ticket_and_only_your_own_photos(client, db, learner_headers, kim):
    r = send_in(client, learner_headers, competency="site-induction")
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "competency"
    make_person(db, "LL099", "Pat Other", email="pat@example.com.au", password="correct horse battery")
    pat = bearer(login(client, "pat@example.com.au")["token"])
    r = client.post("/v1/tickets", headers=learner_headers,
                    json={"competency": "forklift-licence", "number": "LF1",
                          "expires_on": "2031-03-01", "front": sent(client, pat)})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "front"
    signature = sent(client, learner_headers, "signature", PNG, "image/png")
    r = client.post("/v1/tickets", headers=learner_headers,
                    json={"competency": "forklift-licence", "number": "LF1",
                          "expires_on": "2031-03-01", "front": signature})
    assert r.status_code == 422


def test_the_inbox_is_for_managers_oldest_first(client, db, manager_headers, learner_headers,
                                                supervisor_headers, kim):
    send_in(client, learner_headers)
    send_in(client, learner_headers, competency="first-aid", number="FA 778",
            expires_on="2029-05-01")
    r = client.get("/v1/tickets", headers=manager_headers)
    assert [t["competency"]["key"] for t in r.json()] == ["forklift-licence", "first-aid"]
    for headers in (learner_headers, supervisor_headers):
        assert client.get("/v1/tickets", headers=headers).status_code == 403


def test_a_manager_approves_and_it_is_current_until_the_card_date(
        client, manager_headers, learner_headers, kim):
    ticket = send_in(client, learner_headers).json()
    r = client.post(f"/v1/tickets/{ticket['id']}/approve", headers=manager_headers)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["status"] == "approved" and out["decided_by"] == {"code": "MG001", "name": "Mel Grant"}
    item = forklift(client, learner_headers)
    assert (item["status"], item["granted_on"], item["expires_on"], item["waiting"]) == (
        "current", "2026-10-12", "2031-03-01", False)
    record = client.get("/v1/people/LL042/records", headers=manager_headers).json()[0]
    assert record["ticket"] == ticket["id"] and record["note"] == "Ticket LF0012345, checked"
    assert record["recorded_by"]["code"] == "MG001"
    assert client.get("/v1/tickets", headers=manager_headers).json() == []


def test_a_ticket_is_decided_once(client, manager_headers, learner_headers, kim):
    ticket = send_in(client, learner_headers).json()
    client.post(f"/v1/tickets/{ticket['id']}/approve", headers=manager_headers)
    for path in ("approve", "reject"):
        r = client.post(f"/v1/tickets/{ticket['id']}/{path}", headers=manager_headers,
                        json={"reason": "x"})
        assert r.status_code == 409 and r.json()["code"] == "decided"


def test_nobody_verifies_their_own(client, manager, manager_headers, admin_headers, kim):
    client.post("/v1/people/MG001/overrides", headers=admin_headers,
                json={"competency": "forklift-licence", "kind": "extra", "note": "drives too"})
    ticket = send_in(client, manager_headers).json()
    for path in ("approve", "reject"):
        r = client.post(f"/v1/tickets/{ticket['id']}/{path}", headers=manager_headers,
                        json={"reason": "x"})
        assert r.status_code == 403 and r.json()["code"] == "own_ticket"
    assert client.post(f"/v1/tickets/{ticket['id']}/approve",
                       headers=admin_headers).status_code == 200


def test_sent_back_with_a_reason_they_see(client, manager_headers, learner_headers, kim):
    ticket = send_in(client, learner_headers).json()
    r = client.post(f"/v1/tickets/{ticket['id']}/reject", headers=manager_headers,
                    json={"reason": " "})
    assert r.status_code == 422
    r = client.post(f"/v1/tickets/{ticket['id']}/reject", headers=manager_headers,
                    json={"reason": "The photo is blurry: take it again in good light."})
    assert r.json()["status"] == "rejected"
    mine = client.get("/v1/people/LL042/tickets", headers=learner_headers).json()
    assert mine[0]["reason"] == "The photo is blurry: take it again in good light."
    assert forklift(client, learner_headers)["waiting"] is False
    # and they can send it again
    assert send_in(client, learner_headers).status_code == 201


def test_a_card_that_ran_out_while_it_waited_is_not_approved(client, manager_headers,
                                                             learner_headers, kim, today):
    ticket = send_in(client, learner_headers, expires_on="2026-10-20").json()
    today.set(today.value.replace(day=20))
    r = client.post(f"/v1/tickets/{ticket['id']}/approve", headers=manager_headers)
    assert r.status_code == 409 and r.json()["code"] == "card_ran_out"


def test_a_ticket_for_a_competency_deactivated_while_it_waited_is_not_approved(
        client, manager_headers, learner_headers, kim):
    ticket = send_in(client, learner_headers).json()
    client.post("/v1/competencies/forklift-licence/deactivate", headers=manager_headers)
    r = client.post(f"/v1/tickets/{ticket['id']}/approve", headers=manager_headers)
    assert r.status_code == 409 and r.json()["code"] == "inactive"
    assert client.post(f"/v1/tickets/{ticket['id']}/reject", headers=manager_headers,
                       json={"reason": "Forklift licences aren't asked for any more"}).status_code == 200


def test_the_photos_are_shown_to_the_manager(client, manager_headers, learner_headers, kim):
    ticket = send_in(client, learner_headers).json()
    r = client.get(f"/v1/uploads/{ticket['front']}", headers=manager_headers)
    assert r.status_code == 200 and r.content == JPEG


def test_whose_tickets_who_may_read(client, db, learner_headers, supervisor_headers, kim):
    make_person(db, "LL099", "Pat Other")
    assert client.get("/v1/people/LL042/tickets", headers=supervisor_headers).status_code == 200
    assert client.get("/v1/people/LL099/tickets", headers=learner_headers).status_code == 404


def test_two_managers_at_once_approve_it_once(client, db, manager_headers, admin_headers,
                                              learner_headers, kim):
    from lms.models import CompetencyRecord

    ticket = send_in(client, learner_headers).json()
    managers = [manager_headers, admin_headers]

    def approve():
        headers = managers.pop()
        return fresh_client().post(f"/v1/tickets/{ticket['id']}/approve",
                                   headers=headers).status_code

    assert sorted(all_at_once(2, approve)) == [200, 409]
    assert db.query(CompetencyRecord).count() == 1


def test_a_photo_goes_on_one_ticket_only(client, manager_headers, learner_headers, kim):
    """One upload, one ticket: a photo already checked (or sent back) can't
    be put on another ticket, and the front is not the back."""
    front = sent(client, learner_headers)
    body = {"competency": "forklift-licence", "number": "LF1", "expires_on": "2031-03-01",
            "front": front}
    r = client.post("/v1/tickets", headers=learner_headers, json={**body, "back": front})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "back"
    ticket = client.post("/v1/tickets", headers=learner_headers, json=body).json()
    client.post(f"/v1/tickets/{ticket['id']}/reject", headers=manager_headers,
                json={"reason": "Blurry."})
    # the same photo again, on the same ticket or another
    r = client.post("/v1/tickets", headers=learner_headers, json=body)
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "front"
    r = client.post("/v1/tickets", headers=learner_headers,
                    json={**body, "competency": "first-aid", "expires_on": "2029-05-01"})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "front"
    r = client.post("/v1/tickets", headers=learner_headers,
                    json={**body, "front": sent(client, learner_headers), "back": front})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "back"
