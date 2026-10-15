"""Files: sent by the learner app before the ticket, signature or sign-off
that names them, or by the desktop before the module page that shows them;
and shown only to who may see the person they belong to (or, on a
sign-off, the learner it signs off)."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from lms.api.deps import DB, Principal, Who
from lms.api.errors import Forbidden, NotFound
from lms.api.routes.records import one_at_a_time
from lms.models import Person, Upload
from lms.services import uploads

router = APIRouter(tags=["uploads"])
log = logging.getLogger("lms.uploads")

Purpose = Literal["ticket", "signature", "page-image", "page-pdf", "page-video", "signoff-photo"]


class UploadOut(BaseModel):
    id: uuid.UUID
    purpose: str
    content_type: str
    size_bytes: int
    created_at: datetime


def upload_out(row: Upload) -> UploadOut:
    return UploadOut(id=row.id, purpose=row.purpose, content_type=row.content_type,
                     size_bytes=row.size_bytes, created_at=row.created_at)


def sender(who: Who, db: DB, request: Request, purpose: Purpose = Query()) -> Principal:
    """Your own training's files for anyone; a module's for its editors;
    and no more than a day's worth (429). Checked before a byte of the body
    is read."""
    scope = uploads.SENDERS[purpose]
    if not who.has_scope(scope):
        raise Forbidden(f"you do not have the {scope} scope")
    declared = request.headers.get("content-length", "")
    uploads.check_room(db, who.person, purpose, int(declared) if declared.isdigit() else 1)
    # nothing held open while the body comes
    db.commit()
    return who


async def sent(request: Request, purpose: Purpose = Query()) -> uploads.Incoming:
    """The purpose, then the body, written to disk as it comes and read no
    further than that purpose's limit. A wrong purpose is refused before a
    byte of the body is read."""
    _, limit = uploads.PURPOSES[purpose]
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit:
        raise uploads.too_large(purpose)
    file = uploads.Incoming(purpose)
    try:
        async for chunk in request.stream():
            # the disk, off the event loop: a big video doesn't hold up others
            await run_in_threadpool(file.write, chunk)
        await run_in_threadpool(file.finish)
    except BaseException:
        file.discard()
        raise
    return file


@router.post("/uploads", status_code=201, response_model=UploadOut)
def send_file(db: DB, who: Principal = Depends(sender),
              file: uploads.Incoming = Depends(sent)):
    """The file as the body (what counts is its first bytes, not its
    Content-Type). The caller is checked before the body is read
    (dependencies run in order)."""
    # and again once it is all here, with the sender locked, so files sent
    # at once can't all slip in under the day's limit
    person = one_at_a_time(db, who.person.code)
    try:
        uploads.check_room(db, person, file.purpose, file.size)
    except BaseException:
        file.discard()
        raise
    row = uploads.store(db, person, file)
    try:
        db.commit()
    except BaseException:
        # no row, no file: nothing on disk that nothing points to
        uploads.full_path(row).unlink(missing_ok=True)
        raise
    return JSONResponse(status_code=201, content=upload_out(row).model_dump(mode="json"))


def may_see(db, who: Principal, row: Upload) -> bool:
    """Whoever may see the training of the person it belongs to; and a
    sign-off's photo and signatures, whoever may see the learner too."""
    if who.sees(db.get(Person, row.person_id)):
        return True
    learner = uploads.signed_off(db, row.id)
    return learner is not None and who.sees(learner)


@router.get("/uploads/{upload_id}", response_class=Response)
def get_file(upload_id: uuid.UUID, db: DB, who: Who):
    """For the person it belongs to, their supervisor, and managers and
    admins: whoever may see that person's training. A sign-off's photo and
    signatures, sent from the supervisor's phone, for the learner's too."""
    row = db.get(Upload, upload_id)
    if row is None or not may_see(db, who, row):
        raise NotFound(f"no file {upload_id}")
    path = uploads.full_path(row)
    try:
        stat = path.stat()
    except FileNotFoundError:
        # the row is there but the file is not: a volume lost or restored
        # without it. Not found to the caller; someone should look.
        log.warning("upload %s is recorded but missing from disk at %s", upload_id, path)
        raise NotFound(f"no file {upload_id}") from None
    # a PDF under the sandbox shows blank in the browser, so it is saved instead
    shown = "attachment" if row.content_type == "application/pdf" else "inline"
    # sent from disk a piece at a time: a page's video can be 200 MB
    return FileResponse(path, media_type=row.content_type, stat_result=stat,
                        filename=f"{row.id}.{uploads.EXT[row.content_type]}",
                        content_disposition_type=shown,
                        headers={"Cache-Control": "private, no-store",
                                 # opened on its own, it runs nothing and reaches nothing
                                 "Content-Security-Policy": "default-src 'none'; sandbox",
                                 "X-Content-Type-Options": "nosniff"})
