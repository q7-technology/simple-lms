"""Settings an admin changes on the desktop, which take effect without a
restart. What has to be known before the app starts stays in .env."""
from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from lms.api.deps import DB, Principal, require
from lms.api.errors import Conflict
from lms.services import mail, outbox, settings

router = APIRouter(prefix="/settings", tags=["settings"])

SCOPE = "settings:write"


@router.get("")
def read_settings(db: DB, who: Principal = require(SCOPE)) -> dict[str, dict[str, Any]]:
    """Every setting: `value` and where it comes from (`source`: here, env or
    default). The email password says only whether it is `set`."""
    return settings.described(db)


@router.put("")
def change_settings(body: settings.Changes, db: DB,
                    who: Principal = require(SCOPE)) -> dict[str, dict[str, Any]]:
    """Change the settings given, and only those; null goes back to .env or
    the default. All or nothing."""
    settings.save(db, {k: getattr(body, k) for k in body.model_fields_set}, who.person,
                  who.method)
    return settings.described(db)


@router.post("/test-email", status_code=202)
def test_email(db: DB, who: Principal = require(SCOPE)):
    """Queue an email to the caller's own address; the worker sends it."""
    if not who.person.email:
        raise Conflict("no_email", "You have no email address to send it to.")
    if not mail.set_up():
        raise Conflict("no_mail_server", "Set the email server's host and from address first.")
    text = (f"Hi {who.person.name},\n\nThis is a test email from Simple LMS, sent from "
            "Settings. If you can read it, the email server is set up.\n\nSimple LMS")
    outbox.queue_email(db, f"test-email:{who.person.id}:{uuid4().hex}", who.person.email,
                       "Simple LMS: a test email", text)
    db.commit()
    return JSONResponse(status_code=202, content={"to": who.person.email})
