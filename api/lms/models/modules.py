from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean, CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Index, Integer, String,
    Text, UniqueConstraint, Uuid, func, text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from lms.models.base import Base, created_at_column
from lms.models.catalogue import Competency
from lms.models.evidence import Upload
from lms.models.people import Person

PAGE_KINDS = ("text", "image", "pdf", "video", "link")


class ModuleVersion(Base):
    """One version of a module: its pages, its quiz and its pass mark. A
    draft (not yet published) is edited freely; publishing freezes it, and a
    trigger keeps it that way, so an attempt always means what was asked.
    Never deleted. People take the newest published version."""

    __tablename__ = "module_version"
    __table_args__ = (
        UniqueConstraint("competency_id", "version"),
        # what an attempt or progress names as its module and version agree
        UniqueConstraint("id", "competency_id"),
        CheckConstraint("version >= 1", name="version"),
        CheckConstraint("pass_mark between 1 and 100", name="pass_mark"),
        # published, by whom and when, or neither
        CheckConstraint("(published_at is null) = (published_by_id is null)", name="published"),
        # one draft at a time for a module
        Index("uq_module_version_draft", "competency_id", unique=True,
              postgresql_where=text("published_at is null")),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    competency_id: Mapped[int] = mapped_column(ForeignKey("competency.id"), index=True)
    # 1, 2, 3 … for each module
    version: Mapped[int] = mapped_column(Integer)
    # the least score, out of 100, that passes
    pass_mark: Mapped[int] = mapped_column(Integer, default=80)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_by_id: Mapped[int | None] = mapped_column(ForeignKey("person.id"))
    created_at: Mapped[datetime] = created_at_column()
    # changed by every save, so a save based on an older one is refused
    saved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    competency: Mapped[Competency] = relationship()
    published_by: Mapped[Person | None] = relationship()
    pages: Mapped[list[ModulePage]] = relationship(order_by="ModulePage.position")
    questions: Mapped[list[QuizQuestion]] = relationship(order_by="QuizQuestion.position")


class ModulePage(Base):
    """One page of a module version: text, a picture, a PDF, a video or a
    link. Changed only while its version is a draft (a trigger says so)."""

    __tablename__ = "module_page"
    __table_args__ = (
        UniqueConstraint("module_version_id", "position"),
        CheckConstraint("kind in ('text', 'image', 'pdf', 'video', 'link')", name="kind"),
        CheckConstraint("position >= 0", name="position"),
        CheckConstraint("length(trim(title)) > 0", name="title"),
        # a text page has its text; the others may have a line or two under them
        CheckConstraint("kind <> 'text' or coalesce(length(trim(body)), 0) > 0", name="body"),
        # a picture, a PDF and a video are a file; a link is a web address
        CheckConstraint("(kind in ('image', 'pdf', 'video')) = (upload_id is not null)",
                        name="file"),
        CheckConstraint("(kind = 'link') = (url is not null)", name="url"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    module_version_id: Mapped[int] = mapped_column(ForeignKey("module_version.id"), index=True)
    # 0, 1, 2 …: the order they are read in
    position: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(8))
    title: Mapped[str] = mapped_column(String(120))
    body: Mapped[str | None] = mapped_column(Text)
    upload_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("upload.id"), index=True)
    url: Mapped[str | None] = mapped_column(String(2000))

    upload: Mapped[Upload | None] = relationship()


class QuizQuestion(Base):
    """A multiple-choice question: 2 to 6 answers, one of them right.
    Changed only while its version is a draft (a trigger says so)."""

    __tablename__ = "quiz_question"
    __table_args__ = (
        UniqueConstraint("module_version_id", "position"),
        CheckConstraint("position >= 0", name="position"),
        CheckConstraint("length(trim(prompt)) > 0", name="prompt"),
        CheckConstraint("jsonb_typeof(options) = 'array' and jsonb_array_length(options) "
                        "between 2 and 6", name="options"),
        CheckConstraint("correct >= 0 and correct < jsonb_array_length(options)",
                        name="correct"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    module_version_id: Mapped[int] = mapped_column(ForeignKey("module_version.id"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    prompt: Mapped[str] = mapped_column(String(500))
    # the answers to choose from, in the order shown
    options: Mapped[list[str]] = mapped_column(JSONB)
    # which of them is right, counting from 0: never sent to a learner
    correct: Mapped[int] = mapped_column(Integer)


class QuizAttempt(Base):
    """One go at a module's quiz, pass or fail, at a published version of
    that module (a trigger and the foreign key say so). Append-only: every
    attempt is kept (rule 1). A pass is also a grant in the training record."""

    __tablename__ = "quiz_attempt"
    __table_args__ = (
        ForeignKeyConstraint(["module_version_id", "competency_id"],
                             ["module_version.id", "module_version.competency_id"]),
        CheckConstraint("total >= 1 and correct between 0 and total", name="counts"),
        CheckConstraint("score between 0 and 100", name="score"),
        CheckConstraint("jsonb_typeof(answers) = 'array'", name="answers"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("person.id"), index=True)
    competency_id: Mapped[int] = mapped_column(ForeignKey("competency.id"), index=True)
    # the version they answered, whose questions and pass mark never change
    module_version_id: Mapped[int] = mapped_column(Integer)
    # the answer chosen for each question, in order, counting from 0
    answers: Mapped[list[int]] = mapped_column(JSONB)
    correct: Mapped[int] = mapped_column(Integer)
    total: Mapped[int] = mapped_column(Integer)
    # out of 100, rounded down; passed when it reaches the version's pass mark
    score: Mapped[int] = mapped_column(Integer)
    passed: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = created_at_column()

    competency: Mapped[Competency] = relationship()
    module_version: Mapped[ModuleVersion] = relationship(
        primaryjoin="ModuleVersion.id == QuizAttempt.module_version_id",
        foreign_keys=[module_version_id])


class ModuleProgress(Base):
    """How far a person has read in a module, so they carry on where they
    left off, on any device. Not part of the training record: it moves on
    as they read, and goes once they pass."""

    __tablename__ = "module_progress"
    __table_args__ = (
        CheckConstraint("page >= 0", name="page"),
        # a version of this module
        ForeignKeyConstraint(["module_version_id", "competency_id"],
                             ["module_version.id", "module_version.competency_id"]),
    )

    person_id: Mapped[int] = mapped_column(ForeignKey("person.id"), primary_key=True)
    competency_id: Mapped[int] = mapped_column(ForeignKey("competency.id"), primary_key=True)
    module_version_id: Mapped[int] = mapped_column(Integer)
    # the page they are on, counting from 0; one past the last is the quiz
    page: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 server_default=func.now())
