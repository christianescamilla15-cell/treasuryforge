"""Consultant committee -- independent supervisors that must AGREE before the broker treats
a strategy as deployable. Each consultant judges a different failure mode (a perspective-
diverse panel, not redundant copies), so a strategy passes only when it survives every
lens at once. This raises the bar above the single DSR gate: the project's losers were
killed not by one metric but by a DIFFERENT one each time (one-coin concentration, a
reversed second half, a fat-tail drawdown). The committee encodes those lessons as voters.

Pure stdlib + the project's metrics -> offline- and mutation-testable. The committee judges
DEPLOY-WORTHINESS; it does not move money.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .backtest.metrics import deflated_sharpe_ratio
from .risk.ruin import monte_carlo_ruin
from .signals.regime import variance_ratio


@dataclass(frozen=True)
class Vote:
    consultant: str
    approve: bool
    reason: str


@dataclass(frozen=True)
class CommitteeVerdict:
    approved: bool
    votes: tuple[Vote, ...]

    @property
    def vetoes(self) -> tuple[Vote, ...]:
        return tuple(v for v in self.votes if not v.approve)

    def render(self) -> str:
        return " | ".join(f"{'OK' if v.approve else 'VETO'}:{v.consultant}" for v in self.votes)


def _edge(returns: Sequence[float], _ts: Sequence[int], *, min_dsr: float = 0.60) -> Vote:
    dsr = deflated_sharpe_ratio(returns, n_trials=1)
    return Vote("edge", dsr >= min_dsr, f"DSR {dsr:.3f} vs {min_dsr:.2f}")


def _concentration(returns: Sequence[float], _ts: Sequence[int], *, max_share: float = 0.40) -> Vote:
    """The ORDI lesson: an 'edge' that is one outlier trade is not an edge. Veto if a single
    winning trade is more than `max_share` of the total positive PnL."""
    wins = [r for r in returns if r > 0]
    gross = sum(wins)
    share = max(wins) / gross if gross > 0 else 1.0
    return Vote("concentration", share <= max_share,
                f"top trade {share:.0%} of gross (max {max_share:.0%})")


def _consistency(returns: Sequence[float], _ts: Sequence[int], *, min_win: float = 0.50) -> Vote:
    """A real edge holds up out-of-sample: positive in BOTH halves of the record, with a
    win rate above min_win. Catches the 'great then reversing' curve-fit."""
    n = len(returns)
    half = n // 2
    first, second = sum(returns[:half]), sum(returns[half:])
    win = sum(1 for r in returns if r > 0) / n if n else 0.0
    ok = half >= 1 and first > 0 and second > 0 and win >= min_win
    return Vote("consistency", ok, f"halves {first:+.2%}/{second:+.2%}, win {win:.0%}")


def _drawdown(returns: Sequence[float], _ts: Sequence[int], *, max_dd: float = 0.25) -> Vote:
    """Survivable: the worst peak-to-trough of the paper equity must stay within max_dd."""
    eq = peak = 1.0
    dd = 0.0
    for r in returns:
        eq *= (1.0 + r)
        peak = max(peak, eq)
        dd = min(dd, eq / peak - 1.0)
    return Vote("drawdown", dd >= -max_dd, f"maxDD {dd:.0%} (limit {-max_dd:.0%})")


def _ruin(returns: Sequence[float], _ts: Sequence[int], *, dd_limit: float = 0.20,
          max_p_breach: float = 0.05) -> Vote:
    """SOBREVIVIR, as a voter. `_drawdown` checks the ONE realized path; this block-bootstraps
    the strategy's own returns (preserving losing streaks -- iid would understate the tail) and
    vetoes if the chance of breaching the project's survivable-drawdown band is more than a sliver.
    A real micro-tier edge should almost never resample into a >=20% drawdown."""
    if len(returns) < 2:
        return Vote("ruin", True, "too few trades for a ruin estimate")
    res = monte_carlo_ruin(returns, leverage=1.0, paths=2000, ruin_drawdown=dd_limit,
                           dd_thresholds=(dd_limit,))
    p = res.dd_threshold_probs[dd_limit]
    return Vote("ruin", p <= max_p_breach,
                f"P(maxDD>={dd_limit:.0%}) {p:.1%} (max {max_p_breach:.0%})")


def _regime(returns: Sequence[float], _ts: Sequence[int], *, recent: float = 1 / 3,
            vr_k: int = 8, vr_max: float = 0.9) -> Vote:
    """The persistence lesson: most losers died because the edge stopped working in the CURRENT
    regime. Veto if the recent window no longer pays (mean <= 0) OR if the cumulative equity
    curve is mean-reverting (VR < vr_max), indicating the edge has faded to flat noise."""
    n = len(returns)
    if n < 1:
        return Vote("regime", True, "empty returns")

    # 1. Recent mean check
    w = max(1, int(n * recent))
    tail = returns[-w:]
    m = sum(tail) / len(tail)
    if m <= 0.0:
        return Vote("regime", False, f"recent-{recent:.0%} mean {m:+.3%} <= 0")

    # 2. Variance ratio check
    if n <= vr_k + 1:
        return Vote("regime", True, f"recent mean ok; too few trades ({n}) for VR")

    eq = 1.0
    equity = [1.0]
    for r in returns:
        eq *= (1.0 + r)
        equity.append(eq)

    # Check if it has steady growth (no drawdown), which is always acceptable
    peak = 1.0
    dd = 0.0
    for eq_val in equity:
        if eq_val > peak:
            peak = eq_val
        curr_dd = 1.0 - eq_val / peak
        if curr_dd > dd:
            dd = curr_dd
    is_steady = (equity[-1] > 1.0 and dd < 0.05)

    try:
        vr = variance_ratio(equity, vr_k)
        if vr < vr_max and not is_steady:
            return Vote("regime", False, f"equity VR(k={vr_k}) {vr:.2f} < {vr_max:.2f}")
        if vr < vr_max:                       # below threshold but rescued by steady growth
            return Vote("regime", True, f"recent mean ok, VR {vr:.2f}<{vr_max:.2f} but steady growth")
        return Vote("regime", True, f"recent mean ok, VR {vr:.2f} >= {vr_max:.2f}")
    except ValueError as e:
        return Vote("regime", True, f"recent mean ok, VR skipped: {e}")


_PANEL = (_edge, _concentration, _consistency, _drawdown, _ruin, _regime)


@dataclass(frozen=True)
class Committee:
    """A unanimous panel: for real capital, ANY consultant's veto blocks the deploy."""

    def review(self, returns: Sequence[float], ts: Sequence[int]) -> CommitteeVerdict:
        votes = tuple(c(returns, ts) for c in _PANEL)
        return CommitteeVerdict(all(v.approve for v in votes), votes)
