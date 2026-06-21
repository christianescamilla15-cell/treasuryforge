"""The directional blow-out stop on the signal, and the regime gate wired into the
backtest (vetoes entries when the spread isn't tradeable, never invents trades)."""

from __future__ import annotations

import random

import pytest

from treasuryforge.backtest import backtest_pairs
from treasuryforge.signals.pairs import PairsSignal


def test_stop_z_must_exceed_entry():
    with pytest.raises(ValueError):
        PairsSignal(2.0, 0.5, stop_z=2.0)


def test_short_blows_out_when_spread_climbs():
    s = PairsSignal(2.0, 0.5, stop_z=4.0)
    assert s.update(2.5) == -1        # spread high -> short
    assert s.update(4.0) == 0         # climbed against us past stop -> flatten at a loss


def test_long_blows_out_when_spread_falls():
    s = PairsSignal(2.0, 0.5, stop_z=4.0)
    assert s.update(-2.5) == 1        # spread low -> long
    assert s.update(-4.0) == 0        # fell further past stop -> flatten


def test_without_stop_it_holds_through_a_blowout():
    s = PairsSignal(2.0, 0.5)         # no stop -> "wait for reversion" forever
    assert s.update(2.5) == -1
    assert s.update(6.0) == -1        # still short, no stop


def test_favorable_reversion_exits_at_mean_not_via_stop():
    s = PairsSignal(2.0, 0.5, stop_z=4.0)
    assert s.update(2.5) == -1
    assert s.update(0.0) == 0         # reverted through the mean -> normal hysteresis exit


def _rw(n, seed, x0=100.0, sigma=1.0):
    rng = random.Random(seed)
    x = [x0]
    for _ in range(n):
        x.append(x[-1] + rng.gauss(0, sigma))
    return x


def _ar1(n, seed, phi=0.9, mean=100.0, sigma=1.0):
    rng = random.Random(seed)
    x = [mean]
    for _ in range(n):
        x.append(mean + phi * (x[-1] - mean) + rng.gauss(0, sigma))
    return x


def test_gate_vetoes_entries_in_a_broken_regime():
    a = _rw(700, 7)                   # non-stationary spread (beta 0, b const)
    b = [0.0] * len(a)
    base = backtest_pairs(a, b, alpha=0.0, beta=0.0, window=60, regime_gate=False)
    gated = backtest_pairs(a, b, alpha=0.0, beta=0.0, window=60,
                           regime_gate=True, regime_window=240)
    assert base.n_trades > 0          # the naive band does trade the random walk
    assert gated.n_gated > 0          # the gate caught entry attempts
    assert gated.n_trades < base.n_trades   # and strictly removed trades


def test_gate_never_invents_trades_on_a_good_spread():
    a = _ar1(700, 5)                  # stationary, mean-reverting
    b = [0.0] * len(a)
    base = backtest_pairs(a, b, alpha=0.0, beta=0.0, window=60, regime_gate=False)
    gated = backtest_pairs(a, b, alpha=0.0, beta=0.0, window=60,
                           regime_gate=True, regime_window=240, max_half_life=50.0)
    assert gated.n_trades > 0                 # warm regime is tradeable -> it does enter
    assert gated.n_trades <= base.n_trades    # gate only ever removes, never adds
