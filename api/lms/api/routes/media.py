"""A module page's files, opened by a link the API made (services/media.py)
rather than with the token: a picture shown, a PDF saved, a video played
and seeked with HTTP Range requests, as phones need."""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse, Response

from lms.api.deps import DB
from lms.api.errors import NotFound
from lms.models import Upload
from lms.services import media, uploads

router = APIRouter(tags=["media"])
log = logging.getLogger("lms.media")


@router.get("/media/{upload_id}", response_class=Response)
def open_media(upload_id: uuid.UUID, db: DB,
               # bounded so a made-up link is a 404 or 422, never a database error
               session: int = Query(ge=1, le=2**31 - 1),
               expires: int = Query(ge=0, le=2**40),
               sig: str = Query(pattern="^[0-9a-f]{64}$")):
    """Whoever holds the link, while it lasts. A link that is wrong, expired
    or for a session that has ended is a 404, as is a file that is not a
    module's."""
    row = db.get(Upload, upload_id)
    if (row is None or row.purpose not in media.PURPOSES
            or not media.opens(db, upload_id, session, expires, sig)):
        raise NotFound(f"no file {upload_id}")
    db.commit()  # keeps the touch on the session
    path = uploads.full_path(row)
    try:
        stat = path.stat()
    except FileNotFoundError:
        log.warning("upload %s is recorded but missing from disk at %s", upload_id, path)
        raise NotFound(f"no file {upload_id}") from None
    # a PDF under the sandbox shows blank in the browser, so it is saved instead
    shown = "attachment" if row.content_type == "application/pdf" else "inline"
    return FileResponse(path, media_type=row.content_type, stat_result=stat,
                        filename=f"{row.id}.{uploads.EXT[row.content_type]}",
                        content_disposition_type=shown,
                        headers={"Cache-Control": "private, no-store",
                                 # opened on its own, it runs nothing and reaches nothing
                                 "Content-Security-Policy": "default-src 'none'; sandbox",
                                 "X-Content-Type-Options": "nosniff"})
