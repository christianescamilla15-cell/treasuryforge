"""Maturity-tiered position caps (Christian's cold-verdict point 1).

A flat 25%-per-position cap is fine as the FINAL ceiling but reckless for a young strategy:
venue risk, liquidation, API/downtime, a brutal funding flip can each gut an oversized
early position. So the per-position cap RAMPS with proven track record -- a strategy earns
a bigger cap by surviving live for long enough with enough events, not by looking good once.

    micro  2%   ->  small 5%  ->  normal 12%  ->  exceptional 20%  ->  mature 25%

25% is reachable only after months of live evidence. Pure stdlib; the allocator reads
`cap_for(tier)` as a per-candidate cap.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Tier:
    name: str
    max_position: float          # fraction of the (isolated) trading bankroll
    min_days_live: float         # live days required to ADVANCE out of this tier
    min_events: int              # resolved trades/events required to advance


# ordered floor -> ceiling; advancing requires meeting the NEXT tier's gates while in this one
TIERS: tuple[Tier, ...] = (
    Tier("micro", 0.02, 0.0, 0),
    Tier("small", 0.05, 14.0, 30),
    Tier("normal", 0.12, 60.0, 100),
    Tier("exceptional", 0.20, 120.0, 200),
    Tier("mature", 0.25, 240.0, 400),
)
_BY_NAME = {t.name: t for t in TIERS}


def tier(name: str) -> Tier:
    if name not in _BY_NAME:
        raise ValueError(f"unknown tier '{name}'; valid: {[t.name for t in TIERS]}")
    return _BY_NAME[name]


def cap_for(name: str) -> float:
    """The per-position cap for a maturity tier (the value the allocator uses)."""
    return tier(name).max_position


def next_tier(name: str) -> Tier | None:
    idx = TIERS.index(tier(name))
    return TIERS[idx + 1] if idx + 1 < len(TIERS) else None


def can_advance(name: str, days_live: float, events: int) -> bool:
    """True if a strategy in tier `name` has earned the NEXT tier (met its day+event bar).
    The top tier ('mature') never advances. Both conditions are required -- time AND volume."""
    nxt = next_tier(name)
    if nxt is None:
        return False
    return days_live >= nxt.min_days_live and events >= nxt.min_events
