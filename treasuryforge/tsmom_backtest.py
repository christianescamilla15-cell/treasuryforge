"""Continuous-position backtest for TSMOM_VOLSCALED_V2.

Unlike the event-driven momentum backtest, a trend strategy holds a CONTINUOUS position
rebalanced every period, so the honest object is the per-period return SERIES of that
position, net of turnover cost (cost x |Δposition|). From the series we get the annualised
Sharpe -- the metric the runner deflates (DSR) across the parameter sweep. Pure stdlib.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .backtest.metrics import max_drawdown, sharpe_ratio
from .signals.tsmom import TsmomParams, target_position

Bar = tuple[float, float, float, float]   # open, high, low, close


@dataclass(frozen=True)
class TsmomResult:
    returns: list[float] = field(default_factory=list)     # per-period strategy returns (net)
    positions: list[float] = field(default_factory=list)   # the held position each period

    @property
    def n_periods(self) -> int:
        return len(self.returns)

    @property
    def total_net(self) -> float:
        eq = 1.0
        for r in self.returns:
            eq *= 1.0 + r
        return eq - 1.0

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

    @property
    def turnover(self) -> float:
        """Average |Δposition| per period -- how much cost the strategy churns."""
        if len(self.positions) < 2:
            return 0.0
        return sum(abs(self.positions[i] - self.positions[i - 1])
                   for i in range(1, len(self.positions))) / (len(self.positions) - 1)

    @property
    def exposure(self) -> float:
        """Average |position| -- 0 means it sat flat (no signal)."""
        return sum(abs(p) for p in self.positions) / len(self.positions) if self.positions else 0.0

    def sharpe(self, periods_per_year: int | None = None) -> float:
        return sharpe_ratio(self.returns, periods_per_year)


def backtest_tsmom(bars: list[Bar], params: TsmomParams) -> TsmomResult:
    """One coin: decide a vol-scaled position each period from history-to-date, earn it
    over the NEXT period, pay turnover cost. No look-ahead (position at t uses closes<=t)."""
    closes = [b[3] for b in bars]
    n = len(closes)
    rets = [0.0] + [closes[i] / closes[i - 1] - 1.0 if closes[i - 1] > 0 else 0.0
                    for i in range(1, n)]
    warmup = max(params.lookback, params.vol_window) + 1
    strat: list[float] = []
    positions: list[float] = []
    prev_pos = 0.0
    for t in range(warmup, n - 1):
        pos = target_position(closes[: t + 1], rets[1: t + 1], params)
        strat.append(pos * rets[t + 1] - params.cost * abs(pos - prev_pos))
        positions.append(pos)
        prev_pos = pos
    return TsmomResult(returns=strat, positions=positions)


def backtest_tsmom_many(series_by_coin: dict[str, list[Bar]],
                        params: TsmomParams) -> TsmomResult:
    """Equal-weight portfolio: average the per-coin period returns into one series (the
    diversified TSMOM book, where vol-scaling earns its keep)."""
    per_coin = {c: backtest_tsmom(b, params) for c, b in series_by_coin.items()}
    per_coin = {c: r for c, r in per_coin.items() if r.n_periods > 0}
    if not per_coin:
        return TsmomResult()
    length = min(r.n_periods for r in per_coin.values())
    port: list[float] = []
    pos: list[float] = []
    for i in range(length):
        # align on the LAST `length` periods of each coin (most recent, comparable window)
        rvals = [r.returns[r.n_periods - length + i] for r in per_coin.values()]
        pvals = [r.positions[len(r.positions) - length + i] for r in per_coin.values()]
        port.append(sum(rvals) / len(rvals))
        pos.append(sum(pvals) / len(pvals))         # net book position (avg across coins)
    return TsmomResult(returns=port, positions=pos)
