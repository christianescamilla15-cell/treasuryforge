"""Strategy graveyard — rejections become accumulated knowledge.

Without it you re-try the same dead idea under new names (AVAX/LTC pairs →
LTC/AVAX residual → mean-reversion v2 → zscore spread → ...). Every buried
strategy keeps its hypothesis, metrics, the EXACT failure mode, a REVIVAL
CONDITION (what would have to change to earn a retry), and a content fingerprint
so a disguised corpse is caught. Append-only JSONL, survives restarts.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass


# revival_condition entries are (op, value) where op is ">" or "<"
@dataclass
class GraveyardEntry:
    strategy_id: str
    hypothesis: str
    market: str
    date: str
    metrics: dict
    verdict: str
    failure_mode: str
    revival_condition: dict             # {metric: ["<"|">", value]}
    fingerprint: str = ""               # provenance content fingerprint (catch reattempts)


class StrategyGraveyard:
    def __init__(self, path: str) -> None:
        self.path = path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    def bury(self, entry: GraveyardEntry) -> None:
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(entry), separators=(",", ":")) + "\n")
            f.flush()
            os.fsync(f.fileno())

    def all(self) -> list[GraveyardEntry]:
        if not os.path.exists(self.path):
            return []
        out = []
        with open(self.path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    out.append(GraveyardEntry(**json.loads(line)))
        return out

    def find_by_fingerprint(self, fingerprint: str) -> GraveyardEntry | None:
        """Catch a disguised corpse: an 'new' strategy with the same inputs/output
        as something already buried."""
        for e in self.all():
            if e.fingerprint and e.fingerprint == fingerprint:
                return e
        return None

    def check_revival(self, strategy_id: str, current_metrics: dict) -> tuple[bool, list[str]]:
        """Does a buried strategy now meet ALL its revival conditions?
        Returns (can_revive, list of conditions still unmet)."""
        entry = next((e for e in self.all() if e.strategy_id == strategy_id), None)
        if entry is None:
            return False, [f"no buried strategy '{strategy_id}'"]
        unmet = []
        for metric, (op, val) in entry.revival_condition.items():
            cur = current_metrics.get(metric)
            if cur is None:
                unmet.append(f"{metric}: not measured")
            elif op == ">" and not cur > val:
                unmet.append(f"{metric}={cur} not > {val}")
            elif op == "<" and not cur < val:
                unmet.append(f"{metric}={cur} not < {val}")
        return (len(unmet) == 0), unmet
