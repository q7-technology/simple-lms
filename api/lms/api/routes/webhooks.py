"""Webhooks: where Simple LMS sends its events, which ones, and how each
delivery went. An admin's to add, change and turn off, on the Settings
screen; never deleted, since their deliveries name them. The secret is shown
once, when it is made, and is never sent back, as the email password isn't.
An address on the inside (this machine, the local network, a cloud's
metadata service) is refused unless whoever runs the server allows it."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select

from lms.api.deps import DB, Principal, require
from lms.api.errors import Conflict, FieldError, NotFound, commit_unique
from lms.models import Outbox, Webhook
from lms.services import webhooks

router = APIRouter(tags=["webhooks"])

# an admin's, as the rest of Settings is
SCOPE = "settings:write"

URL = r"^https?://\S+$"
EventName = Literal["*", "competency.granted", "competency.revoked", "competency.expiring",
                    "competency.lapsed", "person.updated"]


def _events(value: list[str] | None) -> list[str] | None:
    """Each once, in the order given; `*` is everything, so it is all there is."""
    if value is None:
        return None
    return ["*"] if "*" in value else list(dict.fromkeys(value))


class WebhookIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=120)
    url: str = Field(max_length=500, pattern=URL)
    events: list[EventName] = Field(min_length=1, max_length=20)

    @field_validator("events")
    @classmethod
    def _each_once(cls, v):
        return _events(v)


class WebhookPatch(BaseModel):
    """Leave a field out to keep it."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    url: str | None = Field(default=None, max_length=500, pattern=URL)
    events: list[EventName] | None = Field(default=None, min_length=1, max_length=20)
    active: bool | None = None

    @field_validator("events")
    @classmethod
    def _each_once(cls, v):
        return _events(v)


class WebhookOut(BaseModel):
    id: int
    name: str
    url: str
    events: list[str]
    active: bool
    # deliveries still to go, and those given up on
    waiting: int
    failed: int
    created_at: datetime


class WebhookMade(WebhookOut):
    # shown this once: keep it where the receiver can check signatures with it
    secret: str


class SecretOut(BaseModel):
    secret: str


class DeliveryOut(BaseModel):
    id: int
    event_id: uuid.UUID
    event_type: str
    status: str
    attempts: int
    next_attempt_at: datetime
    last_error: str | None
    done_at: datetime | None
    created_at: datetime


def _counts(db, hook_ids: list[int]) -> dict[tuple[int, str], int]:
    rows = db.execute(select(Outbox.webhook_id, Outbox.status, func.count())
                      .where(Outbox.webhook_id.in_(hook_ids), Outbox.status != "done")
                      .group_by(Outbox.webhook_id, Outbox.status)).all()
    return {(w, s): n for w, s, n in rows}


def webhook_out(db, w: Webhook, counts: dict | None = None) -> WebhookOut:
    counts = _counts(db, [w.id]) if counts is None else counts
    return WebhookOut(id=w.id, name=w.name, url=w.url, events=w.events, active=w.active,
                      waiting=counts.get((w.id, "pending"), 0),
                      failed=counts.get((w.id, "failed"), 0), created_at=w.created_at)


def delivery_out(r: Outbox) -> DeliveryOut:
    return DeliveryOut(id=r.id, event_id=r.payload["event_id"], event_type=r.payload["event_type"],
                       status=r.status, attempts=r.attempts, next_attempt_at=r.next_attempt_at,
                       last_error=r.last_error, done_at=r.done_at, created_at=r.created_at)


def get_webhook(db, webhook_id: int) -> Webhook:
    w = db.get(Webhook, webhook_id)
    if w is None:
        raise NotFound(f"no webhook {webhook_id}")
    return w


def _name_taken(name: str | None) -> FieldError:
    return FieldError("name", f"there is already a webhook called {name}")


def _check_url(url: str) -> None:
    """An internal address (localhost, a private or link-local IP) is
    refused unless LMS_WEBHOOK_ALLOW_PRIVATE is set; the worker checks a
    name's addresses again each time it sends."""
    why = webhooks.check_url(url)
    if why is not None:
        raise FieldError("url", why)


@router.get("/webhooks", response_model=list[WebhookOut])
def list_webhooks(db: DB, who: Principal = require(SCOPE)):
    """By name, turned off or not."""
    rows = db.execute(select(Webhook).order_by(Webhook.name)).scalars().all()
    counts = _counts(db, [w.id for w in rows])
    return [webhook_out(db, w, counts) for w in rows]


@router.post("/webhooks", status_code=201, response_model=WebhookMade)
def add_webhook(body: WebhookIn, db: DB, who: Principal = require(SCOPE)):
    if db.execute(select(Webhook.id).where(Webhook.name == body.name)).first():
        raise _name_taken(body.name)
    _check_url(body.url)
    w = Webhook(name=body.name, url=body.url, events=body.events, secret=webhooks.new_secret(),
                active=True)
    db.add(w)
    commit_unique(db, {"uq_webhook_name": _name_taken(body.name)})
    out = WebhookMade(**webhook_out(db, w, {}).model_dump(), secret=w.secret)
    return JSONResponse(status_code=201, content=out.model_dump(mode="json"))


@router.get("/webhooks/{webhook_id}", response_model=WebhookOut)
def read_webhook(webhook_id: int, db: DB, who: Principal = require(SCOPE)):
    return webhook_out(db, get_webhook(db, webhook_id))


@router.patch("/webhooks/{webhook_id}", response_model=WebhookOut)
def change_webhook(webhook_id: int, body: WebhookPatch, db: DB,
                   who: Principal = require(SCOPE)):
    """What is still waiting goes to the new address. Turned off, it is sent
    nothing more, and what is waiting for it is given up on."""
    w = get_webhook(db, webhook_id)
    if body.name is not None and body.name != w.name:
        if db.execute(select(Webhook.id).where(Webhook.name == body.name)).first():
            raise _name_taken(body.name)
        w.name = body.name
    if body.url is not None:
        _check_url(body.url)
        w.url = body.url
    if body.events is not None:
        w.events = body.events
    if body.active is not None:
        w.active = body.active
    commit_unique(db, {"uq_webhook_name": _name_taken(body.name)})
    return webhook_out(db, w)


@router.post("/webhooks/{webhook_id}/secret", response_model=SecretOut)
def new_secret(webhook_id: int, db: DB, who: Principal = require(SCOPE)):
    """A new secret, shown this once. Everything sent from now on is signed
    with it, what was waiting included; the old one stops at once."""
    w = get_webhook(db, webhook_id)
    w.secret = webhooks.new_secret()
    db.commit()
    return SecretOut(secret=w.secret)


@router.get("/webhooks/{webhook_id}/deliveries", response_model=list[DeliveryOut])
def list_deliveries(webhook_id: int, db: DB,
                    status: Literal["pending", "done", "failed"] | None = None,
                    who: Principal = require(SCOPE)):
    """The latest 50, newest first."""
    w = get_webhook(db, webhook_id)
    q = select(Outbox).where(Outbox.webhook_id == w.id)
    if status:
        q = q.where(Outbox.status == status)
    rows = db.execute(q.order_by(Outbox.id.desc()).limit(50)).scalars().all()
    return [delivery_out(r) for r in rows]


@router.post("/webhooks/{webhook_id}/deliveries/{delivery_id}/retry", response_model=DeliveryOut)
def retry_delivery(webhook_id: int, delivery_id: int, db: DB,
                   who: Principal = require(SCOPE)):
    """A delivery given up on, sent again from the start of the backoff:
    the same event, with the same id."""
    w = get_webhook(db, webhook_id)
    r = db.get(Outbox, delivery_id, with_for_update=True)
    if r is None or r.webhook_id != w.id:
        raise NotFound(f"no delivery {delivery_id} for this webhook")
    if not w.active:
        raise Conflict("inactive", f"{w.name} is turned off: turn it on first")
    if r.status != "failed":
        raise Conflict("not_failed",
                       f"this delivery is {r.status}: only a failed one is sent again")
    r.status, r.attempts, r.next_attempt_at = "pending", 0, datetime.now(UTC)
    db.commit()
    return delivery_out(r)
