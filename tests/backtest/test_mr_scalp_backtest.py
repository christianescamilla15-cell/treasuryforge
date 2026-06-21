"""MR_SCALP backtest — the result accounting (net return, edge/cost, adverse-selection
metrics) is pinned exactly, and an end-to-end run holds the honest invariants
(fills <= placed, costs subtract, no crash)."""

from __future__ import annotations

import math

import pytest

from treasuryforge.backtest.mr_scalp_backtest import (
    BARS_PER_DAY,
    CostModel,
    MrScalpResult,
    Trade,
    backtest_mr_scalp,
)
from treasuryforge.signals.mr_scalp import Bar, MrScalpParams


def _trade(ret, gross=None, bars=5):
    return Trade(0, 0, 100.0, 100.0 * (1 + ret), bars, "TP", ret, gross if gross is not None else ret)


def test_cost_model_round_trip_estimate():
    c = CostModel(maker_fee=0.0001, taker_fee=0.0004, spread=0.0003, slippage=0.0002)
    assert c.round_trip_estimate == pytest.approx(2 * 0.0004 + 0.0003 + 2 * 0.0002)


def test_net_return_compounds():
    r = MrScalpResult(returns=[0.01, -0.005, 0.02])
    assert r.net_return == pytest.approx(1.01 * 0.995 * 1.02 - 1.0)


def test_win_rate_and_filled_losers():
    r = MrScalpResult(trades=[_trade(0.01), _trade(-0.002), _trade(0.0)],
                      returns=[0.01, -0.002, 0.0])
    assert r.win_rate == pytest.approx(1 / 3)         # only +0.01 is a win
    assert r.filled_losers == 2                        # -0.002 and 0.0 (<=0)


def test_gross_net_cost_and_edge_ratio():
    r = MrScalpResult(trades=[_trade(0.001, gross=0.004), _trade(0.001, gross=0.004)],
                      returns=[0.001, 0.001])
    assert r.avg_gross == pytest.approx(0.004)
    assert r.avg_net == pytest.approx(0.001)
    assert r.cost_per_trade == pytest.approx(0.003)
    assert r.edge_cost_ratio == pytest.approx(0.004 / 0.003)


def test_trades_per_day_and_avg_hold():
    r = MrScalpResult(trades=[_trade(0.0, bars=4), _trade(0.0, bars=8)],
                      returns=[0.0, 0.0], n_bars=BARS_PER_DAY)   # 1 day
    assert r.trades_per_day == pytest.approx(2.0)
    assert r.avg_hold == pytest.approx(6.0)


def test_maker_fill_and_missed_rebound_rates():
    r = MrScalpResult(n_placed=10, n_filled=4, n_missed=5, missed_winners=3)
    assert r.maker_fill_rate == pytest.approx(0.4)
    assert r.missed_rebound_rate == pytest.approx(0.6)


def test_empty_result_is_safe():
    r = MrScalpResult()
    assert r.win_rate == 0.0 and r.edge_cost_ratio == 0.0
    assert r.trades_per_day == 0.0 and r.maker_fill_rate == 0.0


def _bars():
    # slow uptrend (EMA lags below) with periodic dips, enough to warm up the slow ATR
    out = []
    px = 100.0
    for i in range(400):
        px *= 1.0003
        dip = 0.985 if i % 37 == 36 else 1.0     # occasional sharp dip
        c = px * dip
        out.append(Bar(o=px, h=px * 1.001, l=c * 0.999, c=c, v=100.0 + i, ts=i))
    return out


def test_end_to_end_invariants():
    res = backtest_mr_scalp(_bars(), MrScalpParams(), CostModel())
    assert res.n_bars == 400
    assert res.n_filled <= res.n_placed <= res.n_signaled     # nothing fills that wasn't placed
    assert res.n_cost_skipped + res.n_placed == res.n_signaled
    for t in res.trades:                                       # costs always subtract: net <= gross
        assert t.ret <= t.gross + 1e-12
        assert not math.isnan(t.ret)
