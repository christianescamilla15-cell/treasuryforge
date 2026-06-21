"""Time-boxed loss circuit breakers (Christian's cold-verdict point 5).

Per-position / per-cluster / ruin caps bound how much you can lose on ONE bet. They say
nothing about how FAST you can start bleeding across the book. These breakers halt trading
when losses accrue too quickly, when a kill is still cooling down, when operational errors
pile up, or when live drifts too far from shadow. A halt is a PAUSE, not a position change --
the agent stops proposing; existing risk caps still govern open positions. Pure stdlib.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LossLimits:
    max_daily_loss: float = 0.02         # halt the day at -2% of the trading bankroll
    max_weekly_loss: float = 0.05        # -5% over 7d
    max_monthly_loss: float = 0.10       # -10% over 30d
    kill_cooldown_days: float = 7.0      # no new deployment for N days after a strategy kill
    max_op_errors: int = 3               # halt after N operational errors in the window
    max_live_gap: float = 0.30           # halt if live underperforms shadow by > this fraction


DEFAULT = LossLimits()


@dataclass(frozen=True)
class BreakerInput:
    pnl_1d: float                        # bankroll-fraction PnL, last 1 / 7 / 30 days
    pnl_7d: float
    pnl_30d: float
    days_since_kill: float               # float('inf') if never killed
    op_errors: int                       # operational errors in the recent window
    live_gap: float                      # (shadow - live) / |shadow|, how far live trails shadow


@dataclass(frozen=True)
class BreakerState:
    reasons: tuple[str, ...]

    @property
    def halted(self) -> bool:
        return bool(self.reasons)

    def render(self) -> str:
        if not self.halted:
            return "breakers: CLEAR (trading allowed)"
        return "breakers: HALTED -> " + "; ".join(self.reasons)


def check_breakers(i: BreakerInput, lim: LossLimits = DEFAULT) -> BreakerState:
    reasons: list[str] = []
    if i.pnl_1d <= -lim.max_daily_loss:
        reasons.append(f"daily loss {i.pnl_1d:+.1%} <= -{lim.max_daily_loss:.0%}")
    if i.pnl_7d <= -lim.max_weekly_loss:
        reasons.append(f"weekly loss {i.pnl_7d:+.1%} <= -{lim.max_weekly_loss:.0%}")
    if i.pnl_30d <= -lim.max_monthly_loss:
        reasons.append(f"monthly loss {i.pnl_30d:+.1%} <= -{lim.max_monthly_loss:.0%}")
    if i.days_since_kill < lim.kill_cooldown_days:
        reasons.append(f"kill cooldown {i.days_since_kill:.1f}d < {lim.kill_cooldown_days:.0f}d")
    if i.op_errors >= lim.max_op_errors:
        reasons.append(f"op errors {i.op_errors} >= {lim.max_op_errors}")
    if i.live_gap > lim.max_live_gap:
        reasons.append(f"live-gap {i.live_gap:.0%} > {lim.max_live_gap:.0%}")
    return BreakerState(reasons=tuple(reasons))
