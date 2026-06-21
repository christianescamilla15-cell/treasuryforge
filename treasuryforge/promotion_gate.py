"""Promotion gate -- the NON-NEGOTIABLE numbers that move a strategy up the funnel
(Christian's cold-verdict point 3). "DSR alto, net positivo, persistencia" leaves room for
human interpretation, and human interpretation is where self-deception lives. This turns
each criterion into a hard threshold; a strategy is promoted ONLY if it passes ALL of them.

The same gate guards every up-step (shadow->micro, micro->scale): you feed the LIVE stats
and it answers PASS/FAIL per criterion, no judgement calls. Pure stdlib, offline-testable.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PromotionCriteria:
    min_dsr: float = 0.60                 # deflated Sharpe (live) -- real edge after deflation
    min_net_apr: float = 0.05             # net-of-cost APR floor (over break-even), e.g. 5%
    min_events: int = 30                  # resolved trades/events (DSR needs a real sample)
    min_days: float = 14.0                # observation window (one good week isn't a regime)
    min_duty_cycle: float = 0.0           # spread strategies: fraction of time above break-even
    max_slippage_ratio: float = 1.5       # realized slippage <= modeled * this (model honest?)
    max_live_shadow_dev: float = 2.0      # live not worse than shadow by > this many sigma


DEFAULT = PromotionCriteria()


@dataclass(frozen=True)
class StrategyStats:
    dsr: float
    net_apr: float
    n_events: int
    n_days: float
    duty_cycle: float
    realized_slippage: float
    modeled_slippage: float
    live_pnl: float                       # realised live PnL over the window
    shadow_pnl: float                     # the shadow's PnL over the same window
    shadow_pnl_std: float                 # shadow PnL dispersion (for the deviation test)


@dataclass(frozen=True)
class GateCheck:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class PromotionDecision:
    checks: tuple[GateCheck, ...]

    @property
    def promoted(self) -> bool:
        return bool(self.checks) and all(c.passed for c in self.checks)

    @property
    def failures(self) -> tuple[str, ...]:
        return tuple(c.name for c in self.checks if not c.passed)

    def render(self) -> str:
        head = "PROMOTE" if self.promoted else f"HOLD ({len(self.failures)} gate(s) failing)"
        lines = [f"=== promotion gate: {head} ==="]
        for c in self.checks:
            lines.append(f"  [{'PASS' if c.passed else 'FAIL'}] {c.name:18} {c.detail}")
        return "\n".join(lines)


def evaluate_promotion(s: StrategyStats,
                       crit: PromotionCriteria = DEFAULT) -> PromotionDecision:
    slip_ceiling = s.modeled_slippage * crit.max_slippage_ratio
    shadow_floor = s.shadow_pnl - crit.max_live_shadow_dev * s.shadow_pnl_std
    checks = (
        GateCheck("dsr", s.dsr >= crit.min_dsr,
                  f"{s.dsr:.2f} >= {crit.min_dsr:.2f}"),
        GateCheck("net_apr", s.net_apr >= crit.min_net_apr,
                  f"{s.net_apr:+.1%} >= {crit.min_net_apr:+.1%}"),
        GateCheck("events", s.n_events >= crit.min_events,
                  f"{s.n_events} >= {crit.min_events}"),
        GateCheck("days", s.n_days >= crit.min_days,
                  f"{s.n_days:.0f} >= {crit.min_days:.0f}"),
        GateCheck("duty_cycle", s.duty_cycle >= crit.min_duty_cycle,
                  f"{s.duty_cycle:.0%} >= {crit.min_duty_cycle:.0%}"),
        GateCheck("slippage", s.realized_slippage <= slip_ceiling,
                  f"{s.realized_slippage:.4f} <= {slip_ceiling:.4f} (modeled x{crit.max_slippage_ratio})"),
        GateCheck("live_vs_shadow", s.live_pnl >= shadow_floor,
                  f"live {s.live_pnl:+.4f} >= shadow_floor {shadow_floor:+.4f}"),
    )
    return PromotionDecision(checks=checks)
