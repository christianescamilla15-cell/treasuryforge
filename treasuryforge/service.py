"""Service runner — the fail-closed outer process around the live supervisor.

This is what a systemd unit launches. Its whole job is to make starting and
stopping SAFE:

  1. run preflight; if it is not READY, do NOT trade — fire the fail-safe and exit
     with SAFE_HALTED (a distinct code so the unit does not restart-loop into
     trading);
  2. on a clean start, RECONCILE any in-flight orders before any new action
     (crash recovery — orders.recover never places);
  3. drive the guarded loop; a tripped dead-man's switch exits DEAD_MAN;
  4. fail-closed: ANY unexpected exception fires the fail-safe (cancel resting
     orders + latch the kill-switch) and exits ERROR — it never leaves exposure
     open on the way down.

The feed, wallet snapshot, and fail-safe action are injected, so the whole
lifecycle is unit-tested with no network, keys, or wall-clock. The venue-specific
__main__ that supplies a real feed/executor is a thin shim added once a venue is
chosen and funded.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from enum import IntEnum

from .live import LiveSupervisor, StepKind, StepResult
from .preflight import PreflightInputs
from .types import MarketTick
from .wallet import SimWallet


class ServiceExit(IntEnum):
    # The exact int values are pinned by test_exit_codes_are_exact. Setting an
    # IntEnum member to None breaks the module IMPORT (int(None) at class creation),
    # which mutmut sees as a collection error and miscounts as 'survived' rather than
    # killed; these are non-viable mutants, excluded with `# pragma: no mutate`.
    OK = 0                 # pragma: no mutate
    SAFE_HALTED = 10       # preflight refused — operator must fix the environment  # pragma: no mutate
    DEAD_MAN = 20          # the dead-man's switch fired  # pragma: no mutate
    ERROR = 30             # unexpected error — failed closed  # pragma: no mutate


# (tick, data_wall_ns, wallet) for each loop iteration; the alias is never evaluated
# at runtime (string annotation), so its mutation is equivalent — excluded.
FeedItem = tuple[MarketTick, int, SimWallet]  # pragma: no mutate


class Service:
    def __init__(self, supervisor: LiveSupervisor, on_halt: Callable[[str], None]) -> None:
        self.supervisor = supervisor
        self.on_halt = on_halt          # fail-safe: cancel resting orders + latch kill-switch
        self.steps: list[StepResult] = []

    def run(self, inputs: PreflightInputs, feed: Iterable[FeedItem]) -> ServiceExit:
        report = self.supervisor.start(inputs)
        if not report.ready:
            self.on_halt("preflight SAFE_HALTED: " + ",".join(c.name for c in report.failures()))
            return ServiceExit.SAFE_HALTED

        # crash recovery: learn the fate of any in-flight order BEFORE acting
        self.supervisor.orders.recover()

        try:
            for tick, data_wall_ns, wallet in feed:
                self.supervisor.observe_data(data_wall_ns)
                result = self.supervisor.step(tick, wallet)
                self.steps.append(result)
                if result.kind is StepKind.HALTED_DEAD:
                    self.on_halt("dead-man's switch tripped")
                    return ServiceExit.DEAD_MAN
                # HALTED_STALE is not fatal — skip this tick, the feed may recover
        except Exception as e:                     # fail-closed: catch EVERYTHING on the way down
            self.on_halt(f"unexpected error: {e!r}")
            return ServiceExit.ERROR
        return ServiceExit.OK
