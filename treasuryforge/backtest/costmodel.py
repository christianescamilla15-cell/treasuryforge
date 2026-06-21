"""Decomposed transaction-cost model: spread + market impact + fees.

Replaces a single flat slippage number with the three real components. Used by
SimExecutor (and later Paper/Live) so backtest and live share ONE cost
definition — the only way backtest-to-live parity is honest.

Discipline from the discovery: this model is ADVISORY for sizing/vetoing. It may
only ever ADD conservatism — it must never be used to relax a hard policy cap.
The square-root impact law cost ~ eta * sigma * sqrt(Q / V) is the standard
practitioner form; eta is a venue-fit constant, not a universal truth.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class CostModel:
    fee_rate: float = 0.001          # taker fee (fraction of notional)
    half_spread: float = 0.0005      # half the bid/ask spread (fraction of price)
    impact_eta: float = 0.1          # square-root impact coefficient

    def cost(self, notional: float, sigma: float = 0.0, adv: float | None = None) -> float:
        """Expected execution cost in quote terms for a trade of `notional`.

        notional : absolute quote value of the trade
        sigma    : per-period volatility (fraction), for the impact term
        adv      : average daily volume in the SAME quote units (None -> no impact)
        """
        notional = abs(notional)
        spread_cost = self.half_spread * notional
        fee_cost = self.fee_rate * notional
        impact_cost = 0.0
        if adv and adv > 0 and sigma > 0:
            impact_cost = self.impact_eta * sigma * math.sqrt(notional / adv) * notional
        return spread_cost + fee_cost + impact_cost

    def cost_bps(self, notional: float, sigma: float = 0.0, adv: float | None = None) -> float:
        if notional <= 0:
            return 0.0
        return 1e4 * self.cost(notional, sigma, adv) / notional
