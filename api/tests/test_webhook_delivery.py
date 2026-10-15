"""The worker delivers each event to its webhook, signed with the webhook's
secret, retried after 1 min, 5, 30 and 2 h; and it drains emails and
deliveries in turn, so neither holds the other up."""
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta

import httpcore
import httpx
import pytest

from lms import worker
from lms.models import Outbox, Webhook
from lms.services import events, outbox, webhooks

T0 = datetime(2026, 10, 12, 0, 0, tzinfo=UTC)


class Receiver:
    """Somewhere to send events: keeps each request, answers `status`, or
    fails to connect when `down` is set."""

    def __init__(self):
        self.got: list[httpx.Request] = []
        self.status = 200
        self.down = False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("Connection refused", request=request)
        self.got.append(request)
        return httpx.Response(self.status, text="thanks" if self.status < 300 else "not now")


@pytest.fixture
def receiver():
    r = Receiver()
    with httpx.Client(transport=httpx.MockTransport(r)) as http:
        r.http = http
        yield r


@pytest.fixture
def hook(db):
    h = Webhook(name="Simple TMS", url="https://tms.example.com.au/lms-events",
                secret="whsec_test", events=["*"])
    db.add(h)
    db.commit()
    return h


def fired(db, data=None) -> Outbox:
    events.emit(db, "competency.granted", data or {"person": {"code": "LL042"}}, now=T0)
    db.commit()
    return db.query(Outbox).filter_by(kind="webhook").order_by(Outbox.id.desc()).first()


def row(db, r: Outbox) -> Outbox:
    db.expire_all()
    return db.get(Outbox, r.id)


def test_an_event_is_posted_signed_with_its_id_and_type(db, hook, receiver):
    r = fired(db)
    assert worker.send_due(db, receiver.http, now=T0) == 1
    [req] = receiver.got
    assert str(req.url) == "https://tms.example.com.au/lms-events"
    assert req.headers["content-type"] == "application/json"
    assert req.headers["x-lms-event-id"] == r.payload["event_id"]
    assert req.headers["x-lms-event-type"] == "competency.granted"
    assert req.headers["user-agent"] == "simple-lms/0.1"
    expected = hmac.new(b"whsec_test", req.content, hashlib.sha256).hexdigest()
    assert req.headers["x-lms-signature"] == f"sha256={expected}"
    assert json.loads(req.content) == r.payload
    assert (row(db, r).status, row(db, r).attempts) == ("done", 1)


def test_a_receiver_checks_the_signature_like_this():
    body = b'{"event_id":"e1"}'
    good = webhooks.sign("whsec_test", body)
    assert webhooks.verify("whsec_test", body, good)
    assert not webhooks.verify("whsec_test", body + b" ", good)
    assert not webhooks.verify("whsec_other", body, good)
    assert not webhooks.verify("whsec_test", body, None)


def test_a_refusal_is_tried_again_after_1_5_30_and_120_minutes(db, hook, receiver):
    r = fired(db)
    receiver.status = 503
    now = T0
    for wait in (60, 300, 1800, 7200):
        assert worker.send_due(db, receiver.http, now=now) == 1
        assert row(db, r).next_attempt_at == now + timedelta(seconds=wait)
        assert row(db, r).last_error == "HTTP 503: not now"
        assert worker.send_due(db, receiver.http, now=now + timedelta(seconds=wait - 1)) == 0
        now += timedelta(seconds=wait)
    worker.send_due(db, receiver.http, now=now)
    assert (row(db, r).status, row(db, r).attempts) == ("failed", 5)
    assert len(receiver.got) == 5


def test_a_receiver_that_cannot_be_reached_is_a_failure_not_a_crash(db, hook, receiver):
    r = fired(db)
    receiver.down = True
    worker.send_due(db, receiver.http, now=T0)
    assert row(db, r).last_error == "ConnectError: Connection refused"
    assert row(db, r).status == "pending"


def test_one_that_fails_does_not_hold_up_the_next(db, hook, receiver):
    first, second = fired(db), fired(db)
    statuses = iter([500, 200])
    receiver.status = 500

    def answer(request):
        receiver.got.append(request)
        return httpx.Response(next(statuses))

    with httpx.Client(transport=httpx.MockTransport(answer)) as http:
        assert worker.send_due(db, http, now=T0) == 2
    assert (row(db, first).status, row(db, second).status) == ("pending", "done")


def test_the_secret_and_address_are_read_when_it_is_sent(db, hook, receiver):
    fired(db)
    hook.url = "https://tms.example.com.au/new-address"
    hook.secret = "whsec_new"
    db.commit()
    worker.send_due(db, receiver.http, now=T0)
    [req] = receiver.got
    assert str(req.url) == "https://tms.example.com.au/new-address"
    assert webhooks.verify("whsec_new", req.content, req.headers["x-lms-signature"])


def test_a_webhook_turned_off_gets_nothing_more(db, hook, receiver):
    r = fired(db)
    hook.active = False
    db.commit()
    worker.send_due(db, receiver.http, now=T0)
    assert receiver.got == []
    assert (row(db, r).status, row(db, r).last_error) == ("failed", "the webhook was turned off")


def test_emails_and_events_take_turns(db, hook, mailbox, monkeypatch):
    order = []
    monkeypatch.setattr(worker.mail, "send", lambda payload: order.append(payload["subject"]))
    for n in range(3):
        outbox.queue_email(db, f"mail{n}", "kim@example.com.au", f"email {n}", "t", now=T0)
        fired(db, {"n": n})

    def answer(request):
        order.append(f"event {json.loads(request.content)['data']['n']}")
        return httpx.Response(200)

    with httpx.Client(transport=httpx.MockTransport(answer)) as http:
        assert worker.send_due(db, http, now=T0) == 6
    assert order == ["email 0", "event 0", "email 1", "event 1", "email 2", "event 2"]


def test_each_kind_has_its_own_limit_per_pass(db, hook, receiver, mailbox):
    for n in range(3):
        outbox.queue_email(db, f"mail{n}", "kim@example.com.au", "s", "t", now=T0)
        fired(db)
    assert worker.send_due(db, receiver.http, now=T0, limit=2) == 4
    assert len(receiver.got) == 2 and len(mailbox.sent) == 2


def test_events_go_while_emails_wait_for_smtp(db, hook, receiver):
    outbox.queue_email(db, "mail", "kim@example.com.au", "s", "t", now=T0)
    fired(db)
    assert worker.send_due(db, receiver.http, now=T0) == 1
    assert len(receiver.got) == 1


# --- what the worker refuses to do --------------------------------------------

def test_a_redirect_is_not_followed(db, hook):
    got = []

    def answer(request):
        got.append(request)
        return httpx.Response(302, headers={"location": "http://169.254.169.254/latest"})

    r = fired(db)
    with httpx.Client(transport=httpx.MockTransport(answer), follow_redirects=True) as http:
        worker.send_due(db, http, now=T0)
    assert len(got) == 1
    assert row(db, r).last_error.startswith("HTTP 302")


def test_only_the_start_of_a_long_answer_is_read(db, hook):
    r = fired(db)

    def answer(request):
        return httpx.Response(500, content=b"x" * 1_000_000)

    with httpx.Client(transport=httpx.MockTransport(answer)) as http:
        worker.send_due(db, http, now=T0)
    assert row(db, r).last_error == "HTTP 500: " + "x" * 200


@pytest.mark.parametrize("address", [
    "127.0.0.1", "10.1.2.3", "172.16.0.9", "192.168.1.20", "169.254.169.254", "100.64.0.1",
    "0.0.0.0", "::1", "fe80::1", "fc00::1", "::ffff:127.0.0.1", "224.0.0.1",
])
def test_an_internal_address_is_refused(address):
    assert not webhooks.address_allowed(address)
    assert webhooks.address_allowed(address, allow_private=True) or address in (
        "0.0.0.0", "224.0.0.1")


@pytest.mark.parametrize("address", ["203.0.113.10", "8.8.8.8", "2606:4700:4700::1111"])
def test_a_public_address_is_allowed(address):
    # 203.0.113.0/24 is for documentation, so Python calls it not global; the
    # others are public resolvers
    assert webhooks.address_allowed(address) == (address != "203.0.113.10")


class Resolver:
    def __init__(self, *addresses):
        self.addresses = addresses

    def __call__(self, host, port):
        return list(self.addresses)


def test_the_guard_refuses_a_name_that_resolves_inside(monkeypatch):
    # a public name pointed at an internal address (DNS rebinding) is refused
    # where the connection is made, after the name is looked up
    monkeypatch.setattr(webhooks, "resolve", Resolver("8.8.8.8", "10.0.0.5"))
    backend = webhooks.GuardedBackend()
    with pytest.raises(httpcore.ConnectError, match="internal address"):
        backend.connect_tcp("tms.example.com.au", 443)


def test_the_worker_client_refuses_an_internal_address_and_says_why(db, monkeypatch):
    db.add(Webhook(name="Inside", url="http://127.0.0.1:9/in", secret="s", events=["*"]))
    db.commit()
    r = fired(db)
    with webhooks.client() as http:
        worker.send_due(db, http, now=T0)
    assert row(db, r).status == "pending"
    assert "internal address" in row(db, r).last_error


def test_the_worker_client_does_not_follow_redirects_nor_read_proxies_from_the_environment():
    with webhooks.client() as http:
        assert http.follow_redirects is False
        assert http.trust_env is False


@pytest.mark.parametrize("url, refused", [
    ("https://tms.example.com.au/in", False),
    ("http://192.168.1.20:8080/in", True),
    ("http://localhost:8080/in", True),
    ("http://lms.localhost/in", True),
    ("http://[::1]/in", True),
    ("http://169.254.169.254/latest/meta-data", True),
    ("http://8.8.8.8/in", False),
])
def test_an_address_given_for_a_webhook_is_checked(url, refused, monkeypatch):
    assert (webhooks.check_url(url) is not None) == refused
    from lms.config import get_settings
    monkeypatch.setattr(get_settings(), "webhook_allow_private", True)
    assert webhooks.check_url(url) is None
