from sqlalchemy import select

from lms.cli import main
from lms.models import Person


def test_create_user_makes_someone_who_can_sign_in(client, db, capsys):
    assert main(["create-user", "--code", "ad001", "--name", "Leighton Lauton",
                 "--email", "Leighton@Example.com.au", "--password",
                 "a long enough password"]) == 0
    assert "AD001 Leighton Lauton <leighton@example.com.au> created as admin" in capsys.readouterr().out
    person = db.execute(select(Person)).scalar_one()
    assert person.permission == "admin" and person.pin_hash is None
    r = client.post("/v1/auth/login", json={"email": "leighton@example.com.au",
                                            "password": "a long enough password"})
    assert r.status_code == 200


def test_create_user_refuses_a_short_password(db, capsys):
    assert main(["create-user", "--code", "AD001", "--name", "L", "--email", "l@example.com",
                 "--password", "short"]) == 1
    assert "at least 12" in capsys.readouterr().err
    assert db.execute(select(Person)).first() is None


def test_create_user_refuses_a_code_or_email_already_taken(db, admin, capsys):
    assert main(["create-user", "--code", admin.code, "--name", "Another",
                 "--email", "another@example.com", "--password", "a long enough password"]) == 1
    assert main(["create-user", "--code", "AD002", "--name", "Another",
                 "--email", admin.email, "--password", "a long enough password"]) == 1
    assert capsys.readouterr().err.count("already exists") == 2


def test_daily_job_queues_the_reminders_now(client, db, manager_headers, learner, capsys):
    import yard
    from lms.models import Outbox

    yard.build(client, manager_headers)
    learner.email = "kim@example.com.au"
    db.commit()
    yard.give_roles(client, manager_headers, "LL042", "forklift-operator")
    yard.grant(client, manager_headers, "LL042", "forklift-licence", "2025-01-01",
               expires_on="2026-11-11")
    assert main(["daily-job", "--on", "2026-10-13"]) == 0
    assert capsys.readouterr().out.strip() == (
        "2026-10-13: 1 reminders and 0 digests queued; the worker sends them")
    assert main(["daily-job", "--on", "2026-10-13"]) == 0
    assert "0 reminders" in capsys.readouterr().out
    assert db.query(Outbox).count() == 1
