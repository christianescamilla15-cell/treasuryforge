"""Backtest-to-live gap detector — the bridge before real capital."""

from __future__ import annotations

from treasuryforge.risk import assess_backtest_live_gap

BT = [0.001] * 100                  # backtest expectancy +0.001/trade


def _gap(live, **kw):
    base = dict(modeled_slippage=0.0005, realized_slippage=0.0005,
                min_live_trades=30, min_degradation=0.5, max_slippage_ratio=2.0)
    base.update(kw)
    return assess_backtest_live_gap("X", BT, live, **base)


def test_insufficient_live_data():
    r = _gap([0.001] * 10)                       # only 10 paper trades
    assert "INSUFFICIENT_LIVE_DATA" in r.verdict


def test_no_backtest_edge():
    r = assess_backtest_live_gap("X", [-0.001] * 100, [0.001] * 50,
                                 modeled_slippage=0.0005, realized_slippage=0.0005)
    assert r.verdict == "REJECT: NO_BACKTEST_EDGE"


def test_edge_decayed_when_live_negative():
    r = _gap([-0.0005] * 50)                      # live expectancy went negative
    assert r.verdict == "REJECT: EDGE_DECAYED"


def test_backtest_live_gap_when_degraded():
    r = _gap([0.0003] * 50)                       # 0.0003/0.001 = 30% retained < 50%
    assert r.verdict == "REJECT: BACKTEST_LIVE_GAP"
    assert r.gap["degradation"] == 0.3


def test_execution_edge_leak_on_slippage():
    r = _gap([0.0008] * 50, realized_slippage=0.002)   # 4x modeled -> leak
    assert r.verdict == "REJECT: EXECUTION_EDGE_LEAK"


def test_approve_stage_1_when_survives():
    r = _gap([0.0008] * 50, maker_fill_rate=0.6, post_fill_drift=-0.0001)
    assert r.verdict == "APPROVE_STAGE_1: MICRO_CAPITAL" and r.approved


def test_render_has_sections():
    out = _gap([0.0008] * 50, maker_fill_rate=0.6).render()
    for s in ("BACKTEST", "PAPER LIVE", "GAP", "EXECUTION QUALITY", "VERDICT"):
        assert s in out
