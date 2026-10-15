"""A Microsoft Entra ID of the tests' own: it signs ID tokens with a key it
makes, publishes that key as the tenant's, and swaps a code for a token as
Microsoft does, checking the client secret, the redirect URI and PKCE. The
tests put it where lms.services.entra talks to Microsoft, so nothing goes
over the network.

Run on its own, it is a stand-in to try signing in with Microsoft by hand
(docs/plans, step 5's walkthrough): its sign-in page asks for an email and an
object id instead of a password.

    .venv/bin/python tests/fake_entra.py --port 8099 --cert cert.pem --key key.pem \\
        --tenant <LMS_ENTRA_TENANT_ID> --client <LMS_ENTRA_CLIENT_ID> --secret <…>

The API talks only to an https address (LMS_ENTRA_AUTHORITY), so it serves
https with a certificate the API's container trusts (SSL_CERT_FILE).
"""
from __future__ import annotations

import base64
import hashlib
import html
import json
import secrets
import time
import urllib.parse
import uuid
from typing import Any

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

TENANT = "6f1c2a4e-7b3d-4e8f-9a01-2b3c4d5e6f70"
CLIENT = "0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"
SECRET = "fake-entra-client-secret"
AUTHORITY = "https://login.microsoftonline.com"
PUBLIC_URL = "https://lms.example.com.au"


def new_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _s256(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


class FakeEntra:
    def __init__(self, tenant: str = TENANT, client: str = CLIENT, secret: str = SECRET,
                 authority: str = AUTHORITY):
        self.tenant, self.client, self.secret, self.authority = tenant, client, secret, authority
        self.key, self.kid = new_key(), "key-1"
        # codes handed out and not yet swapped: code -> what it was given for
        self.codes: dict[str, dict[str, Any]] = {}
        self.key_fetches = 0
        self.token_requests: list[dict[str, str]] = []

    # --- what a test does ---------------------------------------------------

    @property
    def issuer(self) -> str:
        return f"{self.authority}/{self.tenant}/v2.0"

    def rotate(self) -> None:
        """Microsoft rolls its signing key over."""
        n = int(self.kid.rsplit("-", 1)[1]) + 1
        self.key, self.kid = new_key(), f"key-{n}"

    def claims(self, **more) -> dict[str, Any]:
        """An ID token's claims for someone in this tenant; `more` changes
        them (None takes a claim out)."""
        now = int(time.time())
        out = {"iss": self.issuer, "aud": self.client, "tid": self.tenant,
               "oid": str(uuid.uuid4()), "sub": secrets.token_urlsafe(16), "name": "Someone",
               "email": "someone@example.com.au", "xms_edov": True,
               "preferred_username": "someone@example.com.au", "iat": now, "nbf": now,
               "exp": now + 3600, "ver": "2.0"}
        out.update(more)
        return {k: v for k, v in out.items() if v is not None}

    def sign(self, claims: dict[str, Any], key=None, kid: str | None = None,
             alg: str = "RS256") -> str:
        if alg == "none":
            return jwt.encode(claims, None, algorithm="none")
        if alg == "HS256":
            return jwt.encode(claims, "x" * 32, algorithm="HS256", headers={"kid": kid or self.kid})
        return jwt.encode(claims, key or self.key, algorithm=alg, headers={"kid": kid or self.kid})

    def approve(self, url: str, *, token: str | None = None, **claims) -> tuple[str, str]:
        """The person signs in at Microsoft's page `url`: the code and state
        Microsoft sends them back with. The ID token the code is swapped for
        has these claims (and the nonce asked for), or is `token` as it is."""
        parts = urllib.parse.urlsplit(url)
        q = dict(urllib.parse.parse_qsl(parts.query))
        assert f"{parts.scheme}://{parts.netloc}{parts.path}" == \
            f"{self.authority}/{self.tenant}/oauth2/v2.0/authorize"
        assert (q["client_id"], q["response_type"], q["code_challenge_method"]) == \
            (self.client, "code", "S256")
        assert set(q["scope"].split()) >= {"openid", "profile", "email"}
        code = secrets.token_urlsafe(24)
        self.codes[code] = {"challenge": q["code_challenge"], "redirect_uri": q["redirect_uri"],
                            "token": token or self.sign(self.claims(nonce=q["nonce"], **claims))}
        return code, q["state"]

    # --- what Microsoft answers ---------------------------------------------

    def jwks(self) -> dict[str, Any]:
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key()))
        return {"keys": [{**jwk, "kid": self.kid, "use": "sig", "alg": "RS256"}]}

    def get(self, url: str) -> dict[str, Any]:
        assert url == f"{self.authority}/{self.tenant}/discovery/v2.0/keys", url
        self.key_fetches += 1
        return self.jwks()

    def post(self, url: str, data: dict[str, str]) -> dict[str, Any]:
        assert url == f"{self.authority}/{self.tenant}/oauth2/v2.0/token", url
        self.token_requests.append(data)
        given = self.codes.pop(data.get("code", ""), None)
        if data.get("client_id") != self.client or data.get("client_secret") != self.secret:
            return {"error": "invalid_client", "error_description": "AADSTS7000215: bad secret"}
        if given is None:
            return {"error": "invalid_grant", "error_description": "AADSTS70008: code expired"}
        if data.get("redirect_uri") != given["redirect_uri"]:
            return {"error": "invalid_grant", "error_description": "AADSTS50148: redirect_uri"}
        if _s256(data.get("code_verifier", "")) != given["challenge"]:
            return {"error": "invalid_grant", "error_description": "AADSTS501481: verifier"}
        return {"token_type": "Bearer", "scope": "openid profile email",
                "id_token": given["token"], "access_token": "not-used"}


# --- run on its own, for the walkthrough -----------------------------------------

PAGE = """<!doctype html><meta charset="utf-8"><title>Fake Microsoft sign-in</title>
<body style="font-family:sans-serif;max-width:420px;margin:40px auto">
<h1>Fake Microsoft sign-in</h1><p>A stand-in for trying Simple LMS. Not Microsoft.</p>
<form method="post" action="approve">{hidden}
<p><label>Email<br><input name="email" size="40" value="{email}"></label></p>
<p><label>Object id (oid)<br><input name="oid" size="40" value="{oid}"></label></p>
<p><label><input type="checkbox" name="xms_edov" value="1" checked> The tenant owns this
email's domain (xms_edov)</label></p>
<p><button>Sign in</button></p></form>"""


def serve(port: int, fake: FakeEntra, cert: str, key: str) -> None:
    import ssl
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    base = f"/{fake.tenant}/"

    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, body: str | dict, kind: str = "application/json",
                  headers: dict[str, str] | None = None):
            data = (json.dumps(body) if isinstance(body, dict) else body).encode()
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(data)))
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            path, _, query = self.path.partition("?")
            if path == base + "discovery/v2.0/keys":
                return self._send(200, fake.get(fake.authority + path))
            if path == base + "oauth2/v2.0/authorize":
                hidden = "".join(f'<input type="hidden" name="{html.escape(k)}" value="{html.escape(v)}">'
                                 for k, v in urllib.parse.parse_qsl(query))
                return self._send(200, PAGE.format(hidden=hidden, email="", oid=uuid.uuid4()),
                                  "text/html; charset=utf-8")
            self._send(404, {"error": "not_found"})

        def do_POST(self):
            form = dict(urllib.parse.parse_qsl(
                self.rfile.read(int(self.headers.get("Content-Length", 0))).decode()))
            if self.path == base + "oauth2/v2.0/token":
                answer = fake.post(fake.authority + self.path, form)
                return self._send(400 if "error" in answer else 200, answer)
            if self.path == base + "oauth2/v2.0/approve":
                ask = {k: form.pop(k) for k in ("email", "oid") if k in form}
                edov = form.pop("xms_edov", None) == "1"
                url = (f"{fake.authority}{base}oauth2/v2.0/authorize?"
                       + urllib.parse.urlencode(form))
                code, state = fake.approve(url, email=ask.get("email") or None,
                                           oid=ask.get("oid") or str(uuid.uuid4()),
                                           xms_edov=edov or None,
                                           name=ask.get("email") or "Someone")
                back = form["redirect_uri"] + "?" + urllib.parse.urlencode(
                    {"code": code, "state": state})
                return self._send(302, "", "text/plain", {"Location": back})
            self._send(404, {"error": "not_found"})

    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(cert, key)
    server.socket = tls.wrap_socket(server.socket, server_side=True)
    print(f"fake Entra on https://0.0.0.0:{port}{base} (Ctrl-C stops it)")
    server.serve_forever()


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--port", type=int, default=8099)
    p.add_argument("--authority", help="the address the API and the browser use for it, "
                                       "e.g. https://192.168.1.20:8099 (LMS_ENTRA_AUTHORITY)")
    p.add_argument("--cert", required=True, help="its certificate (PEM), for https")
    p.add_argument("--key", required=True, help="the certificate's private key (PEM)")
    p.add_argument("--tenant", default=TENANT)
    p.add_argument("--client", default=CLIENT)
    p.add_argument("--secret", default=SECRET)
    a = p.parse_args()
    serve(a.port, FakeEntra(a.tenant, a.client, a.secret,
                            (a.authority or f"https://127.0.0.1:{a.port}").rstrip("/")),
          a.cert, a.key)
