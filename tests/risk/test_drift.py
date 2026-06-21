"""Page-Hinkley drift kill-switch — the live guard."""

from __future__ import annotations

import random

from treasuryforge.risk import PageHinkley, make_kill_switch


# -- Page-Hinkley core -------------------------------------------------------
def test_no_alarm_on_stationary_stream():
    rng = random.Random(0)
    ph = PageHinkley(delta=0.0005, lam=0.05, direction="decrease")
    for _ in range(500):
        ph.update(0.001 + rng.gauss(0, 0.002))     # stable mean +0.001
    assert not ph.alarm


def test_alarm_on_mean_drop():
    rng = random.Random(1)
    ph = PageHinkley(delta=0.0002, lam=0.02, direction="decrease")
    fired_at = None
    for i in range(600):
        mu = 0.002 if i < 300 else -0.002            # edge flips negative at t=300
        ph.update(mu + rng.gauss(0, 0.001))
        if ph.alarm and fired_at is None:
            fired_at = i
    assert fired_at is not None and fired_at >= 300   # only fires AFTER the drop


def test_increase_detector_flags_rising_slippage():
    rng = random.Random(2)
    ph = PageHinkley(delta=0.0001, lam=0.02, direction="increase")
    for i in range(600):
        s = 0.0005 if i < 300 else 0.002             # slippage triples
        ph.update(s + abs(rng.gauss(0, 0.0001)))
    assert ph.alarm


# -- the kill-switch ---------------------------------------------------------
def test_kill_on_edge_drift():
    ks = make_kill_switch(expectancy_delta=0.0002, expectancy_lambda=0.02,
                          slippage_delta=0.0001, slippage_lambda=0.02)
    rng = random.Random(3)
    verdict = None
    for i in range(600):
        mu = 0.002 if i < 300 else -0.002
        verdict = ks.observe(ret=mu + rng.gauss(0, 0.001))
    assert verdict == "KILL: EDGE_DRIFT_DETECTED" and ks.killed


def test_kill_on_execution_degraded():
    ks = make_kill_switch(expectancy_delta=0.0002, expectancy_lambda=0.02,
                          slippage_delta=0.0001, slippage_lambda=0.02)
    for i in range(600):
        s = 0.0005 if i < 300 else 0.003
        ks.observe(slippage=s)
    assert ks.reason == "KILL: EXECUTION_DEGRADED"


def test_kill_on_drawdown_band():
    ks = make_kill_switch(expectancy_delta=0.001, expectancy_lambda=1.0,
                          slippage_delta=0.001, slippage_lambda=1.0, stress_dd_band=0.30)
    assert ks.observe(drawdown=0.20) is None          # within band
    assert ks.observe(drawdown=0.35).startswith("KILL: DD_EXCEEDS_STRESS_BAND")


def test_stays_killed_and_returns_reason():
    ks = make_kill_switch(expectancy_delta=0.001, expectancy_lambda=1.0,
                          slippage_delta=0.001, slippage_lambda=1.0, stress_dd_band=0.30)
    ks.observe(drawdown=0.40)
    assert ks.killed
    # subsequent observations keep returning the kill reason (no resurrection)
    assert ks.observe(ret=0.005, drawdown=0.01).startswith("KILL: DD_EXCEEDS_STRESS_BAND")


def test_healthy_stream_never_kills():
    ks = make_kill_switch(expectancy_delta=0.0005, expectancy_lambda=0.05,
                          slippage_delta=0.0002, slippage_lambda=0.05, stress_dd_band=0.30)
    rng = random.Random(4)
    for _ in range(500):
        v = ks.observe(ret=0.001 + rng.gauss(0, 0.002), slippage=0.0004, drawdown=0.05)
        assert v is None
    assert not ks.killed
