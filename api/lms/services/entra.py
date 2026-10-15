"""Signing in with Microsoft Entra ID: OpenID Connect's authorisation code
flow with PKCE, done by the API for both apps. Microsoft sends the person
back to the API with a code; the API swaps it for an ID token over its own
connection, checks the token (Microsoft's signature, by the tenant's
published keys; issuer, audience, times, nonce, tenant), and matches it to a
person. Nobody is ever created here: someone Simple LMS doesn't know is
refused. Only the ID token is used: no access token is kept or sent on."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session as Db

from lms.config import Settings
from lms.models import Person

log = logging.getLogger("lms.entra")

SCOPE = "openid profile email"
# a minute either way between Microsoft's clock and ours
LEEWAY = 60
# the tenant's signing keys, fetched again after a day, or sooner when a
# token names a key we don't have (Microsoft has rolled them over), but not
# within 5 minutes of the last fetch: a token naming a made-up key is
# refused without asking Microsoft every time
KEYS_FOR = 24 * 3600
REFETCH_AFTER = 5 * 60
TIMEOUT = 10


class EntraError(Exception):
    """Microsoft's answer could not be used. The person is told only that
    signing in with Microsoft didn't work; the log says why."""


def issuer(s: Settings) -> str:
    return f"{s.entra_authority}/{s.entra_tenant_id}/v2.0"


def _endpoint(s: Settings, path: str) -> str:
    return f"{s.entra_authority}/{s.entra_tenant_id}/{path}"


def redirect_uri(public_url: str) -> str:
    """Registered in Entra as the app's Web redirect URI: under the web
    address in Settings (or LMS_PUBLIC_URL)."""
    return f"{public_url}/v1/auth/entra/callback"


def challenge(verifier: str) -> str:
    """PKCE's S256: the verifier's SHA-256, base64url without padding."""
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def authorise_url(s: Settings, public_url: str, *, state: str, nonce: str, verifier: str,
                  prompt: str) -> str:
    query = urllib.parse.urlencode({
        "client_id": s.entra_client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri(public_url),
        "response_mode": "query",
        "scope": SCOPE,
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge(verifier),
        "code_challenge_method": "S256",
        "prompt": prompt,
    })
    return f"{_endpoint(s, 'oauth2/v2.0/authorize')}?{query}"


# --- talking to Microsoft (tests put a stand-in here) --------------------------

def _https(url: str) -> str:
    """Only ever https: urllib would open http: and file: addresses too."""
    if urllib.parse.urlsplit(url).scheme != "https":
        raise ValueError(f"not an https address: {url}")
    return url


def fetch_json(url: str) -> Any:
    with urllib.request.urlopen(_https(url), timeout=TIMEOUT) as r:
        return json.load(r)


def post_form(url: str, data: dict[str, str]) -> dict[str, Any]:
    """Microsoft's JSON answer, an error ({"error", "error_description"}) as
    much as a token."""
    request = urllib.request.Request(_https(url), data=urllib.parse.urlencode(data).encode(),
                                     headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        try:
            return json.load(e)
        except ValueError:
            return {"error": f"http_{e.code}"}


# --- the tenant's signing keys ---------------------------------------------------

class _Keys:
    def __init__(self):
        self.lock = threading.Lock()
        self.by_kid: dict[str, Any] = {}
        self.fetched_at: float | None = None


_keys = _Keys()
monotonic = time.monotonic


def forget_keys() -> None:
    """Fetch the keys afresh next time (the tests start each one clean)."""
    global _keys
    _keys = _Keys()


def _fetch_keys(s: Settings) -> dict[str, Any]:
    answer = fetch_json(_endpoint(s, "discovery/v2.0/keys"))
    if not isinstance(answer, dict) or not isinstance(answer.get("keys"), list):
        raise ValueError("Microsoft's answer is not a list of keys")
    found = {}
    for jwk in answer["keys"]:
        if not isinstance(jwk, dict):
            continue
        if jwk.get("kty") != "RSA" or jwk.get("use", "sig") != "sig" or "kid" not in jwk:
            continue
        try:
            found[jwk["kid"]] = jwt.PyJWK(jwk, algorithm="RS256").key
        except jwt.PyJWTError:
            continue
    return found


def signing_key(s: Settings, kid: str) -> Any:
    with _keys.lock:
        age = None if _keys.fetched_at is None else monotonic() - _keys.fetched_at
        stale = age is None or age >= KEYS_FOR
        if stale or (kid not in _keys.by_kid and age >= REFETCH_AFTER):
            try:
                _keys.by_kid = _fetch_keys(s)
            except (OSError, ValueError) as e:
                raise EntraError(f"could not fetch the tenant's signing keys: {e}") from e
            _keys.fetched_at = monotonic()
        key = _keys.by_kid.get(kid)
    if key is None:
        raise EntraError(f"the ID token is signed by a key the tenant doesn't publish: {kid}")
    return key


# --- the ID token ------------------------------------------------------------------

def check_id_token(s: Settings, token: str, nonce: str) -> dict[str, Any]:
    """The token's claims, once it is Microsoft's, for this app, from this
    tenant, current, and for this sign-in; EntraError otherwise."""
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as e:
        raise EntraError(f"not an ID token: {e}") from e
    if header.get("alg") != "RS256":
        raise EntraError(f"an ID token signed with {header.get('alg')!r}, not RS256")
    key = signing_key(s, str(header.get("kid")))
    try:
        claims = jwt.decode(token, key, algorithms=["RS256"], audience=s.entra_client_id,
                            issuer=issuer(s), leeway=LEEWAY,
                            options={"require": ["exp", "nbf", "iat", "iss", "aud", "nonce",
                                                 "tid", "oid"]})
    except jwt.PyJWTError as e:
        raise EntraError(f"the ID token was refused: {e}") from e
    if not hmac.compare_digest(str(claims["nonce"]), nonce):
        raise EntraError("the ID token is for another sign-in (its nonce)")
    if claims["tid"] != s.entra_tenant_id:
        raise EntraError(f"the ID token is from another tenant: {claims['tid']}")
    return claims


def redeem(s: Settings, public_url: str, code: str, verifier: str,
           nonce: str) -> dict[str, Any]:
    """Swap Microsoft's code for an ID token, over the API's own connection,
    and check it."""
    try:
        answer = post_form(_endpoint(s, "oauth2/v2.0/token"), {
            "grant_type": "authorization_code",
            "client_id": s.entra_client_id,
            "client_secret": s.entra_client_secret,
            "code": code,
            "redirect_uri": redirect_uri(public_url),
            "code_verifier": verifier,
            "scope": SCOPE,
        })
    except (OSError, ValueError) as e:
        raise EntraError(f"could not reach Microsoft: {e}") from e
    if "id_token" not in answer:
        raise EntraError(f"Microsoft refused the code: {answer.get('error')}: "
                         f"{answer.get('error_description', '')}".strip())
    return check_id_token(s, answer["id_token"], nonce)


# --- who it is -------------------------------------------------------------------

def _verified_email(claims: dict[str, Any]) -> str | None:
    """The email claim, only when Microsoft says the tenant owns its domain
    (the optional claim xms_edov). preferred_username is never used: it is
    a sign-in name, not a checked email."""
    email = claims.get("email")
    if not isinstance(email, str) or claims.get("xms_edov") not in (True, 1, "1", "true"):
        return None
    return email.strip().lower() or None


def match(db: Db, claims: dict[str, Any]) -> Person | None:
    """The person this is: by their Entra object id once they have signed in
    with Microsoft before, else by a verified email, keeping the object id
    from then on. Nobody, or someone deactivated, is None: never created."""
    oid = str(claims["oid"])
    person = db.execute(select(Person).where(Person.entra_oid == oid)
                        .with_for_update()).scalar_one_or_none()
    if person is None:
        email = _verified_email(claims)
        if email is None:
            return None
        person = db.execute(select(Person).where(Person.email == email)
                            .with_for_update()).scalar_one_or_none()
        # someone already linked to another Microsoft account keeps it
        if person is None or person.entra_oid is not None:
            return None
        if person.active:
            person.entra_oid = oid
    return person if person.active else None
