"""Spot-vs-perp BASIS carry — a sibling of funding-carry, but genuinely distinct.

On a perpetual there is no dated-future basis; the perp is tied to spot by FUNDING.
So a basis trade here is the cash-and-carry: when the perp trades ABOVE the index
(premium = (mark - oracle)/oracle > 0, i.e. contango), go long spot + short perp.
You then capture TWO return streams, not one:

  1. funding  — being short the perp, you receive funding while it is positive;
  2. CONVERGENCE — as the perp premium reverts toward the index, the long-spot /
     short-perp pair gains exactly that premium. This is the part the pure
     funding-carry model ignores, and the reason this is a separate track record.

Per-interval return while in-position: funding_rate + (prev_premium - premium)
(the premium SHRINKING is a gain for long-spot/short-perp). ENTER on a rich premium,
EXIT once it converges. Decision-only; never executes. Honest caveat: the premium on
a liquid perp is small and noisy, and funding can flip — this exists to be MEASURED
live net-of-cost through the same DSR / ruin gates, very possibly to be rejected.
"""

from __future__ import annotations

from dataclasses import dataclass

from .funding import Action


@dataclass(frozen=True)
class BasisParams:
    enter_premium: float        # ENTER when premium >= this (perp rich vs spot)
    exit_premium: float         # EXIT when premium <= this (converged / backwardation)
    fee_per_leg: float          # taker fee fraction per leg
    legs_round_trip: int = 4    # open spot+perp, close spot+perp

    def __post_init__(self) -> None:
        if self.exit_premium > self.enter_premium:
            raise ValueError("exit_premium must be <= enter_premium (hysteresis)")

    @property
    def round_trip_cost(self) -> float:
        return self.legs_round_trip * self.fee_per_leg

    @property
    def entry_cost(self) -> float:
        return (self.legs_round_trip / 2) * self.fee_per_leg

    @property
    def exit_cost(self) -> float:
        return (self.legs_round_trip / 2) * self.fee_per_leg


class BasisSignal:
    """Stateful enter/exit on the perp premium, with hysteresis (enter rich, exit
    converged). Funding is captured while held but the ENTRY trigger is the basis."""

    def __init__(self, params: BasisParams) -> None:
        self.p = params
        self._in = False

    @property
    def in_position(self) -> bool:
        return self._in

    def decide(self, premium: float) -> Action:
        if not self._in:
            if premium >= self.p.enter_premium:
                self._in = True
                return Action.ENTER
            return Action.FLAT
        if premium <= self.p.exit_premium:
            self._in = False
            return Action.EXIT
        return Action.HOLD


def premium_from_marks(mark: float, oracle: float) -> float:
    """Perp premium over the index: (mark - oracle) / oracle. >0 = contango."""
    return (mark - oracle) / oracle if oracle > 0 else 0.0
