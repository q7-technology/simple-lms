"""Email through SMTP, as Settings (or .env, LMS_SMTP_*) says. Only the
worker sends, from the outbox; nothing waits on an email."""
from __future__ import annotations

import re
import smtplib
import socket
import ssl
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from email.message import EmailMessage

from lms.config import get_settings
from lms.services import settings

# for each step (connecting, each line read or written)
TIMEOUT_SECONDS = 20
# line breaks and other control characters, which in a header could start a new one
CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f\u2028\u2029]+")


def set_up() -> bool:
    s = settings.current()
    return bool(s.smtp_host and s.smtp_from)


class Watch:
    """The deadline for one email. smtplib's timeout is for each step, so a
    server that answers a byte at a time never trips it; once the deadline
    passes, this shuts the connection's socket (again and again, as
    STARTTLS swaps it), and whatever smtplib is waiting on fails at once."""

    def __init__(self, seconds: float) -> None:
        self.smtp: smtplib.SMTP | None = None
        self.passed = False
        self._done = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(seconds,), daemon=True,
                                        name="mail-deadline")
        self._thread.start()

    def _run(self, seconds: float) -> None:
        if self._done.wait(seconds):
            return
        self.passed = True
        while not self._done.is_set():
            sock = getattr(self.smtp, "sock", None)
            if sock is not None:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
            self._done.wait(0.05)

    def stop(self) -> None:
        self._done.set()
        self._thread.join()


_watch: ContextVar[Watch | None] = ContextVar("mail_watch", default=None)


@contextmanager
def within(seconds: float):
    watch = Watch(seconds)
    token = _watch.set(watch)
    try:
        yield watch
    finally:
        _watch.reset(token)
        watch.stop()


def connect(s: settings.Effective) -> smtplib.SMTP:
    """A connection to the mail server, encrypted as the settings say, and
    held to the deadline of the email it is for."""
    if s.smtp_security == "ssl":
        smtp = smtplib.SMTP_SSL(timeout=TIMEOUT_SECONDS, context=ssl.create_default_context())
    else:
        smtp = smtplib.SMTP(timeout=TIMEOUT_SECONDS)
    watch = _watch.get()
    if watch is not None:
        watch.smtp = smtp     # before connecting: the greeting can trickle too
    code, msg = smtp.connect(s.smtp_host, s.smtp_port)
    if code != 220:
        smtp.close()
        raise smtplib.SMTPConnectError(code, msg)
    if s.smtp_security == "starttls":
        smtp.starttls(context=ssl.create_default_context())
    return smtp


def one_line(value: str) -> str:
    """A header value on one line: names go into subjects, and a name with a
    line break in it must not add a header (or fail the email)."""
    return CONTROL.sub(" ", value).strip()


def message(payload: dict) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = one_line(settings.current().smtp_from)
    msg["To"] = one_line(payload["to"])
    msg["Subject"] = one_line(payload["subject"])
    msg.set_content(payload["text"])
    return msg


def send(payload: dict) -> str | None:
    """Send one email: None when the server took it, else what went wrong.
    All of it within the worker's deadline for a send."""
    s = settings.current()
    seconds = get_settings().worker_send_deadline_seconds
    with within(seconds) as watch:
        try:
            with connect(s) as smtp:
                if s.smtp_user:
                    smtp.login(s.smtp_user, s.smtp_password)
                smtp.send_message(message(payload))
        except (smtplib.SMTPException, OSError) as e:
            if watch.passed:
                return f"TimeoutError: no answer from the mail server within {seconds:g} s"
            return f"{type(e).__name__}: {e}"
    return None
