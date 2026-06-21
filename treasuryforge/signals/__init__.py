"""Signal generators — the 'perceive + compute probability' layer.

Each signal turns market observations into a discrete decision that feeds the
PROPOSE seam. They never execute and never bypass the policy engine. The first
one is funding-carry: the only mechanical edge the Phase-2/Phase-3 research AND
the adversarial deep-research pass all converged on as real (cross-exchange /
triangular micro-arbitrage was debunked — see RESEARCH_arbitrage.md).
"""

from .cointegration import (
    CointegrationResult,
    adf_test,
    engle_granger,
    half_life,
    hedge_ratio,
)
from .funding import (
    FundingCarryParams,
    FundingCarrySignal,
    HyperliquidFundingFeed,
    annualize,
)
from .pairs import PairPosition, PairsSignal, rolling_zscore

__all__ = [
    "CointegrationResult",
    "FundingCarryParams",
    "FundingCarrySignal",
    "HyperliquidFundingFeed",
    "PairPosition",
    "PairsSignal",
    "adf_test",
    "annualize",
    "engle_granger",
    "half_life",
    "hedge_ratio",
    "rolling_zscore",
]
