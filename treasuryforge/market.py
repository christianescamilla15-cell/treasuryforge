"""Deterministic market simulator.

No network, no real data. A seeded random walk so every run with the same seed
produces an identical price path — that reproducibility is what lets us assert
"the system makes the same correct decisions" in tests (bit-exact gate).

You can also pass an explicit `prices` list to script a scenario (e.g. a crash
that should trip the circuit breaker).
"""

from __future__ import annotations

import random
from collections.abc import Iterator

from .types import MarketTick


class MarketSimulator:
    def __init__(
        self,
        symbol: str = "TOKEN",
        start_price: float = 100.0,
        seed: int = 42,
        drift: float = 0.0,
        volatility: float = 0.01,
        prices: list[float] | None = None,
    ) -> None:
        self.symbol = symbol
        self.start_price = start_price
        self._seed = seed
        self.drift = drift
        self.volatility = volatility
        self._scripted = prices

    def ticks(self, n: int) -> Iterator[MarketTick]:
        """Yield `n` deterministic ticks starting at ts=0."""
        if self._scripted is not None:
            for ts, price in enumerate(self._scripted[:n]):
                yield MarketTick(self.symbol, float(price), ts)
            return

        rng = random.Random(self._seed)
        price = self.start_price
        for ts in range(n):
            yield MarketTick(self.symbol, round(price, 6), ts)
            # multiplicative random walk: price stays positive
            shock = rng.gauss(self.drift, self.volatility)
            price = max(price * (1.0 + shock), 1e-9)
