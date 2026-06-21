"""MOMENTUM_IGNITION_V1 -- a directional trend-following candidate (Christian's spec).

Christian's idea encoded as a mechanical, testable rule (no "AI guesses a breakout"):
a coin ignites (jumps X% in one minute) WITH follow-through (the prior minute was also
up), you go long, ride the trend, and exit on a TRAILING reversal (peak +45% -> drop to
+39% -> out) or a hard stop. Single venue, 2 legs, directional -- so unlike cross-venue
carry the round-trip cost is small and a multi-hour hold amortises it easily. The open
question is never "can we detect the pump" (trivial) but whether, across MANY events
including the dumps that trap you, the net-of-cost expectancy is positive.

This module is the rule only. The backtest owns the trade accounting and the honest
metrics; pure stdlib so it is offline- and mutation-testable.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MomentumParams:
    enter_1m: float = 0.01       # 1-bar return that triggers an entry (ignition)
    confirm_1m: float = 0.0      # the PRIOR 1-bar return must be >= this (follow-through)
    trail_frac: float = 0.04     # exit when price falls this far below the running peak
    stop_frac: float = 0.05      # hard stop: exit if price falls this far below entry
    max_hold: int = 240          # force-exit after this many bars (minutes)
    cost: float = 0.0013         # round-trip cost per trade (2 legs fee + slippage)


def entry_ok(prev2_close: float, prev_close: float, close: float, p: MomentumParams) -> bool:
    """Ignition + follow-through: this bar jumped >= enter_1m AND the prior bar was up
    >= confirm_1m. Both conditions guard against entering a single random spike."""
    if prev2_close <= 0 or prev_close <= 0:
        return False
    r_now = close / prev_close - 1.0
    r_prev = prev_close / prev2_close - 1.0
    return r_now >= p.enter_1m and r_prev >= p.confirm_1m


def simulate_exit(entry: float, highs: list[float], lows: list[float], closes: list[float],
                  p: MomentumParams) -> tuple[int, float]:
    """Walk forward from entry over (highs, lows, closes) of the FUTURE bars (entry bar
    excluded). Returns (bars_held, gross_return). Order within a bar is conservative: the
    trailing/stop trigger is checked against the bar LOW before counting any new high."""
    peak = entry
    n = min(p.max_hold, len(closes))
    for j in range(n):
        trail_level = peak * (1.0 - p.trail_frac)
        stop_level = entry * (1.0 - p.stop_frac)
        # a gap straight through the hard stop fills at the stop, not the trail
        if lows[j] <= stop_level and stop_level <= trail_level:
            return j + 1, -p.stop_frac
        if lows[j] <= trail_level:
            return j + 1, trail_level / entry - 1.0
        peak = max(peak, highs[j])
    return n, (closes[n - 1] / entry - 1.0) if n > 0 else 0.0
