"""Monte-Carlo Risk of Ruin + the strategy risk policy (the operational module)."""

from __future__ import annotations

import random

from treasuryforge.risk import (
    StrategyRiskPolicy,
    block_bootstrap,
    geometric_growth,
    kelly_leverage,
    monte_carlo_ruin,
)

# deterministic scalp: 55% wins of +0.30%, 45% losses of -0.30% -> mean +0.03%
SCALP = [0.003 if (i % 20) < 11 else -0.003 for i in range(300)]


# -- block bootstrap ---------------------------------------------------------
def test_block_bootstrap_length_and_membership():
    rng = random.Random(0)
    s = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
    out = block_bootstrap(s, n=25, block_len=3, rng=rng)
    assert len(out) == 25
    assert all(x in s for x in out)


# -- geometric growth + kelly ------------------------------------------------
def test_geometric_growth_positive_low_leverage():
    assert geometric_growth(SCALP, leverage=1.0) > 0


def test_geometric_growth_liquidation_is_minus_inf():
    assert geometric_growth([-0.5, 0.1], leverage=3.0) == float("-inf")  # 1+3*(-0.5) < 0


def test_kelly_leverage_matches_mean_over_var():
    Lk = kelly_leverage(SCALP)
    assert Lk > 20  # E/Var for a ~0.20 per-trade Sharpe scalp is large (~34)


# -- monte carlo ruin --------------------------------------------------------
def test_ruin_rises_with_leverage():
    low = monte_carlo_ruin(SCALP, leverage=1.0, paths=2000, seed=1)
    high = monte_carlo_ruin(SCALP, leverage=30.0, paths=2000, seed=1)
    assert low.p_ruin < 0.05
    assert high.p_ruin > low.p_ruin
    assert high.p_ruin > 0.5            # full-Kelly-ish is near-certain ruin


def test_adverse_regime_raises_ruin():
    base = monte_carlo_ruin(SCALP, leverage=10.0, paths=2000, seed=2)
    stressed = monte_carlo_ruin(SCALP, leverage=10.0, adverse_shift=0.001, paths=2000, seed=2)
    assert stressed.p_ruin > base.p_ruin


def test_fat_tail_shocks_raise_ruin():
    base = monte_carlo_ruin(SCALP, leverage=10.0, paths=2000, seed=3)
    shocked = monte_carlo_ruin(SCALP, leverage=10.0, tail_shock_prob=0.02,
                               tail_shock_mult=5.0, paths=2000, seed=3)
    assert shocked.p_ruin > base.p_ruin


def test_threshold_probs_monotone():
    r = monte_carlo_ruin(SCALP, leverage=15.0, paths=2000, seed=4)
    p20, p30, p50 = r.dd_threshold_probs[0.20], r.dd_threshold_probs[0.30], r.dd_threshold_probs[0.50]
    assert p20 >= p30 >= p50            # deeper drawdowns are rarer


# -- the policy gates (his RiskPolicy made real) -----------------------------
def test_policy_accepts_safe_low_leverage():
    pol = StrategyRiskPolicy(kelly_fraction=0.25, max_leverage=10, max_p_ruin=0.05,
                             max_expected_drawdown=0.30)
    res = pol.assess(SCALP, leverage=3.0, paths=2000, seed=5)
    assert res["accepted"], res["verdict"]


def test_policy_rejects_full_kelly_on_ruin():
    pol = StrategyRiskPolicy(kelly_fraction=0.25, max_leverage=50, max_p_ruin=0.01)
    res = pol.assess(SCALP, leverage=34.0, paths=2000, seed=6)   # full Kelly
    assert not res["accepted"]
    assert "risk_of_ruin" in res["verdict"] or "kelly_cap" in res["verdict"]


def test_policy_rejects_negative_edge():
    losing = [-0.001 if (i % 10) < 6 else 0.001 for i in range(200)]   # mean < 0
    pol = StrategyRiskPolicy()
    res = pol.assess(losing, leverage=1.0, paths=1500, seed=7)
    assert not res["accepted"] and "edge" in res["verdict"]


def test_policy_blocks_good_edge_at_too_high_leverage():
    # even a real edge is blocked if the proposed leverage courts ruin -> the
    # whole point: a good DSR does NOT buy you the right to over-lever
    pol = StrategyRiskPolicy(kelly_fraction=0.5, max_leverage=40, max_p_ruin=0.02)
    res = pol.assess(SCALP, leverage=25.0, paths=2000, seed=8)
    assert not res["accepted"]
