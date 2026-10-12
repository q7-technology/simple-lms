"""New PINs and passwords, and who may change whom."""
from conftest import PIN, bearer, login, pin_login


def test_a_new_pin_unlocks_a_locked_one_and_ends_pin_sessions(client, db, manager_headers,
                                                               learner):
    old = pin_login(client, "LL042")["token"]
    for _ in range(5):
        client.post("/v1/auth/pin-login", json={"code": "LL042", "pin": "0000"})
    db.refresh(learner)
    assert learner.pin_locked
    r = client.post("/v1/people/LL042/pin", headers=manager_headers, json={"pin": "97531"})
    assert r.status_code == 200 and r.json()["pin_locked"] is False
    db.refresh(learner)
    assert (learner.pin_locked, learner.pin_failed_attempts) == (False, 0)
    assert client.get("/v1/auth/me", headers=bearer(old)).status_code == 401
    assert client.post("/v1/auth/pin-login", json={"code": "LL042", "pin": PIN}).status_code == 401
    assert pin_login(client, "LL042", "97531")["token"]


def test_a_new_password_lifts_a_lock_and_ends_password_sessions(client, manager_headers,
                                                                 supervisor):
    old = login(client, supervisor.email)["token"]
    pin = pin_login(client, supervisor.code)["token"]
    r = client.post("/v1/people/SV001/password", headers=manager_headers,
                    json={"password": "a brand new password"})
    assert r.status_code == 200 and r.json()["has_password"] is True
    assert client.get("/v1/auth/me", headers=bearer(old)).status_code == 401
    assert client.get("/v1/auth/me", headers=bearer(pin)).status_code == 200
    assert login(client, supervisor.email, "a brand new password")["token"]


def test_a_password_is_at_least_12_characters(client, manager_headers, supervisor):
    r = client.post("/v1/people/SV001/password", headers=manager_headers,
                    json={"password": "too short"})
    assert r.status_code == 422


def test_a_manager_looks_after_learners_and_supervisors_only(client, manager_headers, admin):
    r = client.post("/v1/people", headers=manager_headers,
                    json={"code": "MG002", "name": "Max", "permission": "manager"})
    assert r.status_code == 403 and r.json()["code"] == "admin_only"
    r = client.post("/v1/people", headers=manager_headers,
                    json={"code": "SV002", "name": "Sue", "permission": "supervisor",
                          "email": "sue@example.com", "password": "a long enough password"})
    assert r.status_code == 201
    r = client.patch("/v1/people/SV002", headers=manager_headers, json={"permission": "admin"})
    assert r.status_code == 403
    assert client.patch("/v1/people/AD001", headers=manager_headers,
                        json={"name": "x"}).status_code == 403
    assert client.post("/v1/people/AD001/password", headers=manager_headers,
                       json={"password": "a long enough password"}).status_code == 403
    assert client.post("/v1/people/AD001/deactivate", headers=manager_headers).status_code == 403

def test_an_admin_looks_after_everyone(client, admin_headers, manager):
    r = client.patch("/v1/people/MG001", headers=admin_headers, json={"permission": "admin"})
    assert r.status_code == 200 and r.json()["permission"] == "admin"
    r = client.post("/v1/people", headers=admin_headers,
                    json={"code": "MG002", "name": "Max", "permission": "manager"})
    assert r.status_code == 201
