"""Crash-only durable state — fixes a real money-relevant bug.

Phase-2 discovery found that the PolicyEngine's latched state (tripped breaker,
drawdown anchor, rate/spend windows) and the run ledger lived only in memory. A
crash + restart silently UN-TRIPPED a latched drawdown breaker and re-anchored
the drawdown floor to the post-loss equity — i.e. the safety stop evaporated
exactly when it mattered.

This module persists that state durably:
  - the ledger is an append-only WAL (one JSON line per event, fsync'd);
  - the latched state is checkpointed atomically (temp file + os.replace, which
    is atomic on both POSIX and Windows) so a crash mid-write can never leave a
    half-written checkpoint.

"Crash-only": recovery is the normal path. A torn final ledger line (process
killed mid-write) is tolerated and skipped on read; the last good checkpoint is
always complete.
"""

from __future__ import annotations

import json
import os
import tempfile


class Journal:
    def __init__(self, directory: str) -> None:
        self.dir = directory
        os.makedirs(directory, exist_ok=True)
        self.ledger_path = os.path.join(directory, "ledger.jsonl")
        self.state_path = os.path.join(directory, "state.json")

    def append_event(self, event: dict) -> None:
        line = json.dumps(event, separators=(",", ":"), sort_keys=True)
        with open(self.ledger_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()
            os.fsync(f.fileno())

    def checkpoint(self, state: dict) -> None:
        """Atomically replace the checkpoint. Never leaves a partial file."""
        fd, tmp = tempfile.mkstemp(dir=self.dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(state, f, sort_keys=True)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.state_path)   # atomic on POSIX and Windows
        except BaseException:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise

    def load_state(self) -> dict | None:
        if not os.path.exists(self.state_path):
            return None
        with open(self.state_path, encoding="utf-8") as f:
            return json.load(f)

    def read_ledger(self) -> list[dict]:
        if not os.path.exists(self.ledger_path):
            return []
        out: list[dict] = []
        with open(self.ledger_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    # a torn last line from a crash mid-write — safe to drop
                    pass
        return out
