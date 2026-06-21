"""Carry economic backtest (Roadmap C2 follow-up) — does the SELECTOR make money?

C2 showed the age-rule and coin-selection raise the break-even HIT RATE out-of-sample.
But a higher hit rate is not PnL: entering after age N forgoes N hours of funding, and
you only profit if the funding you DO collect beats the round-trip. This walks the real
funding series and books the honest carry economics:

  * an episode runs while funding >= exit (hysteresis from enter);
  * you ENTER once the episode reaches `min_age` (min_age=0 = fresh entry);
  * you COLLECT funding every hour while in position;
  * you EXIT when the episode ends (funding < exit) and pay the round-trip ONCE.

Per-position net = (funding collected from entry to episode end) - round_trip. Compare
fresh vs age-gated vs coin-selected to see whether the selector actually nets more.
Pure, stdlib, offline-testable.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field


@dataclass(frozen=True)
class CarryBtResult:
    n_positions: int
    total_funding: float
    total_cost: float
    returns: list[float] = field(default_factory=list)   # per-position net (fractional)
    holds: list[int] = field(default_factory=list)

    @property
    def net(self) -> float:
        return self.total_funding - self.total_cost

    @property
    def win_rate(self) -> float:
        return sum(1 for r in self.returns if r > 0) / len(self.returns) if self.returns else 0.0

    @property
    def avg_hold(self) -> float:
        return sum(self.holds) / len(self.holds) if self.holds else 0.0

    @property
    def net_per_position(self) -> float:
        return self.net / self.n_positions if self.n_positions else 0.0


def backtest_carry(history: Sequence[float], *, enter: float, exit_: float,
                   round_trip: float, min_age: int = 0) -> CarryBtResult:
    """Book the carry over a funding series. min_age gates entry to episodes that have
    already survived that many hours (the C2 survival-momentum rule)."""
    in_episode = False
    age = 0
    in_pos = False
    collected = 0.0
    hold = 0
    returns: list[float] = []
    holds: list[int] = []
    total_funding = 0.0
    n_cost = 0

    def _close() -> None:
        nonlocal in_pos, collected, hold, total_funding, n_cost
        returns.append(collected - round_trip)
        holds.append(hold)
        total_funding += collected
        n_cost += 1
        in_pos, collected, hold = False, 0.0, 0

    for f in history:
        if not in_episode:
            if f >= enter:
                in_episode, age = True, 1
        elif f < exit_:                         # episode ended
            if in_pos:
                _close()
            in_episode, age = False, 0
        else:
            age += 1
        if in_episode and not in_pos and age >= max(min_age, 1):
            in_pos = True                       # enter (collect starts this hour)
        if in_pos:
            collected += f
            hold += 1
    if in_pos:                                  # close an open position at series end
        _close()

    return CarryBtResult(n_positions=len(returns), total_funding=total_funding,
                         total_cost=n_cost * round_trip, returns=returns, holds=holds)
