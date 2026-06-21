"""TSMOM_VOLSCALED_V2 -- vol-scaled time-series momentum (Moskowitz-Ooi-Pedersen form).

V1's naive minute-ignition rule failed the deep gate (DSR 0.507): its only signal lived
in high-volatility coins/regimes and washed out unconditionally. V2 is the form the
literature actually supports (~0.65 Sharpe): the DIRECTION is the sign of the trailing
return over a lookback, and the POSITION SIZE is scaled to a constant volatility target
(target_vol / realized_vol). That vol-scaling is the conditioning -- it normalises the
signal-to-noise across coins and regimes instead of betting fixed size into chaos.

A continuous position (rebalanced each period), NOT discrete pump-events: so the backtest
measures a return SERIES and its Sharpe, the honest object for a trend strategy. Pure stdlib.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class TsmomParams:
    lookback: int = 24          # periods of trailing return that set the LONG/SHORT sign
    vol_window: int = 24        # periods of realized vol for the size scaling
    target_vol: float = 0.01    # per-period vol target (position = target/realized)
    max_leverage: float = 3.0   # cap on |position| (a vol blow-up must not lever to infinity)
    cost: float = 0.0006        # cost per unit of turnover (|Δposition|): one leg fee+slip
    long_short: bool = True     # False = long-only (negative momentum -> flat, no short)


def realized_vol(returns: list[float], window: int) -> float:
    """Std of the last `window` simple returns (population). 0 if too few points."""
    w = returns[-window:]
    n = len(w)
    if n < 2:
        return 0.0
    mean = sum(w) / n
    return math.sqrt(sum((r - mean) ** 2 for r in w) / n)


def momentum_sign(closes: list[float], lookback: int) -> float:
    """+1 if the trailing-`lookback` return is up, -1 if down, 0 if flat / too short."""
    if len(closes) <= lookback or closes[-1 - lookback] <= 0:
        return 0.0
    r = closes[-1] / closes[-1 - lookback] - 1.0
    return 1.0 if r > 0 else (-1.0 if r < 0 else 0.0)


def target_position(closes: list[float], returns: list[float], p: TsmomParams) -> float:
    """The vol-scaled target position in [-max_leverage, max_leverage]. Long-only clamps
    shorts to 0. Returns 0 when vol is undefined (can't size) or momentum is flat."""
    sign = momentum_sign(closes, p.lookback)
    if sign == 0.0 or (not p.long_short and sign < 0):
        return 0.0
    vol = realized_vol(returns, p.vol_window)
    if vol <= 0.0:
        return 0.0
    size = min(p.target_vol / vol, p.max_leverage)
    return sign * size
