"""Stage Ladder + Demotion Rules — strategy lifecycle governance.

APPROVE_STAGE_1 opens a new question: once live, when does a strategy climb, hold,
shrink, or die? This is the state machine that answers it. A strategy never jumps
to full size; it earns capital one rung at a time and is demoted or killed the
moment its live behavior diverges from what the model promised.

  STAGE 0  PAPER_LIVE       capital 0     — verify edge retention
  STAGE 1  MICRO_CAPITAL    0.5-1%        — verify real fills & slippage
  STAGE 2  SMALL_CAPITAL    2-3%          — verify initial capacity
  STAGE 3  NORMAL_CAPITAL   5-10%         — controlled production
  STAGE 4  CAPPED_PRODUCTION portfolio max

Transition priority (worst case wins): KILL > DEMOTE > PROMOTE > HOLD.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class Stage(IntEnum):
    DEAD = -1
    PAPER_LIVE = 0
    MICRO_CAPITAL = 1
    SMALL_CAPITAL = 2
    NORMAL_CAPITAL = 3
    CAPPED_PRODUCTION = 4


STAGE_CAPITAL = {
    Stage.DEAD: 0.0, Stage.PAPER_LIVE: 0.0, Stage.MICRO_CAPITAL: 0.01,
    Stage.SMALL_CAPITAL: 0.03, Stage.NORMAL_CAPITAL: 0.08, Stage.CAPPED_PRODUCTION: 0.20,
}


@dataclass
class LivePerformance:
    edge_retention: float          # E_live / E_backtest
    slippage_ratio: float          # realized / modeled
    live_dd: float                 # observed live max drawdown
    expected_dd_p75: float
    expected_dd_p90: float
    stress_dd_p95: float
    sample_size: int = 0
    min_sample: int = 30
    kill_switch_triggered: bool = False
    adverse_selection: bool = False
    execution_failure: bool = False


@dataclass
class StageDecision:
    from_stage: Stage
    to_stage: Stage
    action: str                    # PROMOTE / HOLD / DEMOTE / KILL / DEAD
    reason: str
    capital_fraction: float

    def render(self) -> str:
        return (f"{self.from_stage.name} --{self.action}--> {self.to_stage.name}"
                f"  (capital {self.capital_fraction:.1%})\n   reason: {self.reason}")


def evaluate_stage(current: Stage, perf: LivePerformance) -> StageDecision:
    if current == Stage.DEAD:
        return StageDecision(current, Stage.DEAD, "DEAD", "already retired", 0.0)

    # -- KILL (highest priority) ------------------------------------------
    kills = []
    if perf.live_dd > perf.stress_dd_p95:
        kills.append(f"live DD {perf.live_dd:.0%} > stress p95 {perf.stress_dd_p95:.0%}")
    if perf.edge_retention < 0.25:
        kills.append(f"edge retention {perf.edge_retention:.0%} < 25%")
    if perf.adverse_selection:
        kills.append("persistent adverse selection")
    if perf.execution_failure:
        kills.append("execution failure")
    if perf.kill_switch_triggered:
        kills.append("kill-switch triggered")
    if kills:
        return StageDecision(current, Stage.DEAD, "KILL", "; ".join(kills), 0.0)

    # -- DEMOTE -----------------------------------------------------------
    dem = []
    if perf.edge_retention < 0.50:
        dem.append(f"edge retention {perf.edge_retention:.0%} < 50%")
    if perf.slippage_ratio > 2.0:
        dem.append(f"slippage {perf.slippage_ratio:.1f}x > 2x")
    if perf.live_dd > perf.expected_dd_p90:
        dem.append(f"live DD {perf.live_dd:.0%} > expected p90 {perf.expected_dd_p90:.0%}")
    if dem:
        to = Stage(max(int(current) - 1, int(Stage.PAPER_LIVE)))
        return StageDecision(current, to, "DEMOTE", "; ".join(dem), STAGE_CAPITAL[to])

    # -- PROMOTE ----------------------------------------------------------
    if (perf.edge_retention >= 0.70 and perf.slippage_ratio <= 1.5
            and perf.live_dd <= perf.expected_dd_p75 and perf.sample_size >= perf.min_sample):
        to = Stage(min(int(current) + 1, int(Stage.CAPPED_PRODUCTION)))
        if to == current:
            return StageDecision(current, current, "HOLD",
                                 "all criteria met but already at production cap",
                                 STAGE_CAPITAL[current])
        return StageDecision(current, to, "PROMOTE",
                             "edge retained, slippage in-model, DD<=p75, sample sufficient",
                             STAGE_CAPITAL[to])

    # -- HOLD -------------------------------------------------------------
    return StageDecision(current, current, "HOLD",
                         "mixed but not dangerous — gather more live data",
                         STAGE_CAPITAL[current])
