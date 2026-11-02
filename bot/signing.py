"""Request signing for DMarket API v2 (Ed25519).

The string that gets signed is: METHOD + path-with-query + body + timestamp.
The path must be byte-for-byte what is sent on the wire, so it is built in one
place (`build_path`) and reused for both signing and the request itself.
"""

from __future__ import annotations

import time
from urllib.parse import urlencode

import nacl.signing

SIGN_PREFIX = "dmar ed25519 "


def build_path(path: str, params: dict | None = None) -> str:
    if not params:
        return path
    return f"{path}?{urlencode(params, doseq=True)}"


def sign_request(
    public_key: str,
    secret_key: str,
    method: str,
    path_with_query: str,
    body: str = "",
    timestamp: float | None = None,
) -> dict[str, str]:
    """Return the three auth headers for one request."""
    ts = str(int(time.time() if timestamp is None else timestamp))
    message = (method.upper() + path_with_query + body + ts).encode("utf-8")
    seed = bytes.fromhex(secret_key)[:32]  # the first 32 bytes are the Ed25519 seed
    signature = nacl.signing.SigningKey(seed).sign(message).signature
    return {
        "X-Api-Key": public_key,
        "X-Request-Sign": SIGN_PREFIX + signature.hex(),
        "X-Sign-Date": ts,
    }
