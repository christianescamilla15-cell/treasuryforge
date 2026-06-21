"""Monte-Carlo Risk of Ruin + the strategy-level risk policy (the 5 gates).

monte_carlo_ruin answers the cruel question: with leverage f, what is the
probability of touching a terminal drawdown (or liquidation) BEFORE the edge
expresses? It resamples the strategy's OWN backtest returns with a BLOCK
bootstrap so losing streaks/regimes are preserved (an iid bootstrap dangerously
underestimates ruin), and can inject fat-tail shocks and an adverse-regime shift
to stress it further.

StrategyRiskPolicy combines the whole framework into accept/reject gates:
  1. economic edge   E[r] > cost+margin
  2. geometric growth  E[ln(1+f r)] > 0       (variance-aware, not E[r])
  3. fractional Kelly  f <= lambda * f_kelly   (and a hard cap)
  4. risk of ruin     P(ruin) < epsilon         (Monte Carlo)
  5. expected drawdown E[max DD] < D
"""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from dataclasses import dataclass


def block_bootstrap(returns: Sequence[float], n: int, block_len: int,
                    rng: random.Random) -> list[float]:
    """Resample `n` returns by concatenating random contiguous blocks, preserving
    short-range serial correlation (streaks, clustering) that iid sampling destroys."""
    rets = list(returns)
    if block_len >= len(rets):
        block_len = max(1, len(rets) // 2)
    out: list[float] = []
    hi = len(rets) - block_len
    while len(out) < n:
        start = rng.randint(0, hi)
        out.extend(rets[start:start + block_len])
    return out[:n]


@dataclass
class MonteCarloRuinResult:
    p_ruin: float                      # P(max drawdown >= ruin_drawdown)
    p_liquidation: float               # P(a single step wiped capital, 1+f*r <= 0)
    expected_max_drawdown: float
    median_final_multiple: float
    dd_threshold_probs: dict[float, float]


def monte_carlo_ruin(
    returns: Sequence[float],
    *,
    leverage: float = 1.0,
    n_steps: int | None = None,
    paths: int = 10_000,
    ruin_drawdown: float = 0.50,
    block_len: int = 10,
    adverse_shift: float = 0.0,        # subtract this from every return (stress the edge down)
    tail_shock_prob: float = 0.0,      # prob a step becomes a large adverse shock
    tail_shock_mult: float = 3.0,      # how many sigmas-ish the shock is (× the step)
    dd_thresholds: Sequence[float] = (0.20, 0.30, 0.50),
    seed: int = 0,
) -> MonteCarloRuinResult:
    rng = random.Random(seed)
    rets = list(returns)
    n = n_steps or len(rets)
    ruin = liq = 0
    dds: list[float] = []
    finals: list[float] = []
    thr_hits = dict.fromkeys(dd_thresholds, 0)

    for _ in range(paths):
        path = block_bootstrap(rets, n, block_len, rng)
        cap = peak = 1.0
        mdd = 0.0
        liquidated = False
        for r in path:
            r_eff = r - adverse_shift
            if tail_shock_prob and rng.random() < tail_shock_prob:
                r_eff = -abs(r_eff) * tail_shock_mult
            cap *= (1.0 + leverage * r_eff)
            if cap <= 0.0:
                cap = 0.0
                liquidated = True
                mdd = 1.0
                break
            if cap > peak:
                peak = cap
            dd = 1.0 - cap / peak
            if dd > mdd:
                mdd = dd
        finals.append(cap)
        dds.append(mdd)
        if liquidated:
            liq += 1
        if mdd >= ruin_drawdown:
            ruin += 1
        for t in dd_thresholds:
            if mdd >= t:
                thr_hits[t] += 1

    finals.sort()
    return MonteCarloRuinResult(
        p_ruin=ruin / paths,
        p_liquidation=liq / paths,
        expected_max_drawdown=sum(dds) / paths,
        median_final_multiple=finals[paths // 2],
        dd_threshold_probs={t: thr_hits[t] / paths for t in dd_thresholds},
    )


def _moments(returns: Sequence[float]) -> tuple[float, float]:
    n = len(returns)
    mean = sum(returns) / n
    var = sum((r - mean) ** 2 for r in returns) / n
    return mean, var


def geometric_growth(returns: Sequence[float], leverage: float) -> float:
    """Mean log-growth per step at the given leverage. -inf if any step liquidates."""
    total = 0.0
    for r in returns:
        x = 1.0 + leverage * r
        if x <= 0.0:
            return float("-inf")
        total += math.log(x)
    return total / len(returns)


def kelly_leverage(returns: Sequence[float]) -> float:
    """Growth-optimal leverage L* = E[r] / Var[r] (full Kelly; use a fraction)."""
    mean, var = _moments(returns)
    return mean / var if var > 0 else 0.0


@dataclass
class StrategyRiskPolicy:
    cost_per_cycle: float = 0.0        # fees+spread+slippage+impact already in returns? set 0
    min_edge_margin: float = 0.0       # required E[r] above cost
    min_dsr: float = 0.6               # don't deploy an edge you can't trust
    kelly_fraction: float = 0.25       # lambda: quarter-Kelly
    max_leverage: float = 10.0         # hard cap regardless of Kelly
    max_p_ruin: float = 0.01
    ruin_drawdown: float = 0.50
    max_expected_drawdown: float = 0.20

    def assess(self, returns: Sequence[float], leverage: float,
               *, dsr: float | None = None, **mc_kwargs) -> dict:
        mean, _ = _moments(returns)
        gates: list[tuple[str, bool, str]] = []

        # 0. is the edge even REAL? (deploy gate — a low DSR means likely noise)
        if dsr is not None:
            gates.append(("edge_is_real", dsr >= self.min_dsr,
                          f"DSR={dsr:.3f} vs min {self.min_dsr:.2f}"))

        # 1. economic edge
        edge_ok = mean > self.cost_per_cycle + self.min_edge_margin
        gates.append(("edge", edge_ok, f"E[r]={mean:.5f} vs cost+margin="
                      f"{self.cost_per_cycle + self.min_edge_margin:.5f}"))

        # 2. geometric growth at this leverage
        g = geometric_growth(returns, leverage)
        gates.append(("geometric_growth", g > 0, f"E[ln(1+fr)]={g:.6f}"))

        # 3. fractional Kelly + hard cap
        Lk = kelly_leverage(returns)
        cap = min(self.kelly_fraction * Lk, self.max_leverage)
        gates.append(("kelly_cap", leverage <= cap + 1e-9,
                      f"L={leverage:.2f} vs {self.kelly_fraction:.0%}*Kelly({Lk:.1f})"
                      f"={self.kelly_fraction * Lk:.2f}, hardcap={self.max_leverage}"))

        # 4. risk of ruin (Monte Carlo) and 5. expected drawdown
        mc = monte_carlo_ruin(returns, leverage=leverage, ruin_drawdown=self.ruin_drawdown,
                              **mc_kwargs)
        gates.append(("risk_of_ruin", mc.p_ruin < self.max_p_ruin,
                      f"P(DD>={self.ruin_drawdown:.0%})={mc.p_ruin:.2%} vs {self.max_p_ruin:.0%}"))
        gates.append(("expected_drawdown", mc.expected_max_drawdown < self.max_expected_drawdown,
                      f"E[maxDD]={mc.expected_max_drawdown:.2%} vs {self.max_expected_drawdown:.0%}"))

        accepted = all(ok for _, ok, _ in gates)
        return {
            "accepted": accepted,
            "verdict": "accept" if accepted else "reject: "
                       + ",".join(name for name, ok, _ in gates if not ok),
            "gates": gates,
            "kelly_leverage": Lk,
            "monte_carlo": mc,
        }
