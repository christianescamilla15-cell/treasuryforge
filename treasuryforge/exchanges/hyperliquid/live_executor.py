"""Hyperliquid two-phase executor for the IdempotentOrderManager — at-most-once.

Implements the manager's TwoPhaseExecutor protocol on Hyperliquid:

  * place_order(intent, origin_id): derive a DETERMINISTIC cloid from origin_id,
    build + guard the order through the dry-run path, then sign + POST via the SDK
    Exchange WITH that cloid. The cloid is HL's native idempotency key — a re-post
    with the same cloid cannot duplicate an active order. Failures raise the shared
    BitsoError with the right category so the manager reconciles vs. retries correctly
    (network/timeout -> INDETERMINATE -> reconcile; venue rejection -> NON_RETRYABLE).

  * reconcile(handle, symbol): find the fills for the cloid (keyless /info) and
    aggregate them into a Fill, or return Unfilled. Matching by cloid is the source
    of truth that keeps retries at-most-once.

Reuses the execution-protocol types (OrderHandle / Unfilled / BitsoError) the manager
requires — they live under exchanges/bitso/ but are exchange-generic by design.
"""

from __future__ import annotations

import hashlib
from typing import Any

from ...types import Fill, Intent, Side
from ..bitso.errors import FATAL_AUTH, INDETERMINATE, NON_RETRYABLE, BitsoError
from ..bitso.executor import OrderHandle, Unfilled
from .executor import HyperliquidExecutor


def origin_to_cloid(origin_id: str) -> str:
    """Deterministic 128-bit Hyperliquid client order id from a logical origin_id.
    The SAME origin_id always yields the SAME cloid, so a retry reuses it and HL
    dedups it — the core of at-most-once."""
    return "0x" + hashlib.sha256(origin_id.encode()).hexdigest()[:32]


class HlTwoPhaseExecutor:
    def __init__(self, exchange: Any, info: Any, master: str, *,
                 max_notional_usd: float, slippage: float = 0.02,
                 cloid_factory: Any = None, reduce_only: bool = False) -> None:
        self.ex = exchange                  # SDK Exchange (agent wallet) — signs + POSTs
        self.info = info                    # HyperliquidInfo — keyless reconcile reads
        self.master = master                # account the fills land under
        self.slippage = slippage
        self.reduce_only = reduce_only      # True = a CLOSE: can only reduce, never flip
        self._cloid_factory = cloid_factory  # str cloid -> SDK Cloid; None = lazy SDK import
        self._preview = HyperliquidExecutor(exchange, info, max_notional_usd=max_notional_usd)

    # -- phase 1: place (sign + POST), never duplicating -------------------
    def place_order(self, intent: Intent, origin_id: str) -> OrderHandle:
        prev = self._preview.preview_order(intent, slippage=self.slippage,
                                           reduce_only=self.reduce_only)
        if not prev.ok or prev.action is None:
            raise BitsoError(NON_RETRYABLE, "guard", prev.reason, 400)   # deterministic, never landed
        cloid = origin_to_cloid(origin_id)
        order = prev.action["orders"][0]
        # use the HL-ROUNDED size/price from the validated payload (szDecimals / 5 sig
        # figs) — the raw values have too many decimals and the SDK rejects them.
        sz, px, tif = float(order["s"]), float(order["p"]), order["t"]["limit"]["tif"]
        ro = bool(order["r"])            # reduce-only flag must reach the SDK, not just the payload
        try:
            raw = self._send(prev.coin, prev.is_buy, sz, px, tif, cloid, ro)
        except BitsoError:
            raise
        except Exception as e:              # network / timeout: outcome UNKNOWN, must reconcile
            raise BitsoError(INDETERMINATE, "network", str(e), 0) from e
        return self._handle(raw, intent, origin_id, prev.coin)

    def _send(self, coin: str, is_buy: bool, sz: float, px: float, tif: str,
              cloid: str, reduce_only: bool) -> Any:
        make = self._cloid_factory or self._sdk_cloid
        return self.ex.order(coin, is_buy, sz, px, {"limit": {"tif": tif}},
                             reduce_only=reduce_only, cloid=make(cloid))

    @staticmethod
    def _sdk_cloid(cloid: str) -> Any:
        from hyperliquid.utils.types import Cloid
        return Cloid.from_str(cloid)

    @staticmethod
    def _handle(raw: Any, intent: Intent, origin_id: str, coin: str) -> OrderHandle:
        try:
            st = raw["response"]["data"]["statuses"][0]
        except (KeyError, IndexError, TypeError) as e:   # malformed -> unknown, reconcile
            raise BitsoError(INDETERMINATE, "parse", str(raw), 0) from e
        if "error" in st:
            msg = str(st["error"]).lower()
            fatal = "not registered" in msg or "does not exist" in msg or "signature" in msg
            raise BitsoError(FATAL_AUTH if fatal else NON_RETRYABLE, "venue", str(st["error"]), 400)
        oid = None
        if "filled" in st:
            oid = str(st["filled"].get("oid", "")) or None
        elif "resting" in st:
            oid = str(st["resting"].get("oid", "")) or None
        return OrderHandle(origin_id=origin_id, oid=oid, book=coin, side=intent.side)

    # -- phase 2: reconcile by cloid (keyless) ----------------------------
    def reconcile(self, handle: OrderHandle, symbol: str) -> Fill | Unfilled:
        cloid = origin_to_cloid(handle.origin_id)
        fills = self.info.fills_for_cloid(self.master, cloid)
        if not fills:
            return Unfilled(handle=handle, reason="no fills for cloid")
        return self._aggregate(fills, symbol or handle.book, handle.side)

    @staticmethod
    def _aggregate(fills: list[dict], symbol: str, side: Side) -> Fill:
        sz = sum(float(f["sz"]) for f in fills)
        notional = sum(float(f["sz"]) * float(f["px"]) for f in fills)
        fee = sum(float(f.get("fee", 0.0)) for f in fills)
        ts = max(int(f.get("time", 0)) for f in fills)
        px = notional / sz if sz > 0 else 0.0
        return Fill(symbol=symbol, side=side, base_amount=sz, price=px, fee=fee,
                    ts=ts, fee_currency="quote")    # HL fees are charged in USDC (quote)
