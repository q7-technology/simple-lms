"""Tickets' photos and signatures: kept on disk under a random id, checked
for what they are, and shown only to who may see whose they are."""
import asyncio
import hashlib
import uuid

import pytest

from conftest import bearer, make_person, pin_login
from files import JPEG, PDF, PNG, send, sent
from lms.services import uploads


def test_a_photo_is_kept_on_disk_under_a_random_id(client, learner_headers, upload_dir):
    r = send(client, learner_headers)
    assert r.status_code == 201, r.text
    out = r.json()
    assert (out["purpose"], out["content_type"], out["size_bytes"]) == ("ticket", "image/jpeg",
                                                                      len(JPEG))
    stored = list(upload_dir.rglob("*.jpg"))
    assert [p.name for p in stored] == [f"{out['id']}.jpg"] and stored[0].read_bytes() == JPEG
    # the same bytes again are another file: nothing is shared between uploads
    assert send(client, learner_headers).json()["id"] != out["id"]


def test_a_ticket_may_be_a_photo_or_a_pdf_and_a_signature_a_png(client, learner_headers):
    assert send(client, learner_headers, data=PNG).json()["content_type"] == "image/png"
    assert send(client, learner_headers, data=PDF).json()["content_type"] == "application/pdf"
    assert send(client, learner_headers, "signature", PNG).status_code == 201
    r = send(client, learner_headers, "signature", JPEG)
    assert r.status_code == 415 and r.json() == {
        "detail": "a signature file must be one of: PNG", "code": "unsupported_type"}


def test_what_counts_is_the_bytes_not_what_the_request_says(client, learner_headers, db):
    from lms.models import Upload

    r = send(client, learner_headers, data=b"<html>not a photo</html>", content_type="image/jpeg")
    assert r.status_code == 415
    assert db.query(Upload).count() == 0


def test_a_file_too_big_is_refused(client, learner_headers, monkeypatch):
    monkeypatch.setitem(uploads.PURPOSES, "ticket", ({"image/jpeg"}, 100))
    r = send(client, learner_headers)
    assert r.status_code == 413 and r.json()["code"] == "too_large"


def test_a_signature_is_read_no_further_than_its_own_limit(client, learner_headers, upload_dir):
    from lms.api.errors import Refused
    from lms.api.routes.uploads import sent as read_body

    _, limit = uploads.PURPOSES["signature"]
    # declared just past a signature's limit: refused, and nothing kept
    r = send(client, learner_headers, "signature", PNG + b"x" * (limit + 1 - len(PNG)),
             content_type="image/png")
    assert r.status_code == 413 and r.json()["code"] == "too_large"
    assert not list(upload_dir.rglob("*.png"))

    # no length declared: read no further than a signature may be
    read = []

    class Body:
        headers = {}

        async def stream(self):
            for n in range(20):
                read.append(n)
                yield b"x" * (limit // 2)

    with pytest.raises(Refused) as refused:
        asyncio.run(read_body(Body(), "signature"))
    assert refused.value.status_code == 413 and len(read) == 3


def test_an_unknown_purpose_or_no_session_is_refused(client, learner_headers):
    assert send(client, learner_headers, "selfie").status_code == 422
    assert send(client, {}).status_code == 401


def test_a_file_is_shown_to_its_owner_their_supervisor_and_a_manager(
        client, db, learner_headers, supervisor_headers, manager_headers):
    file_id = sent(client, learner_headers)
    for headers in (learner_headers, supervisor_headers, manager_headers):
        r = client.get(f"/v1/uploads/{file_id}", headers=headers)
        assert r.status_code == 200 and r.content == JPEG
        assert r.headers["content-type"] == "image/jpeg"
        assert r.headers["cache-control"] == "private, no-store"
        assert r.headers["content-security-policy"] == "default-src 'none'; sandbox"
        assert r.headers["content-disposition"] == f'inline; filename="{file_id}.jpg"'
        assert r.headers["x-content-type-options"] == "nosniff"


def test_anyone_else_finds_nothing(client, db, learner_headers):
    file_id = sent(client, learner_headers)
    make_person(db, "LL099", "Pat Other", pin="1357")
    pat = bearer(pin_login(client, "LL099", "1357")["token"])
    assert client.get(f"/v1/uploads/{file_id}", headers=pat).status_code == 404
    assert client.get("/v1/uploads/7d1f6a2e-5b8c-4c1e-9f00-000000000000",
                      headers=learner_headers).status_code == 404
    assert client.get(f"/v1/uploads/{file_id}").status_code == 401


def test_a_file_lost_from_disk_is_not_found(client, learner_headers, upload_dir):
    file_id = sent(client, learner_headers)
    for p in upload_dir.rglob("*.jpg"):
        p.unlink()
    assert client.get(f"/v1/uploads/{file_id}", headers=learner_headers).status_code == 404


def test_the_row_says_what_was_kept(client, db, learner_headers):
    from lms.models import Upload

    file_id = sent(client, learner_headers, data=PDF, content_type="application/pdf")
    row = db.get(Upload, uuid.UUID(file_id))
    assert row.sha256 == hashlib.sha256(PDF).hexdigest() and row.path.endswith(".pdf")


def test_the_caller_is_checked_before_the_size(client, monkeypatch):
    monkeypatch.setitem(uploads.PURPOSES, "ticket", ({"image/jpeg"}, 50))
    assert send(client, {}).status_code == 401


def test_a_body_without_a_length_is_read_no_further_than_its_limit(
        client, learner_headers, monkeypatch, upload_dir):
    monkeypatch.setitem(uploads.PURPOSES, "ticket", ({"image/jpeg"}, 50))
    r = client.post("/v1/uploads", params={"purpose": "ticket"},
                    content=iter([JPEG[:40], JPEG[40:]]),
                    headers={**learner_headers, "Content-Type": "image/jpeg"})
    assert r.status_code == 413 and r.json()["code"] == "too_large"
    assert not list(upload_dir.rglob("*.jpg"))


def test_a_pdf_is_sent_as_a_download_and_a_photo_shown_inline(client, learner_headers):
    pdf_id = sent(client, learner_headers, data=PDF, content_type="application/pdf")
    png_id = sent(client, learner_headers, data=PNG, content_type="image/png")
    r = client.get(f"/v1/uploads/{pdf_id}", headers=learner_headers)
    # a sandboxed PDF shows blank in the browser: it is saved instead
    assert r.headers["content-disposition"] == f'attachment; filename="{pdf_id}.pdf"'
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["cache-control"] == "private, no-store"
    r = client.get(f"/v1/uploads/{png_id}", headers=learner_headers)
    assert r.headers["content-disposition"] == f'inline; filename="{png_id}.png"'


def test_a_file_whose_row_is_not_kept_is_not_kept_either(
        client, learner_headers, monkeypatch, upload_dir):
    store = uploads.store

    def store_then_fail_commit(db, *args):
        row = store(db, *args)

        def commit():
            raise RuntimeError("the database went away")
        monkeypatch.setattr(db, "commit", commit)
        return row

    monkeypatch.setattr(uploads, "store", store_then_fail_commit)
    with pytest.raises(RuntimeError):
        send(client, learner_headers)
    assert not [p for p in upload_dir.rglob("*") if p.is_file()]


def test_a_file_whose_row_cannot_be_saved_is_not_kept_either(
        client, learner_headers, monkeypatch, upload_dir):
    store = uploads.store

    def store_with_a_failing_flush(db, *args):
        def flush(*_):
            raise RuntimeError("the database went away")
        monkeypatch.setattr(db, "flush", flush)
        return store(db, *args)

    monkeypatch.setattr(uploads, "store", store_with_a_failing_flush)
    with pytest.raises(RuntimeError):
        send(client, learner_headers)
    assert not [p for p in upload_dir.rglob("*") if p.is_file()]
