"""Whether someone has signed in with Microsoft shows on their record, and a
manager can unlink the account, so a wrong match is put right on the desktop."""
from conftest import bearer
from lms.services import sessions


def test_a_record_says_whether_they_sign_in_with_microsoft(client, db, manager_headers, learner):
    assert client.get("/v1/people/LL042", headers=manager_headers).json()["entra_linked"] is False
    learner.entra_oid = "oid-kim"
    db.commit()
    assert client.get("/v1/people/LL042", headers=manager_headers).json()["entra_linked"] is True


def test_unlinking_forgets_the_account_and_ends_its_sessions(client, db, manager_headers, learner):
    learner.entra_oid = "oid-kim"
    by_microsoft = bearer(sessions.start(db, learner, "entra"))
    by_pin = bearer(sessions.start(db, learner, "pin"))
    db.commit()
    r = client.post("/v1/people/LL042/entra/unlink", headers=manager_headers)
    assert r.status_code == 200 and r.json()["entra_linked"] is False
    db.refresh(learner)
    assert learner.entra_oid is None
    assert client.get("/v1/auth/me", headers=by_microsoft).status_code == 401
    assert client.get("/v1/auth/me", headers=by_pin).status_code == 200


def test_only_an_admin_unlinks_a_manager(client, db, manager_headers, admin):
    r = client.post("/v1/people/AD001/entra/unlink", headers=manager_headers)
    assert (r.status_code, r.json()["code"]) == (403, "admin_only")
