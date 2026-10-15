"""practicals: checklist versions and their items, sign-offs and what they ticked

Revision ID: 0004
Revises: 0003b
Create Date: 2026-10-16
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PURPOSES_BEFORE = "purpose in ('ticket', 'signature', 'page-image', 'page-pdf', 'page-video')"
PURPOSES_NOW = ("purpose in ('ticket', 'signature', 'page-image', 'page-pdf', 'page-video', "
                "'signoff-photo')")
APPEND_ONLY = ("practical_version", "practical_item", "signoff", "signoff_item")
# a row written with its parent, in the same transaction, and never after
WRITTEN_WITH = {"practical_item": ("practical_version", "practical_version_id", "version"),
                "signoff_item": ("signoff", "signoff_id", "signoff")}


def _created_at() -> sa.Column:
    return sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
                     nullable=False)


def upgrade() -> None:
    # a sign-off's photo is a file sent like any other
    op.drop_constraint(op.f("ck_upload_purpose"), "upload", type_="check")
    op.create_check_constraint(op.f("ck_upload_purpose"), "upload", PURPOSES_NOW)

    op.create_table(
        "practical_version",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("competency_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("published_by_id", sa.Integer(), nullable=False),
        _created_at(),
        sa.CheckConstraint("version >= 1", name=op.f("ck_practical_version_version")),
        sa.ForeignKeyConstraint(["competency_id"], ["competency.id"],
                                name=op.f("fk_practical_version_competency_id_competency")),
        sa.ForeignKeyConstraint(["published_by_id"], ["person.id"],
                                name=op.f("fk_practical_version_published_by_id_person")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_practical_version")),
        sa.UniqueConstraint("competency_id", "version",
                            name=op.f("uq_practical_version_competency_id_version")),
        # what a sign-off names as its practical and version agree
        sa.UniqueConstraint("id", "competency_id",
                            name=op.f("uq_practical_version_id_competency_id")),
    )
    op.create_index(op.f("ix_practical_version_competency_id"), "practical_version",
                    ["competency_id"])

    op.create_table(
        "practical_item",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("practical_version_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("text", sa.String(length=300), nullable=False),
        sa.CheckConstraint("position >= 0", name=op.f("ck_practical_item_position")),
        sa.CheckConstraint("length(trim(text)) > 0", name=op.f("ck_practical_item_text")),
        sa.ForeignKeyConstraint(["practical_version_id"], ["practical_version.id"],
                                name=op.f("fk_practical_item_practical_version_id_practical_version")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_practical_item")),
        sa.UniqueConstraint("practical_version_id", "position",
                            name=op.f("uq_practical_item_practical_version_id_position")),
        # what a ticked item names as its version agrees
        sa.UniqueConstraint("id", "practical_version_id",
                            name=op.f("uq_practical_item_id_practical_version_id")),
    )
    op.create_index(op.f("ix_practical_item_practical_version_id"), "practical_item",
                    ["practical_version_id"])

    op.create_table(
        "signoff",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("person_id", sa.Integer(), nullable=False),
        sa.Column("competency_id", sa.Integer(), nullable=False),
        sa.Column("practical_version_id", sa.Integer(), nullable=False),
        sa.Column("supervisor_id", sa.Integer(), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("photo_upload_id", sa.Uuid(), nullable=True),
        sa.Column("supervisor_signature_upload_id", sa.Uuid(), nullable=False),
        sa.Column("learner_signature_upload_id", sa.Uuid(), nullable=False),
        _created_at(),
        # nobody signs off their own practical
        sa.CheckConstraint("supervisor_id <> person_id", name=op.f("ck_signoff_not_own")),
        sa.CheckConstraint("supervisor_signature_upload_id <> learner_signature_upload_id",
                           name=op.f("ck_signoff_two_signatures")),
        sa.CheckConstraint("note is null or length(trim(note)) > 0",
                           name=op.f("ck_signoff_note")),
        sa.ForeignKeyConstraint(["person_id"], ["person.id"],
                                name=op.f("fk_signoff_person_id_person")),
        sa.ForeignKeyConstraint(["competency_id"], ["competency.id"],
                                name=op.f("fk_signoff_competency_id_competency")),
        # a version of this practical
        sa.ForeignKeyConstraint(["practical_version_id", "competency_id"],
                                ["practical_version.id", "practical_version.competency_id"],
                                name=op.f("fk_signoff_practical_version_id_practical_version")),
        sa.ForeignKeyConstraint(["supervisor_id"], ["person.id"],
                                name=op.f("fk_signoff_supervisor_id_person")),
        sa.ForeignKeyConstraint(["photo_upload_id"], ["upload.id"],
                                name=op.f("fk_signoff_photo_upload_id_upload")),
        sa.ForeignKeyConstraint(["supervisor_signature_upload_id"], ["upload.id"],
                                name=op.f("fk_signoff_supervisor_signature_upload_id_upload")),
        sa.ForeignKeyConstraint(["learner_signature_upload_id"], ["upload.id"],
                                name=op.f("fk_signoff_learner_signature_upload_id_upload")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_signoff")),
        # what a ticked item names as its sign-off's version agrees
        sa.UniqueConstraint("id", "practical_version_id",
                            name=op.f("uq_signoff_id_practical_version_id")),
    )
    op.create_index(op.f("ix_signoff_person_id"), "signoff", ["person_id"])
    op.create_index(op.f("ix_signoff_competency_id"), "signoff", ["competency_id"])
    # a photo or a signature goes on one sign-off only
    op.create_index("uq_signoff_photo_upload_id", "signoff", ["photo_upload_id"], unique=True,
                    postgresql_where=sa.text("photo_upload_id is not null"))
    op.create_index("uq_signoff_supervisor_signature_upload_id", "signoff",
                    ["supervisor_signature_upload_id"], unique=True)
    op.create_index("uq_signoff_learner_signature_upload_id", "signoff",
                    ["learner_signature_upload_id"], unique=True)

    op.create_table(
        "signoff_item",
        sa.Column("signoff_id", sa.Integer(), nullable=False),
        sa.Column("practical_item_id", sa.Integer(), nullable=False),
        sa.Column("practical_version_id", sa.Integer(), nullable=False),
        # an item of the version the sign-off is for, and of no other
        sa.ForeignKeyConstraint(["signoff_id", "practical_version_id"],
                                ["signoff.id", "signoff.practical_version_id"],
                                name=op.f("fk_signoff_item_signoff_id_signoff")),
        sa.ForeignKeyConstraint(["practical_item_id", "practical_version_id"],
                                ["practical_item.id", "practical_item.practical_version_id"],
                                name=op.f("fk_signoff_item_practical_item_id_practical_item")),
        sa.PrimaryKeyConstraint("signoff_id", "practical_item_id", name=op.f("pk_signoff_item")),
    )

    op.add_column("competency_record", sa.Column("signoff_id", sa.Integer(), nullable=True))
    op.create_foreign_key(op.f("fk_competency_record_signoff_id_signoff"),
                          "competency_record", "signoff", ["signoff_id"], ["id"])
    op.create_unique_constraint(op.f("uq_competency_record_signoff_id"),
                                "competency_record", ["signoff_id"])
    op.create_check_constraint(op.f("ck_competency_record_signoff_grant"), "competency_record",
                               "signoff_id is null or kind = 'granted'")

    # What a supervisor ticked, and the checklist they ticked it on, are
    # kept as they were (rule 1).
    for table in APPEND_ONLY:
        op.execute(f"create trigger {table}_append_only before update or delete "
                   f"on {table} for each row execute function block_change()")
    # An item is written in the transaction that wrote its parent (a
    # version, a sign-off), and never added to it after: the parent's
    # created_at is that transaction's now().
    op.execute("""
        create or replace function written_with() returns trigger
        language plpgsql as $$
        declare
            fresh boolean;
        begin
            execute format('select created_at = now() from %I where id = $1', tg_argv[0])
                into fresh using (to_jsonb(new) ->> tg_argv[1])::int;
            if fresh is not true then
                raise exception '% rows are written with their %, never after',
                    tg_table_name, tg_argv[0] using errcode = 'restrict_violation';
            end if;
            return new;
        end
        $$
    """)
    for table, (parent, column, name) in WRITTEN_WITH.items():
        op.execute(f"create trigger {table}_written_with_{name} before insert on {table} "
                   f"for each row execute function written_with('{parent}', '{column}')")
    # A grant from a sign-off is that person's, for that practical, and
    # recorded by the supervisor who signed it off. Sign-offs never change,
    # so there is nothing to wait for.
    op.execute("""
        create or replace function signoff_grant() returns trigger
        language plpgsql as $$
        begin
            if new.signoff_id is not null and not exists (
                select 1 from signoff s
                where s.id = new.signoff_id and s.person_id = new.person_id
                  and s.competency_id = new.competency_id
                  and s.supervisor_id = new.recorded_by_id) then
                raise exception '% needs a sign-off of the same person, for the same '
                    'competency, by whoever records it', tg_table_name
                    using errcode = 'restrict_violation';
            end if;
            return new;
        end
        $$
    """)
    op.execute("create trigger competency_record_signoff before insert "
               "on competency_record for each row execute function signoff_grant()")


def downgrade() -> None:
    # before 0004 there are no sign-off photos: with them kept, going back
    # is refused rather than losing them
    op.execute("""
        do $$
        begin
            if exists (select 1 from upload where purpose = 'signoff-photo') then
                raise exception 'sign-off photos are kept: remove them by hand before going '
                    'back past 0004';
            end if;
        end
        $$
    """)
    op.execute("drop trigger if exists competency_record_signoff on competency_record")
    op.execute("drop function if exists signoff_grant()")
    for table, (parent, column, name) in WRITTEN_WITH.items():
        op.execute(f"drop trigger if exists {table}_written_with_{name} on {table}")
    op.execute("drop function if exists written_with()")
    for table in APPEND_ONLY:
        op.execute(f"drop trigger if exists {table}_append_only on {table}")
    op.drop_constraint(op.f("ck_competency_record_signoff_grant"), "competency_record",
                       type_="check")
    op.drop_constraint(op.f("uq_competency_record_signoff_id"), "competency_record",
                       type_="unique")
    op.drop_constraint(op.f("fk_competency_record_signoff_id_signoff"), "competency_record",
                       type_="foreignkey")
    op.drop_column("competency_record", "signoff_id")
    op.drop_table("signoff_item")
    op.drop_index("uq_signoff_learner_signature_upload_id", table_name="signoff")
    op.drop_index("uq_signoff_supervisor_signature_upload_id", table_name="signoff")
    op.drop_index("uq_signoff_photo_upload_id", table_name="signoff")
    op.drop_index(op.f("ix_signoff_competency_id"), table_name="signoff")
    op.drop_index(op.f("ix_signoff_person_id"), table_name="signoff")
    op.drop_table("signoff")
    op.drop_index(op.f("ix_practical_item_practical_version_id"), table_name="practical_item")
    op.drop_table("practical_item")
    op.drop_index(op.f("ix_practical_version_competency_id"), table_name="practical_version")
    op.drop_table("practical_version")
    op.drop_constraint(op.f("ck_upload_purpose"), "upload", type_="check")
    op.create_check_constraint(op.f("ck_upload_purpose"), "upload", PURPOSES_BEFORE)
