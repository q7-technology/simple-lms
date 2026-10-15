"""Modules, as the people taking them see them: the newest published
version's pages one at a time, then its quiz, without the right answers.
How far each person has read is kept here, not on the device, so they carry
on where they left off on any phone or tablet, and a shared tablet keeps
nothing of theirs."""
from __future__ import annotations

import math
from datetime import UTC, datetime

from fastapi import APIRouter, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from lms.api.deps import DB, Principal, require
from lms.api.errors import Conflict, FieldError, NotFound, Refused
from lms.api.routes.modules import PageOut, get_module, page_out
from lms.api.routes.people import get_person
from lms.api.routes.records import one_at_a_time
from lms.api.schemas import CompetencyRef, competency_ref, normal_key
from lms.models import Competency, CompetencyRecord, ModuleProgress, ModuleVersion, QuizAttempt
from lms.services import clock, modules

router = APIRouter(tags=["modules"])


class AskedOut(BaseModel):
    """A question as the learner sees it: never which answer is right."""
    prompt: str
    options: list[str]


class TakingOut(BaseModel):
    id: int
    version: int
    pass_mark: int
    pages: list[PageOut]
    questions: list[AskedOut]


class ModuleOut(BaseModel):
    key: str
    name: str
    version: TakingOut
    # the page to open at, counting from 0; one past the last is the quiz
    resume_at: int
    # when the caller may next try the quiz, after too many goes in a row
    # that didn't pass (Settings); null when they may try now
    retry_at: datetime | None = None
    # the same, ready to show where the business is: "2:15 pm", or
    # "1:00 am on Fri 16 Oct" when it isn't today
    retry_at_text: str | None = None


class ProgressIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # the version they are reading: if a newer one came out, they start that
    version: int
    page: int = Field(ge=0)


def in_use(c: Competency) -> None:
    """A deactivated module is asked of nobody: not read, kept or taken.
    Its editors still see its versions."""
    if not c.active:
        raise Conflict("inactive", f"{c.name} isn't in use any more")


def to_take(db, c: Competency) -> ModuleVersion:
    v = modules.newest(db, c)
    if v is None:
        raise NotFound(f"{c.name} has nothing to take yet")
    return v


def same_version(v: ModuleVersion, version: int) -> None:
    if version != v.version:
        raise Conflict("new_version", f"version {v.version} is the one to take now: start it")


@router.get("/modules/{key}", response_model=ModuleOut)
def read_module(key: str, db: DB, who: Principal = require("training:read")):
    """The version to take now, and where the caller left off in it."""
    c = get_module(db, key)
    in_use(c)
    v = to_take(db, c)
    progress = db.get(ModuleProgress, (who.person.id, c.id))
    resume_at = progress.page if progress and progress.module_version_id == v.id else 0
    wait_until = modules.retry_at(db, who.person.id, c)
    return ModuleOut(key=c.key, name=c.name, resume_at=min(resume_at, len(v.pages)),
                     retry_at=wait_until, retry_at_text=modules.retry_text(wait_until),
                     version=TakingOut(id=v.id, version=v.version, pass_mark=v.pass_mark,
                                       pages=[page_out(p, who.session) for p in v.pages],
                                       questions=[AskedOut(prompt=q.prompt, options=q.options)
                                                  for q in v.questions]))


@router.put("/modules/{key}/progress", status_code=204)
def keep_progress(key: str, body: ProgressIn, db: DB,
                  who: Principal = require("training:write")):
    """The page the caller is on now, theirs alone."""
    c = get_module(db, key)
    in_use(c)
    v = to_take(db, c)
    same_version(v, body.version)
    if body.page > len(v.pages):
        raise FieldError("page", f"this version has {len(v.pages)} pages, then the quiz")
    values = {"person_id": who.person.id, "competency_id": c.id, "module_version_id": v.id,
              "page": body.page, "updated_at": datetime.now(UTC)}
    db.execute(insert(ModuleProgress).values(**values).on_conflict_do_update(
        index_elements=["person_id", "competency_id"],
        set_={k: values[k] for k in ("module_version_id", "page", "updated_at")}))
    db.commit()
    return Response(status_code=204)


class AttemptIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # the version they answered: if a newer one came out, they take that
    version: int
    # the answer chosen for each question, in order, counting from 0
    answers: list[int] = Field(max_length=50)


class AttemptOut(BaseModel):
    id: int
    competency: CompetencyRef
    version: int
    correct: int
    total: int
    # out of 100, rounded down
    score: int
    pass_mark: int
    passed: bool
    created_at: datetime


class TakenOut(AttemptOut):
    """An attempt just taken, and when the next go may be (as ModuleOut):
    the fail that starts the wait says so straight away."""
    retry_at: datetime | None = None
    retry_at_text: str | None = None


def attempt_out(a: QuizAttempt) -> AttemptOut:
    return AttemptOut(id=a.id, competency=competency_ref(a.competency),
                      version=a.module_version.version, correct=a.correct, total=a.total,
                      score=a.score, pass_mark=a.module_version.pass_mark, passed=a.passed,
                      created_at=a.created_at)


@router.post("/modules/{key}/attempts", status_code=201, response_model=TakenOut)
def take_quiz(key: str, body: AttemptIn, db: DB, who: Principal = require("training:write")):
    """Your own go at the quiz, marked here, pass or fail, and kept for good.
    A pass is a grant from today, recorded as yours: the one thing anybody
    earns alone (rule 3). The refresher, if there is one, says when it runs
    out. After a fail, try again; after three in a row, wait first."""
    # locked first, so goes sent at once are counted one after the other
    p = one_at_a_time(db, who.person.code)
    c = get_module(db, key)
    in_use(c)
    wait_until = modules.retry_at(db, p.id, c)
    if wait_until is not None:
        now = clock.now()
        raise Refused(429, "cooldown", f"{modules.why_wait()}: try again after "
                      f"{modules.said_at(wait_until, now)}",
                      extra={"retry_at": wait_until.isoformat(),
                             "retry_at_text": modules.said_at(wait_until, now)},
                      headers={"Retry-After": str(math.ceil((wait_until - now).total_seconds()))})
    v = to_take(db, c)
    same_version(v, body.version)
    questions = v.questions
    if len(body.answers) != len(questions):
        raise FieldError("answers", f"answer all {len(questions)} questions")
    for i, (answer, q) in enumerate(zip(body.answers, questions)):
        if not 0 <= answer < len(q.options):
            raise FieldError(f"answers.{i}", "choose one of the answers")
    correct = sum(answer == q.correct for answer, q in zip(body.answers, questions))
    score = modules.score(correct, len(questions))
    attempt = QuizAttempt(person_id=p.id, competency=c, module_version=v, answers=body.answers,
                          correct=correct, total=len(questions), score=score,
                          passed=score >= v.pass_mark)
    db.add(attempt)
    db.flush()
    if attempt.passed:
        db.add(CompetencyRecord(person_id=p.id, competency=c, kind="granted",
                                granted_on=clock.today(), recorded_by=p, quiz_attempt=attempt))
        # done: next time, it starts from the top
        db.execute(delete(ModuleProgress).where(ModuleProgress.person_id == p.id,
                                                ModuleProgress.competency_id == c.id))
    db.commit()
    wait_until = modules.retry_at(db, p.id, c)
    out = TakenOut(**attempt_out(attempt).model_dump(), retry_at=wait_until,
                   retry_at_text=modules.retry_text(wait_until))
    return JSONResponse(status_code=201, content=out.model_dump(mode="json"))


@router.get("/people/{code}/attempts", response_model=list[AttemptOut])
def list_attempts(code: str, db: DB, competency: str | None = None,
                  who: Principal = require("training:read")):
    """Every go at every quiz, pass or fail, newest first. Your own, your
    team's, or (a manager or admin) anyone's."""
    p = get_person(db, code)
    if not who.sees(p):
        raise NotFound(f"no person {code}")
    q = select(QuizAttempt).where(QuizAttempt.person_id == p.id)
    if competency:
        q = q.join(Competency).where(Competency.key == normal_key(competency))
    rows = db.execute(q.order_by(QuizAttempt.id.desc())).scalars().all()
    return [attempt_out(a) for a in rows]
