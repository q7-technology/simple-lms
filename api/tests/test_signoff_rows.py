"""A practical's checklist is written whole and never changed; a sign-off
and the items it ticked are kept as they were, by someone who is not the
learner, and its grant is theirs. The database says so (rules 1 and 3),
whatever the API does."""
import uuid
from datetime import date

import pytest
from sqlalchemy import delete, insert, update
from sqlalchemy.exc import DBAPIError, IntegrityError

from lms.models import (
    Competency, CompetencyRecord, Person, PracticalItem, PracticalVersion, Signoff, SignoffItem,
    Upload,
)


def upload(db, owner, purpose="signature") -> uuid.UUID:
    row = Upload(id=uuid.uuid4(), person_id=owner.id, purpose=purpose, content_type="image/png",
                 size_bytes=3, sha256="0" * 64, path=f"ab/{uuid.uuid4()}.png")
    db.add(row)
    db.flush()
    return row.id


def checklist(db, practical, boss, n, items) -> PracticalVersion:
    """Version n, items and all, in one transaction."""
    v = PracticalVersion(competency_id=practical.id, version=n, published_by_id=boss.id)
    db.add(v)
    db.flush()
    db.add_all([PracticalItem(practical_version_id=v.id, position=i, text=t)
                for i, t in enumerate(items)])
    db.commit()
    return v


def signoff(db, version, kim, sam, *, competency_id=None, items=None, **more) -> Signoff:
    """Kim signed off by Sam on this version, every item ticked, in one transaction."""
    signatures = {"supervisor_signature_upload_id": upload(db, sam),
                  "learner_signature_upload_id": upload(db, sam)}
    s = Signoff(person_id=kim.id, competency_id=competency_id or version.competency_id,
                practical_version_id=version.id, supervisor_id=sam.id, **{**signatures, **more})
    db.add(s)
    db.flush()
    db.add_all([SignoffItem(signoff_id=s.id, practical_item_id=i.id,
                            practical_version_id=version.id)
                for i in (items if items is not None else version.items)])
    db.commit()
    return s


@pytest.fixture
def yard(db):
    """Forklift practical: version 1 of two items; Kim on Sam's team."""
    boss = Person(code="MG001", name="Mel Grant", permission="manager")
    sam = Person(code="SV001", name="Sam Vu", permission="supervisor")
    db.add_all([boss, sam])
    db.flush()
    kim = Person(code="LL042", name="Kim Lee", supervisor_id=sam.id)
    forklift = Competency(key="forklift-practical", name="Forklift practical", kind="practical")
    db.add_all([kim, forklift])
    db.commit()
    one = checklist(db, forklift, boss, 1, ["Checks the forks and chains", "Lifts a pallet"])
    return boss, sam, kim, forklift, one


@pytest.mark.parametrize("change", [
    update(PracticalVersion).values(note="Changed afterwards"),
    update(PracticalItem).values(text="Changed afterwards"),
    delete(PracticalItem),
])
def test_a_checklist_is_kept_as_it_was(db, yard, change):
    with pytest.raises(DBAPIError, match="append-only"):
        db.execute(change)
        db.commit()


def test_nothing_is_added_to_a_checklist_afterwards(db, yard):
    one = yard[4]
    with pytest.raises(DBAPIError, match="written with their practical_version, never after"):
        db.execute(insert(PracticalItem).values(practical_version_id=one.id, position=2,
                                                text="One more"))
        db.commit()


def test_an_item_says_something(db, yard):
    boss, sam, kim, forklift, one = yard
    v = PracticalVersion(competency_id=forklift.id, version=2, published_by_id=boss.id)
    db.add(v)
    db.flush()
    db.add(PracticalItem(practical_version_id=v.id, position=0, text="  "))
    with pytest.raises(IntegrityError, match="ck_practical_item_text"):
        db.commit()


@pytest.mark.parametrize("change", [
    update(Signoff).values(note="Changed afterwards"),
    delete(SignoffItem),
    delete(Signoff),
])
def test_a_signoff_and_what_it_ticked_are_kept_as_they_were(db, yard, change):
    boss, sam, kim, forklift, one = yard
    signoff(db, one, kim, sam)
    with pytest.raises(DBAPIError, match="append-only"):
        db.execute(change)
        db.commit()


def test_nothing_is_ticked_afterwards(db, yard):
    boss, sam, kim, forklift, one = yard
    s = signoff(db, one, kim, sam, items=one.items[:1])
    with pytest.raises(DBAPIError, match="written with their signoff, never after"):
        db.execute(insert(SignoffItem).values(signoff_id=s.id, practical_item_id=one.items[1].id,
                                              practical_version_id=one.id))
        db.commit()


def test_what_is_ticked_is_on_the_checklist_signed_off(db, yard):
    boss, sam, kim, forklift, one = yard
    two = checklist(db, forklift, boss, 2, ["Checks the forks", "Lifts a pallet", "Parks it"])
    with pytest.raises(IntegrityError, match="fk_signoff_item_practical_item_id_practical_item"):
        signoff(db, one, kim, sam, items=two.items)


def test_nobody_signs_off_their_own(db, yard):
    boss, sam, kim, forklift, one = yard
    with pytest.raises(IntegrityError, match="ck_signoff_not_own"):
        signoff(db, one, sam, sam)


def test_a_signoff_is_on_its_own_practicals_checklist(db, yard):
    boss, sam, kim, forklift, one = yard
    other = Competency(key="ewp-practical", name="EWP practical", kind="practical")
    db.add(other)
    db.commit()
    with pytest.raises(IntegrityError, match="fk_signoff_practical_version_id_practical_version"):
        signoff(db, one, kim, sam, competency_id=other.id)


def test_two_people_sign_two_signatures(db, yard):
    boss, sam, kim, forklift, one = yard
    ink = upload(db, sam)
    with pytest.raises(IntegrityError, match="ck_signoff_two_signatures"):
        signoff(db, one, kim, sam, items=[], supervisor_signature_upload_id=ink,
                learner_signature_upload_id=ink)


def test_a_signature_goes_on_one_signoff_only(db, yard):
    boss, sam, kim, forklift, one = yard
    first = signoff(db, one, kim, sam)
    with pytest.raises(IntegrityError, match="uq_signoff_learner_signature_upload_id"):
        signoff(db, one, kim, sam, learner_signature_upload_id=first.learner_signature_upload_id)


def grant(db, s: Signoff, **more):
    row = {"person_id": s.person_id, "competency_id": s.competency_id,
           "recorded_by_id": s.supervisor_id, **more}
    db.add(CompetencyRecord(kind="granted", granted_on=date(2026, 10, 12), signoff_id=s.id, **row))
    db.commit()


def test_a_signoff_is_granted_by_its_supervisor(db, yard):
    boss, sam, kim, forklift, one = yard
    grant(db, signoff(db, one, kim, sam))


@pytest.mark.parametrize("whose", ["person_id", "recorded_by_id"])
def test_a_grant_from_a_signoff_is_that_learners_by_that_supervisor(db, yard, whose):
    boss, sam, kim, forklift, one = yard
    s = signoff(db, one, kim, sam)
    with pytest.raises(DBAPIError, match="needs a sign-off of the same person"):
        grant(db, s, **{whose: boss.id})


def test_a_signoff_grants_once(db, yard):
    boss, sam, kim, forklift, one = yard
    s = signoff(db, one, kim, sam)
    grant(db, s)
    with pytest.raises(IntegrityError, match="uq_competency_record_signoff_id"):
        grant(db, s)


def test_a_signoff_photo_is_one_kind_of_upload(db, yard):
    sam = yard[1]
    upload(db, sam, "signoff-photo")
    db.commit()
    db.add(Upload(id=uuid.uuid4(), person_id=sam.id, purpose="selfie", content_type="image/png",
                  size_bytes=3, sha256="0" * 64, path="ab/s.png"))
    with pytest.raises(IntegrityError, match="ck_upload_purpose"):
        db.commit()


@pytest.mark.parametrize("change", ["update", "delete"])
def test_a_pin_change_is_kept_as_it_was(db, yard, change):
    from lms.models import PinChange

    boss, sam, kim, forklift, one = yard
    db.add(PinChange(person_id=kim.id, changed_by_id=boss.id))
    db.commit()
    with pytest.raises(DBAPIError, match="append-only"):
        if change == "update":
            db.execute(update(PinChange).values(changed_by_id=sam.id))
        else:
            db.execute(delete(PinChange))
        db.commit()


def test_a_file_on_two_signoffs_still_finds_a_learner(db, yard, caplog):
    """The API never lets a signature go on two sign-offs; if one ever did,
    who may see it is still answered, and the log says so."""
    from lms.services import uploads

    boss, sam, kim, forklift, one = yard
    first = signoff(db, one, kim, sam)
    signoff(db, one, kim, sam, learner_signature_upload_id=first.supervisor_signature_upload_id)
    with caplog.at_level("WARNING"):
        assert uploads.signed_off(db, first.supervisor_signature_upload_id) == kim
    assert "on 2 sign-offs" in caplog.text
