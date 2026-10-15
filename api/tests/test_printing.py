"""Certificates of completion and skills cards: Simple LMS renders
nothing. It queues a template's name and the JSON it binds to, and the
worker hands the job to Platen."""
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

import yard
from lms import worker
from lms.config import get_settings
from lms.models import Outbox

PLATEN = "https://platen.example.com.au/intake/jobs"


@pytest.fixture
def platen(monkeypatch):
    """Platen is set up, as LMS_PLATEN_URL and LMS_PLATEN_KEY in .env would."""
    monkeypatch.setattr(get_settings(), "platen_url", PLATEN)
    monkeypatch.setattr(get_settings(), "platen_key", "platen-key")


@pytest.fixture
def kim(client, manager_headers, learner):
    """Kim, a forklift operator: her induction current, her licence
    expiring, her first aid (asked of nobody) lapsed."""
    yard.build(client, manager_headers)
    yard.give_roles(client, manager_headers, "LL042", "forklift-operator")
    yard.grant(client, manager_headers, "LL042", "site-induction", "2026-01-01")
    yard.grant(client, manager_headers, "LL042", "first-aid", "2023-01-01")
    return yard.grant(client, manager_headers, "LL042", "forklift-licence", "2025-01-01",
                      expires_on="2026-11-11", note="LF0012345")


def jobs(db) -> list[dict]:
    db.expire_all()
    return [r.payload for r in db.query(Outbox).filter_by(kind="print").order_by(Outbox.id)]


def test_a_certificate_for_the_completion_that_counts(client, db, manager_headers, platen, kim):
    r = client.post(f"/v1/people/LL042/records/{kim['id']}/certificate", headers=manager_headers)
    assert r.status_code == 202, r.text
    [job] = jobs(db)
    assert r.json() == {"job_id": job["job_id"], "template": "lms-certificate",
                        "printer": "office"}
    assert {k: v for k, v in job.items() if k != "job_id"} == {
        "template": "lms-certificate", "version": "v1", "printer": "office", "copies": 1,
        "reference": {"type": "record", "ref": str(kim["id"])},
        "data": {"certificate_no": str(kim["id"]), "person_name": "Kim Lee",
                 "person_code": "LL042", "competency": "Forklift licence",
                 "kind": "Ticket or licence", "completed_on": "1 Jan 2025",
                 "good_until": "11 Nov 2026", "recorded_by": "Mel Grant",
                 "issued_on": "12 Oct 2026"}}


def test_a_refresher_says_when_it_is_good_until_and_none_says_nothing(client, db, manager_headers,
                                                                      platen, kim):
    records = client.get("/v1/people/LL042/records", headers=manager_headers).json()
    induction = next(r for r in records if r["competency"]["key"] == "site-induction")
    client.post(f"/v1/people/LL042/records/{induction['id']}/certificate",
                headers=manager_headers)
    yard.grant(client, manager_headers, "LL042", "whs-policy", "2026-10-01")
    whs = client.get("/v1/people/LL042/records?competency=whs-policy",
                     headers=manager_headers).json()[0]
    client.post(f"/v1/people/LL042/records/{whs['id']}/certificate", headers=manager_headers)
    assert [j["data"]["good_until"] for j in jobs(db)] == ["1 Jan 2028", ""]


def test_only_for_the_completion_that_counts_now(client, db, manager_headers, platen, kim):
    newer = yard.grant(client, manager_headers, "LL042", "forklift-licence", "2026-10-01",
                       expires_on="2031-10-01")
    r = client.post(f"/v1/people/LL042/records/{kim['id']}/certificate", headers=manager_headers)
    assert r.status_code == 409 and r.json()["code"] == "not_current"
    revoke = client.post("/v1/people/LL042/records/revoke", headers=manager_headers,
                         json={"competency": "forklift-licence", "note": "wrong person"}).json()
    for record in (newer, revoke):
        r = client.post(f"/v1/people/LL042/records/{record['id']}/certificate",
                        headers=manager_headers)
        assert r.status_code == 409 and r.json()["code"] == "not_current"
    assert jobs(db) == []


def test_someone_elses_record_is_not_found(client, manager_headers, platen, kim):
    r = client.post(f"/v1/people/SV001/records/{kim['id']}/certificate", headers=manager_headers)
    assert r.status_code == 404


def test_platen_is_set_up_on_the_settings_screen(client, db, admin_headers, manager_headers,
                                                 kim):
    r = client.put("/v1/settings", headers=admin_headers,
                   json={"platen_url": PLATEN, "platen_key": "platen-key",
                         "certificate_printer": "front office"})
    assert r.status_code == 200, r.text
    # the key is never sent back, as the email password isn't
    assert r.json()["platen_key"] == {"set": True, "source": "here"}
    assert r.json()["platen_url"] == {"value": PLATEN, "source": "here"}
    r = client.post(f"/v1/people/LL042/records/{kim['id']}/certificate", headers=manager_headers)
    assert r.status_code == 202 and r.json()["printer"] == "front office"


def test_platens_address_is_a_web_address(client, admin_headers):
    r = client.put("/v1/settings", headers=admin_headers, json={"platen_url": "platen:8000/jobs"})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "platen_url"


def test_not_until_platen_is_set_up(client, db, manager_headers, kim):
    r = client.post(f"/v1/people/LL042/records/{kim['id']}/certificate", headers=manager_headers)
    assert r.status_code == 409 and r.json()["code"] == "printing_not_set_up"
    r = client.post("/v1/people/LL042/skills-card", headers=manager_headers)
    assert r.status_code == 409 and r.json()["code"] == "printing_not_set_up"


def test_a_manager_prints_and_a_supervisor_does_not(client, supervisor_headers, learner_headers,
                                                    platen, kim):
    for headers in (supervisor_headers, learner_headers):
        assert client.post("/v1/people/LL042/skills-card", headers=headers).status_code == 403


def test_a_skills_card_lists_what_they_are_current_for(client, db, manager_headers, platen, kim,
                                                      monkeypatch):
    monkeypatch.setattr(get_settings(), "skills_card_printer", "card printer")
    yard.grant(client, manager_headers, "LL042", "whs-policy", "2026-10-01")
    r = client.post("/v1/people/ll042/skills-card", headers=manager_headers)
    assert r.status_code == 202, r.text
    [job] = jobs(db)
    assert (job["template"], job["version"], job["printer"], job["reference"]) == (
        "lms-skills-card", "v1", "card printer", {"type": "person", "ref": "LL042"})
    # first aid ran out, so it is not on it; the policy isn't asked of her, and is
    assert job["data"] == {
        "person_name": "Kim Lee", "person_code": "LL042", "roles": "Forklift operator",
        "issued_on": "12 Oct 2026", "count": 3,
        "lines": [
            {"competency": "Forklift licence", "kind": "Ticket or licence",
             "completed_on": "1 Jan 2025", "good_until": "11 Nov 2026"},
            {"competency": "Site induction", "kind": "Online module",
             "completed_on": "1 Jan 2026", "good_until": "1 Jan 2028"},
            {"competency": "WHS policy", "kind": "Policy", "completed_on": "1 Oct 2026",
             "good_until": ""},
        ]}


def test_a_skills_card_with_nothing_on_it_is_not_printed(client, manager_headers, platen,
                                                         learner):
    r = client.post("/v1/people/LL042/skills-card", headers=manager_headers)
    assert r.status_code == 409 and r.json()["code"] == "nothing_current"


# --- the worker hands it to Platen --------------------------------------------

def test_the_worker_hands_it_to_platen(client, db, manager_headers, platen, kim):
    client.post("/v1/people/LL042/skills-card", headers=manager_headers)
    got = []

    def intake(request):
        got.append(request)
        return httpx.Response(202, json={"id": "run-1", "duplicate": False})

    with httpx.Client(transport=httpx.MockTransport(intake)) as http:
        assert worker.send_due(db, http) == 1
    [req] = got
    [job] = jobs(db)
    assert str(req.url) == PLATEN
    assert req.headers["authorization"] == "Bearer platen-key"
    assert req.headers["x-lms-job-id"] == job["job_id"]
    assert json.loads(req.content) == job
    assert db.query(Outbox).filter_by(kind="print").one().status == "done"


def test_platen_saying_no_is_tried_again_in_its_own_words(client, db, manager_headers, platen,
                                                          kim):
    client.post("/v1/people/LL042/skills-card", headers=manager_headers)

    def intake(request):
        return httpx.Response(422, json={"detail": "template: Platen has no template "
                                                   "'lms-skills-card'; make one with that id"})

    with httpx.Client(transport=httpx.MockTransport(intake)) as http:
        worker.send_due(db, http)
    db.expire_all()
    row = db.query(Outbox).filter_by(kind="print").one()
    assert row.last_error == ("Platen answered 422: template: Platen has no template "
                              "'lms-skills-card'; make one with that id")
    assert (row.status, row.attempts) == ("pending", 1)
    assert row.next_attempt_at > datetime.now(UTC) + timedelta(seconds=50)


def test_jobs_wait_untried_while_platen_is_not_set_up(client, db, manager_headers, platen, kim,
                                                      monkeypatch):
    client.post("/v1/people/LL042/skills-card", headers=manager_headers)
    monkeypatch.setattr(get_settings(), "platen_url", "")
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500))) as http:
        assert worker.send_due(db, http) == 0


def test_platens_key_is_never_sent_back(client, admin_headers):
    client.put("/v1/settings", headers=admin_headers, json={"platen_key": "platen-key"})
    r = client.get("/v1/settings", headers=admin_headers)
    assert r.json()["platen_key"] == {"set": True, "source": "here"}
    assert "platen-key" not in r.text


def test_a_redirect_from_platen_is_not_followed(client, db, manager_headers, platen, kim):
    client.post("/v1/people/LL042/skills-card", headers=manager_headers)
    got = []

    def intake(request):
        got.append(request)
        return httpx.Response(307, headers={"location": "https://elsewhere.example.com/jobs"})

    with httpx.Client(transport=httpx.MockTransport(intake), follow_redirects=True) as http:
        worker.send_due(db, http)
    assert len(got) == 1
    db.expire_all()
    assert db.query(Outbox).filter_by(kind="print").one().last_error.startswith(
        "Platen answered 307")

