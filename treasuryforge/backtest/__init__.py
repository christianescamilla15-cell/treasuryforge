"""Cost-aware, overfitting-aware validation gate.

The discovery's single most-repeated, highest-confidence recommendation: nearly
every published edge evaporates under realistic fees/slippage/impact, and a
backtest run over many configs produces a high Sharpe by luck alone. This package
is the gate that makes 'validated before real funds' honest:

  CostModel  — one shared friction model (advisory; may only ADD conservatism)
  metrics    — Sharpe, max drawdown, and the Deflated Sharpe Ratio (selection-
               bias-corrected, pure-stdlib via math.erf)
  cv         — purged + embargoed K-fold splits (no train/test leakage)
"""

from .costmodel import CostModel
from .cv import purged_kfold
from .funding_backtest import FundingBacktestResult, backtest_funding_carry
from .metrics import (
    deflated_sharpe_ratio,
    max_drawdown,
    profit_factor,
    sharpe_ratio,
    sortino_ratio,
)
from .pairs_backtest import PairsBacktestResult, backtest_pairs

__all__ = [
    "CostModel",
    "FundingBacktestResult",
    "PairsBacktestResult",
    "backtest_funding_carry",
    "backtest_pairs",
    "deflated_sharpe_ratio",
    "max_drawdown",
    "profit_factor",
    "purged_kfold",
    "sharpe_ratio",
    "sortino_ratio",
]
