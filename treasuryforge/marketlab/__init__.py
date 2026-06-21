"""Market lab — the high-fidelity environment to test against before prod.

  store.py      local SQLite 'BD' of REAL historical candles / funding / L2 depth
                (synced keyless from Hyperliquid)
  synthetic.py  regime-switching jump-diffusion market with realistic volatility
                (calm / storm / crash + fat-tail jumps), deterministic
  fills.py      realistic matching-engine fills by walking REAL order-book depth
                (true VWAP, slippage, market impact, partial fills) — the
                production-like behavior, not 'fill at mid'
"""

from .fills import FillResult, Level, MatchingFillModel, parse_book, walk_book
from .store import MarketStore
from .synthetic import DEFAULT_REGIMES, Regime, SyntheticMarket

__all__ = [
    "DEFAULT_REGIMES",
    "FillResult",
    "Level",
    "MarketStore",
    "MatchingFillModel",
    "Regime",
    "SyntheticMarket",
    "parse_book",
    "walk_book",
]
