"""Regime gating for pairs trading — the piece the research said is non-optional.

The honest finding (Do & Faff 2010/2012): the surviving stat-arb edge is
REGIME-CONDITIONAL, not continuous. A naive z-band that always trades bleeds cost
in the wrong regime and keeps holding a spread whose cointegration has BROKEN. This
module answers, on a trailing window, "is the spread tradeable RIGHT NOW?":

  1. Still stationary?  Rolling ADF on the (fixed-beta) residual spread. When the
     relationship breaks, the residual starts to trend -> ADF stops rejecting ->
     we stand down. This is the structural-break detector.
  2. Mean-reverting, not trending?  Lo-MacKinlay variance ratio VR(k): <1 mean-
     reverting (negative autocorrelation), ~1 random walk, >1 trending. We require
     VR strictly below 1 — a spread that is a random walk has NO edge to harvest.
  3. Reverting at a tradeable speed?  Half-life in [min,max] bars: too fast => the
     reversion is smaller than the round-trip cost; too slow => the edge decays
     before we can hold it (and capital sits idle).

NOTE: the rolling check uses the PLAIN ADF critical values, not the Engle-Granger
cointegration ones, because here beta is GIVEN (estimated in-sample, not re-fit on
the window) — we are testing "is this given spread still stationary", a plain unit-
root test. The cointegration crit values belong to the in-sample discovery step.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .cointegration import ADF_CRIT, adf_test, half_life


def variance_ratio(x: Sequence[float], k: int) -> float:
    """Lo-MacKinlay variance ratio VR(k) = Var(k-step change) / (k * Var(1-step)).

    <1 mean-reverting, ~1 random walk, >1 trending. Simple (biased) estimator with
    overlapping k-differences — honest enough for a regime gate, not a formal test."""
    if k < 2:
        raise ValueError("k must be >= 2")
    n = len(x)
    if n <= k + 1:
        raise ValueError("series too short for this k")
    d1 = [x[i] - x[i - 1] for i in range(1, n)]
    mu = sum(d1) / len(d1)
    var1 = sum((d - mu) ** 2 for d in d1) / len(d1)
    if var1 <= 1e-12:
        return 1.0
    dk = [x[i] - x[i - k] for i in range(k, n)]
    vark = sum((d - k * mu) ** 2 for d in dk) / len(dk)
    return vark / (k * var1)


@dataclass(frozen=True)
class RegimeAssessment:
    tradeable: bool
    reason: str
    stationary: bool
    adf_stat: float
    half_life: float
    variance_ratio: float
    mean_reverting: bool


def assess_spread_regime(
    spread: Sequence[float],
    *,
    lags: int = 1,
    level: float = 0.05,
    min_half_life: float = 1.0,
    max_half_life: float = 500.0,
    vr_k: int = 8,
    vr_max: float = 0.9,
) -> RegimeAssessment:
    """Is this trailing spread window tradeable right now? Gate = ALL must hold."""
    adf_stat, _ = adf_test(spread, lags=lags)
    stationary = adf_stat < ADF_CRIT[level]
    hl = half_life(spread)
    vr = variance_ratio(spread, vr_k)
    mean_reverting = vr < vr_max

    if not stationary:
        reason = "spread not stationary (relationship breaking)"
    elif hl == float("inf") or hl > max_half_life:
        reason = "half-life too slow / not reverting"
    elif hl < min_half_life:
        reason = "half-life too fast (reversion < cost)"
    elif not mean_reverting:
        reason = f"regime not mean-reverting (VR={vr:.2f})"
    else:
        reason = "ok"

    return RegimeAssessment(
        tradeable=(reason == "ok"),
        reason=reason,
        stationary=stationary,
        adf_stat=adf_stat,
        half_life=hl,
        variance_ratio=vr,
        mean_reverting=mean_reverting,
    )
