"""Carry screener (A3): the cost-gate that kills churn, verdict escalation, and the
selection-bias-honest ranking."""

from __future__ import annotations

import pytest

from treasuryforge.carry_screener import (
    HOURS_PER_YEAR,
    CarryOpportunity,
    ScreenParams,
    Verdict,
    screen,
    screen_coin,
)


# -- mutation-killing: properties, exact arithmetic, every boundary, defaults ----
def _opp(funding=0.0003, expected_funding=0.0024, expected_convergence=0.0002,
         round_trip=0.0010, net_edge=0.0016):
    return CarryOpportunity(coin="X", funding_apr=funding * HOURS_PER_YEAR,
                            expected_funding=expected_funding, expected_convergence=expected_convergence,
                            round_trip_cost=round_trip, net_edge=net_edge, verdict=Verdict.PAPER)


def test_opportunity_properties_exact():
    o = _opp()
    assert o.gross == pytest.approx(0.0024 + 0.0002)             # expected_funding + convergence
    assert o.net_edge_bps == pytest.approx(0.0016 * 1e4)         # *1e4
    assert o.cost_ratio == pytest.approx((o.gross - 0.0016) / o.gross)


def test_funding_apr_uses_hours_per_year():
    o = screen_coin("E", funding=0.00001, premium=0.0, spread=0.0001, vol=0.001)
    assert HOURS_PER_YEAR == 24 * 365
    assert o.funding_apr == pytest.approx(0.00001 * 24 * 365)


def test_funding_pred_overrides_current():
    o = screen_coin("E", funding=0.00001, premium=0.0, spread=0.0001, vol=0.002, funding_pred=0.0004)
    p = ScreenParams()
    assert o.expected_funding == pytest.approx(0.0004 * p.hold_hours)   # uses pred, not current


def test_net_subtracts_round_trip_and_liq_buffer():
    p = ScreenParams(hold_hours=8, liq_buffer=0.00005)
    o = screen_coin("E", funding=0.0004, premium=0.0002, spread=0.0001, vol=0.002, params=p)
    assert o.net_edge == pytest.approx(o.gross - o.round_trip_cost - 0.00005)


def test_dsr_and_days_boundaries_inclusive():
    base = dict(funding=0.0004, premium=0.0002, spread=0.0001, vol=0.002)
    assert screen_coin("C", **base, dsr=0.60, shadow_days=30).verdict is Verdict.LIVE_ELIGIBLE  # == gates
    assert screen_coin("C", **base, dsr=0.60, shadow_days=29).verdict is Verdict.MICRO_ELIGIBLE  # <30
    assert screen_coin("C", **base, dsr=0.60, shadow_days=7).verdict is Verdict.MICRO_ELIGIBLE   # ==7
    assert screen_coin("C", **base, dsr=0.60, shadow_days=6).verdict is Verdict.PAPER            # <7
    assert screen_coin("C", **base, dsr=0.59, shadow_days=40).verdict is Verdict.PAPER           # dsr<0.60


def test_default_screen_params_pinned():
    p = ScreenParams()
    assert p.hold_hours == 8 and p.margin_bps == 0.0001 and p.liq_buffer == 0.00005
    assert p.max_cost_ratio == 0.35 and p.legs == 4


def test_screen_empty_universe():
    assert screen([]) == []


def test_verdict_enum_values_exact():
    assert Verdict.NO_TRADE.value == "NO_TRADE"
    assert Verdict.WATCH.value == "WATCH"
    assert Verdict.PAPER.value == "PAPER"
    assert Verdict.MICRO_ELIGIBLE.value == "MICRO_ELIGIBLE"
    assert Verdict.LIVE_ELIGIBLE.value == "LIVE_ELIGIBLE"


def test_params_and_opp_are_frozen():
    import dataclasses
    with pytest.raises(dataclasses.FrozenInstanceError):
        ScreenParams().hold_hours = 1
    with pytest.raises(dataclasses.FrozenInstanceError):
        _opp().net_edge = 1.0


def test_cost_ratio_inf_when_no_gross():
    o = CarryOpportunity("X", funding_apr=0.0, expected_funding=0.0, expected_convergence=0.0,
                         round_trip_cost=0.001, net_edge=-0.001, verdict=Verdict.NO_TRADE)
    assert o.cost_ratio == float("inf")              # gross 0 -> inf (kills the float("inf") mutation)


def test_dsr_without_shadow_days_is_paper_not_crash():
    # dsr given but shadow_days None -> `or` returns PAPER; `and` would crash on None>=30
    o = screen_coin("X", funding=0.0004, premium=0.0002, spread=0.0001, vol=0.002, dsr=0.65)
    assert o.verdict is Verdict.PAPER


def test_screen_passes_through_every_key():
    cand = [{"coin": "A", "funding": 0.0004, "premium": 0.0002, "spread": 0.0001, "vol": 0.002,
             "funding_pred": 0.0005, "dsr": 0.65, "shadow_days": 40}]
    o = screen(cand)[0]
    assert o.expected_funding == pytest.approx(0.0005 * ScreenParams().hold_hours)  # funding_pred key
    assert o.expected_convergence == pytest.approx(0.0002)            # premium key
    assert o.verdict is Verdict.LIVE_ELIGIBLE                         # dsr + shadow_days keys


def test_screen_premium_defaults_to_zero_not_one():
    o = screen([{"coin": "B", "funding": 0.0004, "spread": 0.0001, "vol": 0.002}])[0]
    assert o.expected_convergence == 0.0             # missing premium -> 0.0 default (kills ->1.0)


def test_negative_net_is_no_trade_the_cost_gate():
    # tiny funding, wide spread / low vol -> round-trip cost dwarfs the carry
    o = screen_coin("X", funding=0.000002, premium=0.0, spread=0.0008, vol=0.0003)
    assert o.net_edge < 0 and o.verdict is Verdict.NO_TRADE      # this is the anti-churn gate


def test_realistic_hl_funding_short_hold_is_no_trade():
    # the honest finding: ~10% APR funding (0.0000125/hr) over an 8h hold = ~1bp of carry,
    # nowhere near the ~10bp four-leg round-trip. Short holds CANNOT cover the cost = churn.
    o = screen_coin("ETH", funding=0.0000125, premium=0.0, spread=0.0002, vol=0.001)
    assert o.verdict is Verdict.NO_TRADE


def test_strong_carry_is_paper_worthy():
    # fat funding over the hold, tight spread, decent vol -> net edge survives the costs
    o = screen_coin("ETH", funding=0.0004, premium=0.0002, spread=0.0001, vol=0.002)
    assert o.net_edge > 0 and o.verdict is Verdict.PAPER
    assert o.gross == pytest.approx(0.0004 * 8 + 0.0002)


def test_convergence_only_counted_in_contango():
    contango = screen_coin("A", funding=0.00003, premium=0.0004, spread=0.0001, vol=0.001)
    backward = screen_coin("B", funding=0.00003, premium=-0.0004, spread=0.0001, vol=0.001)
    assert contango.expected_convergence == pytest.approx(0.0004)
    assert backward.expected_convergence == 0.0                  # short-perp can't capture it


def test_verdict_escalates_only_with_risk_gates():
    base = dict(funding=0.0004, premium=0.0002, spread=0.0001, vol=0.002)
    assert screen_coin("C", **base).verdict is Verdict.PAPER                      # no gates given
    assert screen_coin("C", **base, dsr=0.65, shadow_days=10).verdict is Verdict.MICRO_ELIGIBLE
    assert screen_coin("C", **base, dsr=0.65, shadow_days=40).verdict is Verdict.LIVE_ELIGIBLE
    assert screen_coin("C", **base, dsr=0.40, shadow_days=40).verdict is Verdict.PAPER  # DSR fails


def test_thin_positive_edge_is_only_watch():
    # net edge positive but costs eat > max_cost_ratio of gross -> WATCH, not PAPER
    o = screen_coin("D", funding=0.00016, premium=0.0, spread=0.0001, vol=0.002)
    assert o.net_edge > 0 and o.cost_ratio > 0.35 and o.verdict is Verdict.WATCH


def test_screen_ranks_by_net_edge_and_preserves_universe_size():
    universe = [
        {"coin": "HI", "funding": 0.00006, "premium": 0.0003, "spread": 0.0001, "vol": 0.001},
        {"coin": "LO", "funding": 0.000001, "premium": 0.0, "spread": 0.0008, "vol": 0.0003},
        {"coin": "MID", "funding": 0.00003, "premium": 0.0001, "spread": 0.0002, "vol": 0.0008},
    ]
    ranked = screen(universe)
    assert [o.coin for o in ranked] == ["HI", "MID", "LO"]       # by net edge
    assert len(ranked) == 3                                       # = n_trials for downstream DSR
    assert ranked[-1].verdict is Verdict.NO_TRADE                # the loser is cost-gated out
