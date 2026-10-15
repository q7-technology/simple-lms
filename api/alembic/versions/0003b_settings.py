"""settings: what an admin changes on the Settings screen

Revision ID: 0003b
Revises: 0003
Create Date: 2026-10-16
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003b"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "setting",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("updated_by_id", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
                  nullable=False),
        sa.ForeignKeyConstraint(["updated_by_id"], ["person.id"],
                                name=op.f("fk_setting_updated_by_id_person")),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_setting")),
    )


def downgrade() -> None:
    op.drop_table("setting")
