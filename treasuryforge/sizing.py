"""Volatility-targeting position sizing — a CEILING that feeds PROPOSE.

Scales trade size inversely to recent volatility (target a constant risk budget):
quiet markets size up, turbulent markets size down. RiskMetrics EWMA variance
(lambda = 0.94) is the canonical, ~20-line estimator.

CRITICAL invariant (the whole reason this is safe to add): the returned size is
`min(vol_scaled, max_size)`, a monotone shrink that can NEVER breach the hard
cap. The policy engine remains the sole disposer; this only ever proposes a
SMALLER size. Honest caveat from the discovery: the headline drawdown/Sharpe
improvement numbers in the literature were fabricated/misattributed — measure
the effect on your own out-of-sample data before trusting it. Known failure
mode: it cuts size exactly when a mean-reversion dip-buyer wants more.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class EwmaVol:
    """RiskMetrics exponentially-weighted volatility of a return stream."""

    lam: float = 0.94
    floor: float = 1e-8
    _var: float | None = None

    def update(self, ret: float) -> float:
        if self._var is None:
            self._var = ret * ret
        else:
            self._var = self.lam * self._var + (1.0 - self.lam) * ret * ret
        return self.vol

    @property
    def vol(self) -> float:
        if self._var is None:
            return self.floor
        return max(math.sqrt(self._var), self.floor)


def vol_target_size(
    base_size: float,
    current_vol: float,
    target_vol: float,
    max_size: float,
    vol_floor: float = 1e-8,
) -> float:
    """Return a size scaled to hit `target_vol`, hard-clamped to `max_size`.

    Guarantees, for all finite non-negative inputs:
      * result <= max_size           (never breaches the cap)
      * result >= 0
      * monotone non-increasing in current_vol (more vol -> not-larger size)
    """
    v = max(current_vol, vol_floor)
    scaled = base_size * (target_vol / v)
    return max(0.0, min(scaled, max_size))
