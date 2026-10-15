"""entra: Microsoft sign-ins under way, and sessions signed in with Microsoft

Revision ID: 0005
Revises: 0003b
Create Date: 2026-10-16
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0003b"  # becomes "0004" when merged after step 4
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

METHODS_BEFORE = "method in ('password', 'pin')"
METHODS_NOW = "method in ('password', 'pin', 'entra')"


def upgrade() -> None:
    # a session signed in with Microsoft
    op.drop_constraint(op.f("ck_session_method"), "session", type_="check")
    op.create_check_constraint(op.f("ck_session_method"), "session", METHODS_NOW)

    op.create_table(
        "entra_sign_in",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("state_hash", sa.String(length=64), nullable=False),
        sa.Column("nonce", sa.String(length=64), nullable=False),
        sa.Column("code_verifier", sa.String(length=128), nullable=False),
        sa.Column("app", sa.String(length=8), nullable=False),
        sa.Column("browser_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
                  nullable=False),
        sa.Column("returned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("person_id", sa.Integer(), nullable=True),
        sa.Column("handoff_hash", sa.String(length=64), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        # who asked (their address), so one address can't start too many at once
        sa.Column("client", sa.String(length=64), nullable=True),
        sa.CheckConstraint("app in ('desktop', 'learner')", name=op.f("ck_entra_sign_in_app")),
        # a hand-off is for someone, and only once Microsoft has sent them back
        sa.CheckConstraint("(person_id is null) = (handoff_hash is null)",
                           name=op.f("ck_entra_sign_in_handoff")),
        sa.CheckConstraint("handoff_hash is null or returned_at is not null",
                           name=op.f("ck_entra_sign_in_returned")),
        sa.ForeignKeyConstraint(["person_id"], ["person.id"],
                                name=op.f("fk_entra_sign_in_person_id_person")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_entra_sign_in")),
        sa.UniqueConstraint("state_hash", name=op.f("uq_entra_sign_in_state_hash")),
        sa.UniqueConstraint("handoff_hash", name=op.f("uq_entra_sign_in_handoff_hash")),
    )
    op.create_index(op.f("ix_entra_sign_in_created_at"), "entra_sign_in", ["created_at"])
    op.create_index(op.f("ix_entra_sign_in_client"), "entra_sign_in", ["client", "created_at"])


def downgrade() -> None:
    op.drop_index(op.f("ix_entra_sign_in_client"), table_name="entra_sign_in")
    op.drop_index(op.f("ix_entra_sign_in_created_at"), table_name="entra_sign_in")
    op.drop_table("entra_sign_in")
    # before 0005 there is no such thing as an entra session: end them first
    op.execute("delete from session where method = 'entra'")
    op.drop_constraint(op.f("ck_session_method"), "session", type_="check")
    op.create_check_constraint(op.f("ck_session_method"), "session", METHODS_BEFORE)
