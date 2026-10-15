"""An ID token counts only when it is Microsoft's (signed by a key the
tenant publishes), for this app, from this tenant, current, and for this
sign-in. The keys are fetched once and again when Microsoft rolls them."""
import time

import pytest

from fake_entra import PUBLIC_URL, new_key
from lms.config import get_settings
from lms.services import entra as service
from lms.services.entra import EntraError

NONCE = "the-nonce-for-this-sign-in"


def check(fake, token: str):
    return service.check_id_token(get_settings(), token, NONCE)


def test_microsofts_token_for_this_sign_in_is_taken(entra):
    claims = check(entra, entra.sign(entra.claims(nonce=NONCE, oid="oid-kim")))
    assert (claims["oid"], claims["tid"]) == ("oid-kim", entra.tenant)


@pytest.mark.parametrize("change, why", [
    ({"iss": "https://login.microsoftonline.com/someone-else/v2.0"}, "Invalid issuer"),
    ({"aud": "another-app"}, "Audience doesn't match"),
    ({"exp": int(time.time()) - 120}, "Signature has expired"),
    ({"nbf": int(time.time()) + 600}, "not yet valid"),
    ({"nonce": "another-sign-in"}, "its nonce"),
    ({"nonce": None}, 'Token is missing the "nonce" claim'),
    ({"oid": None}, 'Token is missing the "oid" claim'),
    ({"tid": "9d8c7b6a-0000-4000-8000-000000000000"}, "another tenant"),
])
def test_anything_else_is_refused(entra, change, why):
    with pytest.raises(EntraError, match=why):
        check(entra, entra.sign(entra.claims(**{"nonce": NONCE, **change})))


def test_a_minute_either_way_is_allowed_for_the_clocks(entra):
    assert check(entra, entra.sign(entra.claims(nonce=NONCE, exp=int(time.time()) - 30)))


def test_a_token_signed_by_anyone_else_is_refused(entra):
    with pytest.raises(EntraError, match="Signature verification failed"):
        check(entra, entra.sign(entra.claims(nonce=NONCE), key=new_key()))


@pytest.mark.parametrize("alg", ["none", "HS256"])
def test_only_rs256_will_do(entra, alg):
    with pytest.raises(EntraError, match="not RS256"):
        check(entra, entra.sign(entra.claims(nonce=NONCE), alg=alg))


def test_a_key_the_tenant_doesnt_publish_is_refused(entra):
    with pytest.raises(EntraError, match="doesn't publish: someone-elses"):
        check(entra, entra.sign(entra.claims(nonce=NONCE), kid="someone-elses"))


def test_the_keys_are_fetched_once(entra):
    for _ in range(3):
        check(entra, entra.sign(entra.claims(nonce=NONCE)))
    assert entra.key_fetches == 1


def test_new_keys_are_fetched_when_microsoft_rolls_them(entra):
    check(entra, entra.sign(entra.claims(nonce=NONCE)))
    entra.rotate()
    check(entra, entra.sign(entra.claims(nonce=NONCE)))
    assert entra.key_fetches == 2


def test_the_keys_are_fetched_again_after_a_day(entra, monkeypatch):
    check(entra, entra.sign(entra.claims(nonce=NONCE)))
    later = time.monotonic() + 24 * 3600
    monkeypatch.setattr(service, "monotonic", lambda: later)
    check(entra, entra.sign(entra.claims(nonce=NONCE)))
    assert entra.key_fetches == 2


def test_no_keys_to_be_had_is_a_refusal_not_a_crash(entra, monkeypatch):
    def unreachable(url):
        raise OSError("no route to host")

    monkeypatch.setattr(service, "fetch_json", unreachable)
    with pytest.raises(EntraError, match="could not fetch the tenant's signing keys"):
        check(entra, entra.sign(entra.claims(nonce=NONCE)))


def test_the_authorise_address_asks_for_a_code_with_pkce(entra):
    url = service.authorise_url(get_settings(), PUBLIC_URL, state="st", nonce="no",
                                verifier="v" * 43, prompt="login")
    code, state = entra.approve(url)
    assert state == "st"
    assert "redirect_uri=https%3A%2F%2Flms.example.com.au%2Fv1%2Fauth%2Fentra%2Fcallback" in url
    assert "prompt=login" in url and "code_challenge=" in url and "v" * 43 not in url
