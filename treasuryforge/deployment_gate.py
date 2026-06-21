"""Deployment gate — the wire-but-gate guard between a live signal and real capital.

A strategy's signal may fire every interval, but NO real money is risked until its
live track record clears the gate: a Deflated Sharpe >= min_dsr AND a net APR >= the
floor, over >= min_intervals spanning >= min_days. Below the gate,
`GatedStrategy.decide()` returns None, so the live loop stays HOLD — the system runs
live and watches, but is STRUCTURALLY UNABLE to open a position on an unproven edge.
When the gate clears, the wrapped signal is allowed through, its size CAPPED to the
stage ladder's micro tier (a freshly-promoted edge never deploys at full size).

This is the opposite of a signal generator: it can only WITHHOLD capital, never spend
it. It bootstraps the FIRST deployment from the shadow/live track record's DSR; the
post-deployment promotion up the ladder (MICRO -> SMALL -> ...) is the separate job of
`risk.stages.evaluate_stage`, which needs the live fills (retention/slippage) this gate
unlocks. The track record is injected; the gate is otherwise pure -> offline-testable.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace

from .agent import Strategy
from .backtest.metrics import deflated_sharpe_ratio
from .risk.stages import STAGE_CAPITAL, Stage
from .types import Intent, MarketTick
from .wallet import SimWallet

_DAYS_PER_YEAR = 365.0


@dataclass(frozen=True)
class GateVerdict:
    deploy: bool
    dsr: float
    apr: float
    n: int
    days: float
    tier_fraction: float        # share of equity allowed if deployed (0.0 if not)
    reason: str


@dataclass(frozen=True)
class DeploymentGate:
    """Decides whether a strategy's live track record has earned real capital. The
    defaults mirror the project's promotion triggers: DSR >= 0.60, net APR >= 5%, and
    at least 30 intervals over 14 days of live evidence."""

    min_dsr: float = 0.60
    min_net_apr: float = 0.05
    min_intervals: int = 30
    min_days: float = 14.0
    tier: Stage = Stage.MICRO_CAPITAL

    def evaluate(self, returns: Sequence[float], ts: Sequence[int], *,
                 trial_sharpes: Sequence[float] | None = None) -> GateVerdict:
        """`trial_sharpes` is the per-interval Sharpe of EVERY candidate evaluated in this
        scan (e.g. one per coin). Passing it deflates the DSR by the real multiple-testing
        burden -- the more candidates scanned, the higher the bar a survivor must clear, so a
        wider universe cannot manufacture a false edge. None -> single-trial (legacy)."""
        n = len(returns)
        days = (max(ts) - min(ts)) / 86400.0 if len(ts) >= 2 else 0.0
        if n < self.min_intervals or not any(r != 0 for r in returns):
            return GateVerdict(False, 0.0, 0.0, n, days, 0.0,
                               f"insufficient track record (n={n} < {self.min_intervals})")
        dsr = deflated_sharpe_ratio(returns, n_trials=1, trial_sharpes=trial_sharpes)
        eq = 1.0
        for r in returns:
            eq *= (1.0 + r)
        apr = (eq - 1.0) / (days / _DAYS_PER_YEAR) if days > 0 else 0.0
        fails = []
        if dsr < self.min_dsr:
            fails.append(f"DSR {dsr:.3f} < {self.min_dsr:.2f}")
        if apr < self.min_net_apr:
            fails.append(f"net APR {apr:+.1%} < {self.min_net_apr:.0%}")
        if days < self.min_days:
            fails.append(f"{days:.1f}d < {self.min_days:.0f}d live")
        if fails:
            return GateVerdict(False, dsr, apr, n, days, 0.0, "; ".join(fails))
        return GateVerdict(True, dsr, apr, n, days, STAGE_CAPITAL[self.tier],
                           f"DSR {dsr:.3f} & APR {apr:+.1%} over {n} intervals / {days:.1f}d")


TrackRecord = Callable[[], "tuple[Sequence[float], Sequence[int]]"]


@dataclass
class GatedStrategy:
    """Wraps a live signal so it can only act once its track record clears the gate,
    and then only at the micro tier. Implements the `Strategy` protocol, so it drops
    straight into `LiveSupervisor` in place of a raw signal."""

    inner: Strategy
    track_record: TrackRecord            # () -> (per-interval returns, unix timestamps)
    gate: DeploymentGate = DeploymentGate()
    last_verdict: GateVerdict | None = None

    def decide(self, tick: MarketTick, wallet: SimWallet) -> Intent | None:
        verdict = self.gate.evaluate(*self.track_record())
        self.last_verdict = verdict
        if not verdict.deploy:
            return None                                   # wire-but-gate: stay HOLD
        intent = self.inner.decide(tick, wallet)
        if intent is None:
            return None
        return self._cap_to_tier(intent, tick, wallet, verdict.tier_fraction)

    @staticmethod
    def _cap_to_tier(intent: Intent, tick: MarketTick, wallet: SimWallet,
                     tier_fraction: float) -> Intent:
        """Never let a freshly-promoted edge exceed its tier's share of equity."""
        budget = tier_fraction * wallet.equity({tick.symbol: tick.price})
        if intent.quote_amount is not None:
            if intent.quote_amount <= budget:
                return intent
            return replace(intent, quote_amount=budget,
                           reason=f"{intent.reason} [tier-capped {tier_fraction:.0%}]")
        max_base = budget / tick.price if tick.price > 0 else 0.0
        if intent.base_amount <= max_base:
            return intent
        return replace(intent, base_amount=max_base,
                       reason=f"{intent.reason} [tier-capped {tier_fraction:.0%}]")
