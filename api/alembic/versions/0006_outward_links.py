"""outward links: webhooks and their deliveries, API keys, print jobs, events seen

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-16
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _created_at() -> sa.Column:
    return sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
                     nullable=False)


def upgrade() -> None:
    op.create_table(
        "webhook",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("url", sa.String(length=500), nullable=False),
        sa.Column("secret", sa.String(length=100), nullable=False),
        sa.Column("events", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("active", sa.Boolean(), server_default="true", nullable=False),
        _created_at(),
        sa.CheckConstraint("url ~ '^https?://[^[:space:]]+$'", name=op.f("ck_webhook_url")),
        sa.CheckConstraint("jsonb_typeof(events) = 'array' and jsonb_array_length(events) > 0",
                           name=op.f("ck_webhook_events")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_webhook")),
        sa.UniqueConstraint("name", name=op.f("uq_webhook_name")),
    )
    op.create_table(
        "api_key",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("prefix", sa.String(length=16), nullable=False),
        sa.Column("scopes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_by_id", sa.Integer(), nullable=False),
        _created_at(),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("jsonb_typeof(scopes) = 'array' and jsonb_array_length(scopes) > 0",
                           name=op.f("ck_api_key_scopes")),
        sa.ForeignKeyConstraint(["created_by_id"], ["person.id"],
                                name=op.f("fk_api_key_created_by_id_person")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_api_key")),
        sa.UniqueConstraint("key_hash", name=op.f("uq_api_key_key_hash")),
        sa.UniqueConstraint("name", name=op.f("uq_api_key_name")),
    )
    op.create_table(
        "event_seen",
        sa.Column("key", sa.String(length=200), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        _created_at(),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_event_seen")),
        sa.UniqueConstraint("event_id", name=op.f("uq_event_seen_event_id")),
    )

    # the outbox carries events for webhooks and print jobs for Platen too
    op.add_column("outbox", sa.Column("webhook_id", sa.Integer(), nullable=True))
    op.create_foreign_key(op.f("fk_outbox_webhook_id_webhook"), "outbox", "webhook",
                          ["webhook_id"], ["id"])
    op.create_index(op.f("ix_outbox_webhook_id"), "outbox", ["webhook_id"])
    op.drop_constraint(op.f("ck_outbox_kind"), "outbox", type_="check")
    op.create_check_constraint(op.f("ck_outbox_kind"), "outbox",
                               "kind in ('email', 'webhook', 'print')")
    op.create_check_constraint(op.f("ck_outbox_webhook"), "outbox",
                               "(kind = 'webhook') = (webhook_id is not null)")


def downgrade() -> None:
    # the outbox is a queue, not the training record: events and print jobs
    # in it go with the webhooks they were for
    op.execute("delete from outbox where kind <> 'email'")
    op.drop_constraint(op.f("ck_outbox_webhook"), "outbox", type_="check")
    op.drop_constraint(op.f("ck_outbox_kind"), "outbox", type_="check")
    op.create_check_constraint(op.f("ck_outbox_kind"), "outbox", "kind in ('email')")
    op.drop_index(op.f("ix_outbox_webhook_id"), table_name="outbox")
    op.drop_constraint(op.f("fk_outbox_webhook_id_webhook"), "outbox", type_="foreignkey")
    op.drop_column("outbox", "webhook_id")
    op.drop_table("event_seen")
    op.drop_table("api_key")
    op.drop_table("webhook")
