"""Momentum ignition rule + net-of-cost backtest: entry confirmation, trailing exit,
hard stop, non-overlapping trades, and the honest distribution metrics."""

from __future__ import annotations

import pytest

from treasuryforge.momentum_backtest import backtest_many, backtest_momentum
from treasuryforge.signals.momentum import MomentumParams, entry_ok, simulate_exit

P = MomentumParams(enter_1m=0.05, confirm_1m=0.0, trail_frac=0.10, stop_frac=0.20,
                   max_hold=100, cost=0.001)


def _bar(c, hi=None, lo=None):
    return (c, hi if hi is not None else c, lo if lo is not None else c, c)


def test_entry_needs_ignition_and_follow_through():
    assert entry_ok(100, 101, 110, P)              # +1% then +8.9% -> fires
    assert not entry_ok(100, 101, 103, P)          # +2% < enter_1m -> no
    assert not entry_ok(100, 99, 110, P)           # prior bar DOWN -> confirm fails
    assert not entry_ok(0, 100, 110, P)            # guards zero/garbage prices


def test_entry_boundary_inclusive():
    # this-bar exactly +5% with prior exactly +0% -> both >= inclusive -> fires
    assert entry_ok(100.0, 100.0, 105.0, P)
    assert not entry_ok(100.0, 100.0, 104.99, P)   # just under enter_1m


def test_trailing_exit_locks_in_from_peak():
    # entry 100, rises to 150 (peak), then a bar dips to 134 -> trail 10% of 150 = 135 hit
    highs = [120.0, 150.0, 140.0]
    lows = [118.0, 148.0, 134.0]
    closes = [120.0, 150.0, 135.0]
    held, gross = simulate_exit(100.0, highs, lows, closes, P)
    assert held == 3
    assert gross == pytest.approx(135.0 / 100.0 - 1.0)   # exits at peak*(1-0.10)=135 -> +35%


def test_hard_stop_caps_the_loss():
    # entry 100, never makes a high, gaps down to 75 -> hard stop at 80 (-20%)
    highs = [100.0, 100.0]
    lows = [99.0, 75.0]
    closes = [99.5, 78.0]
    held, gross = simulate_exit(100.0, highs, lows, closes, P)
    assert held == 2 and gross == pytest.approx(-0.20)   # the -stop_frac, not -25%


def test_max_hold_forces_exit_at_close():
    p = MomentumParams(enter_1m=0.05, trail_frac=0.99, stop_frac=0.99, max_hold=3, cost=0.0)
    highs = [101.0, 102.0, 103.0, 104.0]
    lows = [100.0, 101.0, 102.0, 103.0]
    closes = [101.0, 102.0, 103.0, 104.0]
    held, gross = simulate_exit(100.0, highs, lows, closes, p)
    assert held == 3 and gross == pytest.approx(103.0 / 100.0 - 1.0)   # close of bar 3


def test_backtest_books_net_of_cost_and_is_non_overlapping():
    # one clean ignition then a trailing exit; cost subtracted once
    bars = [_bar(100), _bar(100),                      # warmup
            _bar(106, hi=106, lo=100),                 # +6% ignition (prior flat) -> ENTER here (i=2)
            _bar(120, hi=120, lo=105),                 # runs up, peak 120
            _bar(104, hi=120, lo=104)]                 # dips to 104 < trail(120*0.9=108) -> EXIT
    r = backtest_momentum(bars, P)
    assert r.n_trades == 1
    assert r.returns[0] == pytest.approx(108.0 / 106.0 - 1.0 - 0.001)   # entry 106, exit 108, -cost


def test_distribution_metrics_count_losers_honestly():
    from treasuryforge.momentum_backtest import MomentumResult
    r = MomentumResult(returns=[0.30, -0.20, 0.10, -0.05], holds=[10, 5, 8, 3])
    assert r.n_trades == 4 and r.win_rate == pytest.approx(0.5)
    assert r.avg_win == pytest.approx(0.20) and r.avg_loss == pytest.approx(-0.125)
    assert r.expectancy == pytest.approx((0.30 - 0.20 + 0.10 - 0.05) / 4)
    assert r.total_net == pytest.approx(0.15)
    assert r.profit_factor == pytest.approx(0.40 / 0.25)   # gains/losses
    assert r.avg_hold == pytest.approx(6.5)


def test_equity_and_drawdown():
    from treasuryforge.momentum_backtest import MomentumResult
    r = MomentumResult(returns=[0.5, -0.5, 0.2], holds=[1, 1, 1])
    eq = r.equity_curve
    assert eq[0] == pytest.approx(1.5) and eq[1] == pytest.approx(0.75)
    assert r.max_drawdown == pytest.approx(0.5)            # 1.5 -> 0.75 is a 50% drop


def test_result_is_frozen_and_defaults():
    import dataclasses

    from treasuryforge.momentum_backtest import MomentumResult
    r = MomentumResult()
    assert r.returns == [] and r.n_trades == 0 and r.win_rate == 0.0 and r.expectancy == 0.0
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.returns = [1.0]


def test_params_frozen():
    import dataclasses
    with pytest.raises(dataclasses.FrozenInstanceError):
        P.enter_1m = 0.0


def test_backtest_many_pools_across_coins():
    bars = [_bar(100), _bar(100), _bar(106, hi=106, lo=100),
            _bar(120, hi=120, lo=105), _bar(104, hi=120, lo=104)]
    pooled = backtest_many({"A": bars, "B": bars}, P)
    assert pooled.n_trades == 2                            # one per coin, pooled


# -- mutation-killers: defaults, guards, empty/boundary properties --------------
def test_momentum_params_defaults_pinned():
    p = MomentumParams()
    assert (p.enter_1m, p.confirm_1m) == (0.01, 0.0)
    assert (p.trail_frac, p.stop_frac) == (0.04, 0.05)
    assert p.max_hold == 240 and p.cost == 0.0013


def test_entry_ok_small_prices_not_guarded():
    p = MomentumParams(enter_1m=0.05)
    assert entry_ok(0.50, 0.51, 0.57, p)                  # valid sub-1 prices fire (kills <=1 guards)


def test_simulate_exit_empty_and_single_bar():
    p = MomentumParams(trail_frac=0.99, stop_frac=0.99, max_hold=10)
    assert simulate_exit(100.0, [], [], [], p) == (0, 0.0)            # n=0 (kills n>=0 crash / else 1.0)
    held, gross = simulate_exit(100.0, [105.0], [101.0], [104.0], p)  # 1 future bar, no trigger
    assert held == 1 and gross == pytest.approx(104.0 / 100.0 - 1.0)  # kills n>1 -> would give 0.0


def test_result_empty_properties():
    from treasuryforge.momentum_backtest import MomentumResult
    r = MomentumResult()
    assert r.holds == [] and r.avg_win == 0.0 and r.avg_loss == 0.0 and r.avg_hold == 0.0


def test_zero_return_is_a_loss_not_a_win():
    from treasuryforge.momentum_backtest import MomentumResult
    r = MomentumResult(returns=[0.0, 0.1, -0.1], holds=[1, 1, 1])
    assert r.wins == [0.1]                                 # > 0 strict
    assert r.losses == [0.0, -0.1]                         # <= 0 inclusive
    assert r.win_rate == pytest.approx(1 / 3)


def test_backtest_exact_two_trades_pins_scan_indices():
    # a deterministic 2-trade run; exact returns/holds catch any scan-loop index mutation
    p = MomentumParams(enter_1m=0.05, confirm_1m=0.03, trail_frac=0.10, stop_frac=0.20,
                       max_hold=100, cost=0.001)
    bars = [(95, 95, 95, 95), (100, 100, 100, 100), (106, 106, 100, 106),
            (115, 120, 110, 115), (110, 120, 109, 110), (108, 115, 107, 108),
            (108, 108, 108, 108), (115, 115, 108, 115), (125, 130, 120, 125),
            (112, 130, 110, 112)]
    r = backtest_momentum(bars, p)
    assert r.n_trades == 2 and r.holds == [3, 1]
    assert r.returns == pytest.approx([0.017868, -0.101], abs=1e-5)
