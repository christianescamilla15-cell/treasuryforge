"""Vol-targeting sizing invariants + the cost-aware / overfitting-aware gate."""

from __future__ import annotations

from itertools import pairwise

import pytest

from treasuryforge.backtest import (
    CostModel,
    deflated_sharpe_ratio,
    max_drawdown,
    purged_kfold,
    sharpe_ratio,
)
from treasuryforge.sizing import EwmaVol, vol_target_size


# -- vol targeting -----------------------------------------------------------
@pytest.mark.parametrize("vol", [1e-9, 0.001, 0.01, 0.1, 1.0, 10.0])
def test_size_never_breaches_cap(vol):
    # the load-bearing safety property: result is always <= max_size
    s = vol_target_size(base_size=5.0, current_vol=vol, target_vol=0.02, max_size=2.0)
    assert 0.0 <= s <= 2.0


def test_size_shrinks_as_vol_rises():
    sizes = [vol_target_size(1.0, v, 0.02, max_size=1e9) for v in (0.005, 0.01, 0.05, 0.2)]
    assert all(a >= b for a, b in pairwise(sizes))           # monotone non-increasing


def test_ewma_vol_tracks_a_volatile_stream():
    quiet = EwmaVol()
    for _ in range(50):
        quiet.update(0.0001)
    loud = EwmaVol()
    for r in [0.05, -0.05] * 25:
        loud.update(r)
    assert loud.vol > quiet.vol


def test_ewma_vol_exact_recursion_with_defaults():
    # pin the EXACT RiskMetrics recursion (lam=0.94) so any coefficient/operator
    # mutation in the variance update is caught, not just "loud > quiet".
    v = EwmaVol()                                  # defaults: lam=0.94, floor=1e-8
    assert v.vol == pytest.approx(1e-8)            # floor before any data
    v.update(0.2)
    assert v.vol == pytest.approx(0.2)             # first update: var = ret^2 -> vol=|ret|
    v.update(0.1)
    expected_var = 0.94 * 0.04 + (1.0 - 0.94) * 0.01   # exact EWMA step
    assert v.vol == pytest.approx(expected_var ** 0.5)


def test_vol_target_uses_exact_default_floor():
    # current_vol below the floor -> the default floor (exactly 1e-8) is used
    assert vol_target_size(1.0, 0.0, target_vol=1e-8, max_size=1e12) == pytest.approx(1.0)


def test_vol_target_small_size_passes_through_not_raised():
    # a scaled size in (0, 1) must NOT be clamped up — the lower bound is 0.0
    assert vol_target_size(1.0, 10.0, target_vol=2.0, max_size=1e9) == pytest.approx(0.2)


def test_vol_target_zero_base_is_exactly_zero():
    assert vol_target_size(0.0, 0.01, 0.02, max_size=5.0) == 0.0


def test_ewma_vol_respects_custom_lambda():
    # constructing with a non-default lambda forces the generated __init__ to exist
    # (kills the @dataclass-removal mutant) AND pins that lam is actually used.
    v = EwmaVol(lam=0.5, floor=1e-12)
    v.update(0.2)
    v.update(0.1)
    assert v.vol == pytest.approx((0.5 * 0.04 + 0.5 * 0.01) ** 0.5)


# -- cost model --------------------------------------------------------------
def test_cost_is_monotone_in_size():
    cm = CostModel()
    assert cm.cost(1000) < cm.cost(5000)


def test_impact_adds_conservatism_only():
    cm = CostModel()
    base = cm.cost(10_000, sigma=0.0, adv=None)          # no impact term
    with_impact = cm.cost(10_000, sigma=0.02, adv=1_000_000)
    assert with_impact > base                            # impact can only add cost


# -- metrics -----------------------------------------------------------------
def test_sharpe_sign_and_zero():
    assert sharpe_ratio([0.02, 0.01, 0.015, 0.005, 0.012]) > 0      # positive mean, has variance
    assert sharpe_ratio([0.01, -0.01, 0.01, -0.01]) == pytest.approx(0.0, abs=1e-9)
    assert sharpe_ratio([0.01] * 10) == 0.0                         # zero variance -> undefined -> 0


def test_max_drawdown():
    assert max_drawdown([100, 120, 60, 80]) == pytest.approx(0.5)      # 120 -> 60
    assert max_drawdown([100, 101, 102]) == pytest.approx(0.0)


def test_dsr_decreases_with_more_trials():
    # a decent-looking return series; deflate against few vs many trials
    rng = [0.01, 0.012, -0.005, 0.008, 0.011, -0.002, 0.009, 0.013, 0.004, 0.007] * 5
    few = deflated_sharpe_ratio(rng, n_trials=2)
    many = deflated_sharpe_ratio(rng, n_trials=500)
    assert 0.0 <= many <= few <= 1.0                     # more trials -> harder to pass


def test_dsr_is_a_probability():
    rng = [0.02, -0.01, 0.015, 0.005, -0.008, 0.012] * 6
    p = deflated_sharpe_ratio(rng, n_trials=20)
    assert 0.0 <= p <= 1.0


def test_dsr_uses_cross_trial_variance():
    # same returns, same trial COUNT (6) — only the cross-trial Sharpe variance
    # differs. High variance among configs = more selection bias = lower DSR.
    rng = [0.012, 0.013, -0.003, 0.010, 0.011, -0.001, 0.009, 0.014] * 6
    low_var = deflated_sharpe_ratio(rng, trial_sharpes=[0.20, 0.21, 0.19, 0.20, 0.22, 0.20])
    high_var = deflated_sharpe_ratio(rng, trial_sharpes=[0.0, 0.5, -0.3, 0.6, 0.2, -0.4])
    assert 0.0 <= high_var <= 1.0 and 0.0 <= low_var <= 1.0
    assert low_var > high_var      # the corrected DSR reacts to trial dispersion


# -- purged CV ---------------------------------------------------------------
def test_purged_kfold_partitions_test_folds():
    n = 20
    seen = []
    for train, test in purged_kfold(n, k=5, embargo=0):
        seen.extend(test)
        assert not (set(train) & set(test))              # no leakage
    assert sorted(seen) == list(range(n))                # every sample tested once


def test_embargo_removes_samples_after_test_fold():
    no_emb = list(purged_kfold(20, k=5, embargo=0))
    emb = list(purged_kfold(20, k=5, embargo=2))
    # with an embargo, non-final folds drop extra training samples after the test block
    assert len(emb[0][0]) < len(no_emb[0][0])
