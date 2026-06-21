"""Net-of-cost backtest for MOMENTUM_IGNITION_V1 -- the honest gate before any capital.

Runs the momentum rule over a 1-minute OHLC series and books each trade net of the
round-trip cost. Reports the FULL distribution (win rate, avg win/loss, profit factor,
expectancy, equity, max drawdown, Sharpe), because the strategy lives or dies on the
losers -- the pumps that reverse into your entry -- not the cherry-picked winner. The
runner layers parameter-sweep DSR + sub-period stability on top of this. Pure stdlib.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .backtest.metrics import max_drawdown, profit_factor, sharpe_ratio
from .signals.momentum import MomentumParams, entry_ok, simulate_exit

Bar = tuple[float, float, float, float]   # open, high, low, close


@dataclass(frozen=True)
class MomentumResult:
    returns: list[float] = field(default_factory=list)   # per-trade net returns
    holds: list[int] = field(default_factory=list)       # bars held per trade

    @property
    def n_trades(self) -> int:
        return len(self.returns)

    @property
    def wins(self) -> list[float]:
        return [r for r in self.returns if r > 0]

    @property
    def losses(self) -> list[float]:
        return [r for r in self.returns if r <= 0]

    @property
    def win_rate(self) -> float:
        return len(self.wins) / self.n_trades if self.n_trades else 0.0

    @property
    def avg_win(self) -> float:
        return sum(self.wins) / len(self.wins) if self.wins else 0.0

    @property
    def avg_loss(self) -> float:
        return sum(self.losses) / len(self.losses) if self.losses else 0.0

    @property
    def expectancy(self) -> float:
        return sum(self.returns) / self.n_trades if self.n_trades else 0.0

    @property
    def total_net(self) -> float:
        return sum(self.returns)

    @property
    def profit_factor(self) -> float:
        return profit_factor(self.returns)

    @property
    def avg_hold(self) -> float:
        return sum(self.holds) / len(self.holds) if self.holds else 0.0

    @property
    def equity_curve(self) -> list[float]:
        eq, acc = [], 1.0
        for r in self.returns:
            acc *= 1.0 + r
            eq.append(acc)
        return eq

    @property
    def max_drawdown(self) -> float:
        return max_drawdown(self.equity_curve)

    def sharpe(self, periods_per_year: int | None = None) -> float:
        return sharpe_ratio(self.returns, periods_per_year)


def backtest_momentum(bars: list[Bar], params: MomentumParams) -> MomentumResult:
    """Scan a single coin's 1m OHLC series; one trade per ignition, non-overlapping."""
    closes = [b[3] for b in bars]
    highs = [b[1] for b in bars]
    lows = [b[2] for b in bars]
    returns: list[float] = []
    holds: list[int] = []
    i = 2
    n = len(bars)
    while i < n - 1:
        if entry_ok(closes[i - 2], closes[i - 1], closes[i], params):
            held, gross = simulate_exit(closes[i], highs[i + 1:], lows[i + 1:],
                                        closes[i + 1:], params)
            returns.append(gross - params.cost)
            holds.append(held)
            i += held + 1                    # non-overlapping: resume after the exit bar
        else:
            i += 1
    return MomentumResult(returns=returns, holds=holds)


def backtest_many(series_by_coin: dict[str, list[Bar]],
                  params: MomentumParams) -> MomentumResult:
    """Pool trades across many coins into one result (the portfolio-of-events view)."""
    returns: list[float] = []
    holds: list[int] = []
    for bars in series_by_coin.values():
        r = backtest_momentum(bars, params)
        returns.extend(r.returns)
        holds.extend(r.holds)
    return MomentumResult(returns=returns, holds=holds)
