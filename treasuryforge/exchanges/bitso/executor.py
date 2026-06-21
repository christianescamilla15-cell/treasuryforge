"""Two-phase Bitso executor: place_order -> reconcile.

Bitso's `POST /api/v3/orders` returns ONLY `{success, payload:{oid}}` — no price,
no fee. So a real fill cannot be a single synchronous call (the way SimExecutor
models it). It is split:

  place_order(intent, origin_id) -> OrderHandle      (just the order id)
  reconcile(handle, symbol)      -> Fill | Unfilled  (poll user_trades, VWAP)

Only a real, reconciled execution returns a Fill (which then mutates the wallet);
anything not yet filled returns Unfilled so the wallet is never touched on a guess.

The transport is injected — `transport(method, path, body, headers) -> (status, payload)`
— so every byte of signing, param mapping, VWAP aggregation and error handling is
unit-tested offline with canned responses. No network in tests, no keys, no funds.

Fee currency: Bitso charges the fee in the asset RECEIVED — base on a BUY, quote
on a SELL — which is exactly what Fill.fee_currency encodes.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

from ...types import Fill, Intent, OrderType, Side
from .errors import FATAL_AUTH, NON_RETRYABLE, SUBMITTED, BitsoError, classify
from .signer import BitsoSigner

Transport = Callable[[str, str, str, dict], tuple[int, dict]]


def _dec(x: float) -> str:
    """Plain-decimal string (no scientific notation) — exchanges reject 1e-06."""
    return format(Decimal(str(x)), "f")


@dataclass(frozen=True)
class OrderHandle:
    origin_id: str
    oid: str | None
    book: str
    side: Side


@dataclass(frozen=True)
class Unfilled:
    handle: OrderHandle
    reason: str


class BitsoExecutor:
    def __init__(
        self,
        signer: BitsoSigner,
        transport: Transport,
        book_map: dict[str, str] | None = None,
    ) -> None:
        self.signer = signer
        self.transport = transport
        self.book_map = book_map or {}

    # -- helpers ----------------------------------------------------------
    def _book(self, symbol: str) -> str:
        return self.book_map.get(symbol, symbol.lower())

    def _signed(self, method: str, path: str, body_obj: dict | None = None) -> tuple[int, dict]:
        body = json.dumps(body_obj, separators=(",", ":")) if body_obj is not None else ""
        header, _nonce = self.signer.auth_header(method, path, body)
        return self.transport(method, path, body, {"Authorization": header})

    def _to_params(self, intent: Intent) -> dict:
        book = self._book(intent.symbol)
        side = "buy" if intent.side is Side.BUY else "sell"
        if intent.order_type is OrderType.MARKET:
            params = {"book": book, "side": side, "type": "market"}
            if intent.quote_amount is not None:
                if intent.side is not Side.BUY:
                    raise ValueError("quote_amount (spend-exactly) is MARKET BUY only")
                params["minor"] = _dec(intent.quote_amount)        # spend exactly N quote
            else:
                params["major"] = _dec(intent.base_amount)
            return params
        # LIMIT
        if intent.limit_price is None:
            raise ValueError("LIMIT order requires limit_price")
        if intent.quote_amount is not None:
            raise ValueError("quote_amount is not valid for a LIMIT order")
        return {"book": book, "side": side, "type": "limit",
                "major": _dec(intent.base_amount), "price": _dec(intent.limit_price)}

    @staticmethod
    def _error(status: int, payload: dict) -> BitsoError:
        err = payload.get("error", {}) if isinstance(payload, dict) else {}
        code = err.get("code", "")
        cat = classify(status, code, err.get("message", ""))
        return BitsoError(cat, code, err.get("message", "unknown error"), status)

    # -- phase 1: place ---------------------------------------------------
    def place_order(self, intent: Intent, origin_id: str) -> OrderHandle:
        params = dict(self._to_params(intent), origin_id=origin_id)
        status, payload = self._signed("POST", "/api/v3/orders/", params)

        if payload.get("success"):
            oid = payload.get("payload", {}).get("oid")
            return OrderHandle(origin_id=origin_id, oid=oid, book=params["book"], side=intent.side)

        cat = classify(status, payload.get("error", {}).get("code"))
        if cat == SUBMITTED:           # accepted but not final — still a valid handle
            return OrderHandle(origin_id=origin_id, oid=None, book=params["book"], side=intent.side)
        raise self._error(status, payload)

    # -- phase 2: reconcile ----------------------------------------------
    def reconcile(self, handle: OrderHandle, symbol: str) -> Fill | Unfilled:
        # query the authoritative trade log (NOT /orders, which drops fills after ~1h)
        key = handle.oid or handle.origin_id
        qualifier = "oid" if handle.oid else "origin_id"
        path = f"/api/v3/user_trades/?{qualifier}={key}"
        status, payload = self._signed("GET", path)

        if not payload.get("success"):
            cat = classify(status, payload.get("error", {}).get("code"))
            if cat in (FATAL_AUTH, NON_RETRYABLE):
                raise self._error(status, payload)
            return Unfilled(handle, f"reconcile pending ({cat})")

        trades = payload.get("payload", []) or []
        if not trades:
            return Unfilled(handle, "no fills yet")

        total_base = sum(abs(float(t["major"])) for t in trades)
        if total_base <= 0:
            return Unfilled(handle, "zero base filled")
        notional = sum(abs(float(t["major"])) * float(t["price"]) for t in trades)
        vwap = notional / total_base                          # VWAP across partial fills
        total_fee = sum(float(t.get("fees_amount", 0.0)) for t in trades)
        fee_currency = "base" if handle.side is Side.BUY else "quote"
        ts = max((int(t.get("tid", 0)) for t in trades), default=0)

        return Fill(symbol=symbol, side=handle.side, base_amount=total_base,
                    price=vwap, fee=total_fee, ts=ts, fee_currency=fee_currency)
