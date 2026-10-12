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
