"""policies and tickets: uploads, policy versions, ticket submissions, the outbox

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-13
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _created_at() -> sa.Column:
    return sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
                     nullable=False)


def upgrade() -> None:
    op.add_column("competency", sa.Column("card_expires", sa.Boolean(), nullable=False,
                                          server_default=sa.true()))

    op.create_table(
        "upload",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Integer(), nullable=False),
        sa.Column("purpose", sa.String(length=16), nullable=False),
        sa.Column("content_type", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("path", sa.String(length=200), nullable=False),
        _created_at(),
        sa.CheckConstraint("purpose in ('ticket', 'signature')", name=op.f("ck_upload_purpose")),
        sa.ForeignKeyConstraint(["person_id"], ["person.id"], name=op.f("fk_upload_person_id_person")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_upload")),
    )
    op.create_index(op.f("ix_upload_person_id"), "upload", ["person_id"])

    op.create_table(
        "policy_version",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("competency_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("published_by_id", sa.Integer(), nullable=False),
        _created_at(),
        sa.CheckConstraint("version >= 1", name=op.f("ck_policy_version_version")),
        sa.CheckConstraint("length(trim(body)) > 0", name=op.f("ck_policy_version_body")),
        sa.ForeignKeyConstraint(["competency_id"], ["competency.id"],
                                name=op.f("fk_policy_version_competency_id_competency")),
        sa.ForeignKeyConstraint(["published_by_id"], ["person.id"],
                                name=op.f("fk_policy_version_published_by_id_person")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_policy_version")),
        sa.UniqueConstraint("competency_id", "version",
                            name=op.f("uq_policy_version_competency_id_version")),
    )
    op.create_index(op.f("ix_policy_version_competency_id"), "policy_version", ["competency_id"])

    op.create_table(
        "ticket_submission",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("person_id", sa.Integer(), nullable=False),
        sa.Column("competency_id", sa.Integer(), nullable=False),
        sa.Column("number", sa.String(length=64), nullable=False),
        sa.Column("expires_on", sa.Date(), nullable=True),
        sa.Column("front_upload_id", sa.Uuid(), nullable=False),
        sa.Column("back_upload_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("decided_by_id", sa.Integer(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        _created_at(),
        sa.CheckConstraint("status in ('pending', 'approved', 'rejected')",
                           name=op.f("ck_ticket_submission_status")),
        # a reason when rejected, and only then
        sa.CheckConstraint("case when status = 'rejected' then coalesce(length(trim(reason)), 0) > 0"
                           " else reason is null end",
                           name=op.f("ck_ticket_submission_reason")),
        # pending has no decider and no date; approved and rejected have both
        sa.CheckConstraint("(status = 'pending') = (decided_by_id is null)"
                           " and (status = 'pending') = (decided_at is null)",
                           name=op.f("ck_ticket_submission_decided")),
        sa.CheckConstraint("length(trim(number)) > 0", name=op.f("ck_ticket_submission_number")),
        sa.ForeignKeyConstraint(["person_id"], ["person.id"],
                                name=op.f("fk_ticket_submission_person_id_person")),
        sa.ForeignKeyConstraint(["competency_id"], ["competency.id"],
                                name=op.f("fk_ticket_submission_competency_id_competency")),
        sa.ForeignKeyConstraint(["front_upload_id"], ["upload.id"],
                                name=op.f("fk_ticket_submission_front_upload_id_upload")),
        sa.ForeignKeyConstraint(["back_upload_id"], ["upload.id"],
                                name=op.f("fk_ticket_submission_back_upload_id_upload")),
        sa.ForeignKeyConstraint(["decided_by_id"], ["person.id"],
                                name=op.f("fk_ticket_submission_decided_by_id_person")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ticket_submission")),
    )
    op.create_index(op.f("ix_ticket_submission_person_id"), "ticket_submission", ["person_id"])
    op.create_index(op.f("ix_ticket_submission_competency_id"), "ticket_submission",
                    ["competency_id"])
    op.create_index("uq_ticket_submission_waiting", "ticket_submission",
                    ["person_id", "competency_id"], unique=True,
                    postgresql_where=sa.text("status = 'pending'"))

    op.add_column("competency_record", sa.Column("policy_version_id", sa.Integer(), nullable=True))
    op.add_column("competency_record", sa.Column("signed_name", sa.String(length=120),
                                                 nullable=True))
    op.add_column("competency_record", sa.Column("signature_upload_id", sa.Uuid(), nullable=True))
    op.add_column("competency_record", sa.Column("ticket_submission_id", sa.Integer(),
                                                 nullable=True))
    op.create_foreign_key(op.f("fk_competency_record_policy_version_id_policy_version"),
                          "competency_record", "policy_version", ["policy_version_id"], ["id"])
    op.create_foreign_key(op.f("fk_competency_record_signature_upload_id_upload"),
                          "competency_record", "upload", ["signature_upload_id"], ["id"])
    op.create_foreign_key(op.f("fk_competency_record_ticket_submission_id_ticket_submission"),
                          "competency_record", "ticket_submission", ["ticket_submission_id"],
                          ["id"])
    op.create_unique_constraint(op.f("uq_competency_record_ticket_submission_id"),
                                "competency_record", ["ticket_submission_id"])
    op.create_check_constraint(
        op.f("ck_competency_record_signature"), "competency_record",
        "signature_upload_id is null or (policy_version_id is not null and signed_name is not null)")

    op.create_table(
        "outbox",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("key", sa.String(length=200), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
                  nullable=False),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
        _created_at(),
        sa.CheckConstraint("kind in ('email')", name=op.f("ck_outbox_kind")),
        sa.CheckConstraint("status in ('pending', 'done', 'failed')", name=op.f("ck_outbox_status")),
        # sent, and when: done_at is set exactly when it is done
        sa.CheckConstraint("(status = 'done') = (done_at is not null)", name=op.f("ck_outbox_done_at")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_outbox")),
        sa.UniqueConstraint("key", name=op.f("uq_outbox_key")),
    )
    op.create_index("ix_outbox_due", "outbox", ["status", "next_attempt_at"])

    # A policy's text never changes under the people who signed it.
    op.execute("create trigger policy_version_append_only before update or delete "
               "on policy_version for each row execute function block_change()")
    # A ticket is decided once: pending to approved or rejected, and nothing
    # else ever changes. Never deleted.
    op.execute("""
        create or replace function decide_once() returns trigger
        language plpgsql as $$
        begin
            if tg_op = 'DELETE' then
                raise exception '% rows cannot be deleted', tg_table_name
                    using errcode = 'restrict_violation';
            end if;
            if old.status <> 'pending' or new.status = 'pending'
               or (new.id, new.person_id, new.competency_id, new.number, new.expires_on,
                   new.front_upload_id, new.back_upload_id, new.created_at)
                  is distinct from
                  (old.id, old.person_id, old.competency_id, old.number, old.expires_on,
                   old.front_upload_id, old.back_upload_id, old.created_at) then
                raise exception '% is decided once: only a pending ticket is approved or rejected',
                    tg_table_name using errcode = 'restrict_violation';
            end if;
            return new;
        end
        $$
    """)
    op.execute("create trigger ticket_submission_decide_once before update or delete "
               "on ticket_submission for each row execute function decide_once()")


def downgrade() -> None:
    op.execute("drop trigger if exists ticket_submission_decide_once on ticket_submission")
    op.execute("drop function if exists decide_once()")
    op.execute("drop trigger if exists policy_version_append_only on policy_version")
    op.drop_index("ix_outbox_due", table_name="outbox")
    op.drop_table("outbox")
    op.drop_constraint(op.f("ck_competency_record_signature"), "competency_record", type_="check")
    op.drop_constraint(op.f("uq_competency_record_ticket_submission_id"), "competency_record",
                       type_="unique")
    op.drop_constraint(op.f("fk_competency_record_ticket_submission_id_ticket_submission"),
                       "competency_record", type_="foreignkey")
    op.drop_constraint(op.f("fk_competency_record_signature_upload_id_upload"),
                       "competency_record", type_="foreignkey")
    op.drop_constraint(op.f("fk_competency_record_policy_version_id_policy_version"),
                       "competency_record", type_="foreignkey")
    for column in ("ticket_submission_id", "signature_upload_id", "signed_name",
                   "policy_version_id"):
        op.drop_column("competency_record", column)
    op.drop_index("uq_ticket_submission_waiting", table_name="ticket_submission")
    op.drop_index(op.f("ix_ticket_submission_competency_id"), table_name="ticket_submission")
    op.drop_index(op.f("ix_ticket_submission_person_id"), table_name="ticket_submission")
    op.drop_table("ticket_submission")
    op.drop_index(op.f("ix_policy_version_competency_id"), table_name="policy_version")
    op.drop_table("policy_version")
    op.drop_index(op.f("ix_upload_person_id"), table_name="upload")
    op.drop_table("upload")
    op.drop_column("competency", "card_expires")
