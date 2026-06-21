"""Engle-Granger cointegration: the rigorous core of a pairs strategy.

Two non-stationary price series A, B are COINTEGRATED if some linear combination
spread = A - beta*B is stationary (mean-reverting). Engle-Granger is a 2-step test:
  1. OLS hedge ratio: regress A on B -> beta (and intercept).
  2. ADF test on the residual spread: is it stationary (rejects a unit root)?

If the spread is stationary, it reverts to a mean — which is the only thing that
makes a pairs trade work. The half-life says how FAST it reverts (too slow = the
edge decays before you can hold it; too fast = eaten by costs).

Honest caveat the research nailed: most pairs do NOT cointegrate (you will see
this live), and the ones that do give a MODEST Sharpe (~0.69), not the 1.5-3.0
that gets marketed. ADF critical values here are the standard asymptotic
(constant, no trend) values — fine for learning, slightly optimistic vs the exact
Engle-Granger (Phillips-Ouliaris) cointegration critical values.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from .linalg import ols

# ADF critical values for a PLAIN unit-root test (constant, no trend; asymptotic).
ADF_CRIT = {0.01: -3.43, 0.05: -2.86, 0.10: -2.57}

# Engle-Granger COINTEGRATION critical values (Phillips-Ouliaris / MacKinnon, N=2
# variables, constant, no trend). These are MORE NEGATIVE than the plain ADF ones
# because the spread is the residual of an ESTIMATED regression — using the plain
# ADF values here is the classic SPURIOUS-cointegration bug (independent random
# walks falsely test as cointegrated).
COINT_CRIT = {0.01: -3.90, 0.05: -3.34, 0.10: -3.04}


def hedge_ratio(a: Sequence[float], b: Sequence[float]) -> tuple[float, float]:
    """OLS of a on b with intercept: a = alpha + beta*b. Returns (alpha, beta)."""
    X = [[1.0, bi] for bi in b]
    res = ols(X, list(a))
    return res.coef[0], res.coef[1]


def adf_test(y: Sequence[float], lags: int = 1) -> tuple[float, dict[float, float]]:
    """Augmented Dickey-Fuller. Regress dy_t on [const, y_{t-1}, dy_{t-1..lags}].
    The ADF stat is the t-stat on the y_{t-1} coefficient; MORE NEGATIVE than the
    critical value => reject the unit root => stationary."""
    y = list(y)
    dy = [y[i] - y[i - 1] for i in range(1, len(y))]
    start = lags
    rows, target = [], []
    for t in range(start, len(dy)):
        row = [1.0, y[t]]                      # const + level y_{t-1} (y index aligns: dy[t] uses y[t])
        for L in range(1, lags + 1):
            row.append(dy[t - L])
        rows.append(row)
        target.append(dy[t])
    res = ols(rows, target)
    adf_stat = res.tstat(1)                    # coefficient on y_{t-1}
    return adf_stat, ADF_CRIT


def half_life(spread: Sequence[float]) -> float:
    """Mean-reversion half-life from an AR(1) fit: s_t = c + phi*s_{t-1}.
    half_life = -ln(2)/ln(phi). inf if not mean-reverting."""
    s = list(spread)
    X = [[1.0, s[i - 1]] for i in range(1, len(s))]
    y = [s[i] for i in range(1, len(s))]
    phi = ols(X, y).coef[1]
    if not (0.0 < phi < 1.0):
        return float("inf")
    return -math.log(2) / math.log(phi)


@dataclass
class CointegrationResult:
    cointegrated: bool
    alpha: float
    beta: float
    adf_stat: float
    crit_5: float
    half_life: float
    spread: list[float]


def engle_granger(a: Sequence[float], b: Sequence[float], *, lags: int = 1,
                  level: float = 0.05) -> CointegrationResult:
    alpha, beta = hedge_ratio(a, b)
    spread = [a[i] - (alpha + beta * b[i]) for i in range(len(a))]
    adf_stat, _ = adf_test(spread, lags=lags)
    crit_5 = COINT_CRIT[level]              # cointegration crit, NOT plain ADF
    return CointegrationResult(
        cointegrated=adf_stat < crit_5,
        alpha=alpha, beta=beta, adf_stat=adf_stat, crit_5=crit_5,
        half_life=half_life(spread), spread=spread,
    )
