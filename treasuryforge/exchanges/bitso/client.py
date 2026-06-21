"""Read-only / account client for the validation ladder.

Public endpoints need no auth; private ones are HMAC-signed. Same injectable
transport as the executor, so the whole client runs against MockBitsoAPI in local
tests and against the real network only on the VPS.
"""

from __future__ import annotations

import json
from collections.abc import Callable

from .signer import BitsoSigner

Transport = Callable[[str, str, str, dict], tuple[int, dict]]

# Withdrawal endpoint used ONLY for the negative "this key cannot withdraw" probe.
# Confirm against live docs before trusting a live result; a wrong path yields a
# 404 (inconclusive), never a false PASS.
WITHDRAWAL_PROBE_PATH = "/api/v3/withdrawals/"


class BitsoClient:
    def __init__(self, signer: BitsoSigner, transport: Transport) -> None:
        self.signer = signer
        self.transport = transport

    # -- low level --------------------------------------------------------
    def _public(self, path: str) -> tuple[int, dict]:
        return self.transport("GET", path, "", {})

    def _signed(self, method: str, path: str, body_obj: dict | None = None) -> tuple[int, dict]:
        body = json.dumps(body_obj, separators=(",", ":")) if body_obj is not None else ""
        header, _ = self.signer.auth_header(method, path, body)
        return self.transport(method, path, body, {"Authorization": header})

    # -- public -----------------------------------------------------------
    def available_books(self) -> tuple[int, dict]:
        return self._public("/api/v3/available_books/")

    # -- private (account) ------------------------------------------------
    def balance(self) -> tuple[int, dict]:
        return self._signed("GET", "/api/v3/balance/")

    def fees(self) -> tuple[int, dict]:
        return self._signed("GET", "/api/v3/fees/")

    def account_status(self) -> tuple[int, dict]:
        return self._signed("GET", "/api/v3/account_status/")

    def open_orders(self, book: str | None = None) -> tuple[int, dict]:
        path = "/api/v3/open_orders/"
        if book:
            path += f"?book={book}"
        return self._signed("GET", path)

    def cancel_all(self) -> tuple[int, dict]:
        # cancellations are rate-limit-exempt — the panic channel always lands
        return self._signed("DELETE", "/api/v3/orders/all/")

    def probe_withdrawal(self, path: str = WITHDRAWAL_PROBE_PATH) -> tuple[int, dict]:
        """Deliberately un-executable withdrawal. A trade-only key must reject it
        with code 0202 (not authorized). The caller treats a 2xx as a hard FAIL
        (the key CAN withdraw) and a non-0202 rejection as inconclusive."""
        bogus = {"currency": "btc", "amount": "0.00000001", "address": "INVALID_PROBE_ADDRESS"}
        return self._signed("POST", path, bogus)
