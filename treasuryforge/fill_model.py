"""Realistic fill model (Roadmap A2) -- "maker-first" is a fantasy without a fill model.

A passive (post-only) order pays the low maker fee BUT only fills if the price comes
to your level; if it never does you must cross as a taker (3x the fee on Hyperliquid:
0.045% vs 0.015%). Worse, when a passive order DOES fill it is often because the market
moved against you (adverse selection). A backtest that assumes a maker fill every time
overstates the edge; this module prices the honest expected cost of a maker-first leg.

Fill-probability model: a driftless random walk over the wait window touches a barrier
`half_spread` away with probability ~ 2*(1 - Phi(d/sigma_w)) (reflection principle), where
sigma_w = vol*sqrt(wait). It is a defensible HEURISTIC to be calibrated against real fills, not
a microstructure oracle -- higher vol / tighter spread / longer wait => more likely to fill.

Expected leg cost = p*(maker_fee + adverse) + (1-p)*taker_fee. Compare against the
perfect-fill floor (maker_fee): a signal that only survives the floor, not the realistic
cost, must be killed (the A2 gate).
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class FillModelParams:
    maker_fee: float = 0.00015      # Hyperliquid maker
    taker_fee: float = 0.00045      # Hyperliquid taker (3x maker)
    max_maker_wait: int = 3         # intervals to rest passive before crossing as taker
    adverse_bps: float = 0.0001     # adverse-selection cost realized WHEN a maker fill happens


@dataclass(frozen=True)
class FillEstimate:
    expected_cost: float            # fractional, per leg (the honest number)
    maker_fill_prob: float
    adverse_selection: float        # expected adverse cost contribution
    taker_fallback_prob: float

    def is_fill_dependent(self, perfect_cost: float, *, margin: float = 1.5) -> bool:
        """True if the realistic cost is materially worse than the perfect-fill floor --
        a signal that only profits under perfect fills is a mirage."""
        return self.expected_cost > perfect_cost * margin


def _phi(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def maker_fill_probability(half_spread: float, sigma_window: float) -> float:
    """P(a passive order half_spread from mid fills within the window), via the
    barrier-touch (reflection) approximation. 0 when there is no volatility."""
    if sigma_window <= 1e-12:
        return 0.0
    if half_spread <= 0.0:
        return 1.0
    return min(1.0, 2.0 * (1.0 - _phi(half_spread / sigma_window)))


def estimate_leg_cost(params: FillModelParams, *, spread: float, vol: float) -> FillEstimate:
    """Expected cost of ONE maker-first leg given the current spread and per-interval vol."""
    half = spread / 2.0
    sigma_w = vol * math.sqrt(max(params.max_maker_wait, 1))
    p = maker_fill_probability(half, sigma_w)
    adverse = p * params.adverse_bps
    cost = p * (params.maker_fee + params.adverse_bps) + (1.0 - p) * params.taker_fee
    return FillEstimate(expected_cost=cost, maker_fill_prob=p,
                        adverse_selection=adverse, taker_fallback_prob=1.0 - p)


def round_trip_cost(params: FillModelParams, *, spread: float, vol: float, legs: int = 4) -> float:
    """Expected maker-first cost to OPEN and CLOSE a delta-neutral position (default 4
    legs: spot+perp in, spot+perp out)."""
    return legs * estimate_leg_cost(params, spread=spread, vol=vol).expected_cost


def perfect_round_trip_cost(params: FillModelParams, *, legs: int = 4) -> float:
    """The optimistic floor: every leg a maker fill, no adverse selection."""
    return legs * params.maker_fee
