"""Stage Ladder + Demotion Rules — strategy lifecycle governance."""

from __future__ import annotations

from treasuryforge.risk import LivePerformance, Stage, evaluate_stage


def perf(**over) -> LivePerformance:
    base = dict(edge_retention=0.80, slippage_ratio=1.2, live_dd=0.10,
                expected_dd_p75=0.15, expected_dd_p90=0.20, stress_dd_p95=0.30,
                sample_size=50, min_sample=30)
    base.update(over)
    return LivePerformance(**base)


# -- KILL (highest priority) -------------------------------------------------
def test_kill_on_live_dd_over_stress_p95():
    d = evaluate_stage(Stage.MICRO_CAPITAL, perf(live_dd=0.35))   # > p95 0.30
    assert d.action == "KILL" and d.to_stage == Stage.DEAD and d.capital_fraction == 0.0


def test_kill_on_edge_collapse():
    d = evaluate_stage(Stage.NORMAL_CAPITAL, perf(edge_retention=0.20))
    assert d.action == "KILL"


def test_kill_on_execution_failure():
    d = evaluate_stage(Stage.SMALL_CAPITAL, perf(execution_failure=True))
    assert d.action == "KILL"


def test_kill_beats_everything_else():
    # even with otherwise-promotable metrics, a kill condition wins
    d = evaluate_stage(Stage.MICRO_CAPITAL, perf(kill_switch_triggered=True))
    assert d.action == "KILL"


# -- DEMOTE ------------------------------------------------------------------
def test_demote_on_edge_retention():
    d = evaluate_stage(Stage.SMALL_CAPITAL, perf(edge_retention=0.40))
    assert d.action == "DEMOTE" and d.to_stage == Stage.MICRO_CAPITAL


def test_demote_on_slippage():
    d = evaluate_stage(Stage.NORMAL_CAPITAL, perf(slippage_ratio=2.5))
    assert d.action == "DEMOTE" and d.to_stage == Stage.SMALL_CAPITAL


def test_demote_floor_is_paper_live():
    d = evaluate_stage(Stage.PAPER_LIVE, perf(edge_retention=0.45))
    assert d.action == "DEMOTE" and d.to_stage == Stage.PAPER_LIVE


# -- PROMOTE -----------------------------------------------------------------
def test_promote_when_all_criteria_met():
    d = evaluate_stage(Stage.PAPER_LIVE, perf())
    assert d.action == "PROMOTE" and d.to_stage == Stage.MICRO_CAPITAL
    assert d.capital_fraction == 0.01


def test_promote_blocked_by_insufficient_sample():
    d = evaluate_stage(Stage.PAPER_LIVE, perf(sample_size=10))
    assert d.action == "HOLD"


def test_cannot_promote_past_capped():
    d = evaluate_stage(Stage.CAPPED_PRODUCTION, perf())
    assert d.action == "HOLD" and d.to_stage == Stage.CAPPED_PRODUCTION


# -- HOLD --------------------------------------------------------------------
def test_hold_on_mixed_metrics():
    # retention 0.60 (>=0.5 so no demote, <0.7 so no promote), nothing dangerous
    d = evaluate_stage(Stage.MICRO_CAPITAL, perf(edge_retention=0.60))
    assert d.action == "HOLD" and d.to_stage == Stage.MICRO_CAPITAL


def test_dead_stays_dead():
    d = evaluate_stage(Stage.DEAD, perf())
    assert d.to_stage == Stage.DEAD


def test_render():
    out = evaluate_stage(Stage.PAPER_LIVE, perf()).render()
    assert "PROMOTE" in out and "MICRO_CAPITAL" in out
