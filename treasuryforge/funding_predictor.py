"""Funding-continuation predictor (Roadmap C2) — beat the base rate, or be discarded.

The C baseline showed only 6-50% of high-funding episodes last to break-even. A carry
edge therefore requires SELECTING the episodes that will. C2 tests the two simplest
selectors, each held to the honest bar: does it beat the unconditional base rate
OUT-OF-SAMPLE? If not, it is discarded (no complex model is built on a losing simple one).

1. Survival momentum: given an episode has ALREADY lasted `age` hours, the relevant
   question is whether it lasts `age + breakeven` (you collect from entry to the end,
   so you need `breakeven` MORE hours). conditional_reach(age) measures exactly that.
   The rule "enter only after age N" wins iff conditional_reach rises with age.
2. Coin selection: trade only coins whose historical break-even rate is high — tested
   by whether a coin's train-period rate predicts its test-period rate.

Everything is evaluated on a time-ordered train/test split (the test segment is strictly
later, an embargo against leakage). Pure, stdlib, offline-testable.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


def conditional_reach(durations: Sequence[int], age: int, breakeven: int) -> float:
    """Among episodes that survived to `age`, the fraction that reach `age + breakeven`
    (i.e. last `breakeven` MORE hours). age=0 (or 1) is the fresh-entry base rate."""
    at_risk = [d for d in durations if d >= age]
    if not at_risk:
        return 0.0
    return sum(1 for d in at_risk if d >= age + breakeven) / len(at_risk)


def survival_curve(durations: Sequence[int], breakeven: int, max_age: int) -> list[tuple[int, float]]:
    return [(age, conditional_reach(durations, age, breakeven)) for age in range(0, max_age + 1)]


@dataclass(frozen=True)
class AgeRuleEval:
    base_rate: float            # fresh-entry reach rate, in-sample (train)
    best_age: int               # age that maximised conditional_reach on train
    train_rate: float
    test_base_rate: float       # fresh-entry reach rate on test
    test_rate_at_best_age: float
    n_test_at_risk: int         # test episodes surviving to best_age (sample behind the OOS number)

    @property
    def beats_baseline(self) -> bool:
        # OOS, the rule must beat the OOS fresh-entry rate AND rest on real sample
        return self.n_test_at_risk >= 10 and self.test_rate_at_best_age > self.test_base_rate


def evaluate_age_rule(train: Sequence[int], test: Sequence[int], *, breakeven: int,
                      max_age: int) -> AgeRuleEval:
    base = conditional_reach(train, 0, breakeven)
    best_age, train_rate = 0, base
    for age in range(1, max_age + 1):
        r = conditional_reach(train, age, breakeven)
        if r > train_rate:
            best_age, train_rate = age, r
    test_at_risk = [d for d in test if d >= best_age]
    return AgeRuleEval(base_rate=base, best_age=best_age, train_rate=train_rate,
                       test_base_rate=conditional_reach(test, 0, breakeven),
                       test_rate_at_best_age=conditional_reach(test, best_age, breakeven),
                       n_test_at_risk=len(test_at_risk))


@dataclass(frozen=True)
class CoinSelectionEval:
    correlation: float          # train-rate vs test-rate across coins (does it carry over?)
    selected: list[str]         # coins above the train-rate median
    selected_test_rate: float   # their pooled test reach rate
    rest_test_rate: float       # everyone else's

    @property
    def beats_baseline(self) -> bool:
        return self.selected_test_rate > self.rest_test_rate


def evaluate_coin_selection(per_coin_train: dict[str, float], per_coin_test: dict[str, float],
                            per_coin_test_reach: dict[str, tuple[int, int]]) -> CoinSelectionEval:
    """per_coin_train/test: each coin's break-even reach rate in that window.
    per_coin_test_reach: (n_reached, n_episodes) on test, to pool selected vs rest honestly."""
    coins = [c for c in per_coin_train if c in per_coin_test]
    if len(coins) < 3:
        return CoinSelectionEval(0.0, [], 0.0, 0.0)
    tr = [per_coin_train[c] for c in coins]
    te = [per_coin_test[c] for c in coins]
    corr = _pearson(tr, te)
    ranked = sorted(coins, key=lambda c: per_coin_train[c], reverse=True)
    selected = ranked[: max(1, len(ranked) // 2)]      # the top half by train reach rate
    sel_n = sum(per_coin_test_reach[c][0] for c in selected)
    sel_d = sum(per_coin_test_reach[c][1] for c in selected)
    rest_n = sum(per_coin_test_reach[c][0] for c in coins if c not in selected)
    rest_d = sum(per_coin_test_reach[c][1] for c in coins if c not in selected)
    return CoinSelectionEval(correlation=corr, selected=selected,
                             selected_test_rate=sel_n / sel_d if sel_d else 0.0,
                             rest_test_rate=rest_n / rest_d if rest_d else 0.0)


def _pearson(a: Sequence[float], b: Sequence[float]) -> float:
    n = len(a)
    if n < 2:
        return 0.0
    ma, mb = sum(a) / n, sum(b) / n
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    va = sum((x - ma) ** 2 for x in a) ** 0.5
    vb = sum((y - mb) ** 2 for y in b) ** 0.5
    return cov / (va * vb) if va > 0 and vb > 0 else 0.0
