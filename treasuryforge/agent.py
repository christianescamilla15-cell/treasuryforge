"""The agent — the 'brain'.

`Strategy` is the interface: given the latest tick and the wallet, optionally
propose an Intent. The default `MeanReversionAgent` is fully DETERMINISTIC on
purpose: for local validation we want behaviour we can reason about and test
bit-exactly. Later you swap in an `LLMStrategy` implementing the same `decide`
method — and because the policy engine sits downstream, an LLM that misbehaves
still cannot exceed the hard limits.
"""

from __future__ import annotations

from collections import deque
from typing import Protocol

from .types import Intent, MarketTick, Side
from .wallet import SimWallet


class Strategy(Protocol):
    def decide(self, tick: MarketTick, wallet: SimWallet) -> Intent | None: ...


class MeanReversionAgent:
    """Buy dips below the moving average, sell rips above it.

    A simple, transparent strategy whose only job here is to exercise the full
    propose -> policy -> execute loop with plausible, inspectable trades.
    """

    def __init__(
        self,
        symbol: str = "TOKEN",
        window: int = 20,
        threshold: float = 0.02,     # 2% away from the MA triggers a trade
        trade_base: float = 1.0,     # quantity per trade
    ) -> None:
        self.symbol = symbol
        self.window = window
        self.threshold = threshold
        self.trade_base = trade_base
        self._prices: deque[float] = deque(maxlen=window)

    def decide(self, tick: MarketTick, wallet: SimWallet) -> Intent | None:
        self._prices.append(tick.price)
        if len(self._prices) < self.window:
            return None                          # warming up the moving average

        ma = sum(self._prices) / len(self._prices)
        lo = ma * (1.0 - self.threshold)
        hi = ma * (1.0 + self.threshold)

        if tick.price <= lo:
            return Intent(
                self.symbol, Side.BUY, self.trade_base,
                reason=f"price {tick.price:.2f} <= MA-{self.threshold:.0%} ({lo:.2f})",
            )
        if tick.price >= hi and wallet.base_balance(self.symbol) > 0:
            held = wallet.base_balance(self.symbol)
            return Intent(
                self.symbol, Side.SELL, min(self.trade_base, held),
                reason=f"price {tick.price:.2f} >= MA+{self.threshold:.0%} ({hi:.2f})",
            )
        return None
