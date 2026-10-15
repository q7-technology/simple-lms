"""modules: versions of pages and a quiz, attempts, progress, page files

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-15
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PURPOSES_BEFORE = "purpose in ('ticket', 'signature')"
PURPOSES_NOW = "purpose in ('ticket', 'signature', 'page-image', 'page-pdf', 'page-video')"
DRAFT_ONLY = ("module_page", "quiz_question")


def _created_at() -> sa.Column:
    return sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
                     nullable=False)


def upgrade() -> None:
    # a module page's picture, PDF or video is a file sent like any other
    op.drop_constraint(op.f("ck_upload_purpose"), "upload", type_="check")
    op.create_check_constraint(op.f("ck_upload_purpose"), "upload", PURPOSES_NOW)

    op.create_table(
        "module_version",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("competency_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("pass_mark", sa.Integer(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_by_id", sa.Integer(), nullable=True),
        _created_at(),
        sa.CheckConstraint("version >= 1", name=op.f("ck_module_version_version")),
        sa.CheckConstraint("pass_mark between 1 and 100", name=op.f("ck_module_version_pass_mark")),
        # published, by whom and when, or neither
        sa.CheckConstraint("(published_at is null) = (published_by_id is null)",
                           name=op.f("ck_module_version_published")),
        sa.ForeignKeyConstraint(["competency_id"], ["competency.id"],
                                name=op.f("fk_module_version_competency_id_competency")),
        sa.ForeignKeyConstraint(["published_by_id"], ["person.id"],
                                name=op.f("fk_module_version_published_by_id_person")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_module_version")),
        sa.UniqueConstraint("competency_id", "version",
                            name=op.f("uq_module_version_competency_id_version")),
        # what an attempt or progress names as its module and version agree
        sa.UniqueConstraint("id", "competency_id", name=op.f("uq_module_version_id_competency_id")),
    )
    op.create_index(op.f("ix_module_version_competency_id"), "module_version", ["competency_id"])
    # one draft at a time for a module
    op.create_index("uq_module_version_draft", "module_version", ["competency_id"], unique=True,
                    postgresql_where=sa.text("published_at is null"))

    op.create_table(
        "module_page",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("module_version_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("upload_id", sa.Uuid(), nullable=True),
        sa.Column("url", sa.String(length=2000), nullable=True),
        sa.CheckConstraint("kind in ('text', 'image', 'pdf', 'video', 'link')",
                           name=op.f("ck_module_page_kind")),
        sa.CheckConstraint("position >= 0", name=op.f("ck_module_page_position")),
        sa.CheckConstraint("length(trim(title)) > 0", name=op.f("ck_module_page_title")),
        # a text page has its text; the others may have a line or two under them
        sa.CheckConstraint("kind <> 'text' or coalesce(length(trim(body)), 0) > 0",
                           name=op.f("ck_module_page_body")),
        # a picture, a PDF and a video are a file; a link is a web address
        sa.CheckConstraint("(kind in ('image', 'pdf', 'video')) = (upload_id is not null)",
                           name=op.f("ck_module_page_file")),
        sa.CheckConstraint("(kind = 'link') = (url is not null)", name=op.f("ck_module_page_url")),
        sa.ForeignKeyConstraint(["module_version_id"], ["module_version.id"],
                                name=op.f("fk_module_page_module_version_id_module_version")),
        sa.ForeignKeyConstraint(["upload_id"], ["upload.id"],
                                name=op.f("fk_module_page_upload_id_upload")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_module_page")),
        sa.UniqueConstraint("module_version_id", "position",
                            name=op.f("uq_module_page_module_version_id_position")),
    )
    op.create_index(op.f("ix_module_page_module_version_id"), "module_page", ["module_version_id"])
    op.create_index(op.f("ix_module_page_upload_id"), "module_page", ["upload_id"])

    op.create_table(
        "quiz_question",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("module_version_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("prompt", sa.String(length=500), nullable=False),
        sa.Column("options", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("correct", sa.Integer(), nullable=False),
        sa.CheckConstraint("position >= 0", name=op.f("ck_quiz_question_position")),
        sa.CheckConstraint("length(trim(prompt)) > 0", name=op.f("ck_quiz_question_prompt")),
        sa.CheckConstraint("jsonb_typeof(options) = 'array' and jsonb_array_length(options) "
                           "between 2 and 6", name=op.f("ck_quiz_question_options")),
        sa.CheckConstraint("correct >= 0 and correct < jsonb_array_length(options)",
                           name=op.f("ck_quiz_question_correct")),
        sa.ForeignKeyConstraint(["module_version_id"], ["module_version.id"],
                                name=op.f("fk_quiz_question_module_version_id_module_version")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_quiz_question")),
        sa.UniqueConstraint("module_version_id", "position",
                            name=op.f("uq_quiz_question_module_version_id_position")),
    )
    op.create_index(op.f("ix_quiz_question_module_version_id"), "quiz_question",
                    ["module_version_id"])

    op.create_table(
        "quiz_attempt",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("person_id", sa.Integer(), nullable=False),
        sa.Column("competency_id", sa.Integer(), nullable=False),
        sa.Column("module_version_id", sa.Integer(), nullable=False),
        sa.Column("answers", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("correct", sa.Integer(), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        _created_at(),
        sa.CheckConstraint("total >= 1 and correct between 0 and total",
                           name=op.f("ck_quiz_attempt_counts")),
        sa.CheckConstraint("score between 0 and 100", name=op.f("ck_quiz_attempt_score")),
        sa.CheckConstraint("jsonb_typeof(answers) = 'array'", name=op.f("ck_quiz_attempt_answers")),
        sa.ForeignKeyConstraint(["person_id"], ["person.id"],
                                name=op.f("fk_quiz_attempt_person_id_person")),
        sa.ForeignKeyConstraint(["competency_id"], ["competency.id"],
                                name=op.f("fk_quiz_attempt_competency_id_competency")),
        sa.ForeignKeyConstraint(["module_version_id", "competency_id"],
                                ["module_version.id", "module_version.competency_id"],
                                name=op.f("fk_quiz_attempt_module_version_id_module_version")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_quiz_attempt")),
    )
    op.create_index(op.f("ix_quiz_attempt_person_id"), "quiz_attempt", ["person_id"])
    op.create_index(op.f("ix_quiz_attempt_competency_id"), "quiz_attempt", ["competency_id"])

    op.create_table(
        "module_progress",
        sa.Column("person_id", sa.Integer(), nullable=False),
        sa.Column("competency_id", sa.Integer(), nullable=False),
        sa.Column("module_version_id", sa.Integer(), nullable=False),
        sa.Column("page", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
                  nullable=False),
        sa.CheckConstraint("page >= 0", name=op.f("ck_module_progress_page")),
        sa.ForeignKeyConstraint(["person_id"], ["person.id"],
                                name=op.f("fk_module_progress_person_id_person")),
        sa.ForeignKeyConstraint(["competency_id"], ["competency.id"],
                                name=op.f("fk_module_progress_competency_id_competency")),
        sa.ForeignKeyConstraint(["module_version_id", "competency_id"],
                                ["module_version.id", "module_version.competency_id"],
                                name=op.f("fk_module_progress_module_version_id_module_version")),
        sa.PrimaryKeyConstraint("person_id", "competency_id", name=op.f("pk_module_progress")),
    )

    op.add_column("competency_record", sa.Column("quiz_attempt_id", sa.Integer(), nullable=True))
    op.create_foreign_key(op.f("fk_competency_record_quiz_attempt_id_quiz_attempt"),
                          "competency_record", "quiz_attempt", ["quiz_attempt_id"], ["id"])
    op.create_unique_constraint(op.f("uq_competency_record_quiz_attempt_id"),
                                "competency_record", ["quiz_attempt_id"])
    op.create_check_constraint(op.f("ck_competency_record_quiz_grant"), "competency_record",
                               "quiz_attempt_id is null or kind = 'granted'")

    # Every attempt is kept as it was (rule 1).
    op.execute("create trigger quiz_attempt_append_only before update or delete "
               "on quiz_attempt for each row execute function block_change()")
    # A draft is edited freely; publishing it is the last change it ever
    # gets, so an attempt always means what was asked. Never deleted.
    op.execute("""
        create or replace function publish_once() returns trigger
        language plpgsql as $$
        begin
            if tg_op = 'DELETE' then
                raise exception '% rows cannot be deleted', tg_table_name
                    using errcode = 'restrict_violation';
            end if;
            if old.published_at is not null
               or (new.id, new.competency_id, new.version, new.created_at)
                  is distinct from (old.id, old.competency_id, old.version, old.created_at) then
                raise exception '% is frozen once published: start a new version', tg_table_name
                    using errcode = 'restrict_violation';
            end if;
            return new;
        end
        $$
    """)
    op.execute("create trigger module_version_publish_once before update or delete "
               "on module_version for each row execute function publish_once()")
    # Pages and questions change only while their version is a draft. The
    # version is locked first: publishing updates it, so a page sent while
    # it is being published waits, then sees it published.
    op.execute("""
        create or replace function draft_only() returns trigger
        language plpgsql as $$
        begin
            perform 1 from module_version v
                where v.id in (old.module_version_id, new.module_version_id)
                order by v.id for share;
            if exists (select 1 from module_version v
                       where v.id in (old.module_version_id, new.module_version_id)
                         and v.published_at is not null) then
                raise exception '% belongs to a published module version: start a new version',
                    tg_table_name using errcode = 'restrict_violation';
            end if;
            if tg_op = 'DELETE' then
                return old;
            end if;
            return new;
        end
        $$
    """)
    for table in DRAFT_ONLY:
        op.execute(f"create trigger {table}_draft_only before insert or update or delete "
                   f"on {table} for each row execute function draft_only()")
    # An attempt is at a published version: a draft's questions may yet
    # change. Published is for good, so there is nothing to wait for.
    op.execute("""
        create or replace function published_only() returns trigger
        language plpgsql as $$
        begin
            if not exists (select 1 from module_version v
                           where v.id = new.module_version_id and v.published_at is not null) then
                raise exception '% needs a published module version', tg_table_name
                    using errcode = 'restrict_violation';
            end if;
            return new;
        end
        $$
    """)
    op.execute("create trigger quiz_attempt_published_only before insert "
               "on quiz_attempt for each row execute function published_only()")
    # A grant from a quiz is the pass of whoever it grants, for that module.
    # Attempts never change, so there is nothing to wait for.
    op.execute("""
        create or replace function quiz_pass_grant() returns trigger
        language plpgsql as $$
        begin
            if new.quiz_attempt_id is not null and not exists (
                select 1 from quiz_attempt a
                where a.id = new.quiz_attempt_id and a.passed
                  and a.person_id = new.person_id and a.competency_id = new.competency_id) then
                raise exception '% needs a passing quiz attempt by the same person, for the same '
                    'competency', tg_table_name using errcode = 'restrict_violation';
            end if;
            return new;
        end
        $$
    """)
    op.execute("create trigger competency_record_quiz_pass before insert "
               "on competency_record for each row execute function quiz_pass_grant()")


def downgrade() -> None:
    # before 0003 a file is a ticket's or a signature: with page files kept,
    # going back is refused rather than losing them
    op.execute("""
        do $$
        begin
            if exists (select 1 from upload where purpose like 'page-%') then
                raise exception 'module page files are kept: remove them by hand before going '
                    'back past 0003';
            end if;
        end
        $$
    """)
    op.execute("drop trigger if exists competency_record_quiz_pass on competency_record")
    op.execute("drop function if exists quiz_pass_grant()")
    op.execute("drop trigger if exists quiz_attempt_published_only on quiz_attempt")
    op.execute("drop function if exists published_only()")
    for table in DRAFT_ONLY:
        op.execute(f"drop trigger if exists {table}_draft_only on {table}")
    op.execute("drop function if exists draft_only()")
    op.execute("drop trigger if exists module_version_publish_once on module_version")
    op.execute("drop function if exists publish_once()")
    op.execute("drop trigger if exists quiz_attempt_append_only on quiz_attempt")
    op.drop_constraint(op.f("ck_competency_record_quiz_grant"), "competency_record",
                       type_="check")
    op.drop_constraint(op.f("uq_competency_record_quiz_attempt_id"), "competency_record",
                       type_="unique")
    op.drop_constraint(op.f("fk_competency_record_quiz_attempt_id_quiz_attempt"),
                       "competency_record", type_="foreignkey")
    op.drop_column("competency_record", "quiz_attempt_id")
    op.drop_table("module_progress")
    op.drop_index(op.f("ix_quiz_attempt_competency_id"), table_name="quiz_attempt")
    op.drop_index(op.f("ix_quiz_attempt_person_id"), table_name="quiz_attempt")
    op.drop_table("quiz_attempt")
    op.drop_index(op.f("ix_quiz_question_module_version_id"), table_name="quiz_question")
    op.drop_table("quiz_question")
    op.drop_index(op.f("ix_module_page_upload_id"), table_name="module_page")
    op.drop_index(op.f("ix_module_page_module_version_id"), table_name="module_page")
    op.drop_table("module_page")
    op.drop_index("uq_module_version_draft", table_name="module_version")
    op.drop_index(op.f("ix_module_version_competency_id"), table_name="module_version")
    op.drop_table("module_version")
    op.drop_constraint(op.f("ck_upload_purpose"), "upload", type_="check")
    op.create_check_constraint(op.f("ck_upload_purpose"), "upload", PURPOSES_BEFORE)
