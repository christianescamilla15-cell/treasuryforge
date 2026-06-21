"""Pairs trading signal: trade the mean-reverting spread via z-score bands.

Given a (cointegrated) spread, standardize it to a rolling z-score and trade its
reversion: when the spread is unusually HIGH (z >= +entry), SHORT it (sell A, buy
B); when unusually LOW (z <= -entry), LONG it (buy A, sell B); flatten when it
reverts near the mean (|z| <= exit). Hysteresis (entry > exit) avoids churning the
band — the same cost-minimizing principle that makes carry work.

A pairs trade is structurally market-NEUTRAL but requires SHORTING one leg, so live
execution needs a perp/margin venue (Bitso spot can't short). The signal + backtest
are data-only and validate the edge before that venue decision.
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import Enum


class PairPosition(int, Enum):
    SHORT_SPREAD = -1     # spread too high: short A, long B
    FLAT = 0
    LONG_SPREAD = +1      # spread too low: long A, short B


def rolling_zscore(spread: Sequence[float], window: int) -> list[float | None]:
    """Trailing-window z-score. None during warmup (point-in-time: uses only past)."""
    out: list[float | None] = [None] * len(spread)
    for i in range(window - 1, len(spread)):
        w = spread[i - window + 1 : i + 1]
        m = sum(w) / window
        var = sum((x - m) ** 2 for x in w) / window
        sd = var ** 0.5
        out[i] = (spread[i] - m) / sd if sd > 1e-12 else 0.0
    return out


class PairsSignal:
    """Stateful z-band signal with hysteresis. update(z) -> position to hold.

    Optional stop_z is a DIRECTIONAL blow-out stop: if the spread keeps diverging
    AGAINST the position past stop_z (a short whose z climbs to +stop_z, a long
    whose z falls to -stop_z) instead of reverting, flatten at a loss rather than
    "waiting for a reversion" that a broken cointegration may never deliver."""

    def __init__(self, entry_z: float = 2.0, exit_z: float = 0.5,
                 stop_z: float | None = None) -> None:
        if exit_z >= entry_z:
            raise ValueError("exit_z must be < entry_z (hysteresis)")
        if stop_z is not None and stop_z <= entry_z:
            raise ValueError("stop_z must be > entry_z")
        self.entry_z = entry_z
        self.exit_z = exit_z
        self.stop_z = stop_z
        self.position = 0

    def update(self, z: float | None) -> int:
        if z is None:
            return self.position
        if self.position == 0:
            if z >= self.entry_z:
                self.position = PairPosition.SHORT_SPREAD
            elif z <= -self.entry_z:
                self.position = PairPosition.LONG_SPREAD
        else:
            blown = self.stop_z is not None and (
                (self.position == PairPosition.SHORT_SPREAD and z >= self.stop_z)
                or (self.position == PairPosition.LONG_SPREAD and z <= -self.stop_z)
            )
            if blown or abs(z) <= self.exit_z:
                self.position = PairPosition.FLAT
        return int(self.position)
