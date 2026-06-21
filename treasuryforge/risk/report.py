"""Strategy assessment REPORT — the decision-grade output of the whole framework.

Turns a strategy's real return series + its DSR (+ optional purged-CV folds) into
the structured report a human reads before risking capital, with a NAMED verdict:

  REJECT: NO_EDGE              mean return not even positive
  REJECT: EDGE_IS_NOT_RELIABLE DSR below the minimum (likely overfit / too few data)
  REJECT: PATH_TOO_DANGEROUS   edge looks real but ruin / drawdown too high at any size
  ACCEPT: DEPLOY_SMALL         passes everything — but sized to DSR * fractional Kelly

Chain: returns -> mu,sigma,skew,kurt,Sharpe,Sortino,maxDD,PF
       -> DSR / purged-CV -> Kelly -> f = tail_discount * DSR * Kelly (capped)
       -> Monte-Carlo block-bootstrap ruin (naive + stressed) -> verdict.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from ..backtest.metrics import (
    _moments,
    max_drawdown,
    profit_factor,
    sharpe_ratio,
    sortino_ratio,
)
from .ruin import geometric_growth, kelly_leverage, monte_carlo_ruin


@dataclass
class AssessmentReport:
    name: str
    verdict: str
    metrics: dict = field(default_factory=dict)
    validation: dict = field(default_factory=dict)
    sizing: dict = field(default_factory=dict)
    risk: dict = field(default_factory=dict)

    @property
    def accepted(self) -> bool:
        return self.verdict.startswith("ACCEPT")

    def render(self) -> str:
        m, v, s, r = self.metrics, self.validation, self.sizing, self.risk
        L = [f"STRATEGY: {self.name}", "",
             "RAW METRICS",
             f"  mu / cycle:          {m['mu']:+.3e}",
             f"  sigma / cycle:       {m['sigma']:.3e}",
             f"  Sharpe (ann):        {m['sharpe']:.2f}",
             f"  Sortino (ann):       {m['sortino']:.2f}",
             f"  max drawdown:        {m['max_dd']:.1%}",
             f"  profit factor:       {m['profit_factor']:.2f}",
             f"  skew / kurtosis:     {m['skew']:+.2f} / {m['kurt']:.2f}",
             "",
             "VALIDATION",
             f"  DSR:                 {v['dsr']:.3f}",
             f"  DSR minimum:         {v['dsr_min']:.3f}",
             f"  purged-CV:           {v['cv']}",
             f"  regime sensitivity:  {v['regime']}",
             "",
             "SIZING",
             f"  Kelly full:          {s['kelly_full']:.1f}x",
             f"  DSR-adjusted Kelly:  {s['dsr_pct']:.0%} of Kelly",
             f"  tail discount:       {s['tail_discount']:.0%}",
             f"  final sizing:        {s['final_f']:.2f}x  (hard cap {s['cap']:.0f}x)",
             "",
             "RISK",
             f"  log growth @ f:      {r['log_growth']:+.2e}",
             f"  risk of ruin naive:  {r['p_ruin_naive']:.2%}",
             f"  risk of ruin STRESS: {r['p_ruin_stressed']:.2%}  (max {r['max_p_ruin']:.0%})",
             f"  expected DD STRESS:  {r['expected_dd']:.1%}  (max {r['max_dd']:.0%})",
             "",
             "VERDICT", f"  {self.verdict}"]
        return "\n".join(L)


def assess_and_report(
    name: str,
    returns: Sequence[float],
    *,
    dsr: float,
    periods_per_year: int | None = None,
    cv_folds: Sequence[float] | None = None,
    dsr_min: float = 0.60,
    hard_cap: float = 3.0,
    tail_discount: float = 0.5,
    max_p_ruin: float = 0.05,
    ruin_drawdown: float = 0.30,
    max_expected_drawdown: float = 0.20,
    adverse_shift: float | None = None,
    tail_shock_prob: float = 0.005,
    tail_shock_mult: float = 6.0,
    paths: int = 4000,
    seed: int = 1,
) -> AssessmentReport:
    mu, sigma, skew, kurt = _moments(returns)
    eq, acc = [], 1.0
    for x in returns:
        acc *= (1 + x)
        eq.append(acc)

    kelly_full = kelly_leverage(returns)
    final_f = min(hard_cap, tail_discount * max(dsr, 0.0) * kelly_full)
    final_f = max(final_f, 1e-6)
    if adverse_shift is None:
        adverse_shift = 2 * mu

    naive = monte_carlo_ruin(returns, leverage=final_f, ruin_drawdown=ruin_drawdown,
                             paths=paths, seed=seed)
    stressed = monte_carlo_ruin(returns, leverage=final_f, ruin_drawdown=ruin_drawdown,
                                paths=paths, seed=seed, adverse_shift=adverse_shift,
                                tail_shock_prob=tail_shock_prob, tail_shock_mult=tail_shock_mult)
    log_g = geometric_growth(returns, final_f)

    # purged-CV summary + regime sensitivity
    if cv_folds:
        all_pos = all(c > 0 for c in cv_folds)
        cv = f"{'stable' if all_pos else 'UNSTABLE'} (min fold {min(cv_folds):+.1f})"
    else:
        cv = "n/a"
    ratio = stressed.p_ruin / naive.p_ruin if naive.p_ruin > 1e-9 else float("inf")
    regime = "high" if (stressed.p_ruin > 0.05 and ratio > 3) else "moderate" if ratio > 1.5 else "low"

    # named verdict (his three cases)
    edge_real = dsr >= dsr_min
    ruin_ok = stressed.p_ruin < max_p_ruin
    dd_ok = stressed.expected_max_drawdown < max_expected_drawdown
    if mu <= 0:
        verdict = "REJECT: NO_EDGE"
    elif not edge_real:
        verdict = "REJECT: EDGE_IS_NOT_RELIABLE"
    elif not (ruin_ok and dd_ok):
        verdict = "REJECT: PATH_TOO_DANGEROUS"
    else:
        verdict = "ACCEPT: DEPLOY_SMALL"

    return AssessmentReport(
        name=name, verdict=verdict,
        metrics={"mu": mu, "sigma": sigma, "skew": skew, "kurt": kurt,
                 "sharpe": sharpe_ratio(returns, periods_per_year),
                 "sortino": sortino_ratio(returns, periods_per_year),
                 "max_dd": max_drawdown(eq), "profit_factor": profit_factor(returns)},
        validation={"dsr": dsr, "dsr_min": dsr_min, "cv": cv, "regime": regime},
        sizing={"kelly_full": kelly_full, "dsr_pct": max(dsr, 0.0) * tail_discount,
                "tail_discount": tail_discount, "final_f": final_f, "cap": hard_cap},
        risk={"log_growth": log_g, "p_ruin_naive": naive.p_ruin,
              "p_ruin_stressed": stressed.p_ruin, "max_p_ruin": max_p_ruin,
              "expected_dd": stressed.expected_max_drawdown, "max_dd": max_expected_drawdown},
    )
