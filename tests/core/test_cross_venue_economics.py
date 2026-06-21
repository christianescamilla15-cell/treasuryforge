"""Cross-venue economics (v2 P1): the queen metric -- net APR on TOTAL locked capital,
amortised costs, the dual-collateral haircut, breakeven, duty-cycle scaling, AND the
full friction stack from the cold verdict (opportunity cost, settlement, downtime,
exchange tail risk, transfer delay)."""

from __future__ import annotations

import pytest

from treasuryforge.cross_venue_economics import (
    HOURS_PER_YEAR,
    CrossVenueParams,
    breakeven_spread_apr,
    cross_venue_economics,
)


def test_gross_is_not_the_return_full_friction_stack():
    # 30% gross spread, long hold (trade costs amortise to ~0), default params
    e = cross_venue_economics(0.30, hold_hours=24 * 365, params=CrossVenueParams())
    assert e.total_locked_ratio == pytest.approx(1.5)            # 2/2 * (1+0.5)
    assert e.notional_drag_apr == pytest.approx(0.04)            # hedge+orphan+settle+downtime
    assert e.capital_drag_apr == pytest.approx(0.075)           # (0.04+0.01) * 1.5
    # net funding on notional = 0.30 - ~0.0037 amortised - 0.04 drag
    assert e.net_funding_apr_on_notional == pytest.approx(0.2563, abs=0.001)
    # queen metric = 0.2563/1.5 - 0.075 capital drag = ~0.096 -> the 30% gross is ~9.6% on capital
    assert e.net_apr_on_total_capital == pytest.approx(0.0959, abs=0.001)
    assert e.net_apr_on_total_capital < e.gross_spread_apr       # ALWAYS less than gross


def test_amortised_includes_transit_opportunity_cost():
    p = CrossVenueParams()
    e = cross_venue_economics(0.30, hold_hours=HOURS_PER_YEAR, params=p)   # 1yr -> amortised==one_time
    round_trip = p.legs * (p.fee_per_leg + p.slippage_per_leg)
    transit_opp = p.transfer_delay_days / 365.0 * p.opportunity_cost_apr
    one_time = round_trip + p.transfer_friction + transit_opp
    assert e.amortised_trade_cost_apr == pytest.approx(one_time)           # 1yr hold -> amortised = one_time


def test_short_hold_costs_dominate_and_kill_it():
    # a 24h hold can't amortise the round-trip + transfer -> net deeply negative
    e = cross_venue_economics(0.30, hold_hours=24)
    assert e.amortised_trade_cost_apr > 0.30                     # cost APR dwarfs the spread
    assert e.net_apr_on_total_capital < 0 and not e.is_deployable


def test_breakeven_spread_is_materially_higher_than_fees_only():
    # the honest floor at a 30-day hold, vs the naive "fees+hedge+orphan only" floor
    p = CrossVenueParams()
    honest = breakeven_spread_apr(720, p)
    # the queen-zero floor solves net_on_capital==0:  amortised + notional_drag + capital_drag*ratio
    round_trip = p.legs * (p.fee_per_leg + p.slippage_per_leg)
    transit_opp = p.transfer_delay_days / 365.0 * p.opportunity_cost_apr
    amortised = (round_trip + p.transfer_friction + transit_opp) / (720 / HOURS_PER_YEAR)
    expected = amortised + 0.04 + 0.075 * 1.5
    assert honest == pytest.approx(expected)
    assert honest > 0.19                                         # ~19.8% APR -- brutal, and honest
    naive = amortised + p.hedge_rebalance_apr + p.orphan_leg_premium_apr   # old fees-only floor
    assert honest > naive + 0.10                                 # the cost stack raises the bar >10pp


def test_breakeven_spread_nets_to_zero_on_capital():
    # feeding exactly the break-even spread back in must give ~0 on capital (the definition)
    p = CrossVenueParams()
    be = breakeven_spread_apr(720, p)
    e = cross_venue_economics(be, hold_hours=720, params=p)
    assert e.net_apr_on_total_capital == pytest.approx(0.0, abs=1e-9)


def test_each_friction_lowers_the_queen_metric():
    base = cross_venue_economics(0.30, hold_hours=HOURS_PER_YEAR).net_apr_on_total_capital
    for field, bump in [("opportunity_cost_apr", 0.10), ("exchange_risk_apr", 0.05),
                        ("funding_settlement_drag_apr", 0.05), ("downtime_haircut_apr", 0.05)]:
        worse = cross_venue_economics(
            0.30, hold_hours=HOURS_PER_YEAR,
            params=CrossVenueParams(**{field: getattr(CrossVenueParams(), field) + bump}),
        ).net_apr_on_total_capital
        assert worse < base, f"raising {field} must lower the queen metric"


def test_opportunity_cost_is_charged_on_total_capital_not_notional():
    # +1% opportunity cost should drop net_on_capital by ~ (0.01 * locked_ratio) = 0.015
    a = cross_venue_economics(0.30, hold_hours=HOURS_PER_YEAR,
                              params=CrossVenueParams(opportunity_cost_apr=0.04))
    b = cross_venue_economics(0.30, hold_hours=HOURS_PER_YEAR,
                              params=CrossVenueParams(opportunity_cost_apr=0.05))
    # dominant charge is at the capital level: ~0.01*1.5=0.015 (a tiny extra via transit amortising)
    assert (a.net_apr_on_total_capital - b.net_apr_on_total_capital) == pytest.approx(0.015, abs=5e-5)
    assert a.net_apr_on_total_capital - b.net_apr_on_total_capital > 0.01   # NOT just notional-level


def test_breakeven_hold_hours_uses_one_time_with_transit():
    p = CrossVenueParams()
    round_trip = p.legs * (p.fee_per_leg + p.slippage_per_leg)
    transit_opp = p.transfer_delay_days / 365.0 * p.opportunity_cost_apr
    one_time = round_trip + p.transfer_friction + transit_opp
    e = cross_venue_economics(0.30, hold_hours=100, params=p)
    assert e.breakeven_hold_hours == pytest.approx(one_time / (0.30 / HOURS_PER_YEAR))


def test_duty_cycle_scaling():
    e = cross_venue_economics(0.30, hold_hours=24 * 365)
    assert e.effective_apr(0.5) == pytest.approx(e.net_apr_on_total_capital * 0.5)
    assert e.effective_apr(1.0) == pytest.approx(e.net_apr_on_total_capital)
    assert e.effective_apr(0.0) == 0.0


def test_higher_leverage_lifts_apr_on_capital_but_is_the_risk_knob():
    lo = cross_venue_economics(0.30, hold_hours=24 * 365, params=CrossVenueParams(leverage=1.0))
    hi = cross_venue_economics(0.30, hold_hours=24 * 365, params=CrossVenueParams(leverage=3.0))
    assert hi.net_apr_on_total_capital > lo.net_apr_on_total_capital   # less capital locked
    assert hi.total_locked_ratio < lo.total_locked_ratio


def test_zero_spread_infinite_breakeven():
    e = cross_venue_economics(0.0, hold_hours=100)
    assert e.breakeven_hold_hours == float("inf") and not e.is_deployable


def test_economics_is_frozen():
    import dataclasses
    e = cross_venue_economics(0.30, hold_hours=100)
    with pytest.raises(dataclasses.FrozenInstanceError):
        e.net_apr_on_total_capital = 1.0
