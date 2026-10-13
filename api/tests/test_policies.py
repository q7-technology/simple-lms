"""Policies: versions published by a manager, read and signed by each
person with their typed name and a finger signature. A new version needs a
new signature."""
import pytest

import yard
from conftest import bearer, login, make_person, pin_login
from files import JPEG, PNG, sent

WHS = "/v1/policies/whs-policy"


@pytest.fixture
def kim(client, manager_headers, learner):
    """Kim is a picker, and pickers are asked to sign the WHS policy."""
    yard.build(client, manager_headers)
    r = client.put("/v1/roles/picker/requirements", headers=manager_headers,
                   json={"competencies": ["site-induction", "whs-policy"]})
    assert r.status_code == 200
    yard.give_roles(client, manager_headers, "LL042", "picker")
    return learner


def publish(client, headers, body="Wear your PPE on the floor.", note=None):
    r = client.post(f"{WHS}/versions", headers=headers, json={"body": body, "note": note})
    assert r.status_code == 201, r.text
    return r.json()


def sign(client, headers, version=1, name="Kim Lee", signature=None):
    signature = signature or sent(client, headers, "signature", PNG, "image/png")
    return client.post(f"{WHS}/sign", headers=headers,
                       json={"version": version, "signed_name": name, "signature": signature})


def whs_status(client, headers, code="LL042"):
    items = client.get(f"/v1/people/{code}/training", headers=headers).json()["items"]
    return next(i["status"] for i in items if i["key"] == "whs-policy")


def test_versions_are_numbered_and_newest_first(client, manager_headers, kim):
    one = publish(client, manager_headers)
    two = publish(client, manager_headers, "Wear your PPE, and hi-vis in the yard.",
                  note="hi-vis in the yard")
    assert (one["version"], two["version"]) == (1, 2)
    assert two["published_by"] == {"code": "MG001", "name": "Mel Grant"}
    r = client.get(f"{WHS}/versions", headers=manager_headers).json()
    assert [v["version"] for v in r] == [2, 1] and r[0]["note"] == "hi-vis in the yard"


def test_only_a_policy_has_versions(client, manager_headers, kim):
    r = client.post("/v1/policies/site-induction/versions", headers=manager_headers,
                    json={"body": "x"})
    assert r.status_code == 404
    r = client.post(f"{WHS}/versions", headers=manager_headers, json={"body": "  "})
    assert r.status_code == 422


def test_a_learner_or_supervisor_cannot_publish(client, learner_headers, supervisor_headers, kim):
    for headers in (learner_headers, supervisor_headers):
        assert client.post(f"{WHS}/versions", headers=headers,
                           json={"body": "x"}).status_code == 403


def test_the_learner_reads_the_version_to_sign(client, manager_headers, learner_headers, kim):
    r = client.get(WHS, headers=learner_headers)
    assert r.status_code == 404 and r.json()["detail"] == "WHS policy has no version to sign yet"
    publish(client, manager_headers)
    out = client.get(WHS, headers=learner_headers).json()
    assert (out["key"], out["name"]) == ("whs-policy", "WHS policy")
    assert out["version"]["version"] == 1 and out["version"]["body"] == "Wear your PPE on the floor."


def test_signing_makes_it_current(client, manager_headers, learner_headers, kim):
    publish(client, manager_headers)
    assert whs_status(client, learner_headers) == "missing"
    r = sign(client, learner_headers)
    assert r.status_code == 201, r.text
    out = r.json()
    assert (out["kind"], out["granted_on"], out["policy_version"]) == ("granted", "2026-10-12", 1)
    assert out["signed_name"] == "Kim Lee" and out["signature"]
    assert out["recorded_by"] == {"code": "LL042", "name": "Kim Lee"}
    assert whs_status(client, learner_headers) == "current"


def test_a_new_version_needs_a_new_signature(client, manager_headers, learner_headers, kim):
    publish(client, manager_headers)
    sign(client, learner_headers)
    publish(client, manager_headers, "Wear your PPE, and hi-vis in the yard.")
    assert whs_status(client, learner_headers) == "missing"
    # read version 1, but version 2 came out meanwhile
    r = sign(client, learner_headers, version=1)
    assert r.status_code == 409 and r.json()["code"] == "new_version"
    assert sign(client, learner_headers, version=2).status_code == 201
    assert whs_status(client, learner_headers) == "current"


def test_once_for_each_version(client, manager_headers, learner_headers, kim):
    publish(client, manager_headers)
    sign(client, learner_headers)
    r = sign(client, learner_headers)
    assert r.status_code == 409 and r.json()["code"] == "already_signed"


def test_the_typed_name_is_theirs(client, manager_headers, learner_headers, kim):
    publish(client, manager_headers)
    r = sign(client, learner_headers, name="Sam Vu")
    assert r.status_code == 422 and r.json()["errors"] == [
        {"field": "signed_name", "message": "type your name as it is on your record: Kim Lee"}]
    assert sign(client, learner_headers, name="  kim   LEE ").status_code == 201


def test_the_signature_is_their_own_and_a_signature(client, db, manager_headers, learner_headers,
                                                    kim):
    publish(client, manager_headers)
    photo = sent(client, learner_headers, "ticket", JPEG)
    r = sign(client, learner_headers, signature=photo)
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "signature"
    make_person(db, "LL099", "Pat Other", pin="1357")
    pat = bearer(pin_login(client, "LL099", "1357")["token"])
    pats = sent(client, pat, "signature", PNG, "image/png")
    assert sign(client, learner_headers, signature=pats).status_code == 422


def test_a_supervisor_signs_their_own_on_a_pin(client, manager_headers, supervisor, kim):
    publish(client, manager_headers)
    sam = bearer(pin_login(client, supervisor.code)["token"])
    assert sign(client, sam, name="Sam Vu").status_code == 201


def test_signed_on_paper_and_recorded_by_hand_counts_for_the_version_now(
        client, manager_headers, learner_headers, kim):
    publish(client, manager_headers)
    out = yard.grant(client, manager_headers, "LL042", "whs-policy", "2026-10-01",
                     note="signed on paper at the toolbox meeting")
    assert out["policy_version"] == 1 and out["signature"] is None
    assert whs_status(client, learner_headers) == "current"
    publish(client, manager_headers, "Version two.")
    assert whs_status(client, learner_headers) == "missing"


def test_a_deactivated_policy_is_not_signed(client, manager_headers, learner_headers, kim):
    publish(client, manager_headers)
    client.post("/v1/competencies/whs-policy/deactivate", headers=manager_headers)
    r = sign(client, learner_headers)
    assert r.status_code == 409 and r.json()["code"] == "inactive"


def test_a_deactivated_policy_gets_no_new_version(client, manager_headers, kim):
    publish(client, manager_headers)
    client.post("/v1/competencies/whs-policy/deactivate", headers=manager_headers)
    r = client.post(f"{WHS}/versions", headers=manager_headers, json={"body": "Version two."})
    assert r.status_code == 409 and r.json()["code"] == "inactive"
    versions = client.get(f"{WHS}/versions", headers=manager_headers).json()
    assert [v["version"] for v in versions] == [1]


def test_the_matrix_shows_who_has_signed(client, manager_headers, learner_headers, kim, db):
    make_person(db, "LL043", "Ash Patel")
    yard.give_roles(client, manager_headers, "LL043", "picker")
    publish(client, manager_headers)
    sign(client, learner_headers)
    m = client.get("/v1/matrix", headers=manager_headers).json()
    cells = {p["code"]: p["cells"]["whs-policy"]["status"] for p in m["people"]
             if "whs-policy" in p["cells"] and p["code"].startswith("LL")}
    assert cells == {"LL042": "current", "LL043": "missing"}


def test_a_manager_signs_their_own_too(client, db, manager, manager_headers, admin_headers, kim):
    publish(client, admin_headers)
    mel = bearer(login(client, manager.email)["token"])
    assert sign(client, mel, name="Mel Grant").status_code == 201


def test_a_signature_signs_once(client, manager_headers, learner_headers, kim):
    """A drawn signature already on a record can't be put on another."""
    publish(client, manager_headers)
    used = sent(client, learner_headers, "signature", PNG, "image/png")
    assert sign(client, learner_headers, signature=used).status_code == 201
    publish(client, manager_headers, "Version two.")
    r = sign(client, learner_headers, version=2, signature=used)
    assert r.status_code == 422 and r.json()["errors"][0] == {
        "field": "signature", "message": "this signature is already on a record: sign again"}
    assert sign(client, learner_headers, version=2).status_code == 201


def test_nobody_signs_for_someone_else(client, manager_headers, kim):
    """Signing is always the caller's own: there is no one else to name."""
    publish(client, manager_headers)
    sig = sent(client, manager_headers, "signature", PNG, "image/png")
    r = client.post(f"{WHS}/sign", headers=manager_headers,
                    json={"version": 1, "signed_name": "Kim Lee", "signature": sig,
                          "person": "LL042"})
    assert r.status_code == 422
    r = client.post(f"{WHS}/sign", headers=manager_headers,
                    json={"version": 1, "signed_name": "Kim Lee", "signature": sig})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "signed_name"
