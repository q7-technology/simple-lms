"""The settings an admin changes on the Settings screen, and the one place
they are read. Each value is the one set here (a `setting` row) if there is
one, else the one in .env (lms.config), else the default, so a deployment
that only has .env keeps working.

Every process (the API, the worker, the command line) asks current(). The
rows are kept KEEP_SECONDS, so a change made in one process reaches the
others within seconds, with no restart; the process that saved it forgets
its copy at once. What must be known before the app starts, or could lock
everyone out (the database, ports, the domain, the upload folder), stays
in .env only."""
from __future__ import annotations

import re
from dataclasses import dataclass, fields
from datetime import UTC, datetime
from time import monotonic
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, Strict, field_validator
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session as Db

from lms.api.errors import Conflict
from lms.config import get_settings
from lms.db import get_sessionmaker
from lms.models import Person, Setting

KEEP_SECONDS = 5.0
Source = Literal["here", "env", "default"]


@dataclass(frozen=True)
class Effective:
    """Every setting as it stands."""
    # sign-in methods: a code and PIN (the learner app), an email and password,
    # Microsoft (offered only once it is set up: entra_set_up())
    sign_in_pin: bool = True
    sign_in_password: bool = True
    sign_in_entra: bool = True
    # this many goes at a module's quiz in a row that didn't pass, and the
    # learner waits this many minutes before the next (0: no wait)
    quiz_cooldown_tries: int = 3
    quiz_cooldown_minutes: int = 60
    # a learner's reminders: this many days before the last good day
    reminder_days: tuple[int, ...] = (30, 14, 0)
    # whose "today" decides what is current, and when the daily job runs
    timezone: str = "Australia/Melbourne"
    daily_hour: int = 6
    # the email server the worker sends through
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_security: Literal["starttls", "ssl", "none"] = "starttls"
    # where people open Simple LMS, for the links in emails
    public_url: str = ""
    # how much one person may send of their own (tickets' photos,
    # signatures) in 24 hours; an editor's module files have limits of their own
    upload_files_per_day: int = 30
    upload_mb_per_day: int = 200


KEYS = tuple(f.name for f in fields(Effective))
DEFAULTS = Effective()
# the ones .env can give too, by the same name (LMS_<KEY>)
FROM_ENV = ("quiz_cooldown_minutes", "timezone", "daily_hour", "smtp_host", "smtp_port",
            "smtp_user", "smtp_password", "smtp_from", "smtp_security", "public_url")
# never sent back: only whether there is one
SECRET = ("smtp_password",)
# the ways into the desktop, as an admin's session names them
NAMES = {"password": "an email and password", "entra": "Microsoft"}

# line breaks and other control characters
CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f  ]")
Int = Annotated[int, Strict()]
Bool = Annotated[bool, Strict()]


class Changes(BaseModel):
    """What PUT /v1/settings may change. A key left out is left alone; null
    goes back to .env or the default."""
    model_config = ConfigDict(extra="forbid")

    sign_in_pin: Bool | None = None
    sign_in_password: Bool | None = None
    sign_in_entra: Bool | None = None
    quiz_cooldown_tries: Annotated[Int, Field(ge=1, le=20)] | None = None
    # up to a year
    quiz_cooldown_minutes: Annotated[Int, Field(ge=0, le=525600)] | None = None
    reminder_days: Annotated[list[Annotated[Int, Field(ge=0, le=365)]],
                             Field(min_length=1, max_length=10)] | None = None
    timezone: Annotated[str, Field(max_length=64)] | None = None
    daily_hour: Annotated[Int, Field(ge=0, le=23)] | None = None
    smtp_host: Annotated[str, Field(max_length=253)] | None = None
    smtp_port: Annotated[Int, Field(ge=1, le=65535)] | None = None
    smtp_user: Annotated[str, Field(max_length=254)] | None = None
    smtp_password: Annotated[str, Field(max_length=500)] | None = None
    smtp_from: Annotated[str, Field(max_length=254)] | None = None
    smtp_security: Literal["starttls", "ssl", "none"] | None = None
    public_url: Annotated[str, Field(max_length=2000)] | None = None
    upload_files_per_day: Annotated[Int, Field(ge=1, le=100_000)] | None = None
    # up to a terabyte
    upload_mb_per_day: Annotated[Int, Field(ge=1, le=1_000_000)] | None = None

    @field_validator("timezone", "smtp_host", "smtp_user", "smtp_password", "smtp_from",
                     "public_url")
    @classmethod
    def _one_line(cls, value: str | None) -> str | None:
        if value is not None and CONTROL.search(value):
            raise ValueError("must be on one line")
        return value

    @field_validator("reminder_days")
    @classmethod
    def _each_once_furthest_first(cls, value: list[int] | None) -> list[int] | None:
        return sorted(set(value), reverse=True) if value is not None else None

    @field_validator("timezone")
    @classmethod
    def _known_zone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            ZoneInfo(value.strip())
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(f"{value!r} is not a time zone, e.g. Australia/Melbourne") from None
        return value.strip()

    @field_validator("smtp_host")
    @classmethod
    def _host(cls, value: str | None) -> str | None:
        if value is not None and any(c.isspace() for c in value.strip()):
            raise ValueError("a host name has no spaces, e.g. smtp.office365.com")
        return value.strip() if value is not None else None

    @field_validator("smtp_from")
    @classmethod
    def _sender(cls, value: str | None) -> str | None:
        if value is not None and value.strip() and "@" not in value:
            raise ValueError("an email address, e.g. Simple LMS <lms@yourcompany.com.au>")
        return value.strip() if value is not None else None

    @field_validator("public_url")
    @classmethod
    def _web_address(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip().rstrip("/")
        if value and not re.fullmatch(r"https?://[^\s/?#]+(/[^\s?#]*)?", value):
            raise ValueError("a web address starting https://, e.g. https://lms.example.com.au")
        return value


_rows: dict[str, Any] | None = None
_read_at = 0.0


def forget() -> None:
    """Read the rows afresh next time."""
    global _rows
    _rows = None


def _load(db: Db) -> dict[str, Any]:
    return dict(db.execute(select(Setting.key, Setting.value)).all())


def _rows_now() -> dict[str, Any]:
    global _rows, _read_at
    if _rows is None or monotonic() - _read_at > KEEP_SECONDS:
        with get_sessionmaker()() as db:
            _rows = _load(db)
        _read_at = monotonic()
    return _rows


def _effective(rows: dict[str, Any]) -> Effective:
    env = get_settings()
    values: dict[str, Any] = {}
    for key in KEYS:
        if key in rows:
            values[key] = rows[key]
        elif key in FROM_ENV:
            values[key] = getattr(env, key)
    if "reminder_days" in values:
        values["reminder_days"] = tuple(values["reminder_days"])
    return Effective(**values)


def _source(rows: dict[str, Any], key: str) -> Source:
    if key in rows:
        return "here"
    # given in .env and not just the default again: Compose passes every
    # variable, empty or at its default, when .env leaves it out
    env = get_settings()
    if (key in FROM_ENV and key in env.model_fields_set
            and getattr(env, key) != getattr(DEFAULTS, key)):
        return "env"
    return "default"


def current() -> Effective:
    """Every setting as it stands now (give or take KEEP_SECONDS)."""
    return _effective(_rows_now())


def source(key: str) -> Source:
    """Where a setting's value comes from: set here, .env, or the default."""
    return _source(_rows_now(), key)


def described(db: Db) -> dict[str, dict[str, Any]]:
    """Every setting with where it comes from, read fresh, for the screen.
    A secret says only whether it is set."""
    rows = _load(db)
    now = _effective(rows)
    out: dict[str, dict[str, Any]] = {}
    for key in KEYS:
        value = getattr(now, key)
        if key in SECRET:
            out[key] = {"set": bool(value), "source": _source(rows, key)}
        else:
            out[key] = {"value": list(value) if isinstance(value, tuple) else value,
                        "source": _source(rows, key)}
    # the switch can be on with nobody offered the button: say why
    out["sign_in_entra"]["set_up"] = entra_set_up(now)
    return out


def entra_set_up(s: Effective) -> bool:
    """Everything signing in with Microsoft needs: the app registered in the
    tenant (LMS_ENTRA_* in .env only, as the client secret is a secret) and a
    web address for Microsoft to send people back to."""
    env = get_settings()
    return bool(env.entra_tenant_id and env.entra_client_id and env.entra_client_secret
                and s.public_url)


def offered(s: Effective) -> dict[str, bool]:
    """The ways a sign-in page offers: Microsoft only once it is set up."""
    return {"pin": s.sign_in_pin, "password": s.sign_in_password,
            "entra": s.sign_in_entra and entra_set_up(s)}


def admin_ways_in(s: Effective) -> list[str]:
    """How an admin can sign in to change things back. A PIN session never
    carries an admin's scopes, so it doesn't count."""
    on = offered(s)
    return [m for m in ("password", "entra") if on[m]]


def save(db: Db, changes: dict[str, Any], by: Person | None,
         method: str | None = None) -> None:
    """Set each key given (null: back to .env or the default) and commit.
    Refused, with nothing saved, if no admin could sign in afterwards, or if
    it switches off `method`, the way the one saving signed in (so password
    sign-in goes off only from a Microsoft session, which shows Microsoft
    works for an admin)."""
    now = datetime.now(UTC)
    before = _effective(_load(db))
    for key, value in changes.items():
        if key not in KEYS:
            raise KeyError(key)
        if value is None:
            db.execute(delete(Setting).where(Setting.key == key))
        else:
            values = {"key": key, "value": value, "updated_by_id": by.id if by else None,
                      "updated_at": now}
            db.execute(insert(Setting).values(**values).on_conflict_do_update(
                index_elements=["key"],
                set_={k: values[k] for k in ("value", "updated_by_id", "updated_at")}))
    db.flush()
    after = _effective(_load(db))
    if not admin_ways_in(after):
        db.rollback()
        raise Conflict("last_way_in", "Keep email and password or Microsoft sign-in on: it is "
                       "the only way an admin can sign in (a PIN never opens the desktop).")
    if (method in NAMES and getattr(before, f"sign_in_{method}")
            and not getattr(after, f"sign_in_{method}")):
        db.rollback()
        raise Conflict("own_method", f"You signed in with {NAMES[method]}: sign in another way "
                       "before switching it off.")
    db.commit()
    forget()
