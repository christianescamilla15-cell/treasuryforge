"""Dead-man's switch — a client-side liveness guard.

A live bot can wedge: a hung network call, a deadlock, a partitioned VPS. While it
is frozen, its resting orders stay on the book with no one watching them. Most
serious venues offer a server-side `cancelAllAfter(T)` (auto-cancel if not renewed)
— Bitso does NOT. So we build the equivalent ourselves.

The trading loop must `beat()` at least every `timeout_s`. A supervisor (a separate
process, or a periodic check) calls `supervise(now, on_trip)`; if the last beat is
older than the timeout it fires `on_trip` EXACTLY ONCE — cancel all resting orders
and latch the kill-switch — then stays tripped (fail-closed; reset is manual).

The heartbeat is a tiny atomically-written file, so the guard survives a crash: a
fresh supervisor (or the bot restarting) reads a stale heartbeat and trips
immediately, because a stale heartbeat means the bot died while orders were live.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class Heartbeat:
    ts: float          # epoch seconds of the last beat
    seq: int           # monotonically increasing beat counter
    tripped: bool      # latched once the dead-man's switch has fired
    reason: str = ""


class DeadMansSwitch:
    def __init__(self, path: str, timeout_s: float) -> None:
        if timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        self.path = path
        self.timeout_s = timeout_s
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    # -- durable heartbeat (atomic) ---------------------------------------
    def _write(self, hb: Heartbeat) -> None:
        d = os.path.dirname(self.path) or "."
        fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(hb.__dict__, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)        # atomic on POSIX and Windows
        except BaseException:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise

    def read(self) -> Heartbeat | None:
        if not os.path.exists(self.path):
            return None
        with open(self.path, encoding="utf-8") as f:
            return Heartbeat(**json.load(f))

    # -- bot side ---------------------------------------------------------
    def beat(self, now: float) -> Heartbeat:
        """Record liveness. Refused once tripped (a fail-closed switch never
        silently un-trips — recovery is a deliberate reset())."""
        prev = self.read()
        if prev is not None and prev.tripped:
            raise RuntimeError(f"dead-man's switch is tripped: {prev.reason}")
        seq = (prev.seq + 1) if prev else 1
        hb = Heartbeat(ts=now, seq=seq, tripped=False)
        self._write(hb)
        return hb

    # -- supervisor side --------------------------------------------------
    def is_expired(self, now: float) -> bool:
        hb = self.read()
        if hb is None:
            return False                      # never started -> nothing to guard yet
        return (now - hb.ts) > self.timeout_s

    @property
    def tripped(self) -> bool:
        hb = self.read()
        return bool(hb and hb.tripped)

    def supervise(self, now: float, on_trip: Callable[[str], None]) -> bool:
        """If the heartbeat is stale and not already tripped, fire on_trip EXACTLY
        once and latch. Returns whether it tripped on THIS call. on_trip must perform
        the fail-safe (cancel resting orders + latch the policy kill-switch); it runs
        before the trip is persisted so a crash mid-trip re-fires on the next check."""
        hb = self.read()
        if hb is None or hb.tripped:
            return False
        if (now - hb.ts) <= self.timeout_s:
            return False
        reason = f"no heartbeat for {now - hb.ts:.1f}s (> {self.timeout_s:.1f}s timeout)"
        on_trip(reason)                       # do the fail-safe FIRST
        self._write(Heartbeat(ts=hb.ts, seq=hb.seq, tripped=True, reason=reason))
        return True

    def reset(self, now: float) -> Heartbeat:
        """Deliberate manual recovery after a trip — clears the latch and re-beats."""
        prev = self.read()
        hb = Heartbeat(ts=now, seq=(prev.seq + 1 if prev else 1), tripped=False)
        self._write(hb)
        return hb
