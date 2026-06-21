"""Operational risk module — turns the expectancy/Kelly/ruin theory into gates.

The headline gate is Monte-Carlo Risk of Ruin: given a strategy's REAL backtest
returns and a proposed leverage f, estimate P(touch -X% drawdown / liquidation)
BEFORE the edge can express — using block bootstrap (preserves serial
correlation), optional fat-tail shocks, and an adverse-regime shift. If that
probability exceeds the threshold, the trade is BLOCKED even if the DSR is good.

A positive edge says the game is winnable; geometric growth says the capital
grows; risk of ruin says whether you survive long enough for the edge to matter.
"""

from .drift import DriftKillSwitch, PageHinkley, make_kill_switch
from .graveyard import GraveyardEntry, StrategyGraveyard
from .live_gap import BacktestLiveGapReport, assess_backtest_live_gap
from .provenance import ReproducibilityPack, canonical_hash, make_provenance
from .report import AssessmentReport, assess_and_report
from .ruin import (
    MonteCarloRuinResult,
    StrategyRiskPolicy,
    block_bootstrap,
    geometric_growth,
    kelly_leverage,
    monte_carlo_ruin,
)
from .stages import LivePerformance, Stage, StageDecision, evaluate_stage
from .tax import BuyLot, FifoTaxLedger, MatchedTrade

__all__ = [
    "AssessmentReport",
    "BacktestLiveGapReport",
    "BuyLot",
    "DriftKillSwitch",
    "FifoTaxLedger",
    "GraveyardEntry",
    "LivePerformance",
    "MatchedTrade",
    "MonteCarloRuinResult",
    "PageHinkley",
    "ReproducibilityPack",
    "Stage",
    "StageDecision",
    "StrategyGraveyard",
    "StrategyRiskPolicy",
    "assess_and_report",
    "assess_backtest_live_gap",
    "block_bootstrap",
    "canonical_hash",
    "evaluate_stage",
    "geometric_growth",
    "kelly_leverage",
    "make_kill_switch",
    "make_provenance",
    "monte_carlo_ruin",
]
