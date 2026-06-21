"""Carry economic backtest: position booking, the round-trip cost, the age gate, and
that a short choppy episode loses while a long one wins."""

from __future__ import annotations

import pytest

from treasuryforge.carry_backtest import backtest_carry


def test_single_long_episode_nets_funding_minus_round_trip():
    # 10 hours of 0.0001 funding, then it drops -> one position
    hist = [0.0001] * 10 + [0.0]
    r = backtest_carry(hist, enter=0.00005, exit_=0.00001, round_trip=0.0005)
    assert r.n_positions == 1
    assert r.total_funding == pytest.approx(0.001)            # 10 * 0.0001
    assert r.net == pytest.approx(0.001 - 0.0005)             # funding - one round-trip
    assert r.holds == [10] and r.win_rate == 1.0


def test_short_episode_loses_to_the_round_trip():
    hist = [0.0001, 0.0001, 0.0]                              # only 2h -> 0.0002 < 0.0005 cost
    r = backtest_carry(hist, enter=0.00005, exit_=0.00001, round_trip=0.0005)
    assert r.n_positions == 1 and r.net < 0 and r.win_rate == 0.0


def test_age_gate_skips_the_first_hours():
    hist = [0.0001] * 10 + [0.0]
    fresh = backtest_carry(hist, enter=0.00005, exit_=0.00001, round_trip=0.0005, min_age=0)
    aged = backtest_carry(hist, enter=0.00005, exit_=0.00001, round_trip=0.0005, min_age=5)
    assert fresh.holds == [10] and aged.holds == [6]          # aged enters at hour 5 -> holds 6
    assert aged.total_funding < fresh.total_funding           # forgoes the early funding


def test_age_gate_skips_episodes_that_never_reach_age():
    hist = [0.0001, 0.0001, 0.0, 0.0001] * 3                  # all 2h episodes
    aged = backtest_carry(hist, enter=0.00005, exit_=0.00001, round_trip=0.0005, min_age=5)
    assert aged.n_positions == 0                              # none survive to age 5 -> no trades


def test_two_episodes_accumulate():
    hist = [0.0001] * 8 + [0.0, 0.0] + [0.0001] * 8 + [0.0]
    r = backtest_carry(hist, enter=0.00005, exit_=0.00001, round_trip=0.0005)
    assert r.n_positions == 2 and r.total_cost == pytest.approx(2 * 0.0005)


# -- mutation-killing: result arithmetic + properties --------------------------
def test_result_properties_exact():
    hist = [0.0001] * 10 + [0.0]
    r = backtest_carry(hist, enter=0.00005, exit_=0.00001, round_trip=0.0005)
    assert r.net == pytest.approx(r.total_funding - r.total_cost)   # funding - cost
    assert r.net_per_position == pytest.approx(r.net / r.n_positions)
    assert r.avg_hold == pytest.approx(10.0)


def test_win_rate_counts_strictly_positive():
    # two positions: one wins, one clearly loses to the round-trip
    hist = ([0.0001] * 10 + [0.0, 0.0] +        # +1.0e-3 - 5e-4 = win
            [0.00005] * 8 + [0.0])              # 8*5e-5=4e-4 - 5e-4 = -1e-4 -> loss
    r = backtest_carry(hist, enter=0.00004, exit_=0.00001, round_trip=0.0005)
    assert r.n_positions == 2 and r.win_rate == pytest.approx(0.5)


def test_empty_result_safe():
    r = backtest_carry([0.0, 0.0], enter=0.0001, exit_=0.00001, round_trip=0.0005)
    assert r.n_positions == 0 and r.win_rate == 0.0 and r.net_per_position == 0.0 and r.avg_hold == 0.0


def test_result_defaults_and_frozen():
    import dataclasses

    from treasuryforge.carry_backtest import CarryBtResult
    r = CarryBtResult(0, 0.0, 0.0)
    assert r.returns == [] and r.holds == []
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.n_positions = 5


def test_win_rate_zero_is_not_a_win():
    from treasuryforge.carry_backtest import CarryBtResult
    r = CarryBtResult(2, 0.0, 0.0, returns=[0.0, 0.001], holds=[1, 1])
    assert r.win_rate == pytest.approx(0.5)              # 0.0 not > 0


def test_avg_hold_and_net_per_position_exact():
    from treasuryforge.carry_backtest import CarryBtResult
    r = CarryBtResult(2, 0.005, 0.001, returns=[0.002, 0.002], holds=[2, 4])
    assert r.avg_hold == pytest.approx(3.0)             # sum/len, not sum*len
    assert r.net == pytest.approx(0.005 - 0.001)        # funding - cost
    assert r.net_per_position == pytest.approx(r.net / 2)


def test_total_funding_accumulates_two_positions():
    hist = [0.0001] * 8 + [0.0, 0.0] + [0.0001] * 8 + [0.0]
    r = backtest_carry(hist, enter=0.00005, exit_=0.00001, round_trip=0.0005)
    assert r.n_positions == 2 and r.total_funding == pytest.approx(2 * 8 * 0.0001)  # += accumulates


def test_enter_boundary_inclusive():
    r = backtest_carry([0.0001, 0.0001, 0.0], enter=0.0001, exit_=0.00005, round_trip=0.0005)
    assert r.n_positions == 1 and r.holds == [2]        # f == enter starts (kills >= -> >)


def test_exit_boundary_keeps_position():
    r = backtest_carry([0.0001, 0.00005, 0.0001, 0.0], enter=0.0001, exit_=0.00005, round_trip=0.0005)
    assert r.holds == [3]                               # f == exit not < exit -> stays in
