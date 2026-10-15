"""A receiver, Platen or a mail server that answers a byte at a time can't
hold the worker: every send has an overall deadline, however the answer
trickles in."""
import threading

from lms.config import get_settings
from lms.models import Outbox, Webhook
from lms.services import mail, printing, webhooks
from trickler import timed


def test_a_receiver_that_trickles_its_answer_is_cut_off_at_the_deadline(short, trickler):
    t = trickler()
    hook = Webhook(name="Slow", url=f"http://127.0.0.1:{t.port}/in", secret="s", events=["*"],
                   active=True)
    row = Outbox(kind="webhook", key="event:1:1", webhook=hook,
                 payload={"event_id": "e1", "event_type": "competency.granted"})
    with webhooks.client() as http:
        error, took = timed(lambda: webhooks.deliver(http, row))
    assert error is not None and "Timeout" in error
    assert isinstance(error, webhooks.TimedOut)
    assert took < 3.5


def test_platen_trickling_its_answer_is_cut_off_at_the_deadline(db, short, trickler,
                                                                monkeypatch):
    t = trickler()
    monkeypatch.setattr(get_settings(), "platen_url", f"http://127.0.0.1:{t.port}/jobs")
    row = Outbox(kind="print", key="print:1", payload={"job_id": "j1"})
    with printing.client() as http:
        error, took = timed(lambda: printing.send(http, row))
    assert error is not None and "Timeout" in error
    assert took < 3.5


def test_a_mail_server_that_trickles_its_greeting_is_cut_off_at_the_deadline(db, short,
                                                                             trickler,
                                                                             monkeypatch):
    t = trickler(b"220-" + b"z" * 5000 + b"\r\n220 hello\r\n")
    monkeypatch.setattr(get_settings(), "smtp_host", "127.0.0.1")
    monkeypatch.setattr(get_settings(), "smtp_port", t.port)
    monkeypatch.setattr(get_settings(), "smtp_security", "none")
    monkeypatch.setattr(get_settings(), "smtp_from", "lms@example.com.au")
    error, took = timed(lambda: mail.send({"to": "kim@example.com.au", "subject": "s",
                                           "text": "t"}))
    assert error is not None and "no answer" in error
    assert took < 3.5


def test_a_receiver_that_answers_is_sent_to_as_before(short):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    got = []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self):
            got.append(self.rfile.read(int(self.headers["content-length"])))
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        hook = Webhook(name="Quick", url=f"http://127.0.0.1:{server.server_port}/in",
                       secret="s", events=["*"], active=True)
        row = Outbox(kind="webhook", key="event:1:1", webhook=hook,
                     payload={"event_id": "e1", "event_type": "competency.granted",
                              "big": "x" * 100_000})
        with webhooks.client() as http:
            assert webhooks.deliver(http, row) is None
            assert webhooks.deliver(http, row) is None
    finally:
        server.shutdown()
        server.server_close()
    assert len(got) == 2 and len(got[0]) > 100_000
