"""Live supervisor — wires the execution-safety layer into one guarded loop.

It does not trade by itself; it GOVERNS trading. The deterministic sim Runner stays
untouched (it is the validated core); this is the live path that wraps the four
no-regret guards around real execution:

  start()  -> run preflight; the caller must refuse to operate unless .ready
  step()   -> beat the watchdog, REFUSE on a stale feed or insane clock, let the
              policy dispose, and route any approved order through the idempotent
              manager (at-most-once + reconcile-before-retry)
  supervise() -> the dead-man's switch: if the loop stops beating, fire the
              fail-safe (cancel + kill) exactly once

Everything is injected — clock, feed, wallet, executor — so the whole orchestration
is unit-tested with zero network, keys, or wall-clock.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from .agent import Strategy
from .orders import IdempotentOrderManager, OrderState, Outcome, make_origin_id
from .policy import PolicyEngine
from .preflight import PreflightInputs, PreflightReport, run_preflight
from .staleness import NS_PER_S, StalenessGate
from .types import Intent, MarketTick
from .wallet import SimWallet
from .watchdog import DeadMansSwitch


class StepKind(str, Enum):
    HALTED_DEAD = "HALTED_DEAD"     # the dead-man's switch is tripped — refuse to act
    HALTED_STALE = "HALTED_STALE"   # stale data / insane clock — refuse to act
    HOLD = "HOLD"                   # no signal
    DENIED = "DENIED"               # policy rejected the intent
    SUBMITTED = "SUBMITTED"         # order accepted, not yet filled
    FILLED = "FILLED"               # order filled
    OPEN = "OPEN"                   # resting on the book
    REJECTED = "REJECTED"           # exchange rejected the order


_OUTCOME_KIND = {
    OrderState.FILLED: StepKind.FILLED,
    OrderState.OPEN: StepKind.OPEN,
    OrderState.REJECTED: StepKind.REJECTED,
}


@dataclass(frozen=True)
class StepResult:
    kind: StepKind
    reason: str
    outcome: Outcome | None = None

    @property
    def traded(self) -> bool:
        return self.kind in (StepKind.SUBMITTED, StepKind.FILLED, StepKind.OPEN)


@dataclass
class LiveSupervisor:
    policy: PolicyEngine
    agent: Strategy
    orders: IdempotentOrderManager
    watchdog: DeadMansSwitch
    staleness: StalenessGate
    wall_ns: Callable[[], int]
    mono_ns: Callable[[], int]
    origin_for: Callable[[Intent, MarketTick], str] = (
        lambda intent, tick: make_origin_id("live", tick.ts, tick.symbol))

    # -- startup ----------------------------------------------------------
    def start(self, inputs: PreflightInputs) -> PreflightReport:
        """Run preflight. The CALLER must check .ready and refuse to step otherwise."""
        return run_preflight(inputs)

    def observe_data(self, wall_ns: int) -> None:
        """Tell the staleness gate that fresh market data arrived."""
        self.staleness.observe_data(wall_ns)

    # -- the guarded step -------------------------------------------------
    def step(self, tick: MarketTick, wallet: SimWallet) -> StepResult:
        if self.watchdog.tripped:
            return StepResult(StepKind.HALTED_DEAD, "dead-man's switch tripped")

        now_w, now_m = self.wall_ns(), self.mono_ns()
        self.watchdog.beat(now_w / NS_PER_S)                  # prove liveness

        fresh = self.staleness.check(now_w, now_m)
        if not fresh.ok:
            return StepResult(StepKind.HALTED_STALE, fresh.reason)

        intent = self.agent.decide(tick, wallet)
        if intent is None:
            return StepResult(StepKind.HOLD, "no signal")

        verdict = self.policy.evaluate(intent, tick, wallet, data_age_ns=fresh.data_age_ns)
        if not verdict.allowed:
            return StepResult(StepKind.DENIED, verdict.reason)

        origin_id = self.origin_for(intent, tick)
        outcome = self.orders.submit(intent, origin_id, tick.symbol)
        kind = _OUTCOME_KIND.get(outcome.state, StepKind.SUBMITTED)
        return StepResult(kind, outcome.reason, outcome)

    # -- dead-man's switch (run by a supervisor / on a timer) -------------
    def supervise(self, now_wall_s: float, on_trip: Callable[[str], None]) -> bool:
        """If the loop stopped beating, fire on_trip (cancel resting orders + latch
        the kill-switch) exactly once. Returns whether it tripped on this call."""
        return self.watchdog.supervise(now_wall_s, on_trip)
