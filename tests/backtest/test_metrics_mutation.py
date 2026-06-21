"""Exact-value mutation-hardening for metrics.py.

The existing metrics tests are all sign/range/monotonicity checks, which leave
every numeric coefficient (Acklam's rational approximation), operator and formula
mutable without detection. Here each function is pinned to EXACT values captured
from the real implementation, with tolerances tight enough that perturbing any
single coefficient or flipping any operator changes the result and fails.
"""

from __future__ import annotations

import pytest

from treasuryforge.backtest.metrics import (
    _moments,
    _phi,
    _phi_inv,
    deflated_sharpe_ratio,
    expected_max_sharpe,
    max_drawdown,
    profit_factor,
    sharpe_ratio,
    sortino_ratio,
)

R = [0.02, -0.01, 0.03, -0.02, 0.015, 0.005, -0.008, 0.012, 0.001, -0.004]


def test_phi_matches_standard_normal_cdf():
    # exact Φ values -> pins erf usage and the sqrt(2) scale constant
    assert _phi(0.0) == pytest.approx(0.5)
    assert _phi(-2.0) == pytest.approx(0.022750131948, rel=1e-9)
    assert _phi(-1.0) == pytest.approx(0.158655253931, rel=1e-9)
    assert _phi(1.0) == pytest.approx(0.841344746069, rel=1e-9)
    assert _phi(1.96) == pytest.approx(0.975002104852, rel=1e-9)
    assert _phi(2.5) == pytest.approx(0.993790334674, rel=1e-9)


def test_phi_inv_all_three_branches_exact():
    # covers plow (<0.02425), middle, and phigh (>0.97575) branches
    vals = {0.001: -3.090232304709, 0.01: -2.326347874388, 0.02: -2.053748909003,
            0.1: -1.28155156414, 0.3: -0.524400513279, 0.5: 0.0, 0.7: 0.524400513279,
            0.9: 1.28155156414, 0.975: 1.95996398612, 0.99: 2.326347874388,
            0.999: 3.090232304709}
    for p, expect in vals.items():
        assert _phi_inv(p) == pytest.approx(expect, abs=1e-9), p


def test_phi_inv_rejects_out_of_range_with_exact_message():
    # assert the EXACT custom message — otherwise out-of-range p still raises a
    # (different) log-domain ValueError, leaving the bound mutants alive
    for bad in (0.0, 1.0, -0.1, 1.5):
        with pytest.raises(ValueError, match=r"p must be in \(0, 1\)"):
            _phi_inv(bad)


def test_phi_inv_branch_cutoffs_are_exact():
    # p exactly at plow/phigh picks the MIDDLE branch (strict <, >)
    assert _phi_inv(0.02425) == pytest.approx(-1.972961049085, abs=1e-9)
    assert _phi_inv(0.97575) == pytest.approx(1.972961049085, abs=1e-9)


def test_moments_exact():
    mean, std, skew, kurt = _moments(R)
    assert mean == pytest.approx(0.0041, rel=1e-9)
    assert std == pytest.approx(0.014515164484, rel=1e-9)
    assert skew == pytest.approx(0.132395526557, rel=1e-9)
    assert kurt == pytest.approx(2.105436368304, rel=1e-9)


def test_moments_zero_variance_branch():
    assert _moments([0.5, 0.5, 0.5]) == (0.5, 0.0, 0.0, 3.0)


def test_sharpe_exact_and_branches():
    assert sharpe_ratio(R) == pytest.approx(0.282463213179, rel=1e-9)
    assert sharpe_ratio(R, 252) == pytest.approx(4.48396449958, rel=1e-9)
    assert sharpe_ratio([0.01]) == 0.0                 # < 2 observations
    assert sharpe_ratio([0.01, 0.03]) == pytest.approx(2.0)   # exactly 2 obs -> NOT short-circuited
    assert sharpe_ratio([0.01, 0.01, 0.01]) == 0.0     # zero variance


def test_sortino_exact_and_branches():
    assert sortino_ratio(R) == pytest.approx(0.538356374725, rel=1e-9)
    assert sortino_ratio(R, 252) == pytest.approx(8.54614250549, rel=1e-9)
    assert sortino_ratio(R, target=0.005) == pytest.approx(-0.085194275137, rel=1e-9)  # target shifts num+downside
    assert sortino_ratio([0.02, -0.01]) == pytest.approx(0.7071067811865475, rel=1e-9)  # exactly 2 obs
    assert sortino_ratio([0.01]) == 0.0                # < 2 observations
    assert sortino_ratio([0.01, 0.02, 0.03]) == 0.0    # no downside -> dd 0


def test_profit_factor_exact_and_branches():
    assert profit_factor(R) == pytest.approx(1.97619047619, rel=1e-9)
    assert profit_factor([0.01, 0.02]) == float("inf")  # no losses
    assert profit_factor([-0.01, -0.02]) == 0.0         # no gains


def test_max_drawdown_exact():
    assert max_drawdown([100, 120, 90, 130, 80, 140]) == pytest.approx(0.384615384615, rel=1e-9)
    assert max_drawdown([100, 101, 102]) == 0.0
    assert max_drawdown([]) == 0.0
    # peak in (0, 1]: the guard is `peak > 0`, not `peak > 1`
    assert max_drawdown([0.5, 0.25]) == pytest.approx(0.5)
    # peak can be exactly 0: `peak > 0` must skip (a `peak >= 0` mutant divides by zero)
    assert max_drawdown([0.0, -1.0]) == 0.0


def test_expected_max_sharpe_exact_and_scaling():
    assert expected_max_sharpe(1) == 0.0
    assert expected_max_sharpe(2) == pytest.approx(0.519755344082, rel=1e-9)
    assert expected_max_sharpe(10) == pytest.approx(1.574598301855, rel=1e-9)
    assert expected_max_sharpe(100) == pytest.approx(2.53060289492, rel=1e-9)
    assert expected_max_sharpe(1000) == pytest.approx(3.255121510918, rel=1e-9)
    assert expected_max_sharpe(50, sr_std=2.0) == pytest.approx(4.552606187778, rel=1e-9)


def test_deflated_sharpe_exact_both_paths():
    # scalar-n_trials fallback path
    assert deflated_sharpe_ratio(R, n_trials=10) == pytest.approx(4.6821607e-05, rel=1e-6)
    # cross-trial-variance path (the corrected benchmark)
    assert deflated_sharpe_ratio(
        R, trial_sharpes=[0.2, 0.21, 0.19, 0.2, 0.22, 0.2]) == pytest.approx(0.791997586772, rel=1e-9)
    assert deflated_sharpe_ratio([0.01, 0.03], n_trials=5) == pytest.approx(0.790283693912, rel=1e-9)  # 2 obs
    assert deflated_sharpe_ratio([0.01]) == 0.0            # n < 2
    assert deflated_sharpe_ratio([0.01, 0.01, 0.01]) == 0.0  # zero variance
