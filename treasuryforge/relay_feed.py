"""Read the region-permissive funding relay (Binance/Bybit, fetched on a residential
host that can reach venues the VPS cannot) with a FRESHNESS gate.

A relay snapshot older than `max_age_s` is treated as ABSENT: every relayed venue comes
back None, so `venue_spread.pairwise_spreads` simply drops them to `missing` instead of
trading on a stale spread. A powered-off relay therefore degrades cleanly to the
VPS-reachable venues, never to a phantom. Pure stdlib, offline-testable.
"""

from __future__ import annotations

import json


def load_snapshot(path: str) -> dict:
    """The latest relay snapshot, or an empty (ts=0) one if the file is absent/corrupt."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {"ts": 0, "venues": {}}
    except (OSError, ValueError):
        return {"ts": 0, "venues": {}}


def relay_funding(snapshot: dict, coin: str, *, now: int, max_age_s: int) -> dict[str, float | None]:
    """Per-coin {venue: APR or None} from a relay snapshot. Every venue is None when the
    snapshot is stale (older than max_age_s); a venue missing this coin is None too."""
    fresh = (now - int(snapshot.get("ts", 0))) <= max_age_s
    out: dict[str, float | None] = {}
    for venue, coins in snapshot.get("venues", {}).items():
        value = coins.get(coin) if isinstance(coins, dict) else None
        out[venue] = float(value) if (fresh and value is not None) else None
    return out
