"""competency.granted and competency.revoked: fired by every way a grant
or a revoke is made, in the same transaction, with the status it leaves."""
import pytest

import yard
from conftest import make_person
from course import INDUCTION, RIGHT, published
from files import PNG, sent
from lms.models import Outbox, Webhook

KIM = {"code": "LL042", "name": "Kim Lee"}
MEL = {"code": "MG001", "name": "Mel Grant"}


@pytest.fixture
def kim(client, db, manager_headers, learner):
    """Kim is a forklift operator; a webhook hears every grant and revoke."""
    db.add(Webhook(name="Simple TMS", url="https://tms.example.com.au/in", secret="whsec_x",
                   events=["competency.granted", "competency.revoked"]))
    db.commit()
    yard.build(client, manager_headers)
    yard.give_roles(client, manager_headers, "LL042", "forklift-operator")
    return learner


def fired(db, event_type=None) -> list[dict]:
    db.expire_all()
    rows = db.query(Outbox).filter_by(kind="webhook").order_by(Outbox.id).all()
    return [r.payload for r in rows if event_type is None or r.payload["event_type"] == event_type]


def test_a_grant_by_hand(client, db, manager_headers, kim):
    record = yard.grant(client, manager_headers, "LL042", "forklift-licence", "2026-03-01",
                        expires_on="2031-03-01")
    [event] = fired(db)
    assert event["event_type"] == "competency.granted"
    assert event["data"] == {
        "person": KIM,
        "competency": {"key": "forklift-licence", "name": "Forklift licence", "kind": "ticket"},
        "record_id": record["id"], "granted_on": "2026-03-01", "expires_on": "2031-03-01",
        "status": "current", "recorded_by": MEL}


def test_the_last_good_day_is_worked_out_from_the_refresher(client, db, manager_headers, kim):
    yard.grant(client, manager_headers, "LL042", "site-induction", "2024-11-01")
    [event] = fired(db)
    # 24 months on: good until then, and within 30 days of it
    assert (event["data"]["expires_on"], event["data"]["status"]) == ("2026-11-01", "expiring")


def test_a_grant_not_asked_of_them_says_so(client, db, manager_headers, kim):
    yard.grant(client, manager_headers, "LL042", "first-aid", "2026-10-01")
    assert fired(db)[0]["data"]["status"] == "not_required"


def test_a_revoke(client, db, manager_headers, kim):
    yard.grant(client, manager_headers, "LL042", "forklift-licence", "2026-03-01")
    r = client.post("/v1/people/LL042/records/revoke", headers=manager_headers,
                    json={"competency": "forklift-licence", "note": "ticked for the wrong person"})
    [event] = fired(db, "competency.revoked")
    assert event["data"] == {
        "person": KIM,
        "competency": {"key": "forklift-licence", "name": "Forklift licence", "kind": "ticket"},
        "record_id": r.json()["id"], "note": "ticked for the wrong person", "status": "missing",
        "recorded_by": MEL}


def test_nothing_is_fired_for_what_is_refused(client, db, manager_headers, manager, kim):
    r = client.post("/v1/people/MG001/records", headers=manager_headers,
                    json={"competency": "forklift-licence", "granted_on": "2026-03-01"})
    assert r.status_code == 403
    r = client.post("/v1/people/LL042/records/revoke", headers=manager_headers,
                    json={"competency": "forklift-licence", "note": "nothing there"})
    assert r.status_code == 409
    assert fired(db) == []


def test_a_ticket_checked(client, db, manager_headers, learner_headers, kim):
    body = {"competency": "forklift-licence", "number": "LF0012345", "expires_on": "2031-03-01",
            "front": sent(client, learner_headers)}
    ticket = client.post("/v1/tickets", headers=learner_headers, json=body).json()
    assert fired(db) == []   # sent in, not yet checked
    client.post(f"/v1/tickets/{ticket['id']}/approve", headers=manager_headers)
    [event] = fired(db)
    assert (event["data"]["granted_on"], event["data"]["expires_on"], event["data"]["status"],
            event["data"]["recorded_by"]) == ("2026-10-12", "2031-03-01", "current", MEL)


def test_a_policy_signed(client, db, manager_headers, learner_headers, kim):
    client.put("/v1/roles/forklift-operator/requirements", headers=manager_headers,
               json={"competencies": ["site-induction", "forklift-licence", "whs-policy"]})
    client.post("/v1/policies/whs-policy/versions", headers=manager_headers,
                json={"body": "Wear your PPE."})
    signature = sent(client, learner_headers, "signature", PNG, "image/png")
    r = client.post("/v1/policies/whs-policy/sign", headers=learner_headers,
                    json={"version": 1, "signed_name": "Kim Lee", "signature": signature})
    assert r.status_code == 201, r.text
    [event] = fired(db)
    assert (event["data"]["competency"]["key"], event["data"]["status"],
            event["data"]["expires_on"], event["data"]["recorded_by"]) == (
        "whs-policy", "current", None, KIM)


def test_a_module_passed_and_not_a_fail(client, db, manager_headers, learner_headers, kim):
    published(client, manager_headers)
    client.post(f"{INDUCTION}/attempts", headers=learner_headers,
                json={"version": 1, "answers": [1, 0]})
    assert fired(db) == []
    client.post(f"{INDUCTION}/attempts", headers=learner_headers,
                json={"version": 1, "answers": RIGHT})
    [event] = fired(db)
    assert (event["data"]["competency"]["key"], event["data"]["expires_on"],
            event["data"]["recorded_by"]) == ("site-induction", "2028-10-12", KIM)


def test_each_event_has_its_own_id(client, db, manager_headers, kim):
    make_person(db, "LL043", "Ash Patel")
    yard.grant(client, manager_headers, "LL042", "forklift-licence", "2026-03-01")
    yard.grant(client, manager_headers, "LL043", "forklift-licence", "2026-03-01")
    ids = [e["event_id"] for e in fired(db)]
    assert len(set(ids)) == 2


# TODO(step 4): a practical signed off fires competency.granted too. With
# step 4's helpers, have Sam sign off one of Kim's practicals, then:
#     [event] = fired(db)
#     assert (event["data"]["competency"]["kind"], event["data"]["status"],
#             event["data"]["recorded_by"]) == ("practical", "current",
#                                               {"code": "SV001", "name": "Sam Vu"})
