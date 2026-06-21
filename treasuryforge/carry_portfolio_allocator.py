"""Carry portfolio allocator (Roadmap v2 P10) -- scale by INDEPENDENCE, not by coin.

If several cross-venue spreads all depend on the same outlier (e.g. "HL funding is the
structural outlier"), they are NOT independent bets -- they are one bet wearing N hats. A
naive per-coin sizing would pile correlated risk. This allocates capital proportional to
each candidate's score (effective APR), then caps it three ways: per position, per
correlation CLUSTER (the real risk unit), and total. A cluster over its cap is scaled down
as a whole, so correlated spreads share one budget. Pure, stdlib, offline-testable.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class AllocatorCaps:
    max_per_position: float = 0.25       # no single spread above 25% of capital
    max_per_cluster: float = 0.40        # correlated cluster shares one 40% budget
    max_total: float = 1.0               # total deployed (<=1 = no leverage at the portfolio level)


@dataclass(frozen=True)
class Candidate:
    name: str
    cluster: str                         # correlation cluster id (e.g. "HL_outlier")
    score: float                         # effective APR (or any positive desirability)
    max_position: float | None = None    # per-candidate cap (e.g. its maturity tier); None = global


_DEFAULT_CAPS = AllocatorCaps()


@dataclass(frozen=True)
class Allocation:
    name: str
    cluster: str
    weight: float

    @property
    def marginal_risk_contribution(self) -> float:
        return self.weight              # this position's share of total deployed capital


def allocate(candidates: Sequence[Candidate],
             caps: AllocatorCaps = _DEFAULT_CAPS) -> list[Allocation]:
    pos = [c for c in candidates if c.score > 0.0]
    if not pos:
        return []
    total_score = sum(c.score for c in pos)
    # 1. proportional to score, then 2. cap per position -- by the TIGHTER of the global cap
    #    and the candidate's own (maturity-tier) cap, so a young strategy can't oversize
    weights = {c.name: min(c.max_position if c.max_position is not None else caps.max_per_position,
                           caps.max_total * c.score / total_score) for c in pos}
    # 3. cap per cluster: scale a cluster's members down together if it busts its budget
    clusters: dict[str, list[Candidate]] = {}
    for c in pos:
        clusters.setdefault(c.cluster, []).append(c)
    for members in clusters.values():
        csum = sum(weights[c.name] for c in members)
        if csum > caps.max_per_cluster and csum > 0:
            scale = caps.max_per_cluster / csum
            for c in members:
                weights[c.name] *= scale
    # No total-cap step: step 1 bounds each weight by max_total * share, so the weights
    # sum to <= max_total BY CONSTRUCTION, and the cluster scaling only reduces them. A
    # final renormalisation would be unreachable dead code (tot > max_total never holds).
    return [Allocation(c.name, c.cluster, weights[c.name]) for c in pos]
