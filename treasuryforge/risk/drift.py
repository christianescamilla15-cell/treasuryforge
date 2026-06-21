"""Drift kill-switch — the live guard. Edges don't die with an announcement;
they degrade. This catches the moment 'it used to work' becomes 'it just stopped'.

Page-Hinkley is a sequential change-point test on the cumulative deviation of a
stream from its running mean. We run one detector to catch a DROP in live
expectancy and another to catch a RISE in slippage, plus a hard drawdown band.
Any trip fires a named KILL — and KILL means kill, not 'wait and see'.

  KILL: EDGE_DRIFT_DETECTED       live expectancy drifted down
  KILL: EXECUTION_DEGRADED        realized slippage drifted up
  KILL: DD_EXCEEDS_STRESS_BAND    live drawdown blew past the stress band
"""

from __future__ import annotations

from dataclasses import dataclass


class PageHinkley:
    """Sequential change detector. direction='decrease' flags a falling mean
    (use for expectancy); 'increase' flags a rising mean (use for slippage).
    `delta` is the allowed slack; `lam` (lambda) is the alarm threshold."""

    def __init__(self, delta: float = 0.0, lam: float = 0.05, direction: str = "decrease") -> None:
        self.delta = delta
        self.lam = lam
        self.direction = direction
        self.n = 0
        self.mean = 0.0
        self.m = 0.0
        self.extreme = 0.0
        self.alarm = False

    def update(self, x: float) -> float:
        self.n += 1
        self.mean += (x - self.mean) / self.n
        if self.direction == "decrease":
            self.m += x - self.mean + self.delta
            self.extreme = max(self.extreme, self.m)
            ph = self.extreme - self.m
        else:  # increase
            self.m += x - self.mean - self.delta
            self.extreme = min(self.extreme, self.m)
            ph = self.m - self.extreme
        if ph > self.lam:
            self.alarm = True
        return ph

    def reset(self) -> None:
        self.n = 0
        self.mean = self.m = self.extreme = 0.0
        self.alarm = False


@dataclass
class DriftKillSwitch:
    expectancy: PageHinkley
    slippage: PageHinkley
    stress_dd_band: float = 0.30      # hard: live DD beyond the stress p95 band -> kill
    killed: bool = False
    reason: str = ""

    def observe(self, *, ret: float | None = None, slippage: float | None = None,
                drawdown: float | None = None) -> str | None:
        """Feed the latest live observations. Returns a KILL verdict the first time
        any guard trips, then stays killed."""
        if self.killed:
            return self.reason
        if drawdown is not None and drawdown > self.stress_dd_band:
            self._kill(f"KILL: DD_EXCEEDS_STRESS_BAND ({drawdown:.0%} > {self.stress_dd_band:.0%})")
        if ret is not None:
            self.expectancy.update(ret)
            if self.expectancy.alarm:
                self._kill("KILL: EDGE_DRIFT_DETECTED")
        if slippage is not None:
            self.slippage.update(slippage)
            if self.slippage.alarm:
                self._kill("KILL: EXECUTION_DEGRADED")
        return self.reason if self.killed else None

    def _kill(self, reason: str) -> None:
        if not self.killed:
            self.killed = True
            self.reason = reason


def make_kill_switch(*, expectancy_delta: float, expectancy_lambda: float,
                     slippage_delta: float, slippage_lambda: float,
                     stress_dd_band: float = 0.30) -> DriftKillSwitch:
    return DriftKillSwitch(
        expectancy=PageHinkley(expectancy_delta, expectancy_lambda, "decrease"),
        slippage=PageHinkley(slippage_delta, slippage_lambda, "increase"),
        stress_dd_band=stress_dd_band,
    )
