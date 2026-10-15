"""A server that answers a byte at a time, to show the worker's deadline."""
import socket
import threading
import time

import pytest

from lms.config import get_settings


class Trickler:
    """A server on this machine that accepts a connection and then sends
    `answer` a byte every `every` seconds: never long enough between bytes
    for a per-read timeout, and never done."""

    def __init__(self, answer: bytes, every: float = 0.1):
        self.answer, self.every = answer, every
        self.stop = threading.Event()
        self.listener = socket.create_server(("127.0.0.1", 0))
        self.port = self.listener.getsockname()[1]
        self.connections: list[socket.socket] = []
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        self.listener.settimeout(0.1)
        while not self.stop.is_set():
            try:
                conn, _ = self.listener.accept()
            except OSError:
                continue
            self.connections.append(conn)
            threading.Thread(target=self._drip, args=(conn,), daemon=True).start()

    def _drip(self, conn):
        for byte in self.answer:
            if self.stop.wait(self.every):
                return
            try:
                conn.sendall(bytes([byte]))
            except OSError:
                return

    def close(self):
        self.stop.set()
        self.listener.close()
        for c in self.connections:
            c.close()


@pytest.fixture
def trickler():
    made = []

    def make(answer=b"HTTP/1.1 200 OK\r\n" + b"X-Slow: " + b"y" * 5000 + b"\r\n\r\n",
             every=0.1):
        t = Trickler(answer, every)
        made.append(t)
        return t

    yield make
    for t in made:
        t.close()


@pytest.fixture
def short(monkeypatch):
    """A second for each read, two for the whole send."""
    monkeypatch.setattr(get_settings(), "worker_http_timeout_seconds", 1.0)
    monkeypatch.setattr(get_settings(), "worker_send_deadline_seconds", 2.0)
    monkeypatch.setattr(get_settings(), "webhook_allow_private", True)


def timed(call):
    start = time.monotonic()
    result = call()
    return result, time.monotonic() - start
