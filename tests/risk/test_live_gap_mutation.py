"""Mutation-hardening for the backtest-live gap detector: the full verdict
decision tree with each boundary exact, the degradation/slip-ratio math, the
approved property, and the exact render format."""

from __future__ import annotations

import pytest

from treasuryforge.risk import assess_backtest_live_gap
from treasuryforge.risk.live_gap import _mean


def base(**over):
    kw = dict(name="S", backtest_returns=[0.01] * 40, live_returns=[0.008] * 40,
              modeled_slippage=0.001, realized_slippage=0.0012)
    kw.update(over)
    return assess_backtest_live_gap(**kw)


def test_mean_exact_and_empty():
    assert _mean([1.0, 2.0, 3.0]) == 2.0
    assert _mean([]) == 0.0


def test_verdict_decision_tree_each_branch():
    assert base(backtest_returns=[0.0] * 40).verdict == "REJECT: NO_BACKTEST_EDGE"      # Eb==0
    assert base(backtest_returns=[-0.01] * 40).verdict == "REJECT: NO_BACKTEST_EDGE"
    assert base(live_returns=[0.008] * 29).verdict == "REJECT: INSUFFICIENT_LIVE_DATA (29/30)"
    assert "INSUFFICIENT" not in base(live_returns=[0.008] * 30).verdict                # n==min ok
    assert base(live_returns=[0.0] * 40).verdict == "REJECT: EDGE_DECAYED"              # El==0
    assert base(live_returns=[-0.001] * 40).verdict == "REJECT: EDGE_DECAYED"
    assert base(live_returns=[0.004] * 40).verdict == "REJECT: BACKTEST_LIVE_GAP"       # 0.4<0.5
    assert base(realized_slippage=0.003).verdict == "REJECT: EXECUTION_EDGE_LEAK"       # 3x>2x
    assert base().verdict == "APPROVE_STAGE_1: MICRO_CAPITAL"


def test_degradation_boundary_inclusive():
    r = base(live_returns=[0.005] * 40)                  # El/Eb == 0.5 exactly
    assert r.verdict == "APPROVE_STAGE_1: MICRO_CAPITAL"  # not < min -> not a gap
    assert r.gap["degradation"] == pytest.approx(0.5)


def test_slip_ratio_boundary_inclusive():
    r = base(realized_slippage=0.002)                    # ratio == 2.0 exactly
    assert r.verdict == "APPROVE_STAGE_1: MICRO_CAPITAL"  # not > max -> not a leak
    assert r.execution["ratio"] == pytest.approx(2.0)


def test_degradation_zero_when_no_backtest_edge():
    assert base(backtest_returns=[0.0] * 40).gap["degradation"] == 0.0


def test_slip_ratio_inf_when_zero_modeled():
    assert base(modeled_slippage=0.0).execution["ratio"] == float("inf")


def test_approved_property():
    assert base().approved is True
    assert base(backtest_returns=[0.0] * 40).approved is False


def test_maker_fill_na_when_none():
    assert base().execution["maker_fill"] == "n/a"


def test_render_exact_format():
    r = base(maker_fill_rate=0.7, post_fill_drift=-0.0005)
    assert r.render() == "\n".join([
        "STRATEGY: S", "",
        "BACKTEST", "  expectancy/trade:    +1.000e-02", "  Sharpe:              0.00", "",
        "PAPER LIVE", "  trades:              40", "  expectancy/trade:    +8.000e-03",
        "  Sharpe:              0.00", "",
        "GAP", "  expectancy retained: 80%  (min 50%)", "",
        "EXECUTION QUALITY", "  modeled slippage:    0.100%",
        "  realized slippage:   0.120%  (1.2x modeled, max 2.0x)",
        "  maker fill rate:     70%", "  post-fill drift:     -0.050%", "",
        "VERDICT", "  APPROVE_STAGE_1: MICRO_CAPITAL"])
