"""Opportunity duty cycle (Roadmap v2 P6) — how much of the time is the edge even ON?

XRP showed why a snapshot lies: ~30% APR spread that collapsed to ~1% in 12h. The right
question is not "did it hit 30%?" but "what FRACTION of the month is the spread above the
net break-even?". A 30% spread for 4h/month is useless; a 12% spread for 180h/month is far
better. This computes that duty cycle from a spread-APR series against the break-even floor,
and the mean spread while it is on (so the effective APR = economics x duty_cycle is honest).

Pure, stdlib, offline-testable. The caller builds the spread series from venue funding history.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class DutyCycle:
    n: int
    n_on: int                 # intervals with spread >= breakeven
    breakeven_apr: float
    mean_spread_when_on: float
    max_consecutive_on: int   # longest unbroken on-streak (how long you'd actually hold)

    @property
    def fraction(self) -> float:
        return self.n_on / self.n if self.n else 0.0

    def render(self) -> str:
        return (f"duty {self.fraction:.0%} ({self.n_on}/{self.n} above {self.breakeven_apr:.1%} APR), "
                f"mean-when-on {self.mean_spread_when_on:+.1%}, max-streak {self.max_consecutive_on}")


def opportunity_duty_cycle(spread_aprs: Sequence[float], *, breakeven_apr: float) -> DutyCycle:
    on = [s for s in spread_aprs if s >= breakeven_apr]
    streak = best = 0
    for s in spread_aprs:
        if s >= breakeven_apr:
            streak += 1
            best = max(best, streak)
        else:
            streak = 0
    return DutyCycle(n=len(spread_aprs), n_on=len(on), breakeven_apr=breakeven_apr,
                     mean_spread_when_on=sum(on) / len(on) if on else 0.0,
                     max_consecutive_on=best)
