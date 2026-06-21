"""Cross-venue leg execution (v2 P5): SAFE/RESIDUAL/ORPHAN/BOTH_FAILED + unwind cost."""

from __future__ import annotations

import pytest

from treasuryforge.cross_venue_legger import ExecVerdict, LegFillParams, simulate_cross_legs


def test_both_full_is_safe_no_unwind():
    r = simulate_cross_legs(1.0, 1.0)
    assert r.verdict is ExecVerdict.SAFE and r.is_safe
    assert r.hedged_fraction == 1.0 and r.residual_delta == 0.0 and r.unwind_cost == 0.0


def test_orphan_when_one_leg_fails():
    r = simulate_cross_legs(1.0, 0.0)                 # long filled, short failed -> naked long
    assert r.verdict is ExecVerdict.ORPHAN and not r.is_safe
    assert r.residual_delta == 1.0 and r.hedged_fraction == 0.0


def test_both_failed_is_safe_exposure():
    r = simulate_cross_legs(0.0, 0.0)
    assert r.verdict is ExecVerdict.BOTH_FAILED and r.residual_delta == 0.0 and r.unwind_cost == 0.0


def test_partial_within_tolerance_is_safe():
    r = simulate_cross_legs(1.0, 0.97, LegFillParams(max_residual_delta=0.05))
    assert r.verdict is ExecVerdict.SAFE and r.residual_delta == pytest.approx(0.03)


def test_partial_beyond_tolerance_is_residual():
    r = simulate_cross_legs(1.0, 0.80, LegFillParams(max_residual_delta=0.05))
    assert r.verdict is ExecVerdict.RESIDUAL and r.residual_delta == pytest.approx(0.20)


def test_unwind_cost_includes_slippage_and_drift():
    p = LegFillParams(unwind_slippage=0.001, price_drift=0.002)
    r = simulate_cross_legs(1.0, 0.0, p)             # full orphan -> residual 1.0
    assert r.unwind_cost == pytest.approx(1.0 * (0.001 + 0.002))


def test_hedged_is_min_of_legs():
    r = simulate_cross_legs(0.6, 0.9, LegFillParams(max_residual_delta=0.5))
    assert r.hedged_fraction == pytest.approx(0.6)   # only 0.6 is actually delta-neutral
    assert r.residual_delta == pytest.approx(0.3)


# -- mutation-killers: enum values, defaults, frozen, exact verdicts/cost --------
def test_verdict_enum_values():
    assert ExecVerdict.SAFE.value == "SAFE" and ExecVerdict.RESIDUAL.value == "RESIDUAL"
    assert ExecVerdict.ORPHAN.value == "ORPHAN" and ExecVerdict.BOTH_FAILED.value == "BOTH_FAILED"


def test_params_defaults_and_frozen():
    import dataclasses
    p = LegFillParams()
    assert (p.max_residual_delta, p.unwind_slippage, p.price_drift) == (0.05, 0.0010, 0.0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        p.max_residual_delta = 1.0


def test_all_four_verdicts():
    assert simulate_cross_legs(0.0, 0.0).verdict is ExecVerdict.BOTH_FAILED
    assert simulate_cross_legs(0.0, 0.5).verdict is ExecVerdict.ORPHAN   # kills short<=1.0 and long<0
    assert simulate_cross_legs(0.5, 0.0).verdict is ExecVerdict.ORPHAN
    assert simulate_cross_legs(1.0, 0.8).verdict is ExecVerdict.RESIDUAL  # residual 0.2 > 0.05
    assert simulate_cross_legs(1.0, 0.98).verdict is ExecVerdict.SAFE     # residual 0.02 <= 0.05


def test_residual_boundary_and_unwind_cost():
    p = LegFillParams(max_residual_delta=0.5)            # 0.5 is float-exact (1.0-0.5)
    safe = simulate_cross_legs(1.0, 0.5, p)              # residual exactly 0.5
    assert safe.verdict is ExecVerdict.SAFE              # 0.5 not > 0.5 (kills > -> >=)
    assert safe.residual_delta == pytest.approx(0.5) and safe.hedged_fraction == pytest.approx(0.5)
    assert simulate_cross_legs(1.0, 0.4, p).verdict is ExecVerdict.RESIDUAL   # residual 0.6 > 0.5
    r2 = simulate_cross_legs(1.0, 0.8, LegFillParams(max_residual_delta=0.5,
                                                     unwind_slippage=0.002, price_drift=0.001))
    assert r2.unwind_cost == pytest.approx(0.2 * (0.002 + 0.001))   # residual*(slip+|drift|)


def test_result_frozen():
    import dataclasses
    r = simulate_cross_legs(1.0, 1.0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.verdict = ExecVerdict.ORPHAN
