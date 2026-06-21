"""Opportunity duty cycle (v2 P6): fraction on, mean-when-on, longest streak, breakeven."""

from __future__ import annotations

import pytest

from treasuryforge.cross_venue_economics import breakeven_spread_apr
from treasuryforge.opportunity_duty_cycle import opportunity_duty_cycle


def test_fraction_and_mean_when_on():
    spreads = [0.40, 0.01, 0.30, 0.30, 0.01, 0.01]   # 3 of 6 above 0.05
    d = opportunity_duty_cycle(spreads, breakeven_apr=0.05)
    assert d.n == 6 and d.n_on == 3
    assert d.fraction == pytest.approx(0.5)
    assert d.mean_spread_when_on == pytest.approx((0.40 + 0.30 + 0.30) / 3)


def test_breakeven_is_inclusive():
    d = opportunity_duty_cycle([0.05, 0.04], breakeven_apr=0.05)
    assert d.n_on == 1                                 # 0.05 >= 0.05 counts, 0.04 doesn't


def test_max_consecutive_streak():
    # the snapshot trap: a high spread that only lasts briefly has a short streak
    spreads = [0.3, 0.0, 0.3, 0.3, 0.3, 0.0, 0.3]      # streaks: 1, 3, 1
    d = opportunity_duty_cycle(spreads, breakeven_apr=0.05)
    assert d.max_consecutive_on == 3 and d.n_on == 5


def test_never_on_is_zero():
    d = opportunity_duty_cycle([0.0, 0.01, 0.02], breakeven_apr=0.05)
    assert d.fraction == 0.0 and d.mean_spread_when_on == 0.0 and d.max_consecutive_on == 0


def test_empty_series_safe():
    d = opportunity_duty_cycle([], breakeven_apr=0.05)
    assert d.n == 0 and d.fraction == 0.0


def test_uses_economics_breakeven_floor():
    # HONEST 1y floor = amortised(~0.0037) + notional_drag(0.04) + capital_drag*ratio(0.075*1.5)
    be = breakeven_spread_apr(24 * 365)
    assert be == pytest.approx(0.0037 + 0.04 + 0.075 * 1.5, abs=0.001)
    assert be > 0.15                                      # ~15.6% floor -- the full friction stack
    # a spread must clear ~15.6% APR to net anything: most of XRP's intraday range does NOT
    d = opportunity_duty_cycle([0.20, 0.10, 0.30], breakeven_apr=be)
    assert d.n_on == 2                                    # 0.20 and 0.30 clear, 0.10 doesn't


# -- mutation-killers: frozen, exact render, inclusive boundary -----------------
def test_dutycycle_frozen():
    import dataclasses
    d = opportunity_duty_cycle([0.10, 0.02], breakeven_apr=0.05)
    with pytest.raises(dataclasses.FrozenInstanceError):
        d.n_on = 5


def test_render_exact():
    from treasuryforge.opportunity_duty_cycle import DutyCycle
    r = DutyCycle(n=10, n_on=3, breakeven_apr=0.05, mean_spread_when_on=0.12, max_consecutive_on=2)
    assert r.render() == ("duty 30% (3/10 above 5.0% APR), "
                          "mean-when-on +12.0%, max-streak 2")


def test_breakeven_boundary_inclusive():
    # spread exactly at breakeven counts as ON (>= inclusive)
    d = opportunity_duty_cycle([0.05, 0.05, 0.04], breakeven_apr=0.05)
    assert d.n_on == 2 and d.max_consecutive_on == 2 and d.mean_spread_when_on == pytest.approx(0.05)
