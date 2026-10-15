"""The API's logs. uvicorn's access log records each request's full path,
query string and all, and a media link's query string carries its
signature: anyone reading the logs could open the file with it. So a
/v1/media request is logged by its path alone."""
from __future__ import annotations

import logging

MEDIA = "/v1/media/"


class NoMediaSignatures(logging.Filter):
    """Drops the query string from a /v1/media request's access log line.
    uvicorn's access record args are (client_addr, method, full_path,
    http_version, status_code)."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) == 5 and isinstance(args[2], str) \
                and args[2].startswith(MEDIA):
            record.args = (args[0], args[1], args[2].split("?", 1)[0], *args[3:])
        return True


def install() -> None:
    """uvicorn configures its loggers before it imports the app, so the
    filter put on here, at import, stays on."""
    access = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, NoMediaSignatures) for f in access.filters):
        access.addFilter(NoMediaSignatures())
