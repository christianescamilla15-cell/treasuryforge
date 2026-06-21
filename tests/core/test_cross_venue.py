"""Cross-venue spread carry scoring: spread, short-venue choice, and the cost verdict."""

from __future__ import annotations

import pytest

from treasuryforge.cross_venue import cross_venue_opp


def test_spread_and_short_venue():
    o = cross_venue_opp("ETH", hl_apr=0.11, other_apr=-0.05, hold_hours=24)
    assert o.spread_apr == pytest.approx(0.16)
    assert o.short_venue == "HL"                 # HL funding higher -> short the perp there
    o2 = cross_venue_opp("ETH", hl_apr=-0.02, other_apr=0.10, other_name="binance")
    assert o2.short_venue == "binance"


def test_small_spread_is_no_trade():
    # spreads are usually small; 1% APR over 24h ~ 0.27bps vs a 15bp round-trip
    o = cross_venue_opp("BTC", hl_apr=0.11, other_apr=0.10, hold_hours=24)
    assert o.net_edge < 0 and o.verdict == "NO_TRADE"


def test_fat_persistent_spread_can_be_paper():
    # a big spread held long enough clears the doubled cost
    o = cross_venue_opp("X", hl_apr=0.60, other_apr=-0.20, hold_hours=336, round_trip=0.0015)
    assert o.net_edge > 0 and o.verdict == "PAPER"


def test_thin_positive_is_watch():
    # gross just above the round-trip -> positive but cost eats >50% -> WATCH
    o = cross_venue_opp("Y", hl_apr=0.20, other_apr=0.0, hold_hours=70, round_trip=0.0015)
    assert o.net_edge > 0 and o.verdict == "WATCH"


# -- mutation-killing: exact arithmetic, boundaries, defaults ------------------
def test_exact_net_and_bps_and_spread():
    o = cross_venue_opp("Z", hl_apr=0.40, other_apr=-0.20, hold_hours=168, round_trip=0.0015)
    assert o.spread_apr == pytest.approx(0.60)
    gross = 0.60 * 168 / (24 * 365)
    assert o.net_edge == pytest.approx(gross - 0.0015)        # gross - round_trip exactly
    assert o.net_edge_bps == pytest.approx(o.net_edge * 1e4)  # *1e4, not /1e4 or *1e3


def test_short_venue_tie_goes_to_hl():
    o = cross_venue_opp("T", hl_apr=0.05, other_apr=0.05)     # equal -> >= picks HL
    assert o.short_venue == "HL" and o.spread_apr == 0.0


def test_net_zero_boundary_is_no_trade():
    # choose params so net is exactly 0: gross == round_trip
    rt = 0.001
    hold = 100
    spread = rt * (24 * 365) / hold                          # gross = spread*hold/HPY = rt
    o = cross_venue_opp("B", hl_apr=spread, other_apr=0.0, hold_hours=hold, round_trip=rt)
    assert o.net_edge == pytest.approx(0.0, abs=1e-12) and o.verdict == "NO_TRADE"  # net<=0


def test_cost_ratio_exactly_at_threshold_is_paper():
    # cost_ratio == max_cost_ratio (0.5) -> NOT WATCH (strict >), so PAPER
    rt = 0.001
    # want (gross-net)/gross = 0.5 -> net = gross/2 -> gross = 2*rt
    hold = 100
    spread = 2 * rt * (24 * 365) / hold
    o = cross_venue_opp("P", hl_apr=spread, other_apr=0.0, hold_hours=hold, round_trip=rt)
    assert o.cost_ratio == pytest.approx(0.5) and o.verdict == "PAPER"


def test_defaults_are_pinned():
    o = cross_venue_opp("D", hl_apr=0.30, other_apr=0.0)     # all defaults
    assert o.round_trip == 0.0015 and o.hold_hours == 24 and o.other_name == "binance"
