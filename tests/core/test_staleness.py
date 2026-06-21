"""Runtime staleness + clock-sanity gate. Time is injected (exact ns), so freshness
budgets, wall-backward jumps and NTP-step drift are all deterministic. The bot must
refuse to act on stale data or an untrustworthy clock."""

from __future__ import annotations

import dataclasses
import time

import pytest

from treasuryforge.staleness import NS_PER_S, WINDOW_24H_NS, GateVerdict, StalenessGate

NS = 1_000_000_000
W0 = 1_700_000_000 * NS      # a sane wall-clock base (ns)
M0 = 50_000 * NS            # an arbitrary monotonic base (ns)


def _gate(max_age_ns=5 * NS, drift=NS):
    return StalenessGate(max_data_age_ns=max_age_ns, max_clock_drift_ns=drift)


def test_fresh_data_is_ok():
    g = _gate()
    g.observe_data(W0)
    v = g.check(W0 + 2 * NS, M0)                 # 2s old, 5s budget
    assert v.ok and v.reason == "fresh" and v.data_age_ns == 2 * NS


def test_no_data_observed_halts():
    v = _gate().check(W0, M0)
    assert not v.ok and "no market data" in v.reason


def test_stale_data_boundary_is_inclusive():
    g = _gate(max_age_ns=5 * NS)
    g.observe_data(W0)
    assert g.check(W0 + 5 * NS, M0).ok           # age == budget -> still ok (not >)
    g2 = _gate(max_age_ns=5 * NS)
    g2.observe_data(W0)
    v = g2.check(W0 + 5 * NS + 1, M0)            # age == budget + 1ns -> stale
    assert not v.ok and "stale data" in v.reason and v.data_age_ns == 5 * NS + 1


def test_future_data_halts():
    g = _gate()
    g.observe_data(W0 + 10 * NS)
    v = g.check(W0, M0)
    assert not v.ok and "future" in v.reason and v.data_age_ns == -10 * NS


def test_first_check_skips_clock_sanity():
    g = _gate()
    g.observe_data(W0)
    assert g.check(W0, M0).ok                     # no prior reading -> only freshness judged


def test_wall_clock_backward_halts():
    g = _gate()
    g.observe_data(W0)
    g.check(W0, M0)                               # establish previous reading
    v = g.check(W0 - NS, M0 + NS)                 # wall jumped back 1s
    assert not v.ok and "backward" in v.reason


def test_clock_drift_halts():
    g = _gate(drift=NS)
    g.observe_data(W0)
    g.check(W0, M0)
    v = g.check(W0 + 5 * NS, M0 + NS)             # wall +5s but mono +1s -> 4s drift > 1s
    assert not v.ok and "drift" in v.reason


def test_clock_drift_boundary_is_inclusive():
    g = _gate(drift=NS)
    g.observe_data(W0)
    g.check(W0, M0)
    g.observe_data(W0 + 2 * NS)
    v = g.check(W0 + 2 * NS, M0 + NS)             # Δwall 2s, Δmono 1s -> drift 1s == budget
    assert v.ok                                  # exactly at budget -> not a halt


def test_normal_advance_is_ok():
    g = _gate()
    g.observe_data(W0)
    g.check(W0, M0)
    g.observe_data(W0 + NS)
    assert g.check(W0 + NS, M0 + NS).ok          # wall and monotonic advance together


def test_check_now_uses_injected_sources():
    wall = [W0]
    mono = [M0]
    g = StalenessGate(max_data_age_ns=5 * NS, wall_source=lambda: wall[0], mono_source=lambda: mono[0])
    g.observe_data(W0)
    assert g.check_now().ok
    wall[0] = W0 + 100 * NS                       # data is now 100s stale
    assert not g.check_now().ok


def test_requires_positive_budget():
    with pytest.raises(ValueError, match=r"^max_data_age_ns must be positive$"):
        StalenessGate(max_data_age_ns=0)


def test_window_24h_constant_is_exact():
    assert WINDOW_24H_NS == 86_400 * 1_000_000_000


def test_verdict_is_immutable_and_carries_age():
    v = GateVerdict(True, "fresh", 7)
    assert v.ok and v.reason == "fresh" and v.data_age_ns == 7


# ============================================================================
# mutation hardening: exact reasons, constants, frozen verdict, defaults, edges
# ============================================================================
def test_ns_per_s_constant_is_exact():
    assert NS_PER_S == 1_000_000_000


def test_min_budget_of_one_ns_is_valid():
    StalenessGate(max_data_age_ns=1)             # 1 > 0 -> must NOT raise


def test_default_time_sources_and_initial_state():
    g = StalenessGate(max_data_age_ns=NS)
    assert g.wall_source is time.time_ns and g.mono_source is time.monotonic_ns
    assert g._prev_wall_ns is None and g._prev_mono_ns is None and g._last_data_ns is None


def test_verdict_is_frozen_and_defaults_age_none():
    assert GateVerdict(True, "x").data_age_ns is None
    with pytest.raises(dataclasses.FrozenInstanceError):
        GateVerdict(True, "x").ok = False


def test_frozen_wall_clock_is_not_treated_as_backward():
    g = _gate()
    g.observe_data(W0)
    g.check(W0, M0)                              # prev = (W0, M0)
    g.observe_data(W0)
    assert g.check(W0, M0).ok                    # Δwall == 0 is NOT backward (strict <)


def test_exact_halt_reasons():
    assert _gate().check(W0, M0).reason == "no market data observed yet"

    g = _gate(max_age_ns=5 * NS)
    g.observe_data(W0)
    assert g.check(W0 + 5 * NS + 1, M0).reason == f"stale data: age {5 * NS + 1}ns > budget {5 * NS}ns"

    g2 = _gate()
    g2.observe_data(W0 + 10 * NS)
    assert g2.check(W0, M0).reason == f"data timestamp in the future by {10 * NS}ns"

    g3 = _gate()
    g3.observe_data(W0)
    g3.check(W0, M0)
    assert g3.check(W0 - NS, M0 + NS).reason == f"wall clock went backward by {NS}ns"

    g4 = _gate(drift=NS)
    g4.observe_data(W0)
    g4.check(W0, M0)
    assert g4.check(W0 + 5 * NS, M0 + NS).reason == f"clock drift {4 * NS}ns > budget {NS}ns"
