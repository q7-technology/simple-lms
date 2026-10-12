"""The training record and the overrides are append-only, and the database
says so (rule 1)."""
from datetime import date

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.exc import DBAPIError, IntegrityError

from lms.models import Competency, CompetencyRecord, Person, PersonOverride


@pytest.fixture
def setting(db):
    boss = Person(code="MG001", name="Mel Grant", permission="manager")
    kim = Person(code="LL042", name="Kim Lee")
    forklift = Competency(key="forklift-licence", name="Forklift licence", kind="ticket")
    db.add_all([boss, kim, forklift])
    db.flush()
    db.add(CompetencyRecord(person_id=kim.id, competency_id=forklift.id, kind="granted",
                            granted_on=date(2026, 3, 1), expires_on=date(2031, 3, 1),
                            recorded_by_id=boss.id))
    db.add(PersonOverride(person_id=kim.id, competency_id=forklift.id, kind="extra",
                          note="drives the yard forklift on Saturdays", recorded_by_id=boss.id))
    db.commit()
    return boss, kim, forklift


@pytest.mark.parametrize("model", [CompetencyRecord, PersonOverride])
def test_rows_cannot_be_updated(db, setting, model):
    with pytest.raises(DBAPIError, match="append-only"):
        db.execute(update(model).values(note="changed afterwards"))
        db.commit()


@pytest.mark.parametrize("model", [CompetencyRecord, PersonOverride])
def test_rows_cannot_be_deleted(db, setting, model):
    with pytest.raises(DBAPIError, match="append-only"):
        db.execute(delete(model))
        db.commit()


def test_a_correction_is_a_new_row(db, setting):
    boss, kim, forklift = setting
    db.add(CompetencyRecord(person_id=kim.id, competency_id=forklift.id, kind="revoked",
                            note="card was for a different licence class",
                            recorded_by_id=boss.id))
    db.commit()
    kinds = db.execute(select(CompetencyRecord.kind).order_by(CompetencyRecord.id)).scalars()
    assert list(kinds) == ["granted", "revoked"]


def test_a_revoke_needs_a_note_and_a_grant_needs_a_date(db, setting):
    boss, kim, forklift = setting
    db.add(CompetencyRecord(person_id=kim.id, competency_id=forklift.id, kind="revoked",
                            note="  ", recorded_by_id=boss.id))
    with pytest.raises(IntegrityError, match="ck_competency_record_revoke_note"):
        db.commit()
    db.rollback()
    db.add(CompetencyRecord(person_id=kim.id, competency_id=forklift.id, kind="granted",
                            recorded_by_id=boss.id))
    with pytest.raises(IntegrityError, match="ck_competency_record_granted_on"):
        db.commit()
