"""Webhooks: an admin adds where the events go, chooses which, sees how
each delivery went, and sends a failed one again. The secret is shown
once."""
from datetime import UTC, datetime

import pytest

from lms.models import Outbox
from lms.services import events

TMS = {"name": "Simple TMS", "url": "https://tms.example.com.au/lms-events",
       "events": ["competency.granted", "competency.revoked"]}


def add(client, headers, **more):
    return client.post("/v1/webhooks", headers=headers, json={**TMS, **more})


@pytest.fixture
def tms(client, admin_headers):
    r = add(client, admin_headers)
    assert r.status_code == 201, r.text
    return r.json()


def test_an_admin_adds_one_and_sees_its_secret_once(client, admin_headers, tms):
    assert tms["secret"].startswith("whsec_") and len(tms["secret"]) > 40
    assert (tms["name"], tms["url"], tms["events"], tms["active"]) == (
        TMS["name"], TMS["url"], TMS["events"], True)
    assert (tms["waiting"], tms["failed"]) == (0, 0)
    listed = client.get("/v1/webhooks", headers=admin_headers).json()
    assert [w["name"] for w in listed] == ["Simple TMS"]
    assert "secret" not in listed[0]
    assert "secret" not in client.get(f"/v1/webhooks/{tms['id']}", headers=admin_headers).json()


@pytest.mark.parametrize("body, field", [
    ({"events": ["competency.renamed"]}, "events.0"),
    ({"events": []}, "events"),
    ({"url": "tms.example.com.au"}, "url"),
    ({"url": "ftp://tms.example.com.au"}, "url"),
    ({"name": "  "}, "name"),
])
def test_what_is_wrong_is_said(client, admin_headers, body, field):
    r = add(client, admin_headers, **body)
    assert r.status_code == 422
    assert r.json()["errors"][0]["field"] == field


def test_everything_is_a_star_and_the_same_event_is_named_once(client, admin_headers):
    r = add(client, admin_headers, events=["person.updated", "*"])
    assert r.json()["events"] == ["*"]
    r = add(client, admin_headers, name="Twice",
            events=["person.updated", "competency.lapsed", "person.updated"])
    assert r.json()["events"] == ["person.updated", "competency.lapsed"]


def test_two_cannot_share_a_name(client, admin_headers, tms):
    r = add(client, admin_headers)
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "name"


def test_only_an_admin(client, manager_headers, admin_headers, tms):
    assert client.get("/v1/webhooks", headers=manager_headers).status_code == 403
    assert add(client, manager_headers, name="Mine").status_code == 403


def test_changed_and_turned_off(client, admin_headers, tms):
    r = client.patch(f"/v1/webhooks/{tms['id']}", headers=admin_headers,
                     json={"url": "https://tms.example.com.au/v2/lms", "events": ["*"],
                           "active": False})
    assert r.status_code == 200, r.text
    assert (r.json()["url"], r.json()["events"], r.json()["active"]) == (
        "https://tms.example.com.au/v2/lms", ["*"], False)
    assert client.patch("/v1/webhooks/999", headers=admin_headers,
                        json={"active": True}).status_code == 404


def test_a_new_secret_replaces_the_old(client, db, admin_headers, tms):
    r = client.post(f"/v1/webhooks/{tms['id']}/secret", headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["secret"].startswith("whsec_") and r.json()["secret"] != tms["secret"]


def queued(db, at: datetime, event_type="competency.granted"):
    events.emit(db, event_type, {}, now=at)
    db.commit()


def test_its_deliveries_newest_first_and_a_failed_one_sent_again(client, db, admin_headers, tms):
    queued(db, datetime(2026, 10, 12, 1, tzinfo=UTC))
    queued(db, datetime(2026, 10, 12, 2, tzinfo=UTC), "competency.revoked")
    first, second = db.query(Outbox).order_by(Outbox.id).all()
    first.status, first.attempts, first.last_error = "failed", 5, "HTTP 503: not now"
    db.commit()

    out = client.get(f"/v1/webhooks/{tms['id']}/deliveries", headers=admin_headers).json()
    assert [(d["event_type"], d["status"]) for d in out] == [
        ("competency.revoked", "pending"), ("competency.granted", "failed")]
    assert out[1]["event_id"] == first.payload["event_id"]
    assert out[1]["last_error"] == "HTTP 503: not now"
    failed = client.get(f"/v1/webhooks/{tms['id']}/deliveries?status=failed",
                        headers=admin_headers).json()
    assert [d["id"] for d in failed] == [first.id]
    counts = client.get(f"/v1/webhooks/{tms['id']}", headers=admin_headers).json()
    assert (counts["waiting"], counts["failed"]) == (1, 1)

    r = client.post(f"/v1/webhooks/{tms['id']}/deliveries/{first.id}/retry",
                    headers=admin_headers)
    assert r.status_code == 200, r.text
    assert (r.json()["status"], r.json()["attempts"]) == ("pending", 0)
    db.expire_all()
    assert db.get(Outbox, first.id).next_attempt_at <= datetime.now(UTC)

    r = client.post(f"/v1/webhooks/{tms['id']}/deliveries/{second.id}/retry",
                    headers=admin_headers)
    assert r.status_code == 409 and r.json()["code"] == "not_failed"


def test_nothing_is_sent_again_to_a_webhook_turned_off(client, db, admin_headers, tms):
    queued(db, datetime(2026, 10, 12, 1, tzinfo=UTC))
    row = db.query(Outbox).one()
    row.status, row.attempts = "failed", 5
    db.commit()
    client.patch(f"/v1/webhooks/{tms['id']}", headers=admin_headers, json={"active": False})
    r = client.post(f"/v1/webhooks/{tms['id']}/deliveries/{row.id}/retry", headers=admin_headers)
    assert r.status_code == 409 and r.json()["code"] == "inactive"


def test_another_webhooks_delivery_is_not_found(client, db, admin_headers, tms):
    other = add(client, admin_headers, name="Simple WMS").json()
    queued(db, datetime(2026, 10, 12, 1, tzinfo=UTC))
    row = db.query(Outbox).filter_by(webhook_id=tms["id"]).one()
    r = client.post(f"/v1/webhooks/{other['id']}/deliveries/{row.id}/retry",
                    headers=admin_headers)
    assert r.status_code == 404


@pytest.mark.parametrize("url", ["http://127.0.0.1:5432/", "http://localhost/in",
                                 "http://169.254.169.254/latest/meta-data",
                                 "http://192.168.1.20/in"])
def test_an_internal_address_is_refused_unless_the_server_allows_it(client, admin_headers, tms,
                                                                    url, monkeypatch):
    r = add(client, admin_headers, name="Inside", url=url)
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "url"
    r = client.patch(f"/v1/webhooks/{tms['id']}", headers=admin_headers, json={"url": url})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "url"
    from lms.config import get_settings
    monkeypatch.setattr(get_settings(), "webhook_allow_private", True)
    assert add(client, admin_headers, name="Inside", url=url).status_code == 201
