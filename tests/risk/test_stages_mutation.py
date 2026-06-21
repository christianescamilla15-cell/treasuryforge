"""Mutation-hardening for the stage ladder: exact thresholds, capital table,
reason strings, ladder arithmetic and render format. The existing tests assert
action+to_stage but leave every boundary operator, dict value and message string
mutable — pinned here."""

from __future__ import annotations

from treasuryforge.risk import LivePerformance, Stage, evaluate_stage
from treasuryforge.risk.stages import STAGE_CAPITAL


def perf(**over) -> LivePerformance:
    base = dict(edge_retention=0.80, slippage_ratio=1.2, live_dd=0.10,
                expected_dd_p75=0.15, expected_dd_p90=0.20, stress_dd_p95=0.30,
                sample_size=50, min_sample=30)
    base.update(over)
    return LivePerformance(**base)


def test_stage_capital_table_exact():
    assert STAGE_CAPITAL == {
        Stage.DEAD: 0.0, Stage.PAPER_LIVE: 0.0, Stage.MICRO_CAPITAL: 0.01,
        Stage.SMALL_CAPITAL: 0.03, Stage.NORMAL_CAPITAL: 0.08, Stage.CAPPED_PRODUCTION: 0.20,
    }


# -- KILL boundaries + reasons ----------------------------------------------
def test_kill_live_dd_boundary_is_strict():
    assert evaluate_stage(Stage.MICRO_CAPITAL, perf(live_dd=0.30, stress_dd_p95=0.30)).action != "KILL"
    assert evaluate_stage(Stage.MICRO_CAPITAL, perf(live_dd=0.31, stress_dd_p95=0.30)).action == "KILL"


def test_kill_edge_retention_boundary():
    assert evaluate_stage(Stage.SMALL_CAPITAL, perf(edge_retention=0.25)).action == "DEMOTE"  # ==0.25 not kill
    assert evaluate_stage(Stage.SMALL_CAPITAL, perf(edge_retention=0.24)).action == "KILL"


def test_kill_reason_exact_single():
    d = evaluate_stage(Stage.MICRO_CAPITAL, perf(live_dd=0.35))
    assert d.action == "KILL" and d.to_stage == Stage.DEAD and d.capital_fraction == 0.0
    assert d.reason == "live DD 35% > stress p95 30%"


def test_kill_reason_joins_all_conditions_in_order():
    d = evaluate_stage(Stage.MICRO_CAPITAL, perf(live_dd=0.35, edge_retention=0.20,
                       adverse_selection=True, execution_failure=True, kill_switch_triggered=True))
    assert d.reason == ("live DD 35% > stress p95 30%; edge retention 20% < 25%; "
                        "persistent adverse selection; execution failure; kill-switch triggered")


def test_kill_each_flag_independently():
    for flag in ("adverse_selection", "execution_failure", "kill_switch_triggered"):
        assert evaluate_stage(Stage.MICRO_CAPITAL, perf(**{flag: True})).action == "KILL"


# -- DEMOTE boundaries + reasons --------------------------------------------
def test_demote_edge_retention_boundary():
    assert evaluate_stage(Stage.SMALL_CAPITAL, perf(edge_retention=0.50)).action == "HOLD"    # ==0.50 not demote
    assert evaluate_stage(Stage.SMALL_CAPITAL, perf(edge_retention=0.49)).action == "DEMOTE"


def test_demote_slippage_boundary():
    assert evaluate_stage(Stage.SMALL_CAPITAL, perf(slippage_ratio=2.0)).action == "HOLD"      # ==2.0 not demote
    assert evaluate_stage(Stage.SMALL_CAPITAL, perf(slippage_ratio=2.01)).action == "DEMOTE"


def test_demote_live_dd_p90_boundary():
    assert evaluate_stage(Stage.SMALL_CAPITAL,
                          perf(live_dd=0.20, expected_dd_p90=0.20)).action == "HOLD"           # ==p90 not demote
    assert evaluate_stage(Stage.SMALL_CAPITAL,
                          perf(live_dd=0.21, expected_dd_p90=0.20)).action == "DEMOTE"


def test_demote_reason_target_and_capital_exact():
    d = evaluate_stage(Stage.SMALL_CAPITAL, perf(edge_retention=0.40, slippage_ratio=2.5, live_dd=0.25))
    assert d.to_stage == Stage.MICRO_CAPITAL and d.capital_fraction == 0.01
    assert d.reason == "edge retention 40% < 50%; slippage 2.5x > 2x; live DD 25% > expected p90 20%"


def test_demote_floor_is_paper_live():
    d = evaluate_stage(Stage.PAPER_LIVE, perf(edge_retention=0.45))
    assert d.action == "DEMOTE" and d.to_stage == Stage.PAPER_LIVE and d.capital_fraction == 0.0


# -- PROMOTE boundaries (all inclusive) -------------------------------------
def test_promote_edge_retention_boundary_inclusive():
    assert evaluate_stage(Stage.PAPER_LIVE, perf(edge_retention=0.70)).action == "PROMOTE"
    assert evaluate_stage(Stage.PAPER_LIVE, perf(edge_retention=0.69)).action == "HOLD"


def test_promote_slippage_boundary_inclusive():
    assert evaluate_stage(Stage.PAPER_LIVE, perf(slippage_ratio=1.5)).action == "PROMOTE"
    assert evaluate_stage(Stage.PAPER_LIVE, perf(slippage_ratio=1.51)).action == "HOLD"


def test_promote_dd_boundary_inclusive():
    assert evaluate_stage(Stage.PAPER_LIVE, perf(live_dd=0.15, expected_dd_p75=0.15)).action == "PROMOTE"
    assert evaluate_stage(Stage.PAPER_LIVE, perf(live_dd=0.16, expected_dd_p75=0.15)).action == "HOLD"


def test_promote_sample_boundary_inclusive():
    assert evaluate_stage(Stage.PAPER_LIVE, perf(sample_size=30, min_sample=30)).action == "PROMOTE"
    assert evaluate_stage(Stage.PAPER_LIVE, perf(sample_size=29, min_sample=30)).action == "HOLD"


def test_promote_steps_one_rung_with_capital_and_reason():
    d = evaluate_stage(Stage.MICRO_CAPITAL, perf())
    assert d.to_stage == Stage.SMALL_CAPITAL and d.capital_fraction == 0.03
    assert d.reason == "edge retained, slippage in-model, DD<=p75, sample sufficient"


def test_promote_cap_holds_at_capped():
    d = evaluate_stage(Stage.CAPPED_PRODUCTION, perf())
    assert d.action == "HOLD" and d.to_stage == Stage.CAPPED_PRODUCTION and d.capital_fraction == 0.20
    assert d.reason == "all criteria met but already at production cap"


def test_hold_reason_and_dead_state():
    assert evaluate_stage(Stage.MICRO_CAPITAL,
                          perf(edge_retention=0.60)).reason.startswith("mixed but not dangerous")
    dead = evaluate_stage(Stage.DEAD, perf())
    assert dead.action == "DEAD" and dead.reason == "already retired" and dead.capital_fraction == 0.0


def test_render_exact_format():
    out = evaluate_stage(Stage.PAPER_LIVE, perf()).render()
    assert out == ("PAPER_LIVE --PROMOTE--> MICRO_CAPITAL  (capital 1.0%)\n"
                   "   reason: edge retained, slippage in-model, DD<=p75, sample sufficient")
