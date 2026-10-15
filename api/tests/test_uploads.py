"""Tickets' photos and signatures: kept on disk under a random id, checked
for what they are, and shown only to who may see whose they are."""
import asyncio
import hashlib
import uuid

import pytest

from conftest import bearer, make_person, pin_login
from files import JPEG, MOV, MP4, PDF, PNG, WEBM, ftyp, send, sent
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


def test_a_file_is_sent_from_disk_without_being_read_whole(
        client, learner_headers, manager_headers, monkeypatch):
    from pathlib import Path

    file_id = sent(client, learner_headers)
    video = sent(client, manager_headers, "page-video", MP4, "video/mp4")

    def read_bytes(self):
        raise AssertionError("a stored file is streamed, not read whole")
    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    r = client.get(f"/v1/uploads/{file_id}", headers=learner_headers)
    assert r.status_code == 200 and r.content == JPEG
    assert r.headers["content-length"] == str(len(JPEG))
    r = client.get(f"/v1/uploads/{video}", headers=manager_headers)
    assert r.status_code == 200 and r.content == MP4
    assert r.headers["content-type"] == "video/mp4"


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


@pytest.mark.parametrize("purpose, data, content_type", [
    ("page-image", JPEG, "image/jpeg"),
    ("page-image", PNG, "image/png"),
    ("page-pdf", PDF, "application/pdf"),
    ("page-video", MP4, "video/mp4"),
    ("page-video", ftyp(b"isom"), "video/mp4"),
    ("page-video", WEBM, "video/webm"),
    # the DocType wherever it is in the header, its size written long
    ("page-video", b"\x1a\x45\xdf\xa3\x90\x42\xf2\x81\x04\x42\xf3\x81\x08"
                   b"\x42\x82\x40\x04webm" + b"frames" * 40, "video/webm"),
])
def test_an_editor_sends_a_module_pages_files(client, manager_headers, upload_dir, purpose, data,
                                              content_type):
    r = send(client, manager_headers, purpose, data, "application/octet-stream")
    assert r.status_code == 201, r.text
    out = r.json()
    assert (out["purpose"], out["content_type"]) == (purpose, content_type)
    assert [p.name for p in upload_dir.rglob("*") if p.is_file()] == [
        f"{out['id']}.{uploads.EXT[content_type]}"]


@pytest.mark.parametrize("data", [
    MOV, PDF, b"\x1a\x45\xdf\xa3\x42\x82\x88matroska" + b"x" * 40,
    # a Matroska .mkv that says webm somewhere else in its first bytes
    b"\x1a\x45\xdf\xa3\x8b\x42\x82\x88matroska" + b"webm" * 10,
    b"\x1a\x45\xdf\xa3\x93\xec\x86webmxx\x42\x82\x88matroska" + b"x" * 40,
    # a DocType that only starts with webm, and a header cut short
    b"\x1a\x45\xdf\xa3\x88\x42\x82\x85webmx" + b"x" * 40,
    b"\x1a\x45\xdf\xa3\x9f\x42\x82\x84web",
    # an iPhone photo, and the other pictures and sound that start the same way
    ftyp(b"heic"), ftyp(b"mif1"), ftyp(b"avif"), ftyp(b"M4A "),
])
def test_a_video_is_an_mp4_or_a_webm(client, manager_headers, upload_dir, data):
    r = send(client, manager_headers, "page-video", data, "video/quicktime")
    assert r.status_code == 415 and r.json() == {
        "detail": "a page-video file must be one of: MP4, WEBM", "code": "unsupported_type"}
    assert not [p for p in upload_dir.rglob("*") if p.is_file()]


def test_only_an_editor_sends_a_modules_files(client, learner_headers, supervisor_headers):
    for headers in (learner_headers, supervisor_headers):
        r = send(client, headers, "page-video", MP4, "video/mp4")
        assert r.status_code == 403 and r.json()["code"] == "forbidden"


def test_a_video_may_be_200_mb_and_anything_else_20(client, manager_headers):
    assert uploads.PURPOSES["page-video"][1] == 200_000_000
    assert {uploads.PURPOSES[p][1] for p in ("ticket", "page-image", "page-pdf")} == {20_000_000}
    # declared too big: refused before the body is read
    r = client.post("/v1/uploads", params={"purpose": "page-image"}, content=JPEG,
                    headers={**manager_headers, "Content-Length": "20000001"})
    assert r.status_code == 413 and r.json() == {
        "detail": "a page-image file may be 20 MB at most", "code": "too_large"}


def test_a_file_goes_to_disk_as_it_comes(upload_dir):
    """Never held whole in memory: each piece is on disk once it is written."""
    file = uploads.Incoming("page-video")
    for n in range(1, 4):
        file.write(MP4 if n == 1 else b"\x00" * 1_000_000)
        file._file.flush()
        assert file.path.stat().st_size == file.size
    assert file.path.parent == upload_dir and file.path.name.startswith(".upload-")
    assert file.finish() == "video/mp4"
    file.discard()
    assert not file.path.exists()


def test_a_refused_file_leaves_nothing_behind(client, learner_headers, upload_dir, monkeypatch):
    monkeypatch.setitem(uploads.PURPOSES, "ticket", ({"image/jpeg"}, 50))
    r = client.post("/v1/uploads", params={"purpose": "ticket"},
                    content=iter([JPEG[:40], JPEG[40:]]),
                    headers={**learner_headers, "Content-Type": "image/jpeg"})
    assert r.status_code == 413
    assert not [p for p in upload_dir.rglob("*") if p.is_file()]


@pytest.mark.parametrize("data, content_type", [(JPEG, "image/jpeg"), (PNG, "image/png")],
                         ids=["jpeg", "png"])
def test_a_supervisor_sends_a_signoffs_photo(client, supervisor_headers, data, content_type):
    r = send(client, supervisor_headers, "signoff-photo", data, "application/octet-stream")
    assert r.status_code == 201, r.text
    assert (r.json()["purpose"], r.json()["content_type"]) == ("signoff-photo", content_type)


def test_a_signoffs_photo_is_a_picture_of_20_mb_at_most(client, supervisor_headers):
    assert uploads.PURPOSES["signoff-photo"][1] == 20_000_000
    r = send(client, supervisor_headers, "signoff-photo", PDF, "application/pdf")
    assert r.status_code == 415 and r.json() == {
        "detail": "a signoff-photo file must be one of: JPG, PNG", "code": "unsupported_type"}


def test_only_someone_who_signs_off_sends_a_signoffs_photo(client, learner_headers):
    r = send(client, learner_headers, "signoff-photo", JPEG, "image/jpeg")
    assert r.status_code == 403 and r.json()["detail"] == "you do not have the signoffs:write scope"


def test_a_signoffs_files_are_shown_to_the_learner_too(
        client, db, learner, supervisor, supervisor_headers, learner_headers):
    """Sent from Sam's phone, so they are Sam's; but Kim may see what signed her off."""
    from lms.models import Competency, PracticalVersion, Signoff

    photo = sent(client, supervisor_headers, "signoff-photo", JPEG)
    signatures = [sent(client, supervisor_headers, "signature", PNG, "image/png") for _ in "ab"]
    forklift = Competency(key="forklift-practical", name="Forklift practical", kind="practical")
    db.add(forklift)
    db.flush()
    v = PracticalVersion(competency_id=forklift.id, version=1, published_by_id=supervisor.id)
    db.add(v)
    db.flush()
    db.add(Signoff(person_id=learner.id, competency_id=forklift.id, practical_version_id=v.id,
                   supervisor_id=supervisor.id, photo_upload_id=uuid.UUID(photo),
                   supervisor_signature_upload_id=uuid.UUID(signatures[0]),
                   learner_signature_upload_id=uuid.UUID(signatures[1])))
    db.commit()
    for file_id in (photo, *signatures):
        assert client.get(f"/v1/uploads/{file_id}", headers=learner_headers).status_code == 200
    make_person(db, "LL099", "Pat Other", pin="1357", supervisor=supervisor)
    pat = bearer(pin_login(client, "LL099", "1357")["token"])
    assert client.get(f"/v1/uploads/{photo}", headers=pat).status_code == 404
