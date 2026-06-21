"""The forward scalp book must reproduce the momentum rule one bar at a time: enter only on
ignition+follow-through, mark-to-market while held, exit on trail/stop/time, and charge the
half round-trip on the entry and exit bars."""

from __future__ import annotations

import pytest

from treasuryforge.scalp_shadow import ScalpBook
from treasuryforge.signals.momentum import MomentumParams

_HALF = MomentumParams().cost / 2.0          # 0.00065


def _enter(book: ScalpBook) -> tuple[str, float]:
    """Drive the 3 bars that arm + trigger an ignition entry at close 102."""
    book.observe(100, 100, 100)              # warmup (prev2 still 0)
    book.observe(100, 100, 100)              # arms prev2=100, prev=100
    return book.observe(102, 102, 102)       # +2% jump, prior bar flat -> ENTER


def test_flat_and_quiet_never_trades() -> None:
    b = ScalpBook()
    for _ in range(5):
        action, r = b.observe(100, 100, 100)
        assert action == "FLAT" and r == 0.0


def test_enters_on_ignition_with_followthrough() -> None:
    b = ScalpBook()
    action, r = _enter(b)
    assert action == "ENTER" and b.in_pos and b.entry == 102
    assert r == pytest.approx(-_HALF)        # only the entry-leg cost on the entry bar


def test_no_entry_without_followthrough() -> None:
    b = ScalpBook()
    b.observe(100, 100, 100)
    b.observe(100, 100, 99)                  # prior bar DOWN -> confirm fails
    action, r = b.observe(99, 99, 101)       # +2% jump but no follow-through
    assert action == "FLAT" and not b.in_pos and r == 0.0


def test_holds_and_marks_to_market() -> None:
    b = ScalpBook()
    _enter(b)
    action, r = b.observe(105, 103, 104)     # up bar, no exit
    assert action == "HOLD" and b.in_pos and b.peak == 105
    assert r == pytest.approx(104 / 102 - 1.0)


def test_trailing_exit_flattens() -> None:
    b = ScalpBook()
    _enter(b)
    b.observe(105, 103, 104)                 # peak -> 105, trail level 100.8
    action, r = b.observe(104, 100, 101)     # low 100 <= 100.8 -> trail exit
    assert action == "EXIT_TRAIL" and not b.in_pos
    assert r == pytest.approx((105 * 0.96) / 104 - 1.0 - _HALF)


def test_hard_stop_exit_flattens() -> None:
    b = ScalpBook()
    _enter(b)                                # entry 102 -> stop level 96.9
    action, r = b.observe(102, 95, 96)       # gap through the hard stop
    assert action == "EXIT_STOP" and not b.in_pos
    assert r == pytest.approx((102 * 0.95) / 102 - 1.0 - _HALF)


def test_time_exit_after_max_hold() -> None:
    b = ScalpBook(MomentumParams(max_hold=2))
    b.observe(100, 100, 100)
    b.observe(100, 100, 100)
    b.observe(102, 102, 102)                 # ENTER
    b.observe(103, 101.5, 102)               # bars_held=1 -> HOLD
    action, _r = b.observe(103, 101.5, 102)  # bars_held=2 >= max_hold -> EXIT_TIME
    assert action == "EXIT_TIME" and not b.in_pos


def test_reenters_cleanly_after_exit() -> None:
    b = ScalpBook()
    _enter(b)
    b.observe(102, 95, 96)                   # stop out -> flat, state reset
    assert not b.in_pos and b.entry == 0.0 and b.bars_held == 0
    # a fresh ignition arms again and re-enters
    b.observe(96, 96, 96)
    action, _r = b.observe(98, 98, 98)       # +2% over 96 with flat prior -> ENTER
    assert action == "ENTER" and b.in_pos
