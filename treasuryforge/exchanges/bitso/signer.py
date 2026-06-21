"""Bitso request signing — HMAC-SHA256, Nonce v2, pure stdlib.

Auth header:  Authorization: Bitso {key}:{nonce}:{signature}
where signature = hex(HMAC_SHA256(secret, nonce + METHOD + request_path + body)).

Two load-bearing correctness rules from the Phase-3 research:
  * Sign the EXACT bytes you send — serialize the JSON body ONCE and sign that
    same string (re-serializing after signing is the classic silent 401).
  * request_path MUST include any query string.

Nonce v2 (Bitso deprecated v1 in Nov 2025) = 13-digit epoch-milliseconds
followed by a 1-6 digit salt. We mint it monotonically (max(candidate, last+1))
so an NTP step-back or a process restart can never regress it; the caller is
expected to PERSIST `last` in the crash-safe journal and feed it back in.
"""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Callable
from dataclasses import dataclass

_SALT_DIGITS = 6
_SALT_MOD = 10 ** _SALT_DIGITS          # nonce = epoch_ms * 10**6 + salt  == concatenation


@dataclass
class NonceV2:
    """Monotonic Nonce-v2 source. `now_ms` and `salt` are injected so the whole
    thing is deterministic and unit-testable offline (no wall-clock, no RNG)."""

    now_ms: Callable[[], int]
    salt: Callable[[], int]
    last: int = 0

    def next(self) -> int:
        salt = self.salt() % _SALT_MOD
        candidate = self.now_ms() * _SALT_MOD + salt
        nonce = max(candidate, self.last + 1)
        self.last = nonce
        return nonce


class BitsoSigner:
    def __init__(self, api_key: str, api_secret: str, nonce_source: NonceV2) -> None:
        self._key = api_key
        self._secret = api_secret.encode("utf-8")
        self._nonce = nonce_source

    @staticmethod
    def signature(secret: bytes, nonce: int | str, method: str, request_path: str,
                  body: str = "") -> str:
        msg = f"{nonce}{method}{request_path}{body}".encode()
        return hmac.new(secret, msg, hashlib.sha256).hexdigest()

    def auth_header(self, method: str, request_path: str, body: str = "") -> tuple[str, int]:
        """Return (Authorization header value, nonce used). `body` must be the
        exact serialized string that will be sent on the wire."""
        nonce = self._nonce.next()
        sig = self.signature(self._secret, nonce, method.upper(), request_path, body)
        return f"Bitso {self._key}:{nonce}:{sig}", nonce
