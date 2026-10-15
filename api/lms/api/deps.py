from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy.orm import Session as Db

from lms.api.errors import Forbidden, Unauthorised
from lms.db import get_sessionmaker
from lms.models import Person, Session
from lms.services import sessions


def get_db():
    with get_sessionmaker()() as session:
        yield session


DB = Annotated[Db, Depends(get_db)]


@dataclass(slots=True)
class Principal:
    """Whoever is calling: a person with a session, signed in by password or PIN."""

    person: Person
    method: str  # password | pin
    scopes: list[str]
    # the session itself: links to a module's files are made for it
    session: Session

    def has_scope(self, scope: str) -> bool:
        area = scope.split(":")[0]
        return "*" in self.scopes or scope in self.scopes or f"{area}:*" in self.scopes

    @property
    def sees_everyone(self) -> bool:
        return self.has_scope("matrix:read") and self.person.permission in ("manager", "admin")

    def sees(self, other: Person) -> bool:
        """Their own training; their team's (a supervisor); everyone's (a
        manager or admin). A supervisor's team is the people whose supervisor
        they are."""
        if other.id == self.person.id:
            return True
        if not self.has_scope("matrix:read"):
            return False
        return self.sees_everyone or other.supervisor_id == self.person.id


def bearer_token(authorization: str | None) -> str | None:
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    return authorization.split(" ", 1)[1].strip()


def get_principal(db: DB, authorization: Annotated[str | None, Header()] = None) -> Principal:
    raw = bearer_token(authorization)
    if raw is None:
        raise Unauthorised("missing bearer token")
    row = sessions.find(db, raw)
    person = db.get(Person, row.person_id) if row else None
    if row is None or person is None or not person.active:
        raise Unauthorised("session expired or invalid")
    db.commit()  # keeps the touch on last_seen_at
    return Principal(person=person, method=row.method,
                     scopes=sessions.scopes_for(person.permission, row.method), session=row)


Who = Annotated[Principal, Depends(get_principal)]


def require(scope: str):
    """Dependency: the caller must carry this scope."""

    def _check(who: Who) -> Principal:
        if not who.has_scope(scope):
            raise Forbidden(f"you do not have the {scope} scope")
        return who

    return Depends(_check)
