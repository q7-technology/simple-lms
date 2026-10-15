"""Email through SMTP, as Settings (or .env, LMS_SMTP_*) says. Only the
worker sends, from the outbox; nothing waits on an email."""
from __future__ import annotations

import re
import smtplib
import ssl
from email.message import EmailMessage

from lms.services import settings

TIMEOUT_SECONDS = 20
# line breaks and other control characters, which in a header could start a new one
CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f\u2028\u2029]+")


def set_up() -> bool:
    s = settings.current()
    return bool(s.smtp_host and s.smtp_from)


def connect(s: settings.Effective) -> smtplib.SMTP:
    """A connection to the mail server, encrypted as the settings say."""
    if s.smtp_security == "ssl":
        return smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, timeout=TIMEOUT_SECONDS,
                                context=ssl.create_default_context())
    smtp = smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=TIMEOUT_SECONDS)
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
    """Send one email: None when the server took it, else what went wrong."""
    s = settings.current()
    try:
        with connect(s) as smtp:
            if s.smtp_user:
                smtp.login(s.smtp_user, s.smtp_password)
            smtp.send_message(message(payload))
    except (smtplib.SMTPException, OSError) as e:
        return f"{type(e).__name__}: {e}"
    return None
