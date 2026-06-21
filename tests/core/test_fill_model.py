"""Realistic fill model (A2): fill-probability monotonicity, the maker-first expected
cost bounded by [maker, taker], adverse selection, and the fill-dependence kill flag."""

from __future__ import annotations

import pytest

from treasuryforge.fill_model import (
    FillModelParams,
    estimate_leg_cost,
    maker_fill_probability,
    perfect_round_trip_cost,
    round_trip_cost,
)


def test_fill_prob_zero_without_volatility():
    assert maker_fill_probability(half_spread=0.0002, sigma_window=0.0) == 0.0


def test_fill_prob_monotone_in_volatility():
    p_low = maker_fill_probability(0.0002, 0.0002)
    p_high = maker_fill_probability(0.0002, 0.002)
    assert 0.0 <= p_low < p_high <= 1.0          # more vol -> more likely to be reached


def test_fill_prob_saturates_when_spread_zero():
    assert maker_fill_probability(half_spread=0.0, sigma_window=0.001) == 1.0


def test_leg_cost_between_maker_and_taker():
    p = FillModelParams()
    est = estimate_leg_cost(p, spread=0.0004, vol=0.0006)
    assert 0.0 < est.maker_fill_prob < 1.0
    # cost is a blend of (maker+adverse) and taker, so it sits between maker and taker
    assert p.maker_fee < est.expected_cost < p.taker_fee
    assert est.taker_fallback_prob == pytest.approx(1.0 - est.maker_fill_prob)


def test_high_vol_leg_cost_approaches_maker_plus_adverse():
    p = FillModelParams()
    est = estimate_leg_cost(p, spread=0.0001, vol=0.02)     # almost surely fills passive
    assert est.maker_fill_prob > 0.99
    assert est.expected_cost == pytest.approx(p.maker_fee + p.adverse_bps, abs=2e-6)


def test_round_trip_vs_perfect_floor_and_fill_dependence():
    p = FillModelParams()
    realistic = round_trip_cost(p, spread=0.0006, vol=0.0004)   # low vol -> taker fallback likely
    floor = perfect_round_trip_cost(p)                          # 4 * maker
    assert realistic > floor                                    # honest cost exceeds the fantasy
    est = estimate_leg_cost(p, spread=0.0006, vol=0.0004)
    assert est.is_fill_dependent(p.maker_fee)                   # only-profitable-with-perfect-fills flag


# -- mutation-killing: exact blend, defaults, boundaries ------------------------
def test_leg_cost_exact_blend():
    p = FillModelParams(maker_fee=0.0001, taker_fee=0.0004, adverse_bps=0.0001, max_maker_wait=3)
    est = estimate_leg_cost(p, spread=0.0004, vol=0.0006)
    pf = est.maker_fill_prob
    assert est.expected_cost == pytest.approx(pf * (0.0001 + 0.0001) + (1 - pf) * 0.0004)
    assert est.adverse_selection == pytest.approx(pf * 0.0001)   # p * adverse_bps


def test_perfect_floor_is_legs_times_maker():
    p = FillModelParams(maker_fee=0.00015)
    assert perfect_round_trip_cost(p, legs=4) == pytest.approx(4 * 0.00015)
    assert perfect_round_trip_cost(p, legs=2) == pytest.approx(2 * 0.00015)


def test_round_trip_is_legs_times_leg_cost():
    p = FillModelParams()
    leg = estimate_leg_cost(p, spread=0.0004, vol=0.001).expected_cost
    assert round_trip_cost(p, spread=0.0004, vol=0.001, legs=4) == pytest.approx(4 * leg)


def test_fill_dependent_margin_boundary():
    p = FillModelParams()
    est = estimate_leg_cost(p, spread=0.0004, vol=0.001)        # mostly maker -> cost ~ maker+adverse
    # cost just under perfect*1.5 -> not flagged; the default margin is 1.5
    assert est.is_fill_dependent(est.expected_cost / 1.5 - 1e-9)
    assert not est.is_fill_dependent(est.expected_cost / 1.5 + 1e-9)


def test_default_params_pinned():
    p = FillModelParams()
    assert p.maker_fee == 0.00015 and p.taker_fee == 0.00045
    assert p.max_maker_wait == 3 and p.adverse_bps == 0.0001


def test_params_and_estimate_are_frozen():
    import dataclasses
    with pytest.raises(dataclasses.FrozenInstanceError):
        FillModelParams().maker_fee = 0.5
    est = estimate_leg_cost(FillModelParams(), spread=0.0004, vol=0.001)
    with pytest.raises(dataclasses.FrozenInstanceError):
        est.expected_cost = 0.5


def test_fill_dependent_strict_boundary():
    est = estimate_leg_cost(FillModelParams(), spread=0.0004, vol=0.001)
    # at exactly expected_cost == perfect*1.5 -> NOT fill-dependent (kills `>` -> `>=`)
    assert not est.is_fill_dependent(est.expected_cost / 1.5)


def test_maker_fill_probability_known_value():
    # half_spread/sigma = 1 -> Phi(1)=0.8413 -> p = 2*(1-0.8413) = 0.3173 (pins the _phi formula)
    assert maker_fill_probability(1.0, 1.0) == pytest.approx(0.3173, abs=0.002)


def test_cost_rises_with_spread_and_falls_with_wait():
    p = FillModelParams()
    tight = estimate_leg_cost(p, spread=0.0002, vol=0.001).expected_cost
    wide = estimate_leg_cost(p, spread=0.0010, vol=0.001).expected_cost
    assert wide > tight                              # wider spread -> harder maker fill -> costlier
    short_wait = estimate_leg_cost(FillModelParams(max_maker_wait=1), spread=0.0006, vol=0.0005)
    long_wait = estimate_leg_cost(FillModelParams(max_maker_wait=10), spread=0.0006, vol=0.0005)
    assert long_wait.expected_cost < short_wait.expected_cost   # more wait -> more likely to fill


def test_round_trip_default_legs_is_four():
    p = FillModelParams()
    leg = estimate_leg_cost(p, spread=0.0004, vol=0.001).expected_cost
    assert round_trip_cost(p, spread=0.0004, vol=0.001) == pytest.approx(4 * leg)  # default legs 4
    assert perfect_round_trip_cost(p) == pytest.approx(4 * p.maker_fee)
