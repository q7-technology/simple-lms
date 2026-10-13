"""Files: sent by the learner app before the ticket or signature that names
them, and shown only to who may see the person they belong to."""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from lms.api.deps import DB, Principal, Who, require
from lms.api.errors import NotFound, Refused
from lms.models import Person, Upload
from lms.services import uploads

router = APIRouter(tags=["uploads"])
log = logging.getLogger("lms.uploads")


class UploadOut(BaseModel):
    id: uuid.UUID
    purpose: str
    content_type: str
    size_bytes: int
    created_at: datetime


def upload_out(row: Upload) -> UploadOut:
    return UploadOut(id=row.id, purpose=row.purpose, content_type=row.content_type,
                     size_bytes=row.size_bytes, created_at=row.created_at)


@dataclass(frozen=True)
class Sent:
    purpose: str
    data: bytes


async def sent(request: Request, purpose: Literal["ticket", "signature"] = Query()) -> Sent:
    """The purpose, then the body, read no further than that purpose's limit.
    A wrong purpose is refused before a byte of the body is read."""
    _, limit = uploads.PURPOSES[purpose]
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit:
        raise Refused(413, "too_large", "that file is too big")
    data = bytearray()
    async for chunk in request.stream():
        data += chunk
        if len(data) > limit:
            raise Refused(413, "too_large", "that file is too big")
    return Sent(purpose=purpose, data=bytes(data))


@router.post("/uploads", status_code=201, response_model=UploadOut)
def send_file(db: DB, who: Principal = require("training:write"), file: Sent = Depends(sent)):
    """The file as the body (what counts is its first bytes, not its
    Content-Type). The caller is checked before the body is read
    (dependencies run in order)."""
    row = uploads.store(db, who.person, file.purpose, file.data)
    try:
        db.commit()
    except BaseException:
        # no row, no file: nothing on disk that nothing points to
        uploads.full_path(row).unlink(missing_ok=True)
        raise
    return JSONResponse(status_code=201, content=upload_out(row).model_dump(mode="json"))


@router.get("/uploads/{upload_id}", response_class=Response)
def get_file(upload_id: uuid.UUID, db: DB, who: Who):
    """For the person it belongs to, their supervisor, and managers and
    admins: whoever may see that person's training."""
    row = db.get(Upload, upload_id)
    if row is None or not who.sees(db.get(Person, row.person_id)):
        raise NotFound(f"no file {upload_id}")
    try:
        content = uploads.full_path(row).read_bytes()
    except FileNotFoundError:
        # the row is there but the file is not: a volume lost or restored
        # without it. Not found to the caller; someone should look.
        log.warning("upload %s is recorded but missing from disk at %s",
                    upload_id, uploads.full_path(row))
        raise NotFound(f"no file {upload_id}") from None
    # a PDF under the sandbox shows blank in the browser, so it is saved instead
    shown = "attachment" if row.content_type == "application/pdf" else "inline"
    return Response(content=content, media_type=row.content_type,
                    headers={"Cache-Control": "private, no-store",
                             # opened on its own, it runs nothing and reaches nothing
                             "Content-Security-Policy": "default-src 'none'; sandbox",
                             "Content-Disposition":
                                 f'{shown}; filename="{row.id}.{uploads.EXT[row.content_type]}"',
                             "X-Content-Type-Options": "nosniff"})
