"""Command line for what has to happen before anyone can sign in."""
from __future__ import annotations

import argparse
import getpass
import sys

from sqlalchemy import or_, select

from lms.api.schemas import normal_code
from lms.db import get_sessionmaker
from lms.models import PERMISSIONS, Person
from lms.services import access


def cmd_create_user(args) -> int:
    code, email = normal_code(args.code), args.email.strip().lower()
    password = args.password or getpass.getpass("Password: ")
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

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
