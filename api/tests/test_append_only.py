"""The training record, the overrides, the policy versions and the files
sent are append-only, and a ticket is decided once, and the database says so
(rule 1)."""
import uuid
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import delete, insert, select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError

from lms.models import (
    Competency, CompetencyRecord, Outbox, Person, PersonOverride, PolicyVersion, TicketSubmission,
    Upload,
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


@pytest.mark.parametrize("change", [update(Upload).values(path="ab/other.jpg"), delete(Upload)])
def test_a_file_sent_is_never_changed_or_deleted(db, waiting, change):
    """Records and tickets point at it: what a manager checked stays what it was."""
    with pytest.raises(DBAPIError, match="append-only"):
        db.execute(change)
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


def _ticket(db, waiting, **values):
    """A second ticket, inserted as is: no trigger stands in the way of an insert."""
    boss, ticket = waiting
    if "front_upload_id" not in values:
        values["front_upload_id"] = _upload(db, ticket.person_id).id
    values = {"person_id": ticket.person_id, "competency_id": ticket.competency_id,
              "number": "LF0054321",
              "status": "approved", "decided_by_id": boss.id, "decided_at": datetime.now(UTC),
              "reason": None} | values
    db.execute(insert(TicketSubmission).values(**values))
    db.commit()


def _upload(db, person_id, purpose="ticket"):
    u = Upload(id=uuid.uuid4(), person_id=person_id, purpose=purpose, content_type="image/png",
               size_bytes=3, sha256="0" * 64, path=f"ab/{uuid.uuid4()}.png")
    db.add(u)
    db.flush()
    return u


def test_a_signature_is_on_one_record_only(db, setting):
    boss, kim, forklift = setting
    whs = db.execute(select(PolicyVersion)).scalar_one()
    signature = _upload(db, kim.id, "signature")
    row = {"person_id": kim.id, "competency_id": whs.competency_id, "kind": "granted",
           "granted_on": date(2026, 3, 1), "recorded_by_id": kim.id,
           "policy_version_id": whs.id, "signed_name": "Kim Lee",
           "signature_upload_id": signature.id}
    db.execute(insert(CompetencyRecord).values(**row))
    db.commit()
    with pytest.raises(IntegrityError, match="uq_competency_record_signature_upload_id"):
        db.execute(insert(CompetencyRecord).values(**row))
        db.commit()


def test_a_photo_is_the_front_of_one_ticket_only(db, waiting):
    boss, ticket = waiting
    with pytest.raises(IntegrityError, match="uq_ticket_submission_front_upload_id"):
        _ticket(db, waiting, front_upload_id=ticket.front_upload_id)


def test_a_photo_is_the_back_of_one_ticket_only(db, waiting):
    boss, ticket = waiting
    back = _upload(db, ticket.person_id)
    _ticket(db, waiting, back_upload_id=back.id)
    with pytest.raises(IntegrityError, match="uq_ticket_submission_back_upload_id"):
        _ticket(db, waiting, back_upload_id=back.id)


def test_a_ticket_has_two_different_sides(db, waiting):
    boss, ticket = waiting
    photo = _upload(db, ticket.person_id)
    with pytest.raises(IntegrityError, match="ck_ticket_submission_two_sides"):
        _ticket(db, waiting, front_upload_id=photo.id, back_upload_id=photo.id)


@pytest.mark.parametrize("values", [
    {"decided_at": None},
    {"decided_by_id": None},
    {"status": "rejected", "reason": "blurry", "decided_at": None},
])
def test_a_decided_ticket_says_who_and_when(db, waiting, values):
    with pytest.raises(IntegrityError, match="ck_ticket_submission_decided"):
        _ticket(db, waiting, **values)


@pytest.mark.parametrize("values", [
    {"decided_by_id": None},
    {"decided_at": None},
])
def test_a_waiting_ticket_has_no_decision(db, waiting, values):
    boss, ticket = waiting
    with pytest.raises(IntegrityError, match="ck_ticket_submission_decided"):
        _ticket(db, waiting, status="pending", person_id=boss.id, **values)


@pytest.mark.parametrize("values", [
    {"status": "rejected", "reason": None},
    {"status": "rejected", "reason": "  "},
    {"status": "approved", "reason": "looks fine"},
])
def test_only_a_rejected_ticket_has_a_reason(db, waiting, values):
    with pytest.raises(IntegrityError, match="ck_ticket_submission_reason"):
        _ticket(db, waiting, **values)


def test_a_waiting_ticket_has_no_reason(db, waiting):
    boss, _ = waiting
    with pytest.raises(IntegrityError, match="ck_ticket_submission_reason"):
        _ticket(db, waiting, status="pending", person_id=boss.id, decided_by_id=None,
                decided_at=None, reason="not yet")


def test_the_outbox_fills_in_its_own_defaults(db):
    db.execute(text("insert into outbox (kind, key, payload) values ('email', 'k', '{}')"))
    row = db.execute(select(Outbox)).scalar_one()
    assert (row.status, row.attempts, row.done_at) == ("pending", 0, None)
    assert row.next_attempt_at is not None


@pytest.mark.parametrize("status, done_at", [
    ("done", None), ("pending", datetime.now(UTC)), ("failed", datetime.now(UTC)),
])
def test_only_a_sent_email_has_a_done_at(db, status, done_at):
    with pytest.raises(IntegrityError, match="ck_outbox_done_at"):
        db.execute(insert(Outbox).values(kind="email", key="k", payload={}, status=status,
                                         attempts=1, next_attempt_at=datetime.now(UTC),
                                         done_at=done_at))
        db.commit()
