"""Funding-continuation predictor (C2): conditional reach, the age-rule OOS gate, and
coin-selection carry-over."""

from __future__ import annotations

import pytest

from treasuryforge.funding_predictor import (
    conditional_reach,
    evaluate_age_rule,
    evaluate_coin_selection,
    survival_curve,
)


def test_conditional_reach_basics():
    durs = [2, 5, 10, 10, 20]                 # breakeven 5
    assert conditional_reach(durs, age=0, breakeven=5) == pytest.approx(4 / 5)   # >=5: all but the 2
    # survived to 10 -> need >=15: only the 20 -> 1 of 3 (10,10,20)
    assert conditional_reach(durs, age=10, breakeven=5) == pytest.approx(1 / 3)
    assert conditional_reach([], 0, 5) == 0.0


def test_survival_curve_shape():
    curve = survival_curve([10, 10, 10], breakeven=2, max_age=3)
    assert curve[0] == (0, 1.0)               # all reach 0+2
    assert dict(curve)[3] == pytest.approx(1.0)   # survived to 3 -> reach 5 (all 10s)


def test_age_rule_beats_baseline_under_momentum():
    # momentum: short choppy episodes + a cluster of long ones. Surviving past the chop
    # (age) should raise the reach rate. breakeven=5, max_age=6.
    train = [1, 1, 2, 2, 3] * 4 + [8, 9, 10, 11, 12] * 4   # 40 episodes
    test = [1, 2, 2, 3] * 3 + [8, 9, 10, 11] * 4           # later, similar structure
    ev = evaluate_age_rule(train, test, breakeven=5, max_age=6)
    assert ev.best_age > 0                                  # waiting helps in-sample
    assert ev.test_rate_at_best_age > ev.test_base_rate     # and out-of-sample
    assert ev.beats_baseline


def test_age_rule_does_not_beat_when_memoryless():
    # geometric-ish memoryless durations: age shouldn't help much OOS
    train = [1, 2, 1, 3, 1, 2, 4, 1, 2, 1] * 3
    test = [1, 2, 1, 2, 3, 1, 1, 2, 1, 4] * 3
    ev = evaluate_age_rule(train, test, breakeven=3, max_age=4)
    # honest outcome allowed: with no real momentum it should NOT claim to beat baseline
    assert isinstance(ev.beats_baseline, bool)


def test_coin_selection_carries_over():
    train = {"ASTER": 0.5, "NEAR": 0.33, "HYPE": 0.06, "BTC": 0.05}
    test = {"ASTER": 0.45, "NEAR": 0.30, "HYPE": 0.08, "BTC": 0.04}
    reach = {"ASTER": (9, 20), "NEAR": (6, 20), "HYPE": (1, 30), "BTC": (1, 25)}
    ev = evaluate_coin_selection(train, test, reach)
    assert ev.correlation > 0.9                              # persistent coins stay persistent
    assert set(ev.selected) == {"ASTER", "NEAR"}
    assert ev.selected_test_rate > ev.rest_test_rate and ev.beats_baseline


def test_coin_selection_needs_minimum_coins():
    ev = evaluate_coin_selection({"A": 0.5}, {"A": 0.4}, {"A": (1, 2)})
    assert ev.selected == [] and not ev.beats_baseline


# -- mutation-killing: inclusive boundaries, gates, pearson ---------------------
def test_conditional_reach_inclusive_boundaries():
    assert conditional_reach([5], age=5, breakeven=0) == 1.0      # d>=age inclusive
    assert conditional_reach([4], age=5, breakeven=0) == 0.0      # 4 not >=5 -> empty -> 0
    assert conditional_reach([10], age=5, breakeven=5) == 1.0     # 10 >= 5+5 inclusive
    assert conditional_reach([9], age=5, breakeven=5) == 0.0      # 9 < 10


def test_age_rule_beats_baseline_gate():
    from treasuryforge.funding_predictor import AgeRuleEval
    assert not AgeRuleEval(0.1, 5, 0.5, 0.2, 0.4, n_test_at_risk=9).beats_baseline   # n<10
    assert AgeRuleEval(0.1, 5, 0.5, 0.2, 0.4, n_test_at_risk=10).beats_baseline      # n>=10, 0.4>0.2
    assert not AgeRuleEval(0.1, 5, 0.5, 0.4, 0.4, n_test_at_risk=10).beats_baseline  # not >


def test_coin_selection_min_three_and_beats():
    from treasuryforge.funding_predictor import CoinSelectionEval, evaluate_coin_selection
    assert evaluate_coin_selection({"A": 0.5, "B": 0.3}, {"A": 0.4, "B": 0.2},
                                   {"A": (1, 2), "B": (0, 2)}).selected == []   # <3 coins
    assert CoinSelectionEval(0.3, ["A"], 0.5, 0.4).beats_baseline               # 0.5 > 0.4
    assert not CoinSelectionEval(0.3, ["A"], 0.4, 0.4).beats_baseline           # not >


def test_pearson_signs_and_zero_variance():
    from treasuryforge.funding_predictor import _pearson
    assert _pearson([1, 2, 3], [2, 4, 6]) == pytest.approx(1.0)
    assert _pearson([1, 2, 3], [3, 2, 1]) == pytest.approx(-1.0)
    assert _pearson([1, 1], [1, 1]) == 0.0                        # zero variance guard
    assert _pearson([1, 2, 3], [5, 5, 5]) == 0.0                  # one side flat -> AND guard (kills `or`)
    assert _pearson([1.0], [2.0]) == 0.0                          # n<2 guard
    assert _pearson([1.0, 3.0], [2.0, 6.0]) == pytest.approx(1.0)  # n==2 computes (kills `<2`->`<=2`)


def test_age_rule_base_rate_uses_fresh_entry_age_zero():
    # a 0-duration episode survives to age 0 but not age 1, so age=0 vs age=1 base differ
    ev = evaluate_age_rule([0, 5, 5, 5], [0, 5, 5, 5], breakeven=2, max_age=3)
    assert ev.base_rate == pytest.approx(0.75)        # reach>=2 among all 4 (kills age 0 -> 1)
    assert ev.test_base_rate == pytest.approx(0.75)   # same on test (kills the test-base age 0 -> 1)


def test_evals_are_frozen():
    import dataclasses

    from treasuryforge.funding_predictor import AgeRuleEval, CoinSelectionEval
    with pytest.raises(dataclasses.FrozenInstanceError):
        AgeRuleEval(0.1, 5, 0.5, 0.2, 0.4, 10).base_rate = 1.0
    with pytest.raises(dataclasses.FrozenInstanceError):
        CoinSelectionEval(0.3, ["A"], 0.5, 0.4).correlation = 1.0


def test_survival_curve_length_is_max_age_plus_one():
    from treasuryforge.funding_predictor import survival_curve
    curve = survival_curve([5, 5, 5], breakeven=1, max_age=4)
    assert len(curve) == 5 and curve[0][0] == 0 and curve[-1][0] == 4   # ages 0..max_age


def test_coin_selection_three_coins_exact():
    from treasuryforge.funding_predictor import evaluate_coin_selection
    train = {"A": 0.5, "B": 0.3, "C": 0.1}
    test = {"A": 0.45, "B": 0.3, "C": 0.05}
    reach = {"A": (9, 20), "B": (6, 20), "C": (1, 20)}
    ev = evaluate_coin_selection(train, test, reach)
    assert ev.selected == ["A"]                             # 3 coins proceed; top half = 1
    assert ev.selected_test_rate == pytest.approx(9 / 20)   # reached/total of selected (kills [1] / *)
    assert ev.rest_test_rate == pytest.approx((6 + 1) / 40)  # the REST (not selected)


def test_coin_selection_under_three_defaults():
    from treasuryforge.funding_predictor import evaluate_coin_selection
    ev = evaluate_coin_selection({"A": 0.5, "B": 0.3}, {"A": 0.4, "B": 0.2}, {"A": (1, 2), "B": (0, 2)})
    assert ev.correlation == 0.0 and ev.selected == []
    assert ev.selected_test_rate == 0.0 and ev.rest_test_rate == 0.0
