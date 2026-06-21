"""Forward paper-book for the MOMENTUM_IGNITION scalp rule (run live, $0). The backtest's
`simulate_exit` walks FUTURE bars; a live shadow cannot, so this steps the same rule one
1-minute bar at a time, holding position state, and emits a per-bar net return (0 while
flat, mark-to-market while held, minus the half round-trip cost on the entry and exit
bars). The return series feeds the deployment gate's DSR exactly like the funding shadow.

Long-only (the rule enters on an up-ignition). Pure stdlib -> offline- and mutation-testable.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .signals.momentum import MomentumParams, entry_ok


@dataclass
class ScalpBook:
    params: MomentumParams = field(default_factory=MomentumParams)
    in_pos: bool = False
    entry: float = 0.0
    peak: float = 0.0
    bars_held: int = 0
    _prev: float = 0.0          # prior bar close
    _prev2: float = 0.0         # bar-before-prior close

    def observe(self, high: float, low: float, close: float) -> tuple[str, float]:
        """Step one 1-minute bar. Returns (action, net_return_this_bar)."""
        action, r = "FLAT", 0.0
        half_cost = self.params.cost / 2.0

        if self.in_pos:
            self.bars_held += 1
            trail_level = self.peak * (1.0 - self.params.trail_frac)
            stop_level = self.entry * (1.0 - self.params.stop_frac)
            mtm = close / self._prev - 1.0 if self._prev > 0 else 0.0
            if low <= stop_level and stop_level <= trail_level:        # gap through the hard stop
                r, action = (stop_level / self._prev - 1.0) - half_cost, "EXIT_STOP"
                self._flatten()
            elif low <= trail_level:                                   # trailing reversal
                r, action = (trail_level / self._prev - 1.0) - half_cost, "EXIT_TRAIL"
                self._flatten()
            elif self.bars_held >= self.params.max_hold:               # time stop
                r, action = mtm - half_cost, "EXIT_TIME"
                self._flatten()
            else:
                r, action = mtm, "HOLD"
                self.peak = max(self.peak, high)
        elif entry_ok(self._prev2, self._prev, close, self.params):
            r, action = -half_cost, "ENTER"
            self.in_pos, self.entry, self.peak, self.bars_held = True, close, close, 0

        self._prev2, self._prev = self._prev, close
        return action, r

    def _flatten(self) -> None:
        self.in_pos, self.entry, self.peak, self.bars_held = False, 0.0, 0.0, 0
