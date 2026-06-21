"""Backtest the delta-neutral funding-carry strategy net of costs.

Produces a per-interval NET return series (funding accrued minus entry/exit costs),
then scores it with the same overfitting-aware gate used everywhere else
(Sharpe, Deflated Sharpe, max drawdown). Because the position is delta-neutral,
the return is the funding stream minus frictions — there is no price-direction
term, which is exactly why this strategy can clear a fee hurdle that spot
micro-arbitrage cannot.

The model is deliberately conservative: funding is accrued only while in-position,
the entry interval pays the 2-leg open cost, and the exit interval pays the 2-leg
close cost and accrues NO funding (position already closed). Real funding carry
also carries basis/liquidation risk this backtest does NOT model — treat a passing
DSR as necessary, not sufficient.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from ..signals.funding import Action, FundingCarryParams, FundingCarrySignal
from .metrics import deflated_sharpe_ratio, max_drawdown, sharpe_ratio


@dataclass
class FundingBacktestResult:
    returns: list[float] = field(default_factory=list)   # per-interval net returns
    intervals_in_position: int = 0
    n_trades: int = 0                                     # completed entries
    total_return: float = 0.0
    equity_curve: list[float] = field(default_factory=list)

    def sharpe(self, intervals_per_year: int | None = None) -> float:
        return sharpe_ratio(self.returns, intervals_per_year)

    def max_drawdown(self) -> float:
        return max_drawdown(self.equity_curve)

    def deflated_sharpe(self, n_trials: int) -> float:
        return deflated_sharpe_ratio(self.returns, n_trials)


def backtest_funding_carry(
    funding_rates: Sequence[float],
    params: FundingCarryParams,
) -> FundingBacktestResult:
    sig = FundingCarrySignal(params)
    returns: list[float] = []
    in_count = 0
    trades = 0

    for fr in funding_rates:
        action = sig.decide(fr)
        r = 0.0
        if action in (Action.ENTER, Action.HOLD):
            r += fr                      # accrue funding while holding
            in_count += 1
        if action is Action.ENTER:
            r -= params.entry_cost
            trades += 1
        elif action is Action.EXIT:
            r -= params.exit_cost        # close cost, no funding this interval
        returns.append(r)

    equity = []
    acc = 1.0
    for r in returns:
        acc *= (1.0 + r)
        equity.append(acc)

    return FundingBacktestResult(
        returns=returns,
        intervals_in_position=in_count,
        n_trades=trades,
        total_return=(equity[-1] - 1.0) if equity else 0.0,
        equity_curve=equity,
    )
