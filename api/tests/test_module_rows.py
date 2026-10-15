"""A module version is edited while it is a draft and frozen once
published; every quiz attempt is kept as it was. The database says so
(rule 1), whatever the API does."""
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, insert, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError

from lms.models import (
    Competency, CompetencyRecord, ModulePage, ModuleProgress, ModuleVersion, Person, QuizAttempt,
    QuizQuestion, Upload,
)


@pytest.fixture
def module(db):
    """Site induction: version 1 published, version 2 a draft."""
    boss = Person(code="MG001", name="Mel Grant", permission="manager")
    kim = Person(code="LL042", name="Kim Lee")
    induction = Competency(key="site-induction", name="Site induction", kind="module")
    db.add_all([boss, kim, induction])
    db.flush()

    def version(n: int) -> ModuleVersion:
        v = ModuleVersion(competency_id=induction.id, version=n, pass_mark=80)
        db.add(v)
        db.flush()
        db.add(ModulePage(module_version_id=v.id, position=0, kind="text", title="Welcome",
                          body="Sign in at the gatehouse."))
        db.add(QuizQuestion(module_version_id=v.id, position=0, prompt="Where do you sign in?",
                            options=["The gatehouse", "The canteen"], correct=0))
        db.flush()
        return v

    one = version(1)
    one.published_at = datetime.now(UTC)
    one.published_by_id = boss.id
    db.flush()
    two = version(2)
    db.commit()
    return boss, kim, induction, one, two


@pytest.mark.parametrize("model, values", [
    (ModulePage, {"title": "Changed afterwards"}),
    (QuizQuestion, {"correct": 1}),
])
def test_a_published_versions_pages_and_questions_never_change(db, module, model, values):
    boss, kim, induction, one, two = module
    with pytest.raises(DBAPIError, match="published module version"):
        db.execute(update(model).where(model.module_version_id == one.id).values(**values))
        db.commit()


@pytest.mark.parametrize("model", [ModulePage, QuizQuestion])
def test_nothing_is_taken_from_or_added_to_a_published_version(db, module, model):
    boss, kim, induction, one, two = module
    with pytest.raises(DBAPIError, match="published module version"):
        db.execute(delete(model).where(model.module_version_id == one.id))
        db.commit()
    db.rollback()
    row = ({"kind": "text", "title": "One more", "body": "More."} if model is ModulePage
           else {"prompt": "One more?", "options": ["Yes", "No"], "correct": 0})
    with pytest.raises(DBAPIError, match="published module version"):
        db.execute(insert(model).values(module_version_id=one.id, position=1, **row))
        db.commit()


def test_a_draft_is_edited_freely(db, module):
    boss, kim, induction, one, two = module
    db.execute(update(ModulePage).where(ModulePage.module_version_id == two.id)
               .values(title="Welcome to the yard"))
    db.execute(delete(QuizQuestion).where(QuizQuestion.module_version_id == two.id))
    db.execute(update(ModuleVersion).where(ModuleVersion.id == two.id).values(pass_mark=70))
    db.commit()
    db.refresh(two)
    assert two.pass_mark == 70


def test_a_published_version_is_frozen(db, module):
    boss, kim, induction, one, two = module
    with pytest.raises(DBAPIError, match="frozen once published"):
        db.execute(update(ModuleVersion).where(ModuleVersion.id == one.id).values(pass_mark=50))
        db.commit()


def test_a_draft_keeps_its_number(db, module):
    boss, kim, induction, one, two = module
    with pytest.raises(DBAPIError, match="frozen once published"):
        db.execute(update(ModuleVersion).where(ModuleVersion.id == two.id).values(version=3))
        db.commit()


def test_a_version_is_never_deleted(db, module):
    with pytest.raises(DBAPIError, match="cannot be deleted"):
        db.execute(delete(ModuleVersion))
        db.commit()


def test_one_draft_at_a_time(db, module):
    boss, kim, induction, one, two = module
    db.add(ModuleVersion(competency_id=induction.id, version=3, pass_mark=80))
    with pytest.raises(IntegrityError, match="uq_module_version_draft"):
        db.commit()


def test_published_says_by_whom(db, module):
    boss, kim, induction, one, two = module
    with pytest.raises(IntegrityError, match="ck_module_version_published"):
        db.execute(update(ModuleVersion).where(ModuleVersion.id == two.id)
                   .values(published_at=datetime.now(UTC)))
        db.commit()


@pytest.mark.parametrize("options, correct, constraint", [
    (["Only one"], 0, "ck_quiz_question_options"),
    (["a", "b", "c", "d", "e", "f", "g"], 0, "ck_quiz_question_options"),
    (["Yes", "No"], 2, "ck_quiz_question_correct"),
    (["Yes", "No"], -1, "ck_quiz_question_correct"),
])
def test_a_question_has_two_to_six_answers_and_one_is_right(db, module, options, correct,
                                                            constraint):
    two = module[4]
    db.add(QuizQuestion(module_version_id=two.id, position=1, prompt="Well?", options=options,
                        correct=correct))
    with pytest.raises(IntegrityError, match=constraint):
        db.commit()


@pytest.mark.parametrize("row, constraint", [
    ({"kind": "text", "body": "  "}, "ck_module_page_body"),
    ({"kind": "video"}, "ck_module_page_file"),
    ({"kind": "link"}, "ck_module_page_url"),
    ({"kind": "text", "body": "Words.", "url": "https://example.com.au"}, "ck_module_page_url"),
])
def test_each_kind_of_page_has_what_it_needs(db, module, row, constraint):
    two = module[4]
    db.add(ModulePage(module_version_id=two.id, position=1, title="Next", **row))
    with pytest.raises(IntegrityError, match=constraint):
        db.commit()


def test_a_page_file_is_one_kind_of_upload(db, module):
    boss = module[0]
    db.add(Upload(id=uuid.uuid4(), person_id=boss.id, purpose="page-video",
                  content_type="video/mp4", size_bytes=3, sha256="0" * 64, path="ab/v.mp4"))
    db.commit()
    db.add(Upload(id=uuid.uuid4(), person_id=boss.id, purpose="selfie",
                  content_type="image/png", size_bytes=3, sha256="0" * 64, path="ab/s.png"))
    with pytest.raises(IntegrityError, match="ck_upload_purpose"):
        db.commit()


@pytest.fixture
def attempt(db, module):
    boss, kim, induction, one, two = module
    row = QuizAttempt(person_id=kim.id, competency_id=induction.id, module_version_id=one.id,
                      answers=[1], correct=0, total=1, score=0, passed=False)
    db.add(row)
    db.commit()
    return row


@pytest.mark.parametrize("change", [update(QuizAttempt).values(passed=True), delete(QuizAttempt)])
def test_every_attempt_is_kept_as_it_was(db, attempt, change):
    with pytest.raises(DBAPIError, match="append-only"):
        db.execute(change)
        db.commit()


def test_a_page_waits_for_its_version_to_be_published_or_not(engine, module):
    """A page sent while its draft is being published can't slip in after:
    it waits to see whether the version is still a draft."""
    boss, kim, induction, one, two = module
    with engine.connect() as publishing, engine.connect() as writing:
        publishing.execute(update(ModuleVersion).where(ModuleVersion.id == two.id)
                           .values(published_at=datetime.now(UTC), published_by_id=boss.id))
        writing.execute(text("set local lock_timeout = '200ms'"))
        with pytest.raises(OperationalError, match="lock timeout"):
            writing.execute(insert(ModulePage).values(module_version_id=two.id, position=1,
                                                      kind="text", title="Late", body="Late."))
        writing.rollback()
        publishing.rollback()


@pytest.fixture
def other(db):
    """Another module, for rows that say they are one module's but aren't."""
    forklift = Competency(key="forklift", name="Forklift", kind="module")
    db.add(forklift)
    db.commit()
    return forklift


def _attempt(person, competency, version, passed=True) -> QuizAttempt:
    return QuizAttempt(person_id=person.id, competency_id=competency.id,
                       module_version_id=version.id, answers=[0], correct=int(passed), total=1,
                       score=100 if passed else 0, passed=passed)


def test_an_attempt_is_at_a_published_version(db, module):
    boss, kim, induction, one, two = module
    db.add(_attempt(kim, induction, two))
    with pytest.raises(IntegrityError, match="published module version"):
        db.commit()


def test_an_attempt_is_at_a_version_of_its_own_module(db, module, other):
    boss, kim, induction, one, two = module
    db.add(_attempt(kim, other, one))
    with pytest.raises(IntegrityError, match="fk_quiz_attempt_module_version_id_module_version"):
        db.commit()


def test_progress_is_in_a_version_of_its_own_module(db, module, other):
    boss, kim, induction, one, two = module
    db.add(ModuleProgress(person_id=kim.id, competency_id=induction.id, module_version_id=one.id,
                          page=0))
    db.commit()
    db.add(ModuleProgress(person_id=kim.id, competency_id=other.id, module_version_id=one.id,
                          page=0))
    with pytest.raises(IntegrityError,
                       match="fk_module_progress_module_version_id_module_version"):
        db.commit()


def _grant(person, competency, attempt, kind="granted") -> CompetencyRecord:
    return CompetencyRecord(person_id=person.id, competency_id=competency.id, kind=kind,
                            granted_on=datetime.now(UTC).date() if kind == "granted" else None,
                            note=None if kind == "granted" else "Wrong person",
                            recorded_by_id=person.id, quiz_attempt=attempt)


def test_a_pass_is_its_own_grant(db, module):
    """As the quiz does it: the attempt, then its grant, in one go."""
    boss, kim, induction, one, two = module
    attempt = _attempt(kim, induction, one)
    db.add(attempt)
    db.flush()
    db.add(_grant(kim, induction, attempt))
    db.commit()
    assert db.query(CompetencyRecord).one().quiz_attempt_id == attempt.id


@pytest.mark.parametrize("passed, whose, which, kind, error", [
    (False, "kim", "induction", "granted", "passing quiz attempt"),
    (True, "boss", "induction", "granted", "passing quiz attempt"),
    (True, "kim", "other", "granted", "passing quiz attempt"),
    (True, "kim", "induction", "revoked", "ck_competency_record_quiz_grant"),
])
def test_only_a_pass_is_a_grant_and_only_for_whoever_passed(db, module, other, passed, whose,
                                                           which, kind, error):
    boss, kim, induction, one, two = module
    attempt = _attempt(kim, induction, one, passed=passed)
    db.add(attempt)
    db.flush()
    person = {"kim": kim, "boss": boss}[whose]
    competency = {"induction": induction, "other": other}[which]
    db.add(_grant(person, competency, attempt, kind=kind))
    with pytest.raises(IntegrityError, match=error):
        db.commit()
