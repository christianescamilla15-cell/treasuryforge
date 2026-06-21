"""Synthetic market with REALISTIC volatility — for stress-testing before prod.

A regime-switching jump-diffusion process: the market moves between calm, storm
and crash regimes (Markov), each with its own drift and volatility, plus rare
fat-tail JUMPS (the gaps a Gaussian random walk never produces). Deterministic
given a seed, and yields the same MarketTick stream the Runner consumes — so you
can drive the whole agent/policy stack through crashes and vol spikes locally.
"""

from __future__ import annotations

import random
from collections.abc import Iterator
from dataclasses import dataclass, field

from ..types import MarketTick


@dataclass(frozen=True)
class Regime:
    name: str
    drift: float          # mean log-return per step
    vol: float            # volatility per step
    persistence: float    # prob of staying in this regime next step


DEFAULT_REGIMES = [
    Regime("calm", 0.0001, 0.005, 0.98),
    Regime("storm", 0.0, 0.025, 0.92),
    Regime("crash", -0.01, 0.06, 0.85),
]


@dataclass
class SyntheticMarket:
    symbol: str = "TOKEN"
    start_price: float = 100.0
    seed: int = 0
    jump_prob: float = 0.01        # per-step prob of a fat-tail jump
    jump_scale: float = 0.08       # typical jump magnitude (fraction)
    regimes: list[Regime] = field(default_factory=lambda: list(DEFAULT_REGIMES))

    def ticks(self, n: int) -> Iterator[MarketTick]:
        rng = random.Random(self.seed)
        price = self.start_price
        regime = self.regimes[0]
        for ts in range(n):
            yield MarketTick(self.symbol, round(price, 6), ts)
            # Markov regime switch
            if rng.random() > regime.persistence:
                others = [r for r in self.regimes if r is not regime]
                regime = rng.choice(others) if others else regime
            shock = rng.gauss(regime.drift, regime.vol)
            # rare fat-tail jump (the gap a normal walk never gives you)
            if rng.random() < self.jump_prob:
                shock += rng.choice([-1.0, 1.0]) * self.jump_scale * abs(rng.gauss(1.0, 0.5))
            price = max(price * (1.0 + shock), 1e-9)

    def realized_vol(self, n: int = 2000) -> float:
        """Annualization-free realized volatility of a sample path (sanity/tuning)."""
        prices = [t.price for t in self.ticks(n)]
        rets = [prices[i] / prices[i - 1] - 1.0 for i in range(1, len(prices))]
        m = sum(rets) / len(rets)
        return (sum((r - m) ** 2 for r in rets) / len(rets)) ** 0.5
