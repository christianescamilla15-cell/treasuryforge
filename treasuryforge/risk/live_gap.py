"""Backtest-to-Live gap detector — the bridge before real capital.

The risk engine can reject a weak BACKTEST. This module catches the opposite
trap: a strategy that passes every historical gate but is born dead in the air —
killed by latency, real fills, underestimated slippage, a live order book that
differs from history, or an edge that simply no longer exists.

It compares the strategy's BACKTEST returns against its PAPER-LIVE returns
(real signals, realistic hypothetical fills, NO capital), plus the realized vs
modeled execution quality, and emits a staged verdict:

  REJECT: INSUFFICIENT_LIVE_DATA   too few paper trades to conclude — keep running
  REJECT: NO_BACKTEST_EDGE         the backtest had no positive edge to begin with
  REJECT: EDGE_DECAYED             live expectancy <= 0 (the edge vanished)
  REJECT: BACKTEST_LIVE_GAP        live expectancy is far below backtest
  REJECT: EXECUTION_EDGE_LEAK      realized slippage blows past the model
  APPROVE_STAGE_1: MICRO_CAPITAL   survived the air — deploy at the first ladder rung

'You built the judge; this puts cameras on execution so the bot cannot lie to
you live.'
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from ..backtest.metrics import sharpe_ratio


def _mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


@dataclass
class BacktestLiveGapReport:
    name: str
    verdict: str
    backtest: dict = field(default_factory=dict)
    paper_live: dict = field(default_factory=dict)
    gap: dict = field(default_factory=dict)
    execution: dict = field(default_factory=dict)

    @property
    def approved(self) -> bool:
        return self.verdict.startswith("APPROVE")

    def render(self) -> str:
        b, p, g, e = self.backtest, self.paper_live, self.gap, self.execution
        return "\n".join([
            f"STRATEGY: {self.name}", "",
            "BACKTEST",
            f"  expectancy/trade:    {b['E']:+.3e}",
            f"  Sharpe:              {b['sharpe']:.2f}",
            "",
            "PAPER LIVE",
            f"  trades:              {p['n']}",
            f"  expectancy/trade:    {p['E']:+.3e}",
            f"  Sharpe:              {p['sharpe']:.2f}",
            "",
            "GAP",
            f"  expectancy retained: {g['degradation']:.0%}  (min {g['min_degradation']:.0%})",
            "",
            "EXECUTION QUALITY",
            f"  modeled slippage:    {e['modeled']:.3%}",
            f"  realized slippage:   {e['realized']:.3%}  ({e['ratio']:.1f}x modeled,"
            f" max {e['max_ratio']:.1f}x)",
            f"  maker fill rate:     {e['maker_fill']}",
            f"  post-fill drift:     {e['post_fill_drift']:+.3%}",
            "",
            "VERDICT", f"  {self.verdict}"])


def assess_backtest_live_gap(
    name: str,
    backtest_returns: Sequence[float],
    live_returns: Sequence[float],
    *,
    modeled_slippage: float,
    realized_slippage: float,
    maker_fill_rate: float | None = None,
    post_fill_drift: float = 0.0,
    min_live_trades: int = 30,
    min_degradation: float = 0.50,
    max_slippage_ratio: float = 2.0,
    periods_per_year: int | None = None,
) -> BacktestLiveGapReport:
    Eb = _mean(backtest_returns)
    El = _mean(live_returns)
    n_live = len(live_returns)
    degradation = (El / Eb) if Eb > 0 else 0.0
    slip_ratio = (realized_slippage / modeled_slippage) if modeled_slippage > 0 else float("inf")

    if Eb <= 0:
        verdict = "REJECT: NO_BACKTEST_EDGE"
    elif n_live < min_live_trades:
        verdict = f"REJECT: INSUFFICIENT_LIVE_DATA ({n_live}/{min_live_trades})"
    elif El <= 0:
        verdict = "REJECT: EDGE_DECAYED"
    elif degradation < min_degradation:
        verdict = "REJECT: BACKTEST_LIVE_GAP"
    elif slip_ratio > max_slippage_ratio:
        verdict = "REJECT: EXECUTION_EDGE_LEAK"
    else:
        verdict = "APPROVE_STAGE_1: MICRO_CAPITAL"

    return BacktestLiveGapReport(
        name=name, verdict=verdict,
        backtest={"E": Eb, "sharpe": sharpe_ratio(backtest_returns, periods_per_year)},
        paper_live={"E": El, "n": n_live, "sharpe": sharpe_ratio(live_returns, periods_per_year)},
        gap={"degradation": degradation, "min_degradation": min_degradation},
        execution={"modeled": modeled_slippage, "realized": realized_slippage,
                   "ratio": slip_ratio, "max_ratio": max_slippage_ratio,
                   "maker_fill": f"{maker_fill_rate:.0%}" if maker_fill_rate is not None else "n/a",
                   "post_fill_drift": post_fill_drift},
    )
