"""Mutation-hardening for the Monte-Carlo ruin engine and StrategyRiskPolicy.

The Monte Carlo is made DETERMINISTIC here by feeding constant-return paths
(every bootstrapped path is identical) so the path arithmetic — capital compounding,
drawdown, liquidation, threshold counting — is exactly hand-computable. The policy
gates are pinned at their exact boundaries and with their exact verdict/detail
strings. Ground-truth constants were captured from the real (unmutated) functions.
"""

from __future__ import annotations

import random

import pytest

from treasuryforge.risk import (
    StrategyRiskPolicy,
    block_bootstrap,
    geometric_growth,
    kelly_leverage,
    monte_carlo_ruin,
)
from treasuryforge.risk.ruin import _moments

SCALP = [0.003 if (i % 20) < 11 else -0.003 for i in range(300)]


def _gate_map(res):
    return {n: ok for n, ok, _ in res["gates"]}


# === block_bootstrap (exact, seeded) ========================================
def test_block_bootstrap_exact_blocks():
    out = block_bootstrap([1.0, 2, 3, 4, 5, 6, 7, 8, 9, 10], n=12, block_len=3, rng=random.Random(0))
    assert out == [7, 8, 9, 7, 8, 9, 1.0, 2, 3, 5, 6, 7]   # contiguous length-3 blocks


def test_block_bootstrap_reduces_when_block_ge_len():
    # block_len == len -> reduced to max(1, len//2) == 2 (kills >, /2, None, 2e mutants)
    out = block_bootstrap([1.0, 2, 3, 4, 5], n=6, block_len=5, rng=random.Random(0))
    assert out == [4, 5, 4, 5, 1.0, 2]


def test_block_bootstrap_reduces_len3():
    # len 3, block_len>=len -> max(1, 3//2) == 1 (kills the max(2,..) and //3 mutants)
    out = block_bootstrap([1.0, 2, 3], n=4, block_len=3, rng=random.Random(0))
    assert out == [2, 2, 1.0, 2]


# === monte_carlo_ruin: deterministic constant-return paths ==================
def test_decay_path_exact_stats_default_leverage():
    # constant -10% steps, DEFAULT leverage (1.0): every path identical, hand-computable
    r = monte_carlo_ruin([-0.1] * 50, paths=8, block_len=1, seed=0)
    assert r.median_final_multiple == pytest.approx(0.9**50)
    assert r.expected_max_drawdown == pytest.approx(1 - 0.9**50)
    assert r.p_ruin == 1.0                 # mdd ~0.995 >= 0.50
    assert r.p_liquidation == 0.0          # 0.9 > 0, capital never wiped
    assert r.dd_threshold_probs == {0.20: 1.0, 0.30: 1.0, 0.50: 1.0}


def test_growth_path_has_no_drawdown():
    r = monte_carlo_ruin([0.1] * 30, leverage=1.0, paths=6, block_len=1, seed=0)
    assert r.expected_max_drawdown == 0.0
    assert r.p_ruin == 0.0
    assert r.dd_threshold_probs == {0.20: 0.0, 0.30: 0.0, 0.50: 0.0}
    assert r.median_final_multiple == pytest.approx(1.1**30)


def test_liquidation_negative_capital():
    r = monte_carlo_ruin([-1.0] * 3, leverage=2.0, paths=5, block_len=1, seed=0)
    assert r.p_liquidation == 1.0          # 1 + 2*(-1) = -1  -> wiped
    assert r.median_final_multiple == 0.0  # capital floored to 0
    assert r.expected_max_drawdown == 1.0
    assert r.p_ruin == 1.0


def test_liquidation_at_exactly_zero_capital():
    # 1 + 1*(-1) == 0 exactly; the rule is cap <= 0, so it MUST liquidate (kills '<')
    r = monte_carlo_ruin([-1.0] * 3, leverage=1.0, paths=5, block_len=1, seed=0)
    assert r.p_liquidation == 1.0


def test_exact_half_drawdown_counts_on_the_boundary():
    # one -50% step at leverage 1 -> drawdown is EXACTLY 0.50; the >= thresholds include it
    r = monte_carlo_ruin([-0.5], leverage=1.0, n_steps=1, paths=4, block_len=1,
                         ruin_drawdown=0.5, dd_thresholds=(0.5,), seed=0)
    assert r.p_ruin == 1.0                  # mdd 0.5 >= 0.5  (a '>' mutant -> 0.0)
    assert r.dd_threshold_probs[0.5] == 1.0
    assert r.expected_max_drawdown == pytest.approx(0.5)


def test_tail_shock_default_mult_is_three():
    # prob 1.0 -> every step shocked: r_eff = -|0.1| * mult; default mult 3 -> cap *= 0.7
    r = monte_carlo_ruin([0.1] * 10, leverage=1.0, tail_shock_prob=1.0,
                         paths=4, block_len=1, seed=0)
    assert r.median_final_multiple == pytest.approx(0.7**10)


def test_tail_shock_gate_is_and_not_or():
    # a vanishing prob means ~no shocks; an 'or' mutant would shock EVERY step
    r = monte_carlo_ruin([0.05] * 20, leverage=1.0, tail_shock_prob=1e-9,
                         tail_shock_mult=5.0, paths=50, block_len=1, seed=0)
    assert r.expected_max_drawdown == 0.0
    assert r.p_ruin == 0.0


def test_leverage_default_is_one():
    a = monte_carlo_ruin([-0.1] * 20, paths=4, block_len=1, seed=0)            # default leverage
    b = monte_carlo_ruin([-0.1] * 20, leverage=1.0, paths=4, block_len=1, seed=0)
    assert a.median_final_multiple == b.median_final_multiple == pytest.approx(0.9**20)


def test_seed_default_is_zero():
    # the default seed must be 0 (reproducibility contract); compare the CONTINUOUS
    # median multiple, which differs between seeds even when discrete p_ruin collides
    a = monte_carlo_ruin(SCALP, leverage=25.0, paths=500, block_len=10)        # default seed
    b = monte_carlo_ruin(SCALP, leverage=25.0, paths=500, block_len=10, seed=0)
    assert a.median_final_multiple == b.median_final_multiple


def test_block_len_default_is_ten():
    a = monte_carlo_ruin(SCALP, leverage=25.0, paths=400, seed=0)              # default block_len
    b = monte_carlo_ruin(SCALP, leverage=25.0, paths=400, block_len=10, seed=0)
    assert a.p_ruin == b.p_ruin


def test_median_uses_the_middle_not_a_third():
    r = monte_carlo_ruin(SCALP, leverage=25.0, paths=9, block_len=10, seed=4)
    assert r.median_final_multiple == pytest.approx(21.353278674358236)        # finals[9//2]


# === moments / geometric growth / kelly (exact) =============================
def test_moments_exact():
    mean, var = _moments([0.02, -0.01, 0.03, -0.02, 0.01])
    assert mean == pytest.approx(0.006)
    assert var == pytest.approx(0.000344)


def test_kelly_leverage_exact():
    assert kelly_leverage([0.02, -0.01, 0.03, -0.02, 0.01]) == pytest.approx(17.441860465116278)


def test_kelly_zero_variance_is_zero():
    # var == 0 must return 0.0 (not divide-by-zero, not 1.0)
    assert kelly_leverage([0.5, 0.5, 0.5]) == 0.0


def test_geometric_growth_exact():
    assert geometric_growth([0.1, -0.05, 0.2], 1.0) == pytest.approx(0.07544614740357632)


def test_geometric_growth_liquidation_is_minus_inf():
    # 1 + 2*(-0.5) == 0 -> log domain edge; must short-circuit to -inf (kills 'x < 0')
    assert geometric_growth([-0.5, 0.1], 2.0) == float("-inf")


# === StrategyRiskPolicy.assess: names, details, verdict, keys ===============
def _pol(**kw):
    base = dict(cost_per_cycle=0.001, min_edge_margin=0.002, min_dsr=0.6,
                kelly_fraction=0.25, max_leverage=10.0, max_p_ruin=1.0, max_expected_drawdown=1.0)
    base.update(kw)
    return StrategyRiskPolicy(**base)


def test_assess_gate_names_and_details_are_exact():
    res = _pol().assess(SCALP, leverage=3.0, dsr=0.7, paths=300, seed=5)
    assert res["gates"] == [
        ("edge_is_real", True, "DSR=0.700 vs min 0.60"),
        ("edge", False, "E[r]=0.00030 vs cost+margin=0.00300"),
        ("geometric_growth", True, "E[ln(1+fr)]=0.000860"),
        ("kelly_cap", True, "L=3.00 vs 25%*Kelly(33.7)=8.42, hardcap=10.0"),
        ("risk_of_ruin", True, "P(DD>=50%)=0.33% vs 100%"),
        ("expected_drawdown", True, "E[maxDD]=21.47% vs 100%"),
    ]
    assert res["verdict"] == "reject: edge"
    assert sorted(res) == ["accepted", "gates", "kelly_leverage", "monte_carlo", "verdict"]
    assert res["kelly_leverage"] == pytest.approx(33.67003367003367)


def test_verdict_accept_is_exact():
    pol = StrategyRiskPolicy(min_dsr=0.0, cost_per_cycle=0.0, min_edge_margin=0.0,
                             kelly_fraction=0.25, max_leverage=10.0,
                             max_p_ruin=1.0, max_expected_drawdown=1.0)
    res = pol.assess(SCALP, leverage=3.0, dsr=1.0, paths=200, seed=5)
    assert res["accepted"] and res["verdict"] == "accept"


def test_verdict_joins_failed_gates_with_commas():
    pol = StrategyRiskPolicy(min_dsr=0.0, cost_per_cycle=1.0, min_edge_margin=0.0,
                             kelly_fraction=10.0, max_leverage=100.0,
                             max_p_ruin=1.0, max_expected_drawdown=1.0)
    res = pol.assess([0.0] * 10, leverage=1.0, dsr=1.0, paths=100, seed=0)
    assert res["verdict"] == "reject: edge,geometric_growth,kelly_cap"


# === assess gate boundaries (kills the operator mutants) ====================
def test_edge_is_real_passes_at_the_dsr_floor():
    res = _pol(min_dsr=0.6).assess(SCALP, leverage=3.0, dsr=0.6, paths=200, seed=5)
    assert _gate_map(res)["edge_is_real"] is True       # dsr == floor -> '>=' passes


def test_edge_gate_is_strict():
    res = _pol(cost_per_cycle=0.002, min_edge_margin=0.0, min_dsr=0.0).assess(
        [0.002] * 10, leverage=1.0, dsr=1.0, paths=100, seed=0)
    assert _gate_map(res)["edge"] is False              # E[r] == threshold -> not strictly >


def test_edge_threshold_adds_the_margin():
    res = _pol(cost_per_cycle=0.001, min_edge_margin=0.002, min_dsr=0.0).assess(
        [0.0025] * 10, leverage=1.0, dsr=1.0, paths=100, seed=0)
    assert _gate_map(res)["edge"] is False              # 0.0025 < 0.003 (cost+margin, not cost-margin)


def test_geometric_growth_gate_is_strict():
    res = _pol(min_dsr=0.0, cost_per_cycle=-1.0).assess(
        [0.0] * 10, leverage=1.0, dsr=1.0, paths=100, seed=0)
    assert _gate_map(res)["geometric_growth"] is False  # g == 0 -> not strictly > 0


def _kelly_ok(pol, lev):
    return _gate_map(pol.assess(SCALP, leverage=lev, dsr=1.0, paths=200, seed=5))["kelly_cap"]


def test_kelly_cap_epsilon_boundary():
    pol = _pol(kelly_fraction=1.0, max_leverage=10.0)   # Kelly ~33.7 -> cap == 10.0 exactly
    assert _kelly_ok(pol, 10.0 + 1e-9)                  # within 1e-9 tolerance -> passes
    assert not _kelly_ok(pol, 10.0 + 1.5e-9)            # past tolerance -> fails


def test_risk_of_ruin_gate_is_strict():
    pol = StrategyRiskPolicy(min_dsr=0.0, cost_per_cycle=-1.0, kelly_fraction=10.0,
                             max_leverage=100.0, max_p_ruin=1.0, ruin_drawdown=0.5,
                             max_expected_drawdown=1.0)
    res = pol.assess([-0.1] * 50, leverage=1.0, dsr=1.0, paths=8, block_len=1, seed=0)
    assert _gate_map(res)["risk_of_ruin"] is False      # p_ruin 1.0 not < 1.0


def test_expected_drawdown_gate_is_strict():
    emdd = 1 - 0.9**50
    pol = StrategyRiskPolicy(min_dsr=0.0, cost_per_cycle=-1.0, kelly_fraction=10.0,
                             max_leverage=100.0, max_p_ruin=1.0, ruin_drawdown=0.5,
                             max_expected_drawdown=emdd)
    res = pol.assess([-0.1] * 50, leverage=1.0, dsr=1.0, paths=8, block_len=1, seed=0)
    assert _gate_map(res)["expected_drawdown"] is False  # E[maxDD] == max -> not strictly <


# === StrategyRiskPolicy defaults (exercise each default value) ==============
def test_default_min_dsr_is_point_six():
    res = StrategyRiskPolicy().assess(SCALP, leverage=1.0, dsr=1.0, paths=200, seed=5)
    assert _gate_map(res)["edge_is_real"] is True       # 1.0 >= 0.6 (mutant 1.6/None fails)


def test_default_kelly_fraction_is_a_quarter():
    res = StrategyRiskPolicy(max_p_ruin=1.0, max_expected_drawdown=1.0).assess(
        SCALP, leverage=9.0, dsr=1.0, paths=200, seed=5)
    assert _gate_map(res)["kelly_cap"] is False         # 9 > 0.25*Kelly (=8.42); mutant 1.25 -> pass


def test_default_max_leverage_is_ten():
    res = StrategyRiskPolicy(kelly_fraction=1.0, max_p_ruin=1.0, max_expected_drawdown=1.0).assess(
        SCALP, leverage=10.5, dsr=1.0, paths=200, seed=5)
    assert _gate_map(res)["kelly_cap"] is False         # cap=min(Kelly,10)=10; mutant 11 -> pass


def test_default_max_p_ruin_is_one_percent():
    res = StrategyRiskPolicy(kelly_fraction=10.0, max_leverage=100.0,
                             max_expected_drawdown=1.0).assess(
        [-0.1] * 50, leverage=1.0, dsr=1.0, paths=8, block_len=1, seed=0)
    assert _gate_map(res)["risk_of_ruin"] is False      # p_ruin 1.0 vs 0.01; mutant 1.01 -> pass


def test_default_ruin_drawdown_is_half():
    res = StrategyRiskPolicy(kelly_fraction=10.0, max_leverage=100.0,
                             max_p_ruin=0.5, max_expected_drawdown=1.0).assess(
        [-0.1] * 50, leverage=1.0, dsr=1.0, paths=8, block_len=1, seed=0)
    assert _gate_map(res)["risk_of_ruin"] is False      # ruin_dd 0.5 -> p_ruin 1; mutant 1.5 -> 0 -> pass


def test_default_max_expected_drawdown_is_twenty_percent():
    res = StrategyRiskPolicy(kelly_fraction=10.0, max_leverage=100.0,
                             max_p_ruin=1.0).assess(
        [-0.1] * 50, leverage=1.0, dsr=1.0, paths=8, block_len=1, seed=0)
    assert _gate_map(res)["expected_drawdown"] is False  # E[maxDD] 0.99 vs 0.2; mutant 1.2 -> pass
