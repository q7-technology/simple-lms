"""Files people send: a ticket's photos (or a PDF of it), policy
signatures, and a module page's picture, PDF or video. Kept on disk under
LMS_UPLOAD_DIR, one file each, named by a random id; the row says whose it
is and what it is. What a file is comes from its first bytes, never from
what the request says. A file is written to disk as it arrives, never held
in memory whole: a video may be 200 MB."""
from __future__ import annotations

import hashlib
import os
import tempfile
import uuid
from pathlib import Path

from sqlalchemy import exists, or_, select
from sqlalchemy.orm import Session as Db

from lms.api.errors import Refused
from lms.config import get_settings
from lms.models import Person, TicketSubmission, Upload

# what each purpose may be, and how big: 200 MB for a video, 20 MB for
# anything else (the design's limits); a signature is a few kB
PURPOSES = {
    "ticket": ({"image/jpeg", "image/png", "application/pdf"}, 20_000_000),
    "signature": ({"image/png"}, 1_000_000),
    "page-image": ({"image/jpeg", "image/png"}, 20_000_000),
    "page-pdf": ({"application/pdf"}, 20_000_000),
    "page-video": ({"video/mp4", "video/webm"}, 200_000_000),
}
# who may send each: anyone, for their own training; an editor, for a module
SENDERS = {
    "ticket": "training:write",
    "signature": "training:write",
    "page-image": "competencies:write",
    "page-pdf": "competencies:write",
    "page-video": "competencies:write",
}
MAGIC = {"image/png": b"\x89PNG\r\n\x1a\n", "image/jpeg": b"\xff\xd8\xff",
         "application/pdf": b"%PDF-"}
EXT = {"image/png": "png", "image/jpeg": "jpg", "application/pdf": "pdf",
       "video/mp4": "mp4", "video/webm": "webm"}
# enough of the start of a file to say what it is
HEAD = 64
# an MP4 video's ftyp box names one of these as its major brand. A HEIC or
# AVIF photo, an M4A sound and a QuickTime .mov (which most browsers won't
# play) start the same way under brands of their own.
MP4_BRANDS = {b"isom", b"iso2", b"iso4", b"iso5", b"iso6", b"mp41", b"mp42", b"avc1", b"dash",
              b"M4V "}


EBML = b"\x1a\x45\xdf\xa3"
DOCTYPE = b"\x42\x82"


def _vint(data: bytes, at: int) -> tuple[int, int] | None:
    """An EBML variable-length size at `at`: (its value, where it ends)."""
    if at >= len(data) or data[at] == 0:
        return None
    width = 9 - data[at].bit_length()  # the leading zeros, plus one
    if at + width > len(data):
        return None
    value = data[at] & (0xFF >> width)
    for byte in data[at + 1:at + width]:
        value = value << 8 | byte
    return value, at + width


def _doctype(data: bytes) -> bytes | None:
    """The DocType in a Matroska file's EBML header ("webm" or "matroska"),
    read element by element; None if the header isn't all in `data`."""
    if not data.startswith(EBML) or (size := _vint(data, len(EBML))) is None:
        return None
    end = size[1] + size[0]
    at = size[1]
    while at < min(end, len(data)):
        # an element ID keeps its length marker: 1 to 4 bytes
        width = 9 - data[at].bit_length() if data[at] else 9
        if width > 4 or (size := _vint(data, at + width)) is None:
            return None
        element, (length, start) = data[at:at + width], size
        if start + length > end or start + length > len(data):
            return None
        if element == DOCTYPE:
            return data[start:start + length].rstrip(b"\x00")
        at = start + length
    return None


def sniff(data: bytes) -> str | None:
    for content_type, magic in MAGIC.items():
        if data.startswith(magic):
            return content_type
    if data[4:8] == b"ftyp" and data[8:12] in MP4_BRANDS:
        return "video/mp4"
    # a WebM is a Matroska file whose header says webm (an .mkv says matroska)
    if _doctype(data[:HEAD]) == b"webm":
        return "video/webm"
    return None


def full_path(row: Upload) -> Path:
    return Path(get_settings().upload_dir) / row.path


def too_large(purpose: str) -> Refused:
    _, limit = PURPOSES[purpose]
    return Refused(413, "too_large", f"a {purpose} file may be {limit // 1_000_000} MB at most")


class Incoming:
    """A file as it arrives: written to a temporary file beside where it
    will be kept, counted and hashed as it comes, and refused the moment it
    passes its purpose's limit. Nothing has the real name until store()."""

    def __init__(self, purpose: str):
        self.purpose = purpose
        self.size = 0
        self.head = b""
        self._hash = hashlib.sha256()
        folder = Path(get_settings().upload_dir)
        folder.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(dir=folder, prefix=".upload-")
        self.path = Path(name)
        self._file = os.fdopen(fd, "wb")

    def write(self, chunk: bytes) -> None:
        self.size += len(chunk)
        if self.size > PURPOSES[self.purpose][1]:
            raise too_large(self.purpose)
        if len(self.head) < HEAD:
            self.head += chunk[:HEAD - len(self.head)]
        self._hash.update(chunk)
        self._file.write(chunk)

    def finish(self) -> str:
        """All of it on disk, and what it is; refused if it is not what its
        purpose may be."""
        self._file.flush()
        os.fsync(self._file.fileno())
        self._file.close()
        allowed, _ = PURPOSES[self.purpose]
        content_type = sniff(self.head)
        if content_type not in allowed:
            wanted = ", ".join(sorted(EXT[t].upper() for t in allowed))
            raise Refused(415, "unsupported_type",
                          f"a {self.purpose} file must be one of: {wanted}")
        self.content_type = content_type
        return content_type

    @property
    def sha256(self) -> str:
        return self._hash.hexdigest()

    def discard(self) -> None:
        self._file.close()
        self.path.unlink(missing_ok=True)


def store(db: Db, person: Person, file: Incoming) -> Upload:
    """The row, then the file under its real name. A row that can't be
    saved leaves nothing on disk; what is left to go wrong is the commit,
    and the route removes the file then."""
    try:
        upload_id = uuid.uuid4()
        relative = f"{upload_id.hex[:2]}/{upload_id}.{EXT[file.content_type]}"
        row = Upload(id=upload_id, person_id=person.id, purpose=file.purpose,
                     content_type=file.content_type, size_bytes=file.size, sha256=file.sha256,
                     path=relative)
        db.add(row)
        db.flush()
        target = Path(get_settings().upload_dir) / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(file.path, target)
        return row
    finally:
        file.discard()


def mine(db: Db, person: Person, upload_id: uuid.UUID | None, purpose: str) -> Upload | None:
    """One of this person's own files for this purpose, or None."""
    if upload_id is None:
        return None
    row = db.get(Upload, upload_id)
    if row is None or row.person_id != person.id or row.purpose != purpose:
        return None
    return row


def on_a_ticket(db: Db, upload_id: uuid.UUID) -> bool:
    """A photo goes on one ticket only, waiting or decided: what a manager
    checked can't turn up again on another. The sender's row is locked while
    they send, so two at once can't both find it unused."""
    return db.execute(select(exists().where(or_(
        TicketSubmission.front_upload_id == upload_id,
        TicketSubmission.back_upload_id == upload_id)))).scalar()
