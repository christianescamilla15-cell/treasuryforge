"""Regime gate: the variance-ratio classifier and the spread tradeability gate.
The gate is the research's non-negotiable — these pin that it actually distinguishes
a live mean-reverting spread from a broken/trending one."""

from __future__ import annotations

import random

import pytest

from treasuryforge.signals.regime import assess_spread_regime, variance_ratio


def _ar1_level(n, seed, phi, sigma=1.0):
    rng = random.Random(seed)
    x = [0.0]
    for _ in range(n):
        x.append(phi * x[-1] + rng.gauss(0, sigma))
    return x


def _random_walk(n, seed, sigma=1.0):
    rng = random.Random(seed)
    x = [0.0]
    for _ in range(n):
        x.append(x[-1] + rng.gauss(0, sigma))
    return x


def _momentum(n, seed, theta=0.6, sigma=1.0):
    # positively autocorrelated increments -> a trending series (VR > 1)
    rng = random.Random(seed)
    d, x = 0.0, [0.0]
    for _ in range(n):
        d = theta * d + rng.gauss(0, sigma)
        x.append(x[-1] + d)
    return x


def test_vr_mean_reverting_below_one():
    assert variance_ratio(_ar1_level(1500, 1, phi=0.9), 8) < 0.9


def test_vr_random_walk_near_one():
    assert variance_ratio(_random_walk(3000, 2), 8) == pytest.approx(1.0, abs=0.25)


def test_vr_trending_above_one():
    assert variance_ratio(_momentum(1500, 3), 8) > 1.2


def test_vr_constant_series_is_one():
    assert variance_ratio([5.0] * 50, 4) == 1.0


def test_vr_validates_args():
    with pytest.raises(ValueError):
        variance_ratio([1.0, 2.0, 3.0], 1)         # k < 2
    with pytest.raises(ValueError):
        variance_ratio([1.0, 2.0, 3.0], 8)         # series too short for k


def test_regime_tradeable_on_mean_reverting():
    a = assess_spread_regime(_ar1_level(1000, 5, phi=0.9),
                             min_half_life=1.0, max_half_life=50.0, vr_k=8, vr_max=0.9)
    assert a.tradeable and a.stationary and a.mean_reverting and a.reason == "ok"


def test_regime_blocks_random_walk():
    a = assess_spread_regime(_random_walk(1000, 6))
    assert not a.tradeable and not a.stationary
    assert "stationary" in a.reason


def test_regime_blocks_slow_half_life():
    a = assess_spread_regime(_ar1_level(1000, 5, phi=0.9), max_half_life=2.0)   # hl ~6.6 > 2
    assert not a.tradeable and "slow" in a.reason


def test_regime_blocks_when_vr_threshold_unreachable():
    a = assess_spread_regime(_ar1_level(1000, 5, phi=0.9), vr_max=0.01)   # stationary, but VR not < 0.01
    assert not a.tradeable and "mean-reverting" in a.reason


# -- mutation-killing -----------------------------------------------------------
def test_vr_validation_and_constant_guard():
    with pytest.raises(ValueError):
        variance_ratio([1.0, 2.0], 1)                # k < 2
    with pytest.raises(ValueError):
        variance_ratio([1.0, 2.0, 3.0], 8)           # n <= k + 1
    assert variance_ratio([5.0] * 30, 4) == 1.0      # var1 ~ 0 guard returns 1.0


def test_assess_ok_sets_all_flags():
    a = assess_spread_regime(_ar1_level(1000, 5, phi=0.9),
                             min_half_life=1.0, max_half_life=50.0, vr_k=8, vr_max=0.9)
    assert a.tradeable is True and a.reason == "ok"
    assert a.stationary is True and a.mean_reverting is True and a.adf_stat < 0


def test_half_life_too_fast_reason():
    a = assess_spread_regime(_ar1_level(1000, 5, phi=0.9), min_half_life=20.0)  # hl ~6.6 < 20
    assert not a.tradeable and "fast" in a.reason


def test_random_walk_vr_near_one_not_below():
    # a random walk is NOT mean-reverting -> VR ~1, fails the vr_max=0.9 gate
    rng = random.Random(11)
    x = [0.0]
    for _ in range(1500):
        x.append(x[-1] + rng.gauss(0, 1))
    assert variance_ratio(x, 8) > 0.7                # not strongly < 0.9 like a reverting one


def test_variance_ratio_exact_value():
    # pins the d1 range, var1 (d-mu), dk, vark (d-k*mu) and the vark/(k*var1) formula
    assert variance_ratio([0, 1, 3, 2, 4, 3], 2) == pytest.approx(0.84 / 3.68, abs=1e-6)


def test_vr_k_and_n_boundaries_exact():
    variance_ratio([1.0, 2.0, 3.0, 4.0], 2)          # k==2 valid, n=4 > k+1 -> no raise
    with pytest.raises(ValueError, match=r"^k must be >= 2$"):
        variance_ratio([1.0, 2.0, 3.0], 1)
    with pytest.raises(ValueError, match=r"^series too short for this k$"):
        variance_ratio([1.0, 2.0, 3.0], 2)           # n=3 <= k+1=3 -> raises


def test_assessment_is_frozen():
    import dataclasses

    from treasuryforge.signals.regime import RegimeAssessment
    a = RegimeAssessment(True, "ok", True, -3.0, 5.0, 0.5, True)
    with pytest.raises(dataclasses.FrozenInstanceError):
        a.tradeable = False


def test_exact_reason_strings():
    assert assess_spread_regime(_random_walk(1000, 6)).reason == \
        "spread not stationary (relationship breaking)"
    assert assess_spread_regime(_ar1_level(1000, 5, phi=0.9), max_half_life=2.0).reason == \
        "half-life too slow / not reverting"
    assert assess_spread_regime(_ar1_level(1000, 5, phi=0.9), min_half_life=20.0).reason == \
        "half-life too fast (reversion < cost)"
    # stationary + good half-life but VR can't clear the gate -> the VR reason (kills XX-wrap)
    vr_blocked = assess_spread_regime(_ar1_level(1000, 5, phi=0.9), vr_max=0.01).reason
    assert vr_blocked.startswith("regime not mean-reverting (VR=") and vr_blocked.endswith(")")


def test_random_walk_not_mean_reverting_with_default_vr_max():
    a = assess_spread_regime(_random_walk(2000, 9))
    assert a.mean_reverting is False                 # VR ~1 not < 0.9 (kills vr_max 0.9 -> 1.9)
