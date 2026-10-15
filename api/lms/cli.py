"""Command line for what has to happen before anyone can sign in."""
from __future__ import annotations

import argparse
import getpass
import sys
from datetime import date

from sqlalchemy import or_, select

from lms.api.schemas import normal_code
from lms.db import get_sessionmaker
from lms.models import PERMISSIONS, Person
from lms.services import access, clock, daily, settings


def cmd_create_user(args) -> int:
    code, email = normal_code(args.code), args.email.strip().lower()
    password = args.password
    if not password:
        password = getpass.getpass("Password: ")
        if getpass.getpass("Password again: ") != password:
            print("create-user: the passwords don't match", file=sys.stderr)
            return 1
    if len(password) < access.MIN_PASSWORD:
        print(f"create-user: the password needs at least {access.MIN_PASSWORD} characters",
              file=sys.stderr)
        return 1
    with get_sessionmaker()() as db:
        taken = db.execute(select(Person).where(
            or_(Person.code == code, Person.email == email))).scalars().first()
        if taken:
            print(f"create-user: {taken.code} <{taken.email}> already exists", file=sys.stderr)
            return 1
        person = Person(code=code, name=args.name, email=email, permission=args.permission,
                        password_hash=access.hash_password(password), pin_failed_attempts=0,
                        pin_locked=False, password_failed_attempts=0, active=True)
        db.add(person)
        db.commit()
        print(f"{person.code} {person.name} <{person.email}> created as {person.permission}")
    return 0


def _day(text: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a date: write it as YYYY-MM-DD") from None


def cmd_daily_job(args) -> int:
    """What the worker does each morning, now. Safe to run again: nothing
    already queued is queued twice."""
    day = args.on or clock.today()
    with get_sessionmaker()() as db:
        queued = daily.run(db, day)
    print(f"{day.isoformat()}: {queued['reminders']} reminders and {queued['digests']} digests "
          "queued; the worker sends them")
    return 0


def cmd_clear_setting(args) -> int:
    """Put a setting back to .env or the default, whatever Settings says:
    the way back in if a setting ever keeps everyone out."""
    if args.key not in settings.KEYS:
        print(f"clear-setting: no setting {args.key!r}; one of {', '.join(settings.KEYS)}",
              file=sys.stderr)
        return 1
    with get_sessionmaker()() as db:
        settings.save(db, {args.key: None}, None)
    print(f"{args.key} cleared: it comes from .env or the default now")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lms")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("create-user", help="add a person who signs in with an email and password")
    p.add_argument("--code", required=True, help="their person code, e.g. LL001")
    p.add_argument("--name", required=True)
    p.add_argument("--email", required=True)
    p.add_argument("--permission", default="admin", choices=list(PERMISSIONS))
    p.add_argument("--password", help="prompted for if omitted")
    p.set_defaults(func=cmd_create_user)

    p = sub.add_parser("daily-job", help="queue the reminders (and on a Monday the digests) now")
    p.add_argument("--on", type=_day, help="as if today were this date, YYYY-MM-DD (to try it out)")
    p.set_defaults(func=cmd_daily_job)

    p = sub.add_parser("clear-setting",
                       help="put a setting back to .env or the default, e.g. sign_in_pin")
    p.add_argument("key")
    p.set_defaults(func=cmd_clear_setting)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
