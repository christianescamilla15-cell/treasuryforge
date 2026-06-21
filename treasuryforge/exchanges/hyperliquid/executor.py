"""Hyperliquid order executor — wraps the official SDK's Exchange for signing.

Signing on Hyperliquid (EIP-712 / phantom-agent / msgpack) is error-prone, so per
the docs we use the SDK's `Exchange` rather than hand-rolling it. The Exchange is
INJECTED (constructed by the caller from an AGENT wallet that can trade but not
withdraw), so this class stays offline-testable with a fake exchange.

Two hard guards:
  * MIN_NOTIONAL_USD = 10  — Hyperliquid rejects orders below $10. A 20-MXN
    (~$1.10) order is IMPOSSIBLE here; the executor refuses it loudly.
  * max_notional_usd       — your own safety cap. If it is below the $10 floor
    (e.g. a 20-MXN cap), NO order can ever be placed — surfaced as an error, not
    a silent failure.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ...types import Intent, Side
from .wire import build_order_action

MIN_NOTIONAL_USD = 10.0


@dataclass(frozen=True)
class HLOrderResult:
    ok: bool
    oid: int | None
    filled_size: float
    avg_price: float
    raw: object


@dataclass(frozen=True)
class DryRunPreview:
    """The result of building + validating an order WITHOUT signing or sending it.

    `action` is the exact L1 payload that WOULD be signed with the agent key and
    POSTed to /exchange. If `ok` is False the order never even got built — `reason`
    says why (below the $10 venue floor, over the safety cap, or size rounds to 0)."""

    ok: bool
    reason: str
    coin: str
    is_buy: bool
    size: float
    price: float
    notional: float
    action: dict | None = None

    def render(self) -> str:
        verb = "BUY (long)" if self.is_buy else "SELL (short)"
        head = (f"[{'OK ' if self.ok else 'DENY'}] {verb} {self.coin}  "
                f"size~{self.size:.6f} @ ~{self.price:.4f}  notional ${self.notional:.2f}")
        return f"{head}\n      {self.reason}"


class HyperliquidExecutor:
    def __init__(self, exchange, info, *, max_notional_usd: float | None = None) -> None:
        self.ex = exchange                 # SDK Exchange (agent wallet) or a fake
        self.info = info                   # HyperliquidInfo (for live prices)
        self.max_notional_usd = max_notional_usd

    def _price(self, coin: str, fallback: float | None) -> float:
        if fallback is not None:
            return fallback
        return self.info.all_mids()[coin]

    def _guard(self, notional: float, *, reduce_only: bool = False) -> None:
        # the safety cap binds ALWAYS (even a close shouldn't exceed it)
        if self.max_notional_usd is not None and notional > self.max_notional_usd + 1e-9:
            raise ValueError(
                f"order ${notional:.2f} exceeds your safety cap ${self.max_notional_usd:.2f}")
        if reduce_only:
            return                       # a reduce-only CLOSE may be any size (no $10 floor)
        if notional < MIN_NOTIONAL_USD - 1e-9:
            raise ValueError(
                f"order ${notional:.2f} is below Hyperliquid's ${MIN_NOTIONAL_USD:.0f} "
                f"minimum — a ~20-MXN test is impossible here (min ~$10 / ~180 MXN)")
        if self.max_notional_usd is not None and self.max_notional_usd < MIN_NOTIONAL_USD:
            raise ValueError(
                f"safety cap ${self.max_notional_usd:.2f} is below the ${MIN_NOTIONAL_USD:.0f} "
                f"venue minimum — NO Hyperliquid order can satisfy both; raise the cap or "
                f"keep testing on Bitso spot")

    def preview_order(self, intent: Intent, *, price: float | None = None,
                      slippage: float = 0.02, reduce_only: bool = False) -> DryRunPreview:
        """DRY-RUN gate: build + validate the exact L1 payload, sign NOTHING, send
        NOTHING. Everything checkable offline is checked here (venue $10 floor, your
        safety cap, size rounding); signing needs the agent key and happens only on
        the VPS. The live path must never run before this returns ok."""
        coin = intent.symbol
        is_buy = intent.side is Side.BUY
        mid = self._price(coin, price if price is not None else intent.limit_price)
        if intent.order_type.value == "LIMIT" and intent.limit_price is not None:
            px, tif = float(intent.limit_price), "Gtc"
        else:                                           # market-like: a crossing IOC limit
            px, tif = mid * (1.0 + slippage if is_buy else 1.0 - slippage), "Ioc"
        sz = intent.base_amount if intent.quote_amount is None else intent.quote_amount / mid
        notional = sz * mid
        try:
            self._guard(notional, reduce_only=reduce_only)
        except ValueError as e:
            return DryRunPreview(False, str(e), coin, is_buy, sz, px, notional)
        meta = self.info.meta()
        names = [a["name"] for a in meta["universe"]]
        if coin not in names:
            return DryRunPreview(False, f"{coin} not in the perp universe", coin, is_buy, sz, px, notional)
        sz_decimals = int(meta["universe"][names.index(coin)]["szDecimals"])
        try:
            action = build_order_action(names.index(coin), is_buy, px, sz, sz_decimals,
                                        tif=tif, reduce_only=reduce_only)
        except ValueError as e:
            return DryRunPreview(False, str(e), coin, is_buy, sz, px, notional)
        return DryRunPreview(True, "payload built + validated -- NOT signed, NOT sent",
                             coin, is_buy, sz, px, notional, action)

    def place_order(self, intent: Intent, *, price: float | None = None,
                    slippage: float = 0.02) -> HLOrderResult:
        coin = intent.symbol
        is_buy = intent.side is Side.BUY        # SELL perp = the short leg of a carry
        px = self._price(coin, price if price is not None else intent.limit_price)
        sz = intent.base_amount if intent.quote_amount is None else intent.quote_amount / px
        self._guard(sz * px)

        if intent.order_type.value == "MARKET":
            raw = self.ex.market_open(coin, is_buy, sz, None, slippage)
        else:
            raw = self.ex.order(coin, is_buy, sz, intent.limit_price,
                                 {"limit": {"tif": "Gtc"}})
        return self._parse(raw)

    @staticmethod
    def _parse(raw: Any) -> HLOrderResult:
        try:
            statuses = raw["response"]["data"]["statuses"]
            st = statuses[0]
            if "filled" in st:
                f = st["filled"]
                return HLOrderResult(True, int(f.get("oid", 0)),
                                     float(f["totalSz"]), float(f["avgPx"]), raw)
            if "resting" in st:
                return HLOrderResult(True, int(st["resting"].get("oid", 0)), 0.0, 0.0, raw)
            return HLOrderResult(False, None, 0.0, 0.0, raw)        # e.g. {"error": ...}
        except (KeyError, IndexError, TypeError):
            return HLOrderResult(False, None, 0.0, 0.0, raw)
