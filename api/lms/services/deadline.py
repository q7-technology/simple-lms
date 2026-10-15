"""An overall deadline for one send. httpx's timeouts (and a socket's) are
for each step: a receiver that sends a byte every few seconds never trips
one and holds the connection as long as it likes. Inside `within(seconds)`,
every connect, read and write the worker's clients make gets no more than
what is left of the deadline, so the send as a whole is done, one way or
the other, by then.

Only looking up the name is left out: the system resolver has its own
limits."""
from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

import httpcore
import httpx

_until: ContextVar[float | None] = ContextVar("send_deadline", default=None)
# a write is made in pieces, each given what is left, so a receiver reading
# slowly can't stretch one long write past the deadline
PIECE = 16 * 1024


@contextmanager
def within(seconds: float) -> Iterator[None]:
    """Everything sent inside is done within `seconds`, all told."""
    token = _until.set(time.monotonic() + seconds)
    try:
        yield
    finally:
        _until.reset(token)


def left(timeout: float | None, error: type[Exception]) -> float | None:
    """This step's timeout, cut to what is left of the deadline; `error`
    once nothing is."""
    until = _until.get()
    if until is None:
        return timeout
    rest = until - time.monotonic()
    if rest <= 0:
        raise error("no answer within the deadline")
    return rest if timeout is None else min(timeout, rest)


class Stream(httpcore.NetworkStream):
    def __init__(self, stream: httpcore.NetworkStream) -> None:
        self._stream = stream

    def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        return self._stream.read(max_bytes, left(timeout, httpcore.ReadTimeout))

    def write(self, buffer: bytes, timeout: float | None = None) -> None:
        for start in range(0, len(buffer), PIECE):
            self._stream.write(buffer[start:start + PIECE],
                               left(timeout, httpcore.WriteTimeout))

    def close(self) -> None:
        self._stream.close()

    def start_tls(self, ssl_context, server_hostname=None, timeout=None):
        return Stream(self._stream.start_tls(ssl_context, server_hostname,
                                             left(timeout, httpcore.ConnectTimeout)))

    def get_extra_info(self, info: str):
        return self._stream.get_extra_info(info)


class Backend(httpcore.NetworkBackend):
    """httpcore's own sockets (or another backend's), held to the deadline."""

    def __init__(self, inner: httpcore.NetworkBackend | None = None) -> None:
        self._inner = inner or httpcore.SyncBackend()

    def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        return Stream(self._inner.connect_tcp(host, port, left(timeout, httpcore.ConnectTimeout),
                                              local_address, socket_options))

    def connect_unix_socket(self, path, timeout=None, socket_options=None):
        return Stream(self._inner.connect_unix_socket(
            path, left(timeout, httpcore.ConnectTimeout), socket_options))

    def sleep(self, seconds: float) -> None:
        self._inner.sleep(seconds)


def client(backend: httpcore.NetworkBackend) -> httpx.Client:
    """A client that connects through `backend`: no redirects followed, no
    proxies or certificates taken from the environment."""
    transport = httpx.HTTPTransport()
    # httpx has no argument for httpcore's network backend, so its pool is
    # made again with this one (the same settings httpx gives it)
    transport._pool = httpcore.ConnectionPool(ssl_context=httpx.create_ssl_context(),
                                              network_backend=backend)
    return httpx.Client(transport=transport, follow_redirects=False, trust_env=False)
