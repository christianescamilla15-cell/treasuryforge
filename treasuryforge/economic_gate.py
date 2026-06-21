"""Economic gate (Roadmap v2 P9) — the hard pre-filter that kills fee-bleed corpses.

The research found churn is the killer: in some conditions fees were 10-64x the funding
collected (cost/gross of 1200-6400%). Such an "opportunity" must not even reach candidate
status. This is the blunt, non-negotiable gate applied to a cross-venue economics result:

  * CORPSE  -- cost eats >= 100% of gross, OR effective APR (after duty cycle) <= 0
  * REJECT  -- cost eats more than max_cost_gross (default 35%), or effective < min
  * PASS    -- net positive AND costs comfortably below gross

It composes with cross_venue_economics (the queen metric) and the duty cycle, so a
candidate only survives if it earns on TOTAL capital, after costs, scaled by how much of
the time the spread is actually on. Pure, stdlib, offline-testable.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .cross_venue_economics import CrossVenueEconomics


class GateResult(str, Enum):
    CORPSE = "CORPSE"      # not even a candidate
    REJECT = "REJECT"      # a candidate but the cost/edge is too thin
    PASS = "PASS"


@dataclass(frozen=True)
class GateVerdict:
    result: GateResult
    cost_gross_ratio: float
    effective_apr: float
    reason: str

    @property
    def is_pass(self) -> bool:
        return self.result is GateResult.PASS


def economic_gate(econ: CrossVenueEconomics, duty_cycle: float, *,
                  max_cost_gross: float = 0.35, min_effective_apr: float = 0.0) -> GateVerdict:
    gross = econ.gross_spread_apr
    if gross <= 0.0:
        return GateVerdict(GateResult.CORPSE, float("inf"), 0.0, "no spread")
    cost = gross - econ.net_funding_apr_on_notional       # amortised + hedge + orphan
    ratio = cost / gross
    eff = econ.effective_apr(duty_cycle)
    if ratio >= 1.0 or eff <= 0.0:
        return GateVerdict(GateResult.CORPSE, ratio, eff,
                           f"cost/gross {ratio:.0%}, effective {eff:+.1%}")
    if ratio > max_cost_gross or eff < min_effective_apr:
        return GateVerdict(GateResult.REJECT, ratio, eff,
                           f"cost/gross {ratio:.0%} > {max_cost_gross:.0%} or eff {eff:+.1%} thin")
    return GateVerdict(GateResult.PASS, ratio, eff, f"eff {eff:+.1%}, cost/gross {ratio:.0%}")
