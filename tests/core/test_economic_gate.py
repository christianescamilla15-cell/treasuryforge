"""Economic gate (v2 P9): CORPSE for fee-bleed / negative effective, REJECT for thin,
PASS only when net-positive on capital with comfortable cost/gross."""

from __future__ import annotations

import pytest

from treasuryforge.cross_venue_economics import CrossVenueEconomics, cross_venue_economics
from treasuryforge.economic_gate import GateResult, economic_gate


def test_negative_effective_is_corpse():
    # short hold -> costs dwarf gross -> CORPSE regardless of duty
    econ = cross_venue_economics(0.30, hold_hours=24)
    v = economic_gate(econ, duty_cycle=1.0)
    assert v.result is GateResult.CORPSE and not v.is_pass


def test_fat_persistent_spread_passes():
    econ = cross_venue_economics(0.35, hold_hours=24 * 365)   # ~0.20 net on capital
    v = economic_gate(econ, duty_cycle=0.95)                  # mostly on
    assert v.result is GateResult.PASS and v.effective_apr > 0
    assert v.cost_gross_ratio < 0.35


def test_thin_edge_is_reject_not_pass():
    econ = cross_venue_economics(0.05, hold_hours=24 * 365)   # barely above breakeven
    v = economic_gate(econ, duty_cycle=0.9)
    assert v.result in (GateResult.REJECT, GateResult.CORPSE) and not v.is_pass


def test_low_duty_cycle_can_demote_to_corpse():
    econ = cross_venue_economics(0.35, hold_hours=24 * 365)
    on = economic_gate(econ, duty_cycle=0.95)
    off = economic_gate(econ, duty_cycle=0.0)                 # never on -> effective 0 -> CORPSE
    assert on.result is GateResult.PASS and off.result is GateResult.CORPSE


def test_zero_spread_is_corpse():
    v = economic_gate(cross_venue_economics(0.0, hold_hours=100), duty_cycle=1.0)
    assert v.result is GateResult.CORPSE and v.cost_gross_ratio == float("inf")


def test_min_effective_apr_threshold():
    econ = cross_venue_economics(0.35, hold_hours=24 * 365)   # ~0.19 effective at duty 1.0
    assert economic_gate(econ, 1.0, min_effective_apr=0.30).result is GateResult.REJECT  # demands 30%
    assert economic_gate(econ, 1.0, min_effective_apr=0.05).result is GateResult.PASS


# -- mutation-killers: enum values, frozen, exact reasons, ratio, boundaries ----
def test_gate_enum_values():
    assert GateResult.CORPSE.value == "CORPSE"
    assert GateResult.REJECT.value == "REJECT"
    assert GateResult.PASS.value == "PASS"


def test_verdict_frozen():
    import dataclasses
    v = economic_gate(cross_venue_economics(0.0, hold_hours=100), 1.0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        v.result = GateResult.PASS


def test_no_spread_exact():
    v = economic_gate(cross_venue_economics(0.0, hold_hours=100), 1.0)
    assert v.result is GateResult.CORPSE
    assert v.effective_apr == 0.0 and v.cost_gross_ratio == float("inf")
    assert v.reason == "no spread"


def _econ(gross, net_funding, net_cap):
    return CrossVenueEconomics(gross_spread_apr=gross, amortised_trade_cost_apr=0.0,
                               notional_drag_apr=0.0, capital_drag_apr=0.0,
                               net_funding_apr_on_notional=net_funding, total_locked_ratio=1.5,
                               net_apr_on_total_capital=net_cap, breakeven_hold_hours=100.0)


def test_reject_window_ratio_and_default_cap():
    econ = _econ(0.10, 0.06, 0.04)                            # ratio 0.40 (>0.35), eff 0.04>0
    v = economic_gate(econ, duty_cycle=1.0)
    assert v.result is GateResult.REJECT
    assert v.cost_gross_ratio == pytest.approx(0.40)         # cost/gross (kills cost*gross)
    assert v.effective_apr == pytest.approx(0.04)
    assert v.reason == f"cost/gross {0.40:.0%} > {0.35:.0%} or eff {0.04:+.1%} thin"
    assert economic_gate(econ, 1.0, max_cost_gross=0.5).result is GateResult.PASS   # kills 0.35 default


def test_ratio_at_one_is_corpse():
    v = economic_gate(_econ(0.10, 0.0, 0.05), duty_cycle=1.0)  # ratio 1.0, eff 0.05>0
    assert v.result is GateResult.CORPSE                       # ratio>=1.0 (kills > and >=2.0)


def test_pass_and_corpse_reasons_exact():
    p = economic_gate(cross_venue_economics(0.35, hold_hours=24 * 365), duty_cycle=0.95)
    assert p.result is GateResult.PASS
    assert p.reason == f"eff {p.effective_apr:+.1%}, cost/gross {p.cost_gross_ratio:.0%}"
    c = economic_gate(cross_venue_economics(0.30, hold_hours=24), duty_cycle=1.0)
    assert c.result is GateResult.CORPSE
    assert c.reason == f"cost/gross {c.cost_gross_ratio:.0%}, effective {c.effective_apr:+.1%}"
