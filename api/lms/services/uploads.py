"""Files people send: a ticket's photos (or a PDF of it) and policy
signatures. Kept on disk under LMS_UPLOAD_DIR, one file each, named by a
random id; the row says whose it is and what it is. What a file is comes
from its first bytes, never from what the request says."""
from __future__ import annotations

import hashlib
import os
import tempfile
import uuid
from pathlib import Path

from sqlalchemy.orm import Session as Db

from lms.api.errors import Refused
from lms.config import get_settings
from lms.models import Person, Upload

# what each purpose may be, and how big: 20 MB for a ticket (the design's
# limit for anything that is not a video); a signature is a few kB
PURPOSES = {
    "ticket": ({"image/jpeg", "image/png", "application/pdf"}, 20_000_000),
    "signature": ({"image/png"}, 1_000_000),
}
MAGIC = {"image/png": b"\x89PNG\r\n\x1a\n", "image/jpeg": b"\xff\xd8\xff",
         "application/pdf": b"%PDF-"}
EXT = {"image/png": "png", "image/jpeg": "jpg", "application/pdf": "pdf"}


def sniff(data: bytes) -> str | None:
    for content_type, magic in MAGIC.items():
        if data.startswith(magic):
            return content_type
    return None


def full_path(row: Upload) -> Path:
    return Path(get_settings().upload_dir) / row.path


def _write(target: Path, data: bytes) -> None:
    """All of it or none of it: a half-written file never has the real name."""
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=".upload-")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, target)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def store(db: Db, person: Person, purpose: str, data: bytes) -> Upload:
    allowed, limit = PURPOSES[purpose]
    if len(data) > limit:
        raise Refused(413, "too_large", f"a {purpose} file may be {limit // 1_000_000} MB at most")
    content_type = sniff(data)
    if content_type not in allowed:
        wanted = ", ".join(sorted(EXT[t].upper() for t in allowed))
        raise Refused(415, "unsupported_type", f"a {purpose} file must be one of: {wanted}")
    upload_id = uuid.uuid4()
    relative = f"{upload_id.hex[:2]}/{upload_id}.{EXT[content_type]}"
    _write(Path(get_settings().upload_dir) / relative, data)
    row = Upload(id=upload_id, person_id=person.id, purpose=purpose, content_type=content_type,
                 size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest(), path=relative)
    db.add(row)
    db.flush()
    return row


def mine(db: Db, person: Person, upload_id: uuid.UUID | None, purpose: str) -> Upload | None:
    """One of this person's own files for this purpose, or None."""
    if upload_id is None:
        return None
    row = db.get(Upload, upload_id)
    if row is None or row.person_id != person.id or row.purpose != purpose:
        return None
    return row
