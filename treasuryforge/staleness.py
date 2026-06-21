"""Runtime staleness + clock-sanity gate — the bot refuses to act on old data or
an untrustworthy clock.

A live decision is only valid if (a) the market data feeding it is recent and
(b) the local clock is trustworthy. The monotonic clock never runs backward, so
we compare it against the wall clock between checks: if the wall clock jumps (an
NTP step, a manual change, a VM pause/resume) the two diverge and every timestamp
and staleness computation becomes unreliable — the loop must halt. And if the
freshest data is older than its budget, the bot is not trading, it is guessing.

The policy already has a staleness rule that takes data_age_ns but is inert in the
deterministic simulator (no real clock, no real data age). This module supplies
the REAL data_age_ns from wall-clock arrivals and adds the clock-sanity check the
simulator never needed. Time sources are injected so tests are deterministic.

Live windows: a 24h rate/spend window is just window=WINDOW_24H_NS with tick.ts set
to a wall-clock-ns timestamp, which the existing PolicyEngine._prune already honors.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

NS_PER_S = 1_000_000_000
WINDOW_24H_NS = 24 * 3600 * NS_PER_S


@dataclass(frozen=True)
class GateVerdict:
    ok: bool
    reason: str
    data_age_ns: int | None = None


@dataclass
class StalenessGate:
    max_data_age_ns: int
    max_clock_drift_ns: int = NS_PER_S          # tolerated |Δwall − Δmono| between checks
    wall_source: Callable[[], int] = field(default=time.time_ns)
    mono_source: Callable[[], int] = field(default=time.monotonic_ns)
    _last_data_ns: int | None = None
    _prev_wall_ns: int | None = None
    _prev_mono_ns: int | None = None

    def __post_init__(self) -> None:
        if self.max_data_age_ns <= 0:
            raise ValueError("max_data_age_ns must be positive")

    def observe_data(self, wall_ns: int) -> None:
        """Record that fresh market data arrived at this wall-clock timestamp."""
        self._last_data_ns = wall_ns

    def check(self, now_wall_ns: int, now_mono_ns: int) -> GateVerdict:
        """Decide whether it is safe to act right now. Clock sanity is judged
        against the previous check; freshness against the last observed data."""
        clock = self._clock_verdict(now_wall_ns, now_mono_ns)
        self._prev_wall_ns, self._prev_mono_ns = now_wall_ns, now_mono_ns
        if clock is not None:
            return clock

        if self._last_data_ns is None:
            return GateVerdict(False, "no market data observed yet")
        age = now_wall_ns - self._last_data_ns
        if age < 0:
            return GateVerdict(False, f"data timestamp in the future by {-age}ns", age)
        if age > self.max_data_age_ns:
            return GateVerdict(False, f"stale data: age {age}ns > budget {self.max_data_age_ns}ns", age)
        return GateVerdict(True, "fresh", age)

    def check_now(self) -> GateVerdict:
        return self.check(self.wall_source(), self.mono_source())

    def _clock_verdict(self, now_wall_ns: int, now_mono_ns: int) -> GateVerdict | None:
        """Return a HALT verdict if the clock looks wrong vs the previous reading,
        else None (clock trustworthy / first reading)."""
        if self._prev_wall_ns is None or self._prev_mono_ns is None:
            return None
        d_wall = now_wall_ns - self._prev_wall_ns
        d_mono = now_mono_ns - self._prev_mono_ns
        if d_wall < 0:
            return GateVerdict(False, f"wall clock went backward by {-d_wall}ns")
        drift = abs(d_wall - d_mono)
        if drift > self.max_clock_drift_ns:
            return GateVerdict(False, f"clock drift {drift}ns > budget {self.max_clock_drift_ns}ns")
        return None
