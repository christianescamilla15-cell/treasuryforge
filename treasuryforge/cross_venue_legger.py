"""Cross-venue two-leg execution risk (Roadmap v2 P5) -- the non-atomicity hazard.

Unlike the single-venue HL rail, a cross-venue position has NO atomicity between the two
exchanges: one leg can fill while the other fails, partials leave a residual delta, a venue
can time out or go stale, and price drifts between the two sends. The edge can be real and
still die here. This models the leg outcomes and the cost of flattening whatever is left:

  * SAFE     -- both legs filled, residual delta within tolerance (delta-neutral as intended)
  * RESIDUAL -- partial fills leave an unhedged delta above tolerance -> a rebalance cost
  * ORPHAN   -- one leg filled, the other didn't -> a NAKED directional position to unwind now
  * BOTH_FAILED -- nothing landed (safe, no exposure)

The unwind cost (slippage + the price drift since entry) feeds the orphan-leg risk premium
in the economics, so the queen metric prices this risk instead of ignoring it. Pure, stdlib.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ExecVerdict(str, Enum):
    SAFE = "SAFE"
    RESIDUAL = "RESIDUAL"
    ORPHAN = "ORPHAN"
    BOTH_FAILED = "BOTH_FAILED"


@dataclass(frozen=True)
class LegFillParams:
    max_residual_delta: float = 0.05     # tolerable unhedged fraction before it's RESIDUAL
    unwind_slippage: float = 0.0010      # fractional cost to emergency-close an exposed leg
    price_drift: float = 0.0             # |price move| between the two sends (fractional)


_DEFAULT_LEG = LegFillParams()


@dataclass(frozen=True)
class ExecResult:
    hedged_fraction: float               # min(a, b): the part that is actually delta-neutral
    residual_delta: float                # |a - b|: the unhedged exposure
    unwind_cost: float                   # cost to flatten the residual NOW
    verdict: ExecVerdict

    @property
    def is_safe(self) -> bool:
        return self.verdict is ExecVerdict.SAFE


def simulate_cross_legs(long_filled: float, short_filled: float,
                        params: LegFillParams = _DEFAULT_LEG) -> ExecResult:
    """long_filled / short_filled are the fill fractions (0..1) of each venue's leg."""
    hedged = min(long_filled, short_filled)
    residual = abs(long_filled - short_filled)
    unwind_cost = residual * (params.unwind_slippage + abs(params.price_drift))
    if long_filled <= 0.0 and short_filled <= 0.0:
        verdict = ExecVerdict.BOTH_FAILED
    elif long_filled <= 0.0 or short_filled <= 0.0:
        verdict = ExecVerdict.ORPHAN                 # one side naked -> unwind immediately
    elif residual > params.max_residual_delta:
        verdict = ExecVerdict.RESIDUAL
    else:
        verdict = ExecVerdict.SAFE
    return ExecResult(hedged_fraction=hedged, residual_delta=residual,
                      unwind_cost=unwind_cost, verdict=verdict)
