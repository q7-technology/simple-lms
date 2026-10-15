"""A session may be signed in with Microsoft, and a Microsoft sign-in under
way hands over to someone only once Microsoft has sent them back."""
from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError

from conftest import make_person
from lms.models import EntraSignIn, Session


def test_a_session_may_be_signed_in_with_microsoft(db):
    kim = make_person(db, "LL042", "Kim Lee")
    now = datetime.now(UTC)
    db.add(Session(person_id=kim.id, token_hash="a" * 64, method="entra", last_seen_at=now,
                   expires_at=now, idle_seconds=900))
    db.commit()
    db.add(Session(person_id=kim.id, token_hash="b" * 64, method="sso", last_seen_at=now,
                   expires_at=now, idle_seconds=900))
    with pytest.raises(IntegrityError, match="ck_session_method"):
        db.commit()


def sign_in(**more) -> EntraSignIn:
    return EntraSignIn(**{"state_hash": "s" * 64, "nonce": "n", "code_verifier": "v",
                          "app": "learner", "browser_hash": "b" * 64, **more})


@pytest.mark.parametrize("more, constraint", [
    ({"app": "kiosk"}, "ck_entra_sign_in_app"),
    ({"handoff_hash": "h" * 64}, "ck_entra_sign_in_handoff"),
])
def test_a_sign_in_under_way_holds_together(db, more, constraint):
    db.add(sign_in(**more))
    with pytest.raises(IntegrityError, match=constraint):
        db.commit()


def test_a_hand_off_waits_for_microsoft_to_send_them_back(db):
    kim = make_person(db, "LL042", "Kim Lee")
    db.add(sign_in(person_id=kim.id, handoff_hash="h" * 64))
    with pytest.raises(IntegrityError, match="ck_entra_sign_in_returned"):
        db.commit()
    db.rollback()
    db.add(sign_in(person_id=kim.id, handoff_hash="h" * 64, returned_at=datetime.now(UTC)))
    db.commit()
