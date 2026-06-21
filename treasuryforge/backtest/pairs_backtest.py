"""Backtest a dollar-neutral pairs trade on the spread, net of costs.

Position p in {-1,0,+1} units of the spread S = A - beta*B. PnL of holding the
spread one step = p * dS (long A / short beta*B gains as the spread widens). We
normalize PnL by the gross dollar notional (|A| + |beta*B|) so returns are a
fraction of deployed capital, and charge fee_per_leg on every unit of position
CHANGE (each unit of spread is two legs).

Point-in-time correct: the position decided after observing z at t-1 is the one
that earns over [t-1, t]; the cost of changing into it is paid at t. No look-ahead.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from ..signals.pairs import PairsSignal, rolling_zscore
from ..signals.regime import assess_spread_regime
from .metrics import deflated_sharpe_ratio, max_drawdown, sharpe_ratio


@dataclass
class PairsBacktestResult:
    returns: list[float] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)
    n_trades: int = 0
    pct_in_position: float = 0.0
    total_return: float = 0.0
    n_gated: int = 0          # entries the regime gate vetoed

    def sharpe(self, periods_per_year: int | None = None) -> float:
        return sharpe_ratio(self.returns, periods_per_year)

    def max_drawdown(self) -> float:
        return max_drawdown(self.equity_curve)

    def deflated_sharpe(self, n_trials: int) -> float:
        return deflated_sharpe_ratio(self.returns, n_trials)


def backtest_pairs(
    a: Sequence[float],
    b: Sequence[float],
    *,
    alpha: float,
    beta: float,
    window: int = 60,
    entry_z: float = 2.0,
    exit_z: float = 0.5,
    stop_z: float | None = None,
    fee_per_leg: float = 0.0005,
    regime_gate: bool = False,
    regime_window: int = 240,
    min_half_life: float = 1.0,
    max_half_life: float = 500.0,
    vr_k: int = 8,
    vr_max: float = 0.9,
    regime_level: float = 0.05,
) -> PairsBacktestResult:
    spread = [a[i] - (alpha + beta * b[i]) for i in range(len(a))]
    z = rolling_zscore(spread, window)
    notional = (sum(a) / len(a)) + abs(beta) * (sum(b) / len(b))
    if notional <= 0:
        notional = 1.0

    sig = PairsSignal(entry_z, exit_z, stop_z=stop_z)
    pos: list[int] = []
    n_gated = 0
    for t, zt in enumerate(z):
        prev = sig.position
        new = sig.update(zt)                    # pos[t] = position held after observing t
        if regime_gate and prev == 0 and new != 0:
            # an entry was just opened — only allow it if the trailing regime supports it
            ok = False
            if t + 1 >= regime_window:
                a_reg = assess_spread_regime(
                    spread[t + 1 - regime_window : t + 1],
                    level=regime_level, min_half_life=min_half_life,
                    max_half_life=max_half_life, vr_k=vr_k, vr_max=vr_max)
                ok = a_reg.tradeable
            if not ok:
                sig.position = 0                # veto the entry, stay flat
                new = 0
                n_gated += 1
        pos.append(new)

    returns: list[float] = []
    in_count = 0
    trades = 0
    for t in range(1, len(spread)):
        held = pos[t - 1]                       # held going into step t (point-in-time)
        pnl = held * (spread[t] - spread[t - 1]) / notional
        cost = fee_per_leg * abs(pos[t] - pos[t - 1])
        if pos[t] != 0 and pos[t - 1] == 0:
            trades += 1
        if held != 0:
            in_count += 1
        returns.append(pnl - cost)

    equity, acc = [], 1.0
    for r in returns:
        acc *= (1.0 + r)
        equity.append(acc)

    return PairsBacktestResult(
        returns=returns,
        equity_curve=equity,
        n_trades=trades,
        pct_in_position=in_count / len(returns) if returns else 0.0,
        total_return=(equity[-1] - 1.0) if equity else 0.0,
        n_gated=n_gated,
    )
