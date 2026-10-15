"""Certificates of completion and skills cards, printed by Platen (or any
print service that takes the same job). Simple LMS never renders a
document: it queues a template's name and the JSON it binds to, the worker
sends it, and Platen prints it, as Simple TMS sends its run sheets."""
from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime

import httpx
from sqlalchemy.orm import Session as Db

from lms.config import get_settings
from lms.models import CompetencyRecord, Outbox, Person
from lms.services import deadline, settings, standing, webhooks
from lms.services.daily import formatted
from lms.services.status import expiry
from lms.services.webhooks import USER_AGENT

# The Platen page templates that print them: make each with this id and publish it.
CERTIFICATE, CERTIFICATE_VERSION = "lms-certificate", "v1"
SKILLS_CARD, SKILLS_CARD_VERSION = "lms-skills-card", "v1"
KIND_WORDS = {"module": "Online module", "practical": "Practical", "ticket": "Ticket or licence",
              "policy": "Policy"}


def set_up() -> bool:
    return bool(settings.current().platen_url)


def _day(d: date | None) -> str:
    """Text only, never null, so every binding in the template has something."""
    return formatted(d) if d is not None else ""


def certificate_data(r: CompetencyRecord, p: Person, today: date) -> dict:
    """What the certificate template binds to: one completion."""
    c = r.competency
    return {
        "certificate_no": str(r.id), "person_name": p.name, "person_code": p.code,
        "competency": c.name, "kind": KIND_WORDS[c.kind], "completed_on": _day(r.granted_on),
        "good_until": _day(expiry(r.granted_on, r.expires_on, c.refresher_months)),
        "recorded_by": r.recorded_by.name, "issued_on": _day(today),
    }


def skills_card_data(db: Db, p: Person, today: date) -> dict:
    """What the skills card template binds to: the person at the top, a line
    for each competency they are current for, asked of them or not, by name
    (Platen gives a page template a row per entry in `lines`)."""
    st = standing.load(db, [p.id], today)
    held = sorted(st.held(p.id).items(), key=lambda h: st.competencies[h[0]].name)
    lines = [{"competency": st.competencies[c].name, "kind": KIND_WORDS[st.competencies[c].kind],
              "completed_on": _day(s.granted_on), "good_until": _day(s.expires_on)}
             for c, s in held]
    return {"person_name": p.name, "person_code": p.code,
            "roles": ", ".join(r.name for r in p.roles), "issued_on": _day(today),
            "count": len(lines), "lines": lines}


def queue(db: Db, template: str, version: str, printer: str, reference: dict,
          data: dict) -> dict:
    """A print job on the queue, as Platen's intake takes it."""
    job_id = uuid.uuid4()
    job = {"job_id": str(job_id), "template": template, "version": version, "printer": printer,
           "copies": 1, "reference": reference, "data": data}
    db.add(Outbox(kind="print", key=f"print:{job_id}", payload=job, status="pending",
                  attempts=0, next_attempt_at=datetime.now(UTC)))
    db.flush()
    return job


def client() -> httpx.Client:
    """The worker's client for Platen. Platen's address is an admin's own
    setting and is often on this machine or the local network, so it isn't
    held to a webhook's public addresses; but it is held to the deadline,
    no redirect is followed (the key goes nowhere else) and no proxy is
    taken from the environment."""
    return deadline.client(deadline.Backend())


def send(http: httpx.Client, row: Outbox) -> str | None:
    """Hand one job to Platen's intake: None when it took it, otherwise why
    not, in Platen's own words where it gave some. Never the key."""
    s = settings.current()
    headers = {"Content-Type": "application/json", "X-LMS-Job-Id": row.payload["job_id"],
               "User-Agent": USER_AGENT}
    if s.platen_key:
        headers["Authorization"] = f"Bearer {s.platen_key}"
    body = json.dumps(row.payload, separators=(",", ":")).encode()
    env = get_settings()
    try:
        with deadline.within(env.worker_send_deadline_seconds), \
                http.stream("POST", s.platen_url, content=body, headers=headers,
                            timeout=env.worker_http_timeout_seconds,
                            follow_redirects=False) as resp:
            if 200 <= resp.status_code < 300:
                return None
            text = webhooks.said(resp, limit=2000)
    except httpx.HTTPError as e:
        return f"{type(e).__name__}: {e}"
    try:
        detail = json.loads(text).get("detail")
    except (ValueError, AttributeError):
        detail = None
    said = detail if isinstance(detail, str) else text[:200]
    return f"Platen answered {resp.status_code}: {said}"
