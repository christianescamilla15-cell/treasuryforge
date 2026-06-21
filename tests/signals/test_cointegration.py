"""Engle-Granger cointegration + pairs signal/backtest. The rigorous core."""

from __future__ import annotations

import math
import random

import pytest

from treasuryforge.backtest import backtest_pairs
from treasuryforge.signals.cointegration import adf_test, engle_granger, half_life, hedge_ratio
from treasuryforge.signals.linalg import ols
from treasuryforge.signals.pairs import PairsSignal, rolling_zscore


def _random_walk(n, seed, sigma=1.0):
    rng = random.Random(seed)
    x = [0.0]
    for _ in range(n):
        x.append(x[-1] + rng.gauss(0, sigma))
    return x


def _ar1(n, seed, phi=0.7, sigma=1.0):
    rng = random.Random(seed)
    x = [0.0]
    for _ in range(n):
        x.append(phi * x[-1] + rng.gauss(0, sigma))
    return x


# -- OLS sanity --------------------------------------------------------------
def test_ols_recovers_known_line():
    # y = 3 + 2x exactly
    X = [[1.0, float(i)] for i in range(20)]
    y = [3.0 + 2.0 * i for i in range(20)]
    res = ols(X, y)
    assert res.coef[0] == pytest.approx(3.0)
    assert res.coef[1] == pytest.approx(2.0)


# -- ADF ---------------------------------------------------------------------
def test_adf_rejects_unit_root_for_stationary_ar1():
    adf, crit = adf_test(_ar1(600, 1), lags=1)
    assert adf < crit[0.05]                  # stationary -> reject


def test_adf_fails_to_reject_for_random_walk():
    # a true random walk should not reject the unit root (a single realization can
    # land in the ~5% tail; use the 1% level so the unit test is robust to the seed)
    adf, crit = adf_test(_random_walk(600, 42), lags=1)
    assert adf > crit[0.01]                  # non-stationary -> do NOT reject


def test_half_life_matches_theory():
    hl = half_life(_ar1(2000, 3, phi=0.7))
    theory = -math.log(2) / math.log(0.7)    # ~1.94
    assert hl == pytest.approx(theory, rel=0.4)


# -- Engle-Granger -----------------------------------------------------------
def test_cointegrated_pair_detected_and_beta_recovered():
    rng = random.Random(7)
    b = _random_walk(600, 7)
    a = [2.0 * b[i] + rng.gauss(0, 0.5) for i in range(len(b))]   # A = 2B + stationary noise
    r = engle_granger(a, b)
    assert r.cointegrated
    assert r.beta == pytest.approx(2.0, abs=0.1)
    assert r.adf_stat < r.crit_5


def test_independent_walks_not_cointegrated():
    r = engle_granger(_random_walk(600, 8), _random_walk(600, 9))
    assert not r.cointegrated


def test_hedge_ratio_intercept_and_slope():
    b = list(range(100))
    a = [5.0 + 3.0 * x for x in b]
    alpha, beta = hedge_ratio(a, b)
    assert alpha == pytest.approx(5.0) and beta == pytest.approx(3.0)


# -- z-score + signal --------------------------------------------------------
def test_rolling_zscore_warmup_and_value():
    z = rolling_zscore([1, 2, 3, 4, 5], window=3)
    assert z[0] is None and z[1] is None       # warmup
    assert z[2] is not None


def test_pairs_signal_bands_and_hysteresis():
    sig = PairsSignal(entry_z=2.0, exit_z=0.5)
    assert sig.update(1.0) == 0                 # inside band -> flat
    assert sig.update(2.5) == -1                # z high -> short spread
    assert sig.update(1.0) == -1                # still > exit -> hold
    assert sig.update(0.2) == 0                 # within exit -> flat
    assert sig.update(-2.5) == 1                # z low -> long spread


def test_pairs_signal_requires_hysteresis():
    with pytest.raises(ValueError):
        PairsSignal(entry_z=1.0, exit_z=1.0)


# -- backtest economics ------------------------------------------------------
def test_pairs_backtest_profits_on_mean_reverting_spread():
    # construct a clean cointegrated pair; the strategy should net positive at low fees
    rng = random.Random(11)
    b = _random_walk(1500, 11)
    a = [1.5 * b[i] + _ar1_noise for i, _ar1_noise in
         enumerate(_ar1(1500, 12, phi=0.85, sigma=2.0))]
    r = engle_granger(a, b)
    res = backtest_pairs(a, b, alpha=r.alpha, beta=r.beta, window=60,
                         entry_z=2.0, exit_z=0.5, fee_per_leg=0.0002)
    assert res.n_trades > 0
    assert res.total_return > 0                 # captures the reversion net of small fees


def test_pairs_backtest_high_fees_kill_the_edge():
    rng = random.Random(11)
    b = _random_walk(1500, 11)
    a = [1.5 * b[i] + n for i, n in enumerate(_ar1(1500, 12, phi=0.85, sigma=2.0))]
    r = engle_granger(a, b)
    cheap = backtest_pairs(a, b, alpha=r.alpha, beta=r.beta, fee_per_leg=0.0002)
    pricey = backtest_pairs(a, b, alpha=r.alpha, beta=r.beta, fee_per_leg=0.02)
    assert pricey.total_return < cheap.total_return   # cost eats the edge
