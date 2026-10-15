"""Delivering an event to a webhook, signed as Simple WMS signs its own:
X-LMS-Signature is `sha256=` and the hex HMAC-SHA256 of the exact body,
keyed with the webhook's secret. X-LMS-Event-Id and X-LMS-Event-Type say
what it is before the body is read. The address and secret are the
webhook's as they are when it is sent, so a fixed address or a new secret
applies to what is still waiting.

What the worker won't do for a webhook: connect to an internal address
(loopback, private, link-local, shared, reserved; checked on the address the
name resolves to, where the connection is made, so a name re-pointed inside
is caught too) unless LMS_WEBHOOK_ALLOW_PRIVATE says so; follow a redirect;
read proxies from the environment; wait more than the timeout; or read more
than the start of an answer."""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import secrets
import socket
import time
from urllib.parse import urlsplit

import httpcore
import httpx

from lms.config import get_settings
from lms.models import Outbox
from lms.services.outbox import GiveUp

USER_AGENT = "simple-lms/0.1"
# how much of a refusal's body is kept as its error
SAID = 200


def sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def verify(secret: str, body: bytes, header: str | None) -> bool:
    """What a receiver does: True only if the header is the signature of
    exactly these bytes, compared in constant time."""
    if not secret or not header:
        return False
    return hmac.compare_digest(sign(secret, body).encode(), header.strip().encode())


# --- where a webhook may point --------------------------------------------------

def address_allowed(address: str, allow_private: bool = False) -> bool:
    """Whether the worker may connect to this IP address for a webhook: a
    public one, or (with allow_private) one on this machine or the local
    network. Never an unspecified or multicast one."""
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return False
    if ip.version == 6 and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if ip.is_unspecified or ip.is_multicast:
        return False
    return allow_private or ip.is_global


def _allow_private() -> bool:
    return get_settings().webhook_allow_private


def check_url(url: str) -> str | None:
    """Why this address can't be a webhook's, or None. Catches what can be
    told from the address itself (localhost, an internal IP); a name is
    checked again on what it resolves to each time it is sent to."""
    if _allow_private():
        return None
    host = (urlsplit(url).hostname or "").lower().rstrip(".")
    if host == "localhost" or host.endswith(".localhost"):
        return f"{host} is this machine: a webhook goes to a public address"
    try:
        ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        return None
    if not address_allowed(host):
        return f"{host} is an internal address: a webhook goes to a public address"
    return None


def resolve(host: str, port: int) -> list[str]:
    """Every address the name has, as the connection would look them up."""
    return list(dict.fromkeys(
        info[4][0] for info in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)))


class GuardedBackend(httpcore.NetworkBackend):
    """httpcore's own sockets, refusing to connect to an internal address.
    The name is looked up here and the connection made to the address that
    was checked, so it can't resolve to a public address for the check and
    an internal one for the connection. TLS still checks the certificate
    against the name in the URL."""

    def __init__(self, allow_private: bool = False) -> None:
        self.allow_private = allow_private
        self._sockets = httpcore.SyncBackend()

    def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        try:
            addresses = resolve(host, port)
        except OSError as e:
            raise httpcore.ConnectError(f"{host} could not be looked up: {e}") from e
        refused = [a for a in addresses if not address_allowed(a, self.allow_private)]
        if refused or not addresses:
            raise httpcore.ConnectError(
                f"refused: {host} is an internal address ({', '.join(refused)}); "
                "LMS_WEBHOOK_ALLOW_PRIVATE allows one")
        last: Exception | None = None
        for address in addresses:
            try:
                return self._sockets.connect_tcp(address, port, timeout, local_address,
                                                 socket_options)
            except httpcore.ConnectError as e:
                last = e
        raise last  # type: ignore[misc]

    def connect_unix_socket(self, path, timeout=None, socket_options=None):
        raise httpcore.ConnectError("refused: a webhook is not a local socket")

    def sleep(self, seconds: float) -> None:
        self._sockets.sleep(seconds)


def client(allow_private: bool | None = None) -> httpx.Client:
    """The worker's client for webhooks: guarded, no redirects followed, no
    proxies or certificates taken from the environment."""
    allow = _allow_private() if allow_private is None else allow_private
    transport = httpx.HTTPTransport()
    # httpx has no argument for httpcore's network backend, so its pool is
    # made again with the guarded one (the same settings httpx gives it)
    transport._pool = httpcore.ConnectionPool(ssl_context=httpx.create_ssl_context(),
                                              network_backend=GuardedBackend(allow))
    return httpx.Client(transport=transport, follow_redirects=False, trust_env=False)


# --- sending one ----------------------------------------------------------------

def said(resp: httpx.Response, deadline: float, limit: int = SAID) -> str:
    """The start of what a receiver answered, no more: a huge or dripping
    answer can't hold the worker."""
    got = b""
    for chunk in resp.iter_bytes():
        got += chunk
        if len(got) >= limit * 4 or time.monotonic() > deadline:
            break
    return got.decode(resp.encoding or "utf-8", errors="replace")[:limit]


def deliver(http: httpx.Client, row: Outbox) -> str | None:
    """Post one event to its webhook: None when it answered 2xx, else what
    went wrong. A webhook turned off since is given up on. A redirect is
    not followed: it is a refusal like any other."""
    hook = row.webhook
    if not hook.active:
        raise GiveUp("the webhook was turned off")
    body = json.dumps(row.payload, separators=(",", ":")).encode()
    headers = {
        "Content-Type": "application/json",
        "X-LMS-Signature": sign(hook.secret, body),
        "X-LMS-Event-Id": row.payload["event_id"],
        "X-LMS-Event-Type": row.payload["event_type"],
        "User-Agent": USER_AGENT,
    }
    timeout = get_settings().worker_http_timeout_seconds
    try:
        with http.stream("POST", hook.url, content=body, headers=headers, timeout=timeout,
                         follow_redirects=False) as resp:
            if 200 <= resp.status_code < 300:
                return None
            return f"HTTP {resp.status_code}: {said(resp, time.monotonic() + timeout)}"
    except httpx.HTTPError as e:
        return f"{type(e).__name__}: {e}"


def new_secret() -> str:
    """What a webhook's bodies are signed with: 256 random bits."""
    return "whsec_" + secrets.token_urlsafe(32)
