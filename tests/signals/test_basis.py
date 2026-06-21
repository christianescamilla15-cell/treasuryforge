"""Spot-vs-perp basis signal: hysteresis on the premium, costs, premium math."""

from __future__ import annotations

import pytest

from treasuryforge.signals.basis import BasisParams, BasisSignal, premium_from_marks
from treasuryforge.signals.funding import Action


def _sig(enter=0.0010, exit_=0.0002):
    return BasisSignal(BasisParams(enter_premium=enter, exit_premium=exit_, fee_per_leg=0.0003))


def test_enters_on_rich_premium_holds_then_exits_on_convergence():
    s = _sig()
    assert s.decide(0.0005) is Action.FLAT       # premium below enter -> stay out
    assert s.decide(0.0012) is Action.ENTER      # rich -> enter
    assert s.decide(0.0008) is Action.HOLD       # still above exit -> hold
    assert s.decide(0.0001) is Action.EXIT       # converged -> exit
    assert s.decide(0.0001) is Action.FLAT       # out again


def test_hysteresis_boundaries_are_inclusive():
    s = _sig(enter=0.0010, exit_=0.0002)
    assert s.decide(0.0010) is Action.ENTER      # == enter -> enters
    assert s.decide(0.0002) is Action.EXIT       # == exit -> exits


def test_params_reject_inverted_band():
    with pytest.raises(ValueError):
        BasisParams(enter_premium=0.0002, exit_premium=0.0010, fee_per_leg=0.0003)


def test_costs_split_round_trip():
    p = BasisParams(enter_premium=0.001, exit_premium=0.0, fee_per_leg=0.0003)
    assert p.round_trip_cost == pytest.approx(4 * 0.0003)
    assert p.entry_cost == pytest.approx(2 * 0.0003) and p.exit_cost == pytest.approx(2 * 0.0003)


def test_premium_from_marks():
    assert premium_from_marks(1010.0, 1000.0) == pytest.approx(0.01)
    assert premium_from_marks(100.0, 0.0) == 0.0      # guard div-by-zero


# -- mutation-killing -----------------------------------------------------------
def test_in_position_tracks_state():
    s = _sig()
    assert s.in_position is False                     # exactly False, not None (kills _in=None)
    s.decide(0.0012)
    assert s.in_position is True                      # ENTER set _in True
    s.decide(0.0001)
    assert s.in_position is False                     # EXIT cleared it to False


def test_params_are_frozen():
    import dataclasses
    p = BasisParams(enter_premium=0.001, exit_premium=0.0, fee_per_leg=0.0003)
    with pytest.raises(dataclasses.FrozenInstanceError):
        p.enter_premium = 0.5                         # kills frozen=True -> frozen=False


def test_equal_band_is_allowed_not_rejected():
    # exit == enter must NOT raise (kills the `>` -> `>=` mutation in __post_init__)
    BasisParams(enter_premium=0.001, exit_premium=0.001, fee_per_leg=0.0003)


def test_inverted_band_message():
    with pytest.raises(ValueError, match="hysteresis"):
        BasisParams(enter_premium=0.0002, exit_premium=0.0010, fee_per_leg=0.0003)


def test_premium_from_marks_oracle_guard_strict_gt_zero():
    assert premium_from_marks(1.0, 0.5) == pytest.approx(1.0)   # oracle 0.5 (>0 not >1) computes


def test_costs_exact_and_round_trip_sum():
    p = BasisParams(enter_premium=0.001, exit_premium=0.0, fee_per_leg=0.0002, legs_round_trip=4)
    assert p.entry_cost == pytest.approx(2 * 0.0002)  # legs/2 * fee
    assert p.exit_cost == pytest.approx(2 * 0.0002)
    assert p.round_trip_cost == pytest.approx(4 * 0.0002)


def test_premium_from_marks_negative_backwardation():
    assert premium_from_marks(990.0, 1000.0) == pytest.approx(-0.01)


def test_flat_stays_flat_below_enter():
    s = _sig(enter=0.0010)
    assert s.decide(0.0009) is Action.FLAT and not s.in_position
