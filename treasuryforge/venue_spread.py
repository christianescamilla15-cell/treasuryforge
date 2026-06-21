"""Multi-venue funding spread (Roadmap v2) -- the WIDEST pairwise spread across venues.

With N venues you capture the widest pair at each moment, not a fixed pair. This is the
whole reason a 3rd venue raises the opportunity duty cycle: when one pair converges (XRP
HL-OKX went to 0%), another may still be wide (XRP HL-Binance held ~4%). You always take
the widest available pair, and short the higher-funding venue / long the lower.

Pure, stdlib, offline-testable -- no I/O, so the duty-cycle and economics machinery can be
fed from any venue set without coupling to a fetcher.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations


@dataclass(frozen=True)
class VenueSpread:
    short_venue: str        # the higher-funding venue (short it to RECEIVE funding)
    long_venue: str         # the lower-funding venue (long it)
    spread_apr: float       # |funding difference|, annualised (always >= 0)


@dataclass(frozen=True)
class SpreadMatrix:
    funding_apr: dict[str, float]      # venue -> funding APR (only the reachable venues)
    pairwise: tuple[VenueSpread, ...]  # every reachable pair, widest first
    missing: tuple[str, ...]           # venues that were unreachable this tick

    @property
    def widest(self) -> VenueSpread | None:
        return self.pairwise[0] if self.pairwise else None

    @property
    def widest_apr(self) -> float:
        return self.pairwise[0].spread_apr if self.pairwise else 0.0


def pairwise_spreads(funding_by_venue: dict[str, float | None]) -> SpreadMatrix:
    """funding_by_venue: venue -> annualised funding APR, or None if unreachable this tick.

    Returns every pairwise spread among the reachable venues, widest first. A spread shorts
    the higher-funding venue and longs the lower (delta-neutral, captures the difference)."""
    reachable = {v: f for v, f in funding_by_venue.items() if f is not None}
    missing = tuple(sorted(v for v, f in funding_by_venue.items() if f is None))
    pairs: list[VenueSpread] = []
    for a, b in combinations(sorted(reachable), 2):
        hi, lo = (a, b) if reachable[a] >= reachable[b] else (b, a)
        pairs.append(VenueSpread(short_venue=hi, long_venue=lo,
                                 spread_apr=abs(reachable[a] - reachable[b])))
    pairs.sort(key=lambda s: s.spread_apr, reverse=True)
    return SpreadMatrix(funding_apr=reachable, pairwise=tuple(pairs), missing=missing)
