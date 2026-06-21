"""MockBitsoAPI — high-fidelity in-process emulator of Bitso's HTTP contract.

This is what makes "exhaustive local testing before touching a peso" real: it
emulates Bitso's actual response shapes and behaviours so the FULL validation
ladder, the executor's place/reconcile, the error taxonomy, and idempotency can
be exercised end-to-end with zero network, zero keys, zero funds.

Faithfully models:
  * the {success, payload} envelope and {success:false, error:{code,message}} errors;
  * private endpoints requiring an Authorization header (else 0201);
  * a trade-only key: any withdrawal returns 0202 (unless withdrawals_allowed);
  * the order -> user_trades flow; market orders fill immediately;
  * the BUY fee charged in the BASE asset, the SELL fee in the QUOTE asset;
  * resting LIMIT orders that stay open until cancelled (for the kill-path test);
  * insufficient-funds (0379) and below-minimum rejections;
  * injectable HTTP 420 rate-limiting;
  * origin_id reuse allowed after a market order completes (so the JOURNAL, not
    the exchange, must provide at-most-once — letting us prove idempotency).

It is a callable matching the transport contract: (method, path, body, headers)
-> (status, payload).
"""

from __future__ import annotations

import json
from decimal import Decimal
from urllib.parse import parse_qs, urlsplit


def _f(x: float) -> str:
    return format(Decimal(str(x)), "f")


def _ok(payload) -> tuple[int, dict]:
    return 200, {"success": True, "payload": payload}


def _err(status: int, code: str, message: str) -> tuple[int, dict]:
    return status, {"success": False, "error": {"code": code, "message": message}}


class MockBitsoAPI:
    def __init__(
        self,
        *,
        balances: dict[str, float] | None = None,
        fee_taker: float = 0.0078,
        fee_maker: float = 0.0060,
        prices: dict[str, float] | None = None,
        withdrawals_allowed: bool = False,
    ) -> None:
        self.balances = balances or {"mxn": 200.0, "btc": 0.0, "eth": 0.0}
        self.fee_taker = fee_taker
        self.fee_maker = fee_maker
        self.prices = prices or {"btc_mxn": 1_000_000.0, "eth_mxn": 50_000.0}
        self.withdrawals_allowed = withdrawals_allowed
        self.books = {
            "btc_mxn": {"book": "btc_mxn", "minimum_value": "10.00", "maximum_value": "5000000.00",
                        "minimum_amount": "0.000006", "maximum_amount": "500.00", "tick_size": "1"},
            "eth_mxn": {"book": "eth_mxn", "minimum_value": "10.00", "maximum_value": "5000000.00",
                        "minimum_amount": "0.0006", "maximum_amount": "1000.00", "tick_size": "1"},
        }
        self._tid = 0
        self._oid = 0
        self.orders: dict[str, dict] = {}
        self.trades: dict[str, list[dict]] = {}
        self.calls: list[tuple[str, str]] = []
        self._inject_rate_limit = 0

    # test hooks
    def inject_rate_limit(self, n: int = 1) -> None:
        self._inject_rate_limit = n

    # -- transport entrypoint --------------------------------------------
    def __call__(self, method: str, path: str, body: str, headers: dict) -> tuple[int, dict]:  # noqa: C901 - emulator endpoint dispatcher; the branches ARE the API surface
        self.calls.append((method, path))
        if self._inject_rate_limit > 0:
            self._inject_rate_limit -= 1
            return _err(420, "0301", "rate limited")

        parts = urlsplit(path)
        base = parts.path
        query = {k: v[0] for k, v in parse_qs(parts.query).items()}
        params = json.loads(body) if body else {}
        authed = bool(headers.get("Authorization"))

        if base == "/api/v3/available_books/" and method == "GET":
            return _ok(list(self.books.values()))            # public

        # everything below is private
        if not authed:
            return _err(401, "0201", "invalid signature / missing auth")

        if base == "/api/v3/balance/" and method == "GET":
            return _ok({"balances": [{"currency": c, "available": _f(v), "total": _f(v)}
                                     for c, v in self.balances.items()]})
        if base == "/api/v3/fees/" and method == "GET":
            return _ok({"fees": [{"book": b, "taker_fee_decimal": _f(self.fee_taker),
                                  "maker_fee_decimal": _f(self.fee_maker)} for b in self.books]})
        if base == "/api/v3/account_status/" and method == "GET":
            return _ok({"status": "active", "daily_limit": "10000.00", "cellphone_number": "verified"})
        if base == "/api/v3/open_orders/" and method == "GET":
            book = query.get("book")
            return _ok([o for o in self.orders.values()
                        if o["status"] == "open" and (book is None or o["book"] == book)])
        if base == "/api/v3/orders/all/" and method == "DELETE":
            cancelled = [oid for oid, o in self.orders.items() if o["status"] == "open"]
            for oid in cancelled:
                self.orders[oid]["status"] = "cancelled"
            return _ok(cancelled)
        if base == "/api/v3/user_trades/" and method == "GET":
            t_oid: str | None = query.get("oid")
            if t_oid is None and "origin_id" in query:
                t_oid = next((k for k, o in self.orders.items()
                              if o.get("origin_id") == query["origin_id"]), None)
            return _ok(self.trades.get(t_oid, []) if t_oid else [])
        if base.endswith("withdrawals/") and method == "POST":
            if not self.withdrawals_allowed:
                return _err(401, "0202", "API key is not authorized to execute the requested method")
            return _err(400, "0300", "withdrawal probe (allowed key) — invalid params")
        if base == "/api/v3/orders/" and method == "POST":
            return self._place(params)

        return _err(404, "0404", f"unknown endpoint {method} {base}")

    # -- order matching ---------------------------------------------------
    def _place(self, p: dict) -> tuple[int, dict]:
        book = p.get("book")
        side = p.get("side")
        otype = p.get("type")
        origin_id = p.get("origin_id")
        if book not in self.books:
            return _err(400, "0308", "unknown book")
        base_ccy, quote_ccy = book.split("_")
        price = self.prices[book]

        oid = f"oid{self._oid}"
        self._oid += 1

        if otype == "market":
            if "minor" in p:                       # spend exactly N quote (BUY only)
                quote_amt = float(p["minor"])
                base_gross = quote_amt / price
            else:
                base_gross = float(p["major"])
                quote_amt = base_gross * price

            if quote_amt < 10.0 - 1e-9:
                return _err(400, "0309", "below minimum_value")

            if side == "buy":
                if self.balances.get(quote_ccy, 0.0) < quote_amt - 1e-9:
                    return _err(400, "0379", "insufficient funds")
                fee = base_gross * self.fee_taker
                self.balances[quote_ccy] = self.balances.get(quote_ccy, 0.0) - quote_amt
                self.balances[base_ccy] = self.balances.get(base_ccy, 0.0) + base_gross - fee
                fee_ccy = base_ccy
            else:
                if self.balances.get(base_ccy, 0.0) < base_gross - 1e-9:
                    return _err(400, "0379", "insufficient funds")
                fee = quote_amt * self.fee_taker
                self.balances[base_ccy] = self.balances.get(base_ccy, 0.0) - base_gross
                self.balances[quote_ccy] = self.balances.get(quote_ccy, 0.0) + quote_amt - fee
                fee_ccy = quote_ccy

            self._tid += 1
            self.trades[oid] = [{"oid": oid, "book": book, "side": side, "major": _f(base_gross),
                                 "minor": _f(quote_amt), "price": _f(price), "fees_amount": _f(fee),
                                 "fees_currency": fee_ccy, "tid": self._tid}]
            self.orders[oid] = {"oid": oid, "book": book, "side": side, "type": "market",
                                "status": "completed", "origin_id": origin_id}
            return _ok({"oid": oid})

        if otype == "limit":
            self.orders[oid] = {"oid": oid, "book": book, "side": side, "type": "limit",
                                "status": "open", "price": p.get("price"),
                                "original_amount": p.get("major"), "origin_id": origin_id}
            return _ok({"oid": oid})

        return _err(400, "0310", f"unknown order type {otype}")
