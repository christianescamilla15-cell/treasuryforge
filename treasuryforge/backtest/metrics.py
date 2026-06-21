"""Performance metrics, including the Deflated Sharpe Ratio.

The DSR (Bailey & Lopez de Prado) corrects a Sharpe estimate for: the number of
configurations tried (selection bias), the sample length, and the return
distribution's skew/kurtosis. It answers the question that actually matters
before risking funds: 'given that I tried N strategies, is this Sharpe better
than the best I'd expect from pure luck?' Pure stdlib via math.erf.

Conservative use (per the discovery): feed the RAW number of configurations ever
evaluated as the trial count — without an append-only log of every config tried,
DSR is a vanity metric.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

_SQRT2 = math.sqrt(2.0)
# Euler-Mascheroni and e, for the expected-max-of-N-Gaussians approximation
_EULER = 0.5772156649015329


def _phi(x: float) -> float:
    """Standard normal CDF."""
    return 0.5 * (1.0 + math.erf(x / _SQRT2))


def _phi_inv(p: float) -> float:
    """Inverse standard normal CDF (Acklam's rational approximation)."""
    if not 0.0 < p < 1.0:
        raise ValueError("p must be in (0, 1)")
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
               ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
                ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    q = p - 0.5
    r = q * q
    return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / \
           (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)


def _moments(returns: Sequence[float]) -> tuple[float, float, float, float]:
    n = len(returns)
    mean = sum(returns) / n
    var = sum((r - mean) ** 2 for r in returns) / n
    std = math.sqrt(var) if var > 0 else 0.0
    if std == 0:
        return mean, 0.0, 0.0, 3.0
    skew = sum((r - mean) ** 3 for r in returns) / n / std ** 3
    kurt = sum((r - mean) ** 4 for r in returns) / n / std ** 4
    return mean, std, skew, kurt


def sharpe_ratio(returns: Sequence[float], periods_per_year: int | None = None) -> float:
    """Non-annualized Sharpe of a per-period return series; annualized if given."""
    if len(returns) < 2:
        return 0.0
    mean, std, _, _ = _moments(returns)
    if std == 0:
        return 0.0
    sr = mean / std
    return sr * math.sqrt(periods_per_year) if periods_per_year else sr


def sortino_ratio(returns: Sequence[float], periods_per_year: int | None = None,
                  target: float = 0.0) -> float:
    """Like Sharpe but penalizes only DOWNSIDE deviation (volatility that hurts)."""
    if len(returns) < 2:
        return 0.0
    mean = sum(returns) / len(returns)
    downside = [min(r - target, 0.0) for r in returns]
    dd = math.sqrt(sum(d * d for d in downside) / len(returns))
    if dd == 0:
        return 0.0
    s = (mean - target) / dd
    return s * math.sqrt(periods_per_year) if periods_per_year else s


def profit_factor(returns: Sequence[float]) -> float:
    """Gross gains / gross losses. >1 is net-positive; the higher the more robust."""
    gains = sum(r for r in returns if r > 0)
    losses = -sum(r for r in returns if r < 0)
    return gains / losses if losses > 0 else float("inf")


def max_drawdown(equity_curve: Sequence[float]) -> float:
    """Largest peak-to-trough fractional drop (>= 0)."""
    peak = -math.inf
    mdd = 0.0
    for v in equity_curve:
        peak = max(peak, v)
        if peak > 0:
            mdd = max(mdd, (peak - v) / peak)
    return mdd


def expected_max_sharpe(n_trials: int, sr_std: float = 1.0) -> float:
    """Expected maximum of N independent N(0, sr_std^2) Sharpe estimates."""
    if n_trials <= 1:
        return 0.0
    inv = _phi_inv
    return sr_std * ((1 - _EULER) * inv(1 - 1.0 / n_trials)
                     + _EULER * inv(1 - 1.0 / (n_trials * math.e)))


def deflated_sharpe_ratio(
    returns: Sequence[float],
    n_trials: int | None = None,
    sr_benchmark: float | None = None,
    *,
    trial_sharpes: Sequence[float] | None = None,
) -> float:
    """Probability the TRUE Sharpe > benchmark, after selection-bias deflation.

    Returns a probability in [0, 1]. A common promotion gate is DSR > 0.95.

    The deflation benchmark (Bailey & Lopez de Prado) is the expected MAX Sharpe a
    lucky search would produce, which depends on BOTH the number of trials AND the
    cross-trial VARIANCE of the Sharpe estimates. The right input is
    `trial_sharpes` — the per-observation (non-annualized) Sharpe of EVERY config
    you evaluated. Passing it computes the benchmark correctly. Passing only a
    scalar `n_trials` falls back to assuming unit cross-trial variance, which is
    mis-scaled for tiny per-interval Sharpes (the known bug) — kept only for
    backward compatibility.
    """
    n = len(returns)
    if n < 2:
        return 0.0
    mean, std, skew, kurt = _moments(returns)
    if std == 0:
        return 0.0
    sr = mean / std

    if sr_benchmark is None:
        if trial_sharpes is not None and len(trial_sharpes) >= 2:
            N = len(trial_sharpes)
            mt = sum(trial_sharpes) / N
            var_t = sum((s - mt) ** 2 for s in trial_sharpes) / (N - 1)
            sr_benchmark = expected_max_sharpe(N, sr_std=math.sqrt(max(var_t, 0.0)))
        else:
            sr_benchmark = expected_max_sharpe(max(n_trials or 2, 2))   # sr_std=1 fallback

    # variance of the Sharpe estimator (Mertens), with skew/kurtosis correction
    denom = (1.0 - skew * sr + (kurt - 1.0) / 4.0 * sr * sr)
    denom = max(denom, 1e-12)
    z = (sr - sr_benchmark) * math.sqrt(n - 1) / math.sqrt(denom)
    return _phi(z)
