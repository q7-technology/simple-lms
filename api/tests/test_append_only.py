"""The training record, the overrides and the policy versions are
append-only, and a ticket is decided once, and the database says so (rule 1)."""
import uuid
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.exc import DBAPIError, IntegrityError

from lms.models import (
    Competency, CompetencyRecord, Person, PersonOverride, PolicyVersion, TicketSubmission, Upload,
)


@pytest.fixture
def setting(db):
    boss = Person(code="MG001", name="Mel Grant", permission="manager")
    kim = Person(code="LL042", name="Kim Lee")
    forklift = Competency(key="forklift-licence", name="Forklift licence", kind="ticket")
    whs = Competency(key="whs-policy", name="WHS policy", kind="policy")
    db.add_all([boss, kim, forklift, whs])
    db.flush()
    db.add(CompetencyRecord(person_id=kim.id, competency_id=forklift.id, kind="granted",
                            granted_on=date(2026, 3, 1), expires_on=date(2031, 3, 1),
                            recorded_by_id=boss.id))
    db.add(PersonOverride(person_id=kim.id, competency_id=forklift.id, kind="extra",
                          note="drives the yard forklift on Saturdays", recorded_by_id=boss.id))
    db.add(PolicyVersion(competency_id=whs.id, version=1, body="Wear your PPE.",
                         published_by_id=boss.id))
    db.commit()
    return boss, kim, forklift


@pytest.mark.parametrize("model", [CompetencyRecord, PersonOverride, PolicyVersion])
def test_rows_cannot_be_updated(db, setting, model):
    with pytest.raises(DBAPIError, match="append-only"):
        db.execute(update(model).values(note="changed afterwards"))
        db.commit()


@pytest.mark.parametrize("model", [CompetencyRecord, PersonOverride, PolicyVersion])
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


@pytest.fixture
def waiting(db, setting):
    boss, kim, forklift = setting
    front = Upload(id=uuid.uuid4(), person_id=kim.id, purpose="ticket", content_type="image/jpeg",
                   size_bytes=3, sha256="0" * 64, path="ab/front.jpg")
    db.add(front)
    db.flush()
    ticket = TicketSubmission(person_id=kim.id, competency_id=forklift.id, number="LF0012345",
                              expires_on=date(2031, 3, 1), front_upload_id=front.id,
                              status="pending")
    db.add(ticket)
    db.commit()
    return boss, ticket


def test_a_ticket_is_decided_once(db, waiting):
    boss, ticket = waiting
    db.execute(update(TicketSubmission).values(status="approved", decided_by_id=boss.id,
                                               decided_at=datetime.now(UTC)))
    db.commit()
    with pytest.raises(DBAPIError, match="decided once"):
        db.execute(update(TicketSubmission).values(status="rejected", reason="changed my mind"))
        db.commit()


def test_a_ticket_cannot_be_changed_while_it_waits(db, waiting):
    with pytest.raises(DBAPIError, match="decided once"):
        db.execute(update(TicketSubmission).values(number="LF0099999"))
        db.commit()


def test_a_ticket_is_never_deleted(db, waiting):
    with pytest.raises(DBAPIError, match="cannot be deleted"):
        db.execute(delete(TicketSubmission))
        db.commit()
