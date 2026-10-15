"""A module's files open by a link the API made: no token in the URL, a
video seeked with Range requests, and the link good only for its file, its
session and a few hours."""
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import update

from conftest import login, pin_login
from files import JPEG, MP4, PDF, sent
from lms.models import Session
from lms.services import media, sessions


@pytest.fixture
def video(client, manager_headers):
    return sent(client, manager_headers, "page-video", MP4, "video/mp4")


def a_link(db, token: str, upload_id: str, now: datetime | None = None) -> str:
    """What the API puts in a module's page for this session."""
    row = sessions.find(db, token)
    db.commit()
    return media.link(row, uuid.UUID(upload_id), now)


def expires(link: str) -> int:
    return int(parse_qs(urlsplit(link).query)["expires"][0])


def test_a_link_opens_the_file_without_a_token(client, db, manager_headers, video):
    link = a_link(db, manager_headers["Authorization"].split()[1], video)
    assert "lms_s." not in link
    r = client.get(link)
    assert r.status_code == 200 and r.content == MP4
    assert r.headers["content-type"] == "video/mp4"
    assert r.headers["accept-ranges"] == "bytes"
    assert r.headers["content-disposition"] == f'inline; filename="{video}.mp4"'
    assert r.headers["cache-control"] == "private, no-store"
    assert r.headers["content-security-policy"] == "default-src 'none'; sandbox"
    assert r.headers["x-content-type-options"] == "nosniff"


def test_a_video_is_seeked_with_a_range(client, db, manager_headers, video):
    link = a_link(db, manager_headers["Authorization"].split()[1], video)
    r = client.get(link, headers={"Range": "bytes=10-19"})
    assert r.status_code == 206 and r.content == MP4[10:20]
    assert r.headers["content-range"] == f"bytes 10-19/{len(MP4)}"
    assert r.headers["content-type"] == "video/mp4"
    r = client.get(link, headers={"Range": f"bytes={len(MP4) - 5}-"})
    assert r.status_code == 206 and r.content == MP4[-5:]
    r = client.get(link, headers={"Range": f"bytes={len(MP4)}-"})
    assert r.status_code == 416


def test_a_pdf_is_saved_and_a_picture_shown(client, db, manager_headers):
    token = manager_headers["Authorization"].split()[1]
    pdf = sent(client, manager_headers, "page-pdf", PDF, "application/pdf")
    picture = sent(client, manager_headers, "page-image", JPEG)
    r = client.get(a_link(db, token, pdf))
    assert r.headers["content-disposition"] == f'attachment; filename="{pdf}.pdf"'
    r = client.get(a_link(db, token, picture))
    assert r.headers["content-disposition"] == f'inline; filename="{picture}.jpg"'
    assert r.content == JPEG


def test_a_link_is_for_its_own_file(client, db, manager_headers, video):
    token = manager_headers["Authorization"].split()[1]
    other = sent(client, manager_headers, "page-video", MP4, "video/mp4")
    link = a_link(db, token, video).replace(video, other)
    assert client.get(link).status_code == 404
    tampered = a_link(db, token, video)[:-4] + "0000"
    assert client.get(tampered).status_code == 404


def test_a_link_is_for_its_own_session(client, db, manager, manager_headers, video):
    link = a_link(db, manager_headers["Authorization"].split()[1], video)
    other = login(client, manager.email)["token"]
    mine = parse_qs(urlsplit(link).query)
    theirs = sessions.find(db, other)
    db.commit()
    moved = link.replace(f"session={mine['session'][0]}", f"session={theirs.id}")
    assert client.get(moved).status_code == 404


def test_a_link_ends_with_its_session(client, db, manager_headers, video):
    link = a_link(db, manager_headers["Authorization"].split()[1], video)
    assert client.post("/v1/auth/logout", headers=manager_headers).status_code == 204
    assert client.get(link).status_code == 404


def test_a_link_ends_when_a_pin_session_is_left_idle(client, db, learner, manager_headers, video):
    token = pin_login(client, learner.code)["token"]
    link = a_link(db, token, video)
    assert client.get(link).status_code == 200
    db.execute(update(Session).where(Session.token_hash == sessions._hash(token))
               .values(last_seen_at=datetime.now(UTC) - timedelta(minutes=16)))
    db.commit()
    assert client.get(link).status_code == 404


def test_opening_a_link_counts_as_using_the_session(client, db, learner, video):
    token = pin_login(client, learner.code)["token"]
    link = a_link(db, token, video)
    db.execute(update(Session).where(Session.token_hash == sessions._hash(token))
               .values(last_seen_at=datetime.now(UTC) - timedelta(minutes=10)))
    db.commit()
    assert client.get(link).status_code == 200
    db.expire_all()
    row = sessions.find(db, token)
    assert datetime.now(UTC) - row.last_seen_at < timedelta(minutes=1)


def test_a_link_lasts_six_hours_and_never_past_its_session(client, db, learner, video):
    token = pin_login(client, learner.code)["token"]
    row = sessions.find(db, token)
    db.commit()
    now = datetime.now(UTC)
    soon = media.link(row, uuid.UUID(video), now)
    assert expires(soon) == int((now + timedelta(hours=6)).timestamp())
    # a PIN session ends 12 hours after it began
    late = media.link(row, uuid.UUID(video), now + timedelta(hours=11))
    assert expires(late) == int(row.expires_at.timestamp())
    old = media.link(row, uuid.UUID(video), now - timedelta(hours=7))
    assert client.get(old).status_code == 404


def test_a_link_never_opens_someones_own_file(client, db, learner, learner_headers):
    """A ticket's photo or a signature is fetched with the token, by who may see it."""
    photo = sent(client, learner_headers)
    link = a_link(db, learner_headers["Authorization"].split()[1], photo)
    assert client.get(link).status_code == 404


def test_a_file_lost_from_disk_is_not_found(client, db, manager_headers, video, upload_dir):
    link = a_link(db, manager_headers["Authorization"].split()[1], video)
    for p in upload_dir.rglob("*.mp4"):
        p.unlink()
    assert client.get(link).status_code == 404


@pytest.mark.parametrize("query", [
    "session=99999999999999999999&expires=1&sig=" + "a" * 64,
    "session=1&expires=99999999999999999999999&sig=" + "a" * 64,
    "session=1&expires=1&sig=%C3%A9%C3%A9",
    "session=-1&expires=1&sig=" + "a" * 64,
])
def test_a_made_up_link_is_refused_plainly(client, video, query):
    assert client.get(f"/v1/media/{video}?{query}").status_code in (404, 422)
