"""Funding persistence (Roadmap C, the baseline) — does high funding LAST long enough?

B1 showed the cost-gate clears at multi-week holds, so the carry thesis now rests on a
single empirical question: when funding is at the cap, how long does it STAY there? At
~10.95% APR a 2-leg round-trip needs ~17 days just to break even, so a carry only works
if high-funding episodes persist that long. This measures it from REAL funding history.

An "episode" starts when funding crosses ENTER (from below) and ends when it drops below
EXIT (the same hysteresis the carry signal uses). We record each episode's duration and
report how many reach the break-even hold. This is the honest baseline any funding
PREDICTOR must beat: if episodes rarely last to break-even, no model makes carry work;
if they routinely do, the edge is real (conditional on detecting a flip early).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field


@dataclass(frozen=True)
class PersistenceStats:
    n_episodes: int
    durations: list[int] = field(default_factory=list)   # intervals each episode lasted
    breakeven_intervals: int = 0
    last_censored: bool = False        # the final episode was still open at the series end

    @property
    def median_duration(self) -> float:
        if not self.durations:
            return 0.0
        s = sorted(self.durations)
        n = len(s)
        return float(s[n // 2]) if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0

    @property
    def mean_duration(self) -> float:
        return sum(self.durations) / len(self.durations) if self.durations else 0.0

    @property
    def pct_reach_breakeven(self) -> float:
        if not self.durations:
            return 0.0
        return sum(1 for d in self.durations if d >= self.breakeven_intervals) / len(self.durations)

    def render(self) -> str:
        return (f"episodes={self.n_episodes}  median={self.median_duration:.0f}h  "
                f"mean={self.mean_duration:.0f}h  reach_breakeven({self.breakeven_intervals}h)="
                f"{self.pct_reach_breakeven:.0%}" + ("  [last open]" if self.last_censored else ""))


def funding_persistence(history: Sequence[float], *, enter_rate: float, exit_rate: float,
                        breakeven_intervals: int) -> PersistenceStats:
    """Episode durations of a funding series under enter/exit hysteresis."""
    if exit_rate > enter_rate:
        raise ValueError("exit_rate must be <= enter_rate")
    durations: list[int] = []
    in_regime = False
    dur = 0
    for f in history:
        if not in_regime:
            if f >= enter_rate:
                in_regime, dur = True, 1
        elif f < exit_rate:
            durations.append(dur)
            in_regime = False
        else:
            dur += 1
    censored = in_regime
    if in_regime:
        durations.append(dur)
    return PersistenceStats(n_episodes=len(durations), durations=durations,
                            breakeven_intervals=breakeven_intervals, last_censored=censored)
