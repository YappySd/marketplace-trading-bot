import nacl.signing
import pytest

from bot.money import api_cents, cents_to_dollar_string, format_usd, usd_to_cents
from bot.signing import SIGN_PREFIX, build_path, sign_request
from tests.helpers import PUBLIC_KEY, SECRET_KEY


def test_build_path_adds_query():
    assert build_path("/a/b") == "/a/b"
    assert build_path("/a/b", {"x": 1, "y": "z w"}) == "/a/b?x=1&y=z+w"


def test_signature_is_valid_for_the_documented_message():
    path = "/exchange/v1/market/items?gameId=a8db&limit=5"
    headers = sign_request(PUBLIC_KEY, SECRET_KEY, "get", path, "", timestamp=1700000000)

    assert headers["X-Api-Key"] == PUBLIC_KEY
    assert headers["X-Sign-Date"] == "1700000000"
    assert headers["X-Request-Sign"].startswith(SIGN_PREFIX)

    signature = bytes.fromhex(headers["X-Request-Sign"][len(SIGN_PREFIX):])
    verify_key = nacl.signing.SigningKey(bytes.fromhex(SECRET_KEY)[:32]).verify_key
    verify_key.verify(("GET" + path + "" + "1700000000").encode(), signature)  # raises if wrong


def test_signature_covers_the_body():
    body = '{"a":1}'
    headers = sign_request(PUBLIC_KEY, SECRET_KEY, "POST", "/x", body, timestamp=5)
    signature = bytes.fromhex(headers["X-Request-Sign"][len(SIGN_PREFIX):])
    verify_key = nacl.signing.SigningKey(bytes.fromhex(SECRET_KEY)[:32]).verify_key
    verify_key.verify(("POST/x" + body + "5").encode(), signature)
    with pytest.raises(Exception):
        verify_key.verify(("POST/x" + '{"a":2}' + "5").encode(), signature)


def test_usd_to_cents():
    assert usd_to_cents("1.50") == 150
    assert usd_to_cents(4) == 400
    assert usd_to_cents(0.1 + 0.2) == 30  # floats do not leak rounding errors
    assert usd_to_cents("0.005") == 1
    with pytest.raises(ValueError):
        usd_to_cents("abc")


def test_api_cents_and_formatting():
    assert api_cents("1234") == 1234
    assert api_cents(7) == 7
    with pytest.raises(ValueError):
        api_cents("x")
    assert format_usd(1234) == "$12.34"
    assert format_usd(5) == "$0.05"
    assert format_usd(-250) == "-$2.50"
    assert cents_to_dollar_string(1005) == "10.05"
