"""skeleton: people, sessions, roles, competencies, overrides, the training record

Revision ID: 0001
Revises:
Create Date: 2026-10-12
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

APPEND_ONLY = ("competency_record", "person_override")


def _created_at() -> sa.Column:
    return sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
                     nullable=False)


def upgrade() -> None:
    op.create_table(
        "person",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=True),
        sa.Column("entra_oid", sa.String(length=64), nullable=True),
        sa.Column("permission", sa.String(length=16), nullable=False),
        sa.Column("supervisor_id", sa.Integer(), nullable=True),
        sa.Column("pin_hash", sa.String(length=200), nullable=True),
        sa.Column("pin_failed_attempts", sa.Integer(), nullable=False),
        sa.Column("pin_locked", sa.Boolean(), nullable=False),
        sa.Column("password_hash", sa.String(length=200), nullable=True),
        sa.Column("password_failed_attempts", sa.Integer(), nullable=False),
        sa.Column("password_locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        _created_at(),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("code = upper(code)", name=op.f("ck_person_code_upper")),
        sa.CheckConstraint("email = lower(email)", name=op.f("ck_person_email_lower")),
        sa.CheckConstraint("permission in ('learner', 'supervisor', 'manager', 'admin')",
                           name=op.f("ck_person_permission")),
        sa.CheckConstraint("supervisor_id <> id", name=op.f("ck_person_not_own_supervisor")),
        sa.ForeignKeyConstraint(["supervisor_id"], ["person.id"],
                                name=op.f("fk_person_supervisor_id_person")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_person")),
        sa.UniqueConstraint("code", name=op.f("uq_person_code")),
        sa.UniqueConstraint("email", name=op.f("uq_person_email")),
        sa.UniqueConstraint("entra_oid", name=op.f("uq_person_entra_oid")),
    )
    op.create_index(op.f("ix_person_supervisor_id"), "person", ["supervisor_id"])
    op.create_table(
        "session",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("person_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("method", sa.String(length=8), nullable=False),
        _created_at(),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("method in ('password', 'pin')", name=op.f("ck_session_method")),
        sa.ForeignKeyConstraint(["person_id"], ["person.id"],
                                name=op.f("fk_session_person_id_person")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_session")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_session_token_hash")),
    )
    op.create_index(op.f("ix_session_person_id"), "session", ["person_id"])
    op.create_table(
        "role",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        _created_at(),
        sa.CheckConstraint("key = lower(key)", name=op.f("ck_role_key_lower")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_role")),
        sa.UniqueConstraint("key", name=op.f("uq_role_key")),
    )
    op.create_table(
        "competency",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("refresher_months", sa.Integer(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        _created_at(),
        sa.CheckConstraint("key = lower(key)", name=op.f("ck_competency_key_lower")),
        sa.CheckConstraint("kind in ('module', 'practical', 'ticket', 'policy')",
                           name=op.f("ck_competency_kind")),
        sa.CheckConstraint("refresher_months between 1 and 240",
                           name=op.f("ck_competency_refresher_months")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_competency")),
        sa.UniqueConstraint("key", name=op.f("uq_competency_key")),
    )
    op.create_table(
        "person_role",
        sa.Column("person_id", sa.Integer(), nullable=False),
        sa.Column("role_id", sa.Integer(), nullable=False),
        _created_at(),
        sa.ForeignKeyConstraint(["person_id"], ["person.id"],
                                name=op.f("fk_person_role_person_id_person")),
        sa.ForeignKeyConstraint(["role_id"], ["role.id"], name=op.f("fk_person_role_role_id_role")),
        sa.PrimaryKeyConstraint("person_id", "role_id", name=op.f("pk_person_role")),
    )
    op.create_index(op.f("ix_person_role_role_id"), "person_role", ["role_id"])
    op.create_table(
        "role_requirement",
        sa.Column("role_id", sa.Integer(), nullable=False),
        sa.Column("competency_id", sa.Integer(), nullable=False),
        _created_at(),
        sa.ForeignKeyConstraint(["role_id"], ["role.id"],
                                name=op.f("fk_role_requirement_role_id_role")),
        sa.ForeignKeyConstraint(["competency_id"], ["competency.id"],
                                name=op.f("fk_role_requirement_competency_id_competency")),
        sa.PrimaryKeyConstraint("role_id", "competency_id", name=op.f("pk_role_requirement")),
    )
    op.create_index(op.f("ix_role_requirement_competency_id"), "role_requirement",
                    ["competency_id"])
    op.create_table(
        "person_override",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("person_id", sa.Integer(), nullable=False),
        sa.Column("competency_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=False),
        sa.Column("recorded_by_id", sa.Integer(), nullable=False),
        _created_at(),
        sa.CheckConstraint("kind in ('extra', 'waive', 'clear')",
                           name=op.f("ck_person_override_kind")),
        sa.CheckConstraint("length(trim(note)) > 0", name=op.f("ck_person_override_note")),
        sa.ForeignKeyConstraint(["person_id"], ["person.id"],
                                name=op.f("fk_person_override_person_id_person")),
        sa.ForeignKeyConstraint(["competency_id"], ["competency.id"],
                                name=op.f("fk_person_override_competency_id_competency")),
        sa.ForeignKeyConstraint(["recorded_by_id"], ["person.id"],
                                name=op.f("fk_person_override_recorded_by_id_person")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_person_override")),
    )
    op.create_index(op.f("ix_person_override_person_id"), "person_override", ["person_id"])
    op.create_index(op.f("ix_person_override_competency_id"), "person_override",
                    ["competency_id"])
    op.create_table(
        "competency_record",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("person_id", sa.Integer(), nullable=False),
        sa.Column("competency_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("granted_on", sa.Date(), nullable=True),
        sa.Column("expires_on", sa.Date(), nullable=True),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("recorded_by_id", sa.Integer(), nullable=False),
        _created_at(),
        sa.CheckConstraint("kind in ('granted', 'revoked')", name=op.f("ck_competency_record_kind")),
        sa.CheckConstraint("kind = 'revoked' or granted_on is not null",
                           name=op.f("ck_competency_record_granted_on")),
        sa.CheckConstraint("kind = 'granted' or length(trim(note)) > 0",
                           name=op.f("ck_competency_record_revoke_note")),
        sa.CheckConstraint("expires_on > granted_on",
                           name=op.f("ck_competency_record_expires_after_granted")),
        sa.ForeignKeyConstraint(["person_id"], ["person.id"],
                                name=op.f("fk_competency_record_person_id_person")),
        sa.ForeignKeyConstraint(["competency_id"], ["competency.id"],
                                name=op.f("fk_competency_record_competency_id_competency")),
        sa.ForeignKeyConstraint(["recorded_by_id"], ["person.id"],
                                name=op.f("fk_competency_record_recorded_by_id_person")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_competency_record")),
    )
    op.create_index(op.f("ix_competency_record_person_id"), "competency_record", ["person_id"])
    op.create_index(op.f("ix_competency_record_competency_id"), "competency_record",
                    ["competency_id"])

    # The training record and the overrides are append-only. A mistake is
    # put right by a new row.
    op.execute("""
        create or replace function block_change() returns trigger
        language plpgsql as $$
        begin
            raise exception '% is append-only: rows cannot be updated or deleted', tg_table_name
                using errcode = 'restrict_violation';
        end
        $$
    """)
    for table in APPEND_ONLY:
        op.execute(f"create trigger {table}_append_only before update or delete "
                   f"on {table} for each row execute function block_change()")


def downgrade() -> None:
    for table in APPEND_ONLY:
        op.execute(f"drop trigger if exists {table}_append_only on {table}")
    op.execute("drop function if exists block_change()")
    op.drop_index(op.f("ix_competency_record_competency_id"), table_name="competency_record")
    op.drop_index(op.f("ix_competency_record_person_id"), table_name="competency_record")
    op.drop_table("competency_record")
    op.drop_index(op.f("ix_person_override_competency_id"), table_name="person_override")
    op.drop_index(op.f("ix_person_override_person_id"), table_name="person_override")
    op.drop_table("person_override")
    op.drop_index(op.f("ix_role_requirement_competency_id"), table_name="role_requirement")
    op.drop_table("role_requirement")
    op.drop_index(op.f("ix_person_role_role_id"), table_name="person_role")
    op.drop_table("person_role")
    op.drop_table("competency")
    op.drop_table("role")
    op.drop_index(op.f("ix_session_person_id"), table_name="session")
    op.drop_table("session")
    op.drop_index(op.f("ix_person_supervisor_id"), table_name="person")
    op.drop_table("person")
