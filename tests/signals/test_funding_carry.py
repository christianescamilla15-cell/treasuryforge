"""Funding-carry signal + delta-neutral backtest through the overfitting gate."""

from __future__ import annotations

import pytest

from treasuryforge.backtest import backtest_funding_carry
from treasuryforge.signals.funding import (
    Action,
    FundingCarryParams,
    FundingCarrySignal,
    HyperliquidFundingFeed,
    annualize,
)


def params(**over) -> FundingCarryParams:
    base = dict(enter_rate=0.0001, exit_rate=0.00002, fee_per_leg=0.0005, legs_round_trip=4)
    base.update(over)
    return FundingCarryParams(**base)


def test_age_rule_delays_entry_until_episode_survives():
    s = FundingCarrySignal(params(), min_age=3)
    assert s.decide(0.0002) is Action.FLAT      # episode age 1 < 3 -> wait
    assert s.decide(0.0002) is Action.FLAT      # age 2 < 3 -> wait
    assert s.decide(0.0002) is Action.ENTER     # age 3 >= 3 -> enter
    assert s.decide(0.0002) is Action.HOLD
    assert s.decide(0.0) is Action.EXIT         # funding gone -> exit


def test_age_resets_if_episode_dies_before_age():
    s = FundingCarrySignal(params(), min_age=3)
    assert s.decide(0.0002) is Action.FLAT      # age 1
    assert s.decide(0.0) is Action.FLAT         # episode died (age->0), never entered
    assert s.decide(0.0002) is Action.FLAT      # fresh episode age 1 again
    assert s.decide(0.0002) is Action.FLAT      # age 2
    assert s.decide(0.0002) is Action.ENTER     # age 3 -> enter


def test_min_age_zero_is_plain_hysteresis():
    s = FundingCarrySignal(params(), min_age=0)
    assert s.decide(0.0002) is Action.ENTER     # enters immediately (age 1 >= max(0,1))


# -- signal decision logic ---------------------------------------------------
def test_enters_on_high_funding_holds_then_exits_on_low():
    sig = FundingCarrySignal(params(enter_rate=0.0001, exit_rate=0.00002))
    assert sig.decide(0.00005) is Action.FLAT      # below enter -> stay out
    assert sig.decide(0.0002) is Action.ENTER      # above enter -> open
    assert sig.decide(0.00015) is Action.HOLD      # still above exit -> hold
    assert sig.decide(0.00001) is Action.EXIT      # below exit -> close
    assert sig.decide(0.00001) is Action.FLAT      # stays out


def test_hysteresis_required():
    with pytest.raises(ValueError):
        FundingCarryParams(enter_rate=0.0001, exit_rate=0.0002, fee_per_leg=0.0005)


def test_round_trip_cost_and_breakeven():
    p = params(enter_rate=0.0001, fee_per_leg=0.0005, legs_round_trip=4)
    assert p.round_trip_cost == pytest.approx(0.002)            # 4 * 0.0005
    # need 0.002 / 0.0001 = 20 intervals of funding just to break even
    assert p.breakeven_intervals() == pytest.approx(20.0)


def test_expected_net_carry_sign():
    sig = FundingCarrySignal(params(enter_rate=0.0001, fee_per_leg=0.0005))
    # holding 10 intervals at 0.0001 = 0.001 funding < 0.002 cost -> negative
    assert sig.expected_net_carry(0.0001, 10) < 0
    # holding 40 intervals -> 0.004 > 0.002 cost -> positive
    assert sig.expected_net_carry(0.0001, 40) > 0


def test_annualize():
    # 0.0001 per hour * 24 * 365 ~ 0.876 (87.6% APR, the volatile headline)
    assert annualize(0.0001, 24 * 365) == pytest.approx(0.876)


# -- backtest economics ------------------------------------------------------
def test_sustained_high_funding_is_net_positive_after_costs():
    rates = [0.0003] * 200                                      # strong, stable funding
    res = backtest_funding_carry(rates, params())
    assert res.n_trades == 1                                    # one entry, holds throughout
    assert res.total_return > 0                                 # funding beats the 2-leg entry cost
    assert res.intervals_in_position == 200


def test_funding_below_breakeven_loses_money():
    # tiny funding that never covers the round-trip cost, toggling in/out -> bleeds
    rates = [0.00011, 0.000005] * 50                            # whipsaw around the bands
    res = backtest_funding_carry(rates, params())
    assert res.total_return < 0                                 # cost-churn dominates
    assert res.n_trades >= 2


def test_flat_zero_funding_does_nothing():
    res = backtest_funding_carry([0.0] * 100, params())
    assert res.n_trades == 0 and res.total_return == pytest.approx(0.0)


def test_no_price_direction_term_only_funding_minus_cost():
    # delta-neutral: return must equal accrued funding minus the entry cost exactly
    rates = [0.0003] * 10
    p = params()
    res = backtest_funding_carry(rates, p)
    expected = sum(rates) - p.entry_cost                        # 10*0.0003 - 0.001
    assert sum(res.returns) == pytest.approx(expected)


def test_backtest_runs_through_dsr_gate():
    # a decent stable carry should yield a positive Sharpe; DSR is a probability
    rates = [0.0002 + (0.00005 if i % 2 else -0.00005) for i in range(300)]
    res = backtest_funding_carry(rates, params())
    assert res.sharpe() > 0
    dsr = res.deflated_sharpe(n_trials=50)
    assert 0.0 <= dsr <= 1.0


# -- keyless feed (offline, injected transport) ------------------------------
def test_feed_parses_current_funding():
    fake = lambda body: [
        {"universe": [{"name": "BTC"}, {"name": "ETH"}]},
        [{"funding": "0.0000125"}, {"funding": "0.0000300"}],
    ]
    feed = HyperliquidFundingFeed(fake)
    assert feed.current_funding("BTC") == pytest.approx(0.0000125)
    assert feed.current_funding("ETH") == pytest.approx(0.00003)


def test_feed_parses_history():
    fake = lambda body: [{"fundingRate": "0.0001"}, {"fundingRate": "-0.00002"}]
    feed = HyperliquidFundingFeed(fake)
    assert feed.funding_history("BTC") == [pytest.approx(0.0001), pytest.approx(-0.00002)]
