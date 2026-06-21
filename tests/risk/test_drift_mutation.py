"""Mutation-hardening for the Page-Hinkley drift kill-switch: exact recursion,
strict alarm threshold, latch, reset, and the kill-switch boundaries/reasons.
Existing tests are random/statistical; these pin the deterministic math."""

from __future__ import annotations

import random

import pytest

from treasuryforge.risk import PageHinkley, make_kill_switch
from treasuryforge.risk.drift import DriftKillSwitch


def test_page_hinkley_decrease_exact_recursion():
    ph = PageHinkley(delta=0.0, lam=10.0, direction="decrease")
    assert [round(ph.update(x), 10) for x in (1.0, 0.0, 0.0)] == [0.0, 0.5, 0.8333333333]
    assert ph.n == 3
    assert ph.mean == pytest.approx(1 / 3)
    assert ph.m == pytest.approx(-5 / 6)
    assert ph.extreme == 0.0
    assert not ph.alarm


def test_page_hinkley_increase_exact_recursion():
    ph = PageHinkley(delta=0.0, lam=10.0, direction="increase")
    assert [round(ph.update(x), 10) for x in (0.0, 1.0, 1.0)] == [0.0, 0.5, 0.8333333333]
    assert ph.m == pytest.approx(5 / 6)
    assert ph.extreme == 0.0


def test_decrease_adds_delta_slack():
    ph = PageHinkley(delta=0.1, lam=10.0, direction="decrease")
    assert [round(ph.update(x), 10) for x in (1.0, 0.0)] == [0.0, 0.4]


def test_increase_subtracts_delta_slack():
    ph = PageHinkley(delta=0.1, lam=10.0, direction="increase")
    # step1 x=0: m += 0-0-0.1 = -0.1, extreme=min(0,-0.1)=-0.1, ph=-0.1-(-0.1)=0.0
    # step2 x=1: mean=0.5, m += 1-0.5-0.1 = 0.4 -> m=0.3, extreme=-0.1, ph=0.3-(-0.1)=0.4
    assert [round(ph.update(x), 10) for x in (0.0, 1.0)] == [0.0, 0.4]


def test_alarm_threshold_is_strict():
    ph = PageHinkley(delta=0.0, lam=0.5, direction="decrease")
    ph.update(1.0)                                    # ph 0.0
    assert ph.update(0.0) == pytest.approx(0.5)       # ph == lam exactly
    assert not ph.alarm                               # strict > -> no alarm at equality
    ph.update(0.0)                                    # ph 0.833 > 0.5
    assert ph.alarm


def test_alarm_latches_after_recovery():
    ph = PageHinkley(delta=0.0, lam=0.4, direction="decrease")
    for x in (1.0, 0.0, 0.0):
        ph.update(x)
    assert ph.alarm
    ph.update(5.0)                                    # mean jumps, ph drops, alarm stays
    assert ph.alarm


def test_page_hinkley_constructor_defaults():
    # defaults: delta=0.0, lam=0.05, direction='decrease'
    d = PageHinkley()
    assert d.alarm is False                                          # not None
    phs = [round(d.update(x), 10) for x in (1.0, 0.0, 0.0)]
    assert phs == [0.0, 0.5, 0.8333333333]                          # delta default 0.0 (mutant 1.0 differs)
    assert d.alarm                                                  # 0.83 > 0.05 default lam (1.05 mutant: no alarm)


def test_page_hinkley_default_direction_is_decrease():
    d = PageHinkley()
    # decrease branch on [0,1,1] yields all-zero ph; the increase branch would not
    assert [round(d.update(x), 10) for x in (0.0, 1.0, 1.0)] == [0.0, 0.0, 0.0]


def test_reset_clears_all_state():
    ph = PageHinkley(delta=0.0, lam=0.4, direction="decrease")
    for x in (1.0, 0.0, 0.0):
        ph.update(x)
    assert ph.alarm
    ph.reset()
    assert (ph.n, ph.mean, ph.m, ph.extreme, ph.alarm) == (0, 0.0, 0.0, 0.0, False)


# -- DriftKillSwitch ---------------------------------------------------------
def test_drawdown_band_boundary_strict_and_reason():
    ks = make_kill_switch(expectancy_delta=0.001, expectancy_lambda=1e9,
                          slippage_delta=0.001, slippage_lambda=1e9, stress_dd_band=0.30)
    assert ks.observe(drawdown=0.30) is None          # == band -> not killed (strict >)
    assert ks.observe(drawdown=0.31) == "KILL: DD_EXCEEDS_STRESS_BAND (31% > 30%)"


def test_edge_and_execution_kill_reasons_exact():
    ks = make_kill_switch(expectancy_delta=0.0002, expectancy_lambda=0.02,
                          slippage_delta=0.0001, slippage_lambda=0.02)
    rng = random.Random(3)
    v = None
    for i in range(600):
        mu = 0.002 if i < 300 else -0.002
        v = ks.observe(ret=mu + rng.gauss(0, 0.001))
    assert v == "KILL: EDGE_DRIFT_DETECTED"

    ks2 = make_kill_switch(expectancy_delta=0.0002, expectancy_lambda=0.02,
                           slippage_delta=0.0001, slippage_lambda=0.02)
    for i in range(600):
        ks2.observe(slippage=(0.0005 if i < 300 else 0.003))
    assert ks2.reason == "KILL: EXECUTION_DEGRADED"


def test_first_kill_reason_wins_and_latches():
    ks = make_kill_switch(expectancy_delta=0.001, expectancy_lambda=1e9,
                          slippage_delta=0.001, slippage_lambda=1e9, stress_dd_band=0.30)
    first = ks.observe(drawdown=0.50)
    assert first == "KILL: DD_EXCEEDS_STRESS_BAND (50% > 30%)" and ks.killed
    assert ks.observe(drawdown=0.99) == "KILL: DD_EXCEEDS_STRESS_BAND (50% > 30%)"   # reason latches


def test_kill_switch_dataclass_defaults():
    ks = DriftKillSwitch(expectancy=PageHinkley(direction="decrease"),
                         slippage=PageHinkley(direction="increase"))
    assert ks.killed is False and ks.reason == "" and ks.stress_dd_band == 0.30
    assert ks.observe(drawdown=0.30) is None                        # == default band -> no kill
    assert ks.observe(drawdown=0.31) == "KILL: DD_EXCEEDS_STRESS_BAND (31% > 30%)"


def test_make_kill_switch_default_band_is_030():
    ks = make_kill_switch(expectancy_delta=0.001, expectancy_lambda=1e9,
                          slippage_delta=0.001, slippage_lambda=1e9)   # stress_dd_band omitted
    assert ks.stress_dd_band == 0.30
    assert ks.observe(drawdown=0.31) == "KILL: DD_EXCEEDS_STRESS_BAND (31% > 30%)"


def test_make_kill_switch_wires_directions_and_params():
    ks = make_kill_switch(expectancy_delta=0.01, expectancy_lambda=0.05,
                          slippage_delta=0.02, slippage_lambda=0.06, stress_dd_band=0.25)
    assert ks.expectancy.direction == "decrease"
    assert (ks.expectancy.delta, ks.expectancy.lam) == (0.01, 0.05)
    assert ks.slippage.direction == "increase"
    assert (ks.slippage.delta, ks.slippage.lam) == (0.02, 0.06)
    assert ks.stress_dd_band == 0.25
