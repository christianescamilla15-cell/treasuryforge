"""Multi-venue funding spread: the widest pairwise spread across N venues, short/long
direction, and graceful degradation when a venue is unreachable."""

from __future__ import annotations

import pytest

from treasuryforge.venue_spread import VenueSpread, pairwise_spreads


def test_three_venues_widest_pair_and_direction():
    # XRP-like: HL +10.9, OKX +11.0, BIN +6.9 -> widest is OKX-BIN (or HL-BIN), 4.1
    m = pairwise_spreads({"HL": 0.109, "OKX": 0.110, "BIN": 0.069})
    assert len(m.pairwise) == 3                       # C(3,2)
    assert m.missing == ()
    w = m.widest
    assert w is not None
    assert w.spread_apr == pytest.approx(0.041)       # 0.110 - 0.069
    assert w.short_venue == "OKX" and w.long_venue == "BIN"   # short the higher funding
    assert m.widest_apr == pytest.approx(0.041)


def test_widest_beats_a_fixed_pair():
    # ZEC-like: HL +2.9, OKX -4.2, BIN -10.0. HL-OKX (fixed) = 7.1, but HL-BIN = 12.9 is widest
    m = pairwise_spreads({"HL": 0.029, "OKX": -0.042, "BIN": -0.100})
    assert m.widest.spread_apr == pytest.approx(0.129)        # HL - BIN
    assert m.widest.short_venue == "HL" and m.widest.long_venue == "BIN"
    fixed_hl_okx = next(s for s in m.pairwise
                        if {s.short_venue, s.long_venue} == {"HL", "OKX"})
    assert fixed_hl_okx.spread_apr == pytest.approx(0.071)
    assert m.widest.spread_apr > fixed_hl_okx.spread_apr      # the whole point


def test_pairs_sorted_widest_first():
    m = pairwise_spreads({"A": 0.10, "B": 0.00, "C": 0.05})
    aprs = [s.spread_apr for s in m.pairwise]
    assert aprs == sorted(aprs, reverse=True)                 # descending
    assert aprs[0] == pytest.approx(0.10)                     # A-B


def test_unreachable_venue_degrades_gracefully():
    # Binance None this tick -> fall back to the HL-OKX pair, no crash
    m = pairwise_spreads({"HL": 0.029, "OKX": -0.042, "BIN": None})
    assert m.missing == ("BIN",)
    assert "BIN" not in m.funding_apr
    assert len(m.pairwise) == 1                               # only HL-OKX survives
    assert m.widest.spread_apr == pytest.approx(0.071)


def test_single_reachable_venue_has_no_pair():
    m = pairwise_spreads({"HL": 0.05, "OKX": None, "BIN": None})
    assert m.pairwise == () and m.widest is None and m.widest_apr == 0.0
    assert m.missing == ("BIN", "OKX")                        # sorted


def test_empty_input():
    m = pairwise_spreads({})
    assert m.pairwise == () and m.funding_apr == {} and m.widest_apr == 0.0


def test_equal_funding_zero_spread_deterministic_direction():
    # exactly equal -> spread 0; direction uses >= so the sorted-first venue is "short"
    m = pairwise_spreads({"HL": 0.05, "OKX": 0.05})
    assert m.widest.spread_apr == 0.0
    assert m.widest.short_venue == "HL" and m.widest.long_venue == "OKX"   # a>=b path


def test_spread_is_frozen():
    import dataclasses
    s = VenueSpread("HL", "OKX", 0.07)
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.spread_apr = 0.0
