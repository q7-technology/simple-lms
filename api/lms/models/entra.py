from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from lms.models.base import Base


class EntraSignIn(Base):
    """One sign-in with Microsoft under way: sent to Microsoft with a state,
    a nonce and a PKCE challenge, back with a code, then handed to the app
    that started it by a one-time code only that app can use. Kept a day,
    then cleared away: it is not part of the training record."""

    __tablename__ = "entra_sign_in"
    __table_args__ = (
        CheckConstraint("app in ('desktop', 'learner')", name="app"),
        # a hand-off is for someone, and only once Microsoft has sent them back
        CheckConstraint("(person_id is null) = (handoff_hash is null)", name="handoff"),
        CheckConstraint("handoff_hash is null or returned_at is not null", name="returned"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # the state sent to Microsoft, which comes back in the address: its hash only
    state_hash: Mapped[str] = mapped_column(String(64), unique=True)
    # must come back inside the ID token, so a token meant for another sign-in is refused
    nonce: Mapped[str] = mapped_column(String(64))
    # PKCE: sent to Microsoft with the code, proving this API asked for it
    code_verifier: Mapped[str] = mapped_column(String(128))
    # desktop or learner: where the person goes back to
    app: Mapped[str] = mapped_column(String(8))
    # the hash of a secret the app keeps in the tab: only it can finish
    browser_hash: Mapped[str] = mapped_column(String(64))
    # cleared away a day on, by this index
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 server_default=func.now(), index=True)
    returned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    person_id: Mapped[int | None] = mapped_column(ForeignKey("person.id"))
    handoff_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
