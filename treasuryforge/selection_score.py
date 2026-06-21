"""Selection-skill scorecard -- does Christian's DISCRETIONARY pick beat the mechanical
baseline? The moonshot ignition rule is negative-EV (-9% per bet on Coinbase). The open
question is whether picking WHICH ignition to take adds edge that price data can't see.

This is the honest test of skill-vs-luck: log EVERY ignition (the full universe, no
survivorship), let the user mark picks BEFORE the outcome is known (no hindsight), resolve
all of them by the same rule, then compare the picked subset's expected value to the whole
population's. A two-sample z on (picked - unpicked) guards against a few lucky picks looking
like skill. Pure stdlib.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Resolved:
    coin: str
    picked: bool
    realized_return: float       # net-of-cost outcome of the ignition, same rule for all


def _mean_se(xs: list[float]) -> tuple[float, float]:
    n = len(xs)
    if n == 0:
        return 0.0, 0.0
    m = sum(xs) / n
    if n < 2:
        return m, 0.0
    var = sum((x - m) ** 2 for x in xs) / (n - 1)
    return m, math.sqrt(var / n)                     # standard error of the mean


@dataclass(frozen=True)
class SelectionScore:
    n: int
    n_picked: int
    n_unpicked: int
    ev_all: float
    ev_picked: float
    ev_unpicked: float
    edge_vs_unpicked: float                          # the skill signal: picked - unpicked
    edge_z: float                                    # / combined SE; >= 2 is ~95% one-sided

    @property
    def beats_baseline(self) -> bool:
        # needs a real sample of picks AND a statistically separated edge -- a few lucky
        # picks must NOT register as skill
        return self.n_picked >= 20 and self.edge_vs_unpicked > 0.0 and self.edge_z >= 2.0

    @property
    def verdict(self) -> str:
        if self.n_picked < 20:
            return f"NEED MORE DATA ({self.n_picked}/20 picks resolved)"
        if self.beats_baseline:
            return "SELECTION EDGE (picks beat the population, statistically separated)"
        if self.edge_vs_unpicked > 0:
            return "promising but not yet significant (positive edge, z < 2)"
        return "NO EDGE -- picks do not beat the mechanical baseline (consistent with luck)"


def score(records: list[Resolved]) -> SelectionScore:
    picked = [r.realized_return for r in records if r.picked]
    unpicked = [r.realized_return for r in records if not r.picked]
    allr = [r.realized_return for r in records]
    ev_all, _ = _mean_se(allr)
    ev_p, se_p = _mean_se(picked)
    ev_u, se_u = _mean_se(unpicked)
    edge = ev_p - ev_u
    comb_se = math.sqrt(se_p ** 2 + se_u ** 2)
    z = edge / comb_se if comb_se > 0 else 0.0
    return SelectionScore(
        n=len(allr), n_picked=len(picked), n_unpicked=len(unpicked),
        ev_all=ev_all, ev_picked=ev_p, ev_unpicked=ev_u,
        edge_vs_unpicked=edge, edge_z=z)
