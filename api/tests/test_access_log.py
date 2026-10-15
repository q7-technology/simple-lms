"""The access log keeps every request, but never a media link's signature:
whoever reads the logs could open the file with it."""
import logging

from uvicorn.logging import AccessFormatter

import lms.api.app  # noqa: F401 - the app puts the filter on uvicorn's access log
from lms.api.logs import NoMediaSignatures

SIG = "ab" * 32


def logged(path: str) -> str:
    """What uvicorn's access log writes for a GET of this path."""
    record = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1,
                               '%s - "%s %s HTTP/%s" %d',
                               ("127.0.0.1:5000", "GET", path, "1.1", 200), None)
    assert NoMediaSignatures().filter(record)
    return AccessFormatter('%(client_addr)s - "%(request_line)s" %(status_code)s',
                           use_colors=False).format(record)


def test_a_media_links_signature_is_not_logged():
    line = logged(f"/v1/media/0b5e?session=1&expires=2&sig={SIG}")
    assert SIG not in line
    assert '"GET /v1/media/0b5e HTTP/1.1" 200 OK' in line


def test_any_other_request_is_logged_as_it_came():
    line = logged("/v1/people?q=sam&sig=1")
    assert line == '127.0.0.1:5000 - "GET /v1/people?q=sam&sig=1 HTTP/1.1" 200 OK'


def test_the_app_puts_it_on_uvicorns_access_log():
    filters = logging.getLogger("uvicorn.access").filters
    assert any(isinstance(f, NoMediaSignatures) for f in filters)
