"""Cross-venue funding carry (Roadmap, was deferred) — MEASURE before building.

Single-venue carry is break-even. The cross-venue idea: short the perp on the venue
where funding is high-positive and long it on the venue where funding is low/negative,
delta-neutral. Net funding = the SPREAD between venues, which can exceed either alone.

But funding is arbitraged ACROSS venues (the whole point is to pin perp to spot), so
spreads tend to be small, while the cost roughly DOUBLES (a round-trip on TWO venues,
4 perp legs, plus collateral on both and transfer/latency risk). So this is almost
certainly marginal too -- but we measure it honestly instead of assuming.

This is decision-only: it scores the spread net of a (doubled) cost over a hold and
emits a verdict, exactly like the single-venue screener. Building an actual cross-venue
executor (exchange risk, collateral fragmentation, cross-liquidation) waits on a YES here.
"""

from __future__ import annotations

from dataclasses import dataclass

HOURS_PER_YEAR = 24 * 365


@dataclass(frozen=True)
class CrossVenueOpp:
    coin: str
    hl_apr: float
    other_apr: float
    other_name: str
    short_venue: str            # where you SHORT the perp (receive the higher funding)
    round_trip: float
    hold_hours: int
    net_edge: float             # fractional, over the hold
    verdict: str

    @property
    def spread_apr(self) -> float:
        return abs(self.hl_apr - self.other_apr)

    @property
    def net_edge_bps(self) -> float:
        return self.net_edge * 1e4

    @property
    def gross(self) -> float:
        return self.spread_apr * self.hold_hours / HOURS_PER_YEAR

    @property
    def cost_ratio(self) -> float:
        return (self.gross - self.net_edge) / self.gross if self.gross > 1e-12 else float("inf")


def cross_venue_opp(coin: str, *, hl_apr: float, other_apr: float, other_name: str = "binance",
                    round_trip: float = 0.0015, hold_hours: int = 24,
                    max_cost_ratio: float = 0.5) -> CrossVenueOpp:
    """Score the cross-venue spread carry. round_trip defaults to ~15bps (two venues,
    4 legs, no held-spot overlay)."""
    spread_apr = abs(hl_apr - other_apr)
    short_venue = "HL" if hl_apr >= other_apr else other_name
    gross = spread_apr * hold_hours / HOURS_PER_YEAR        # fractional spread over the hold
    net = gross - round_trip
    if net <= 0:
        verdict = "NO_TRADE"
    elif gross <= 0 or (gross - net) / gross > max_cost_ratio:
        verdict = "WATCH"
    else:
        verdict = "PAPER"
    return CrossVenueOpp(coin=coin, hl_apr=hl_apr, other_apr=other_apr, other_name=other_name,
                         short_venue=short_venue, round_trip=round_trip, hold_hours=hold_hours,
                         net_edge=net, verdict=verdict)
