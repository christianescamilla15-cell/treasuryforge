"""Vol-scaled TSMOM signal + continuous-position backtest: momentum sign, vol scaling,
leverage cap, long-only clamp, no look-ahead, and net-of-turnover accounting."""

from __future__ import annotations

import pytest

from treasuryforge.signals.tsmom import (
    TsmomParams,
    momentum_sign,
    realized_vol,
    target_position,
)
from treasuryforge.tsmom_backtest import backtest_tsmom, backtest_tsmom_many


def test_realized_vol_exact():
    assert realized_vol([0.01, -0.01, 0.01, -0.01], 4) == pytest.approx(0.01)   # mean 0, |r|=0.01
    assert realized_vol([0.05], 4) == 0.0                                       # <2 -> 0
    assert realized_vol([], 10) == 0.0


def test_momentum_sign_direction_and_boundary():
    assert momentum_sign([1, 2, 3, 4, 5], 2) == 1.0          # 5 > 3 over lookback 2
    assert momentum_sign([5, 4, 3, 2, 1], 2) == -1.0         # down
    assert momentum_sign([1, 2, 3, 3], 1) == 0.0             # flat over last 1 (3==3)
    assert momentum_sign([1, 2, 3], 3) == 0.0                # len <= lookback -> 0


def test_target_position_vol_scaling_and_cap():
    p = TsmomParams(lookback=2, vol_window=4, target_vol=0.02, max_leverage=3.0)
    closes = [1, 1, 1, 2, 3]                                  # up -> long
    rets = [0.0, 0.0, 1.0, 0.5]                               # vol of these (window 4)
    rv = realized_vol(rets, 4)
    pos = target_position(closes, rets, p)
    assert pos == pytest.approx(min(0.02 / rv, 3.0))         # vol-scaled, sign +1
    # tiny vol -> would lever huge -> capped at max_leverage
    calm = target_position([1, 1, 1, 1, 2], [0.0, 0.0, 0.0, 0.0], p)
    assert calm == 0.0                                       # vol 0 -> can't size -> flat


def test_long_only_clamps_shorts():
    p = TsmomParams(lookback=2, vol_window=3, target_vol=0.02, long_short=False)
    down = [3, 3, 3, 2, 1]
    rets = [0.0, 0.0, -0.33, -0.5]
    assert target_position(down, rets, p) == 0.0             # negative momentum -> flat (no short)
    p2 = TsmomParams(lookback=2, vol_window=3, target_vol=0.02, long_short=True)
    assert target_position(down, rets, p2) < 0.0            # long_short -> shorts


def test_backtest_no_lookahead_and_net_accounting():
    # rising series -> goes long after warmup, earns the up-moves minus turnover cost
    bars = [(0, 0, 0, c) for c in [1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8]]
    p = TsmomParams(lookback=2, vol_window=2, target_vol=0.05, max_leverage=2.0, cost=0.001)
    r = backtest_tsmom(bars, p)
    assert r.n_periods > 0
    # every strategy return uses a position decided from PAST closes only (no look-ahead):
    # reconstruct the first period explicitly
    warmup = max(p.lookback, p.vol_window) + 1               # = 3
    closes = [b[3] for b in bars]
    rets = [0.0] + [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))]
    pos0 = target_position(closes[: warmup + 1], rets[1: warmup + 1], p)
    expected0 = pos0 * rets[warmup + 1] - p.cost * abs(pos0 - 0.0)
    assert r.returns[0] == pytest.approx(expected0)


def test_result_metrics_and_frozen():
    import dataclasses

    from treasuryforge.tsmom_backtest import TsmomResult
    r = TsmomResult(returns=[0.5, -0.5, 0.2], positions=[1.0, -1.0, 0.5])
    assert r.n_periods == 3
    assert r.equity_curve[1] == pytest.approx(0.75)         # 1.5 * 0.5
    assert r.max_drawdown == pytest.approx(0.5)
    assert r.total_net == pytest.approx(1.5 * 0.5 * 1.2 - 1.0)
    assert r.turnover == pytest.approx((abs(-1 - 1) + abs(0.5 - -1)) / 2)   # mean |Δpos|
    assert r.exposure == pytest.approx((1 + 1 + 0.5) / 3)
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.returns = []


def test_flat_signal_sits_out():
    bars = [(0, 0, 0, 1.0) for _ in range(20)]               # constant price -> no momentum, no vol
    r = backtest_tsmom(bars, TsmomParams(lookback=3, vol_window=3))
    assert r.exposure == 0.0 and r.total_net == pytest.approx(0.0)   # never positions


def test_portfolio_averages_coins():
    bars = [(0, 0, 0, c) for c in [1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7]]
    p = TsmomParams(lookback=2, vol_window=2, target_vol=0.05)
    pooled = backtest_tsmom_many({"A": bars, "B": bars}, p)
    solo = backtest_tsmom(bars, p)
    # two identical coins -> portfolio return equals the single-coin return each period
    assert pooled.returns[-1] == pytest.approx(solo.returns[-1])


# -- mutation-killers: defaults, frozen, exact vol, index, empty metrics --------
def test_tsmom_params_frozen_and_defaults():
    import dataclasses
    p = TsmomParams()
    assert (p.lookback, p.vol_window) == (24, 24)
    assert p.target_vol == 0.01 and p.max_leverage == 3.0
    assert p.cost == 0.0006 and p.long_short is True
    with pytest.raises(dataclasses.FrozenInstanceError):
        p.lookback = 1


def test_realized_vol_nonzero_mean_and_n2():
    assert realized_vol([0.0, 0.0, 0.3], 3) == pytest.approx(0.02 ** 0.5)   # mean .1, var .02 (pop)
    assert realized_vol([0.0, 0.2], 2) == pytest.approx(0.1)                # n=2 computes (kills <=2 / <3)


def test_momentum_sign_index_pinned():
    assert momentum_sign([1.0, 5.0, 1.0, 1.0, 2.0], 2) == 1.0    # closes[-1]/closes[-3]=2/1>1 -> +1
    assert momentum_sign([1.0, 5.0, 1.0, 1.0, 0.5], 2) == -1.0   # 0.5/1<1 -> -1 (kills wrong index)


def test_tsmom_result_defaults_and_empty_metrics():
    from treasuryforge.tsmom_backtest import TsmomResult
    r = TsmomResult()
    assert r.returns == [] and r.positions == []
    assert r.turnover == 0.0 and r.exposure == 0.0 and r.total_net == 0.0


def test_turnover_needs_two_positions():
    from treasuryforge.tsmom_backtest import TsmomResult
    assert TsmomResult(returns=[0.1], positions=[1.0]).turnover == 0.0   # len<2 (kills <=2/<3/else 1.0)
    r2 = TsmomResult(returns=[0.1, 0.1], positions=[1.0, 0.5])
    assert r2.turnover == pytest.approx(0.5)


def _P():
    return TsmomParams(lookback=2, vol_window=2, target_vol=0.05, max_leverage=2.0, cost=0.001)


def test_backtest_exact_series_pins_indices():
    # deterministic series; exact returns + positions catch any rets/slice/position mutation
    bars = [(0, 0, 0, c) for c in [1.0, 1.1, 1.2, 1.3, 1.25, 1.4, 1.5, 1.45, 1.6]]
    r = backtest_tsmom(bars, _P())
    assert r.returns == pytest.approx([-0.078923, 0.097347, 0.044886, -0.068036, 0.097701], abs=1e-5)
    assert r.positions == pytest.approx([2.0, 0.8211, 0.6311, 2.0, 0.9545], abs=1e-3)


def test_portfolio_positions_average_and_filter_short():
    bars = [(0, 0, 0, c) for c in [1.0, 1.1, 1.2, 1.3, 1.25, 1.4, 1.5, 1.45, 1.6]]
    short = [(0, 0, 0, 1.0)] * 3                              # too short -> 0 periods, filtered out
    pooled = backtest_tsmom_many({"A": bars, "B": bars, "S": short}, _P())
    solo = backtest_tsmom(bars, _P())
    # S excluded (n_periods 0); A,B identical -> pooled position == solo position (kills *len, index)
    assert pooled.positions[-1] == pytest.approx(solo.positions[-1])
    assert pooled.n_periods == solo.n_periods
