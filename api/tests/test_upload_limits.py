"""How much one person may send in a day: a learner's tickets and
signatures (Settings), and an editor's module files. Counted from the
uploads kept in the last 24 hours, and refused before the body is read."""
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from conftest import all_at_once, fresh_client
from files import JPEG, PNG, send
from lms.models import Upload
from lms.services import settings, uploads
from lms.services.modules import said_at


def kept(db, person, purpose="ticket", size=1000, ago=timedelta(hours=1), n=1):
    """n uploads already kept for this person, `ago` before now."""
    for _ in range(n):
        db.add(Upload(id=uuid.uuid4(), person_id=person.id, purpose=purpose,
                      content_type="image/jpeg", size_bytes=size, sha256="0" * 64,
                      path="00/none.jpg", created_at=datetime.now(UTC) - ago))
    db.commit()


def test_a_learner_sends_30_files_a_day_by_default(client, db, learner, learner_headers,
                                                   upload_dir):
    assert (settings.current().upload_files_per_day, settings.current().upload_mb_per_day) == (
        30, 200)
    kept(db, learner, n=28, ago=timedelta(hours=2))
    kept(db, learner, "signature", ago=timedelta(hours=23))
    assert send(client, learner_headers).status_code == 201
    r = send(client, learner_headers, "signature", PNG, "image/png")
    assert r.status_code == 429, r.text
    out = r.json()
    # the oldest of the day's 30 is 23 hours old: one more in an hour
    oldest = db.query(Upload).filter_by(purpose="signature").one().created_at
    when = said_at(oldest + timedelta(hours=24), datetime.now(UTC))
    assert out == {"code": "too_many_uploads",
                   "detail": f"You've sent 30 files in the last 24 hours, the most for a day. "
                             f"You can send more after {when}."}
    assert int(r.headers["Retry-After"]) > 0
    assert len([p for p in upload_dir.rglob("*") if p.is_file()]) == 1


def test_only_the_last_24_hours_count(client, db, learner, learner_headers):
    kept(db, learner, n=40, ago=timedelta(hours=25))
    assert send(client, learner_headers).status_code == 201


def test_a_learner_sends_200_mb_a_day(client, db, learner, learner_headers):
    kept(db, learner, size=150_000_000, ago=timedelta(hours=3))
    kept(db, learner, size=40_000_000, ago=timedelta(hours=1))
    # 190 MB so far: a small one goes, one declared past 200 MB does not
    assert send(client, learner_headers).status_code == 201
    r = client.post("/v1/uploads", params={"purpose": "ticket"}, content=JPEG,
                    headers={**learner_headers, "Content-Length": "15000000"})
    assert r.status_code == 429 and r.json()["code"] == "too_many_uploads"
    # once the 150 MB goes out of the day, in 21 hours
    when = said_at(db.query(Upload).filter_by(size_bytes=150_000_000).one().created_at
                   + timedelta(hours=24), datetime.now(UTC))
    assert r.json()["detail"] == ("That would take you past the 200 MB a person can send in a "
                                  f"day. You can send more after {when}.")
    kept(db, learner, size=10_000_000)
    r = send(client, learner_headers)
    assert r.status_code == 429 and "200 MB" in r.json()["detail"]


def test_the_learners_limits_are_settings(client, db, admin, learner, learner_headers):
    settings.save(db, {"upload_files_per_day": 2, "upload_mb_per_day": 1}, admin)
    kept(db, learner)
    assert send(client, learner_headers).status_code == 201
    r = send(client, learner_headers)
    assert r.status_code == 429 and r.json()["detail"].startswith(
        "You've sent 2 files in the last 24 hours, the most for a day.")
    settings.save(db, {"upload_files_per_day": 10}, admin)
    kept(db, learner, size=1_000_000)
    r = send(client, learner_headers)
    assert r.status_code == 429 and r.json()["detail"].startswith(
        "That would take you past the 1 MB a person can send in a day. You can send more after")


def test_an_editors_module_files_count_on_their_own(client, db, manager, manager_headers,
                                                    learner_headers):
    assert (uploads.PAGE_FILES_PER_DAY, uploads.PAGE_BYTES_PER_DAY) == (200, 5_000_000_000)
    # a learner's day full of tickets is no bar to an editor's page files
    kept(db, manager, n=30)
    assert send(client, manager_headers, "page-image", PNG, "image/png").status_code == 201
    kept(db, manager, "page-image", n=199)
    r = send(client, manager_headers, "page-image", PNG, "image/png")
    assert r.status_code == 429 and r.json()["detail"].startswith(
        "You've sent 200 module files in the last 24 hours, the most for a day.")
    # and a learner's own are counted apart from anyone's module files
    assert send(client, learner_headers).status_code == 201


def test_a_supervisors_own_files_count_on_their_own(client, db, supervisor, supervisor_headers):
    # a day of sign-offs is two signatures and a photo each: past a learner's 30
    assert (uploads.STAFF_FILES_PER_DAY, uploads.STAFF_BYTES_PER_DAY) == (200, 2_000_000_000)
    kept(db, supervisor, "signature", n=20)
    kept(db, supervisor, "signoff-photo", n=10)
    assert send(client, supervisor_headers, "signature", PNG, "image/png").status_code == 201
    kept(db, supervisor, "signature", n=169)
    r = send(client, supervisor_headers, "signature", PNG, "image/png")
    assert r.status_code == 429 and r.json()["detail"].startswith(
        "You've sent 200 files in the last 24 hours, the most for a day.")


def test_page_files_are_5_gb_a_day(client, db, manager, manager_headers):
    kept(db, manager, "page-video", size=200_000_000, n=25)
    r = client.post("/v1/uploads", params={"purpose": "page-video"}, content=b"x",
                    headers={**manager_headers, "Content-Length": "199000000"})
    assert r.status_code == 429
    assert "past the 5 GB a person can send in a day" in r.json()["detail"]


def test_the_limit_is_checked_before_the_body_is_read(client, db, learner, learner_headers):
    kept(db, learner, n=30)
    read = []

    def body():
        read.append(1)
        yield JPEG

    r = client.post("/v1/uploads", params={"purpose": "ticket"}, content=body(),
                    headers={**learner_headers, "Content-Type": "image/jpeg"})
    assert r.status_code == 429 and read == []


def test_files_sent_all_at_once_still_stop_at_the_limit(client, db, admin, learner,
                                                        learner_headers):
    settings.save(db, {"upload_files_per_day": 3}, admin)
    codes = all_at_once(6, lambda: send(fresh_client(), learner_headers).status_code)
    assert sorted(codes) == [201] * 3 + [429] * 3
    assert db.query(Upload).count() == 3


@pytest.mark.parametrize("field,value", [
    ("upload_files_per_day", 0), ("upload_files_per_day", 100_001),
    ("upload_mb_per_day", 0), ("upload_mb_per_day", 1_000_001), ("upload_mb_per_day", "200"),
])
def test_the_limits_are_whole_numbers_in_range(client, admin_headers, field, value):
    r = client.put("/v1/settings", headers=admin_headers, json={field: value})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == field


def test_a_file_bigger_than_a_days_worth_never_fits(client, db, admin, learner_headers):
    settings.save(db, {"upload_mb_per_day": 1}, admin)
    r = client.post("/v1/uploads", params={"purpose": "ticket"}, content=JPEG,
                    headers={**learner_headers, "Content-Length": "2000000"})
    assert r.status_code == 429 and r.json()["detail"] == (
        "A file this big is more than the 1 MB a person can send in a day.")
