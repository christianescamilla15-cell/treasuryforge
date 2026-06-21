"""Autonomous scalp shadow (paper, $0, no keys) -- runs the MOMENTUM_IGNITION rule forward
on live 1-minute bars across the liquid HL perps, journaling per-bar returns so the
deployment gate can measure its live DSR. It NEVER trades real money; the deployment gate
(deployment_gate.py) is what would promote it to real micro capital IF its DSR ever clears
0.60 over >=30 intervals / >=14 days. Until then it just accumulates the honest verdict.

Persistent loop (systemd Type=simple, Restart=always): every --interval it steps each
coin's ScalpBook by its newest CLOSED 1-min bar and appends (action, r) to
state/scalp_<coin>/ledger.jsonl (kind='scalp').

    python scripts/run_scalp_shadow.py --top 15 --interval 60
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request

sys.path.insert(0, ".")

from treasuryforge.journal import Journal
from treasuryforge.scalp_shadow import ScalpBook


def _post(body: dict):
    req = urllib.request.Request("https://api.hyperliquid.xyz/info",
        data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "treasuryforge/0.1"})
    with urllib.request.urlopen(req, timeout=15) as r:  # nosec B310
        return json.loads(r.read().decode())


def _liquid(top: int, min_vol: float) -> list[str]:
    meta, ctxs = _post({"type": "metaAndAssetCtxs"})
    pool = [(float(c.get("dayNtlVlm", 0) or 0), a["name"]) for a, c in zip(meta["universe"], ctxs)]
    pool = sorted((p for p in pool if p[0] >= min_vol), reverse=True)
    return [name for _v, name in pool[:top]]


def _last_closed_1m(coin: str, now_ms: int) -> tuple[int, float, float, float] | None:
    cs = _post({"type": "candleSnapshot",
                "req": {"coin": coin, "interval": "1m", "startTime": now_ms - 4 * 60_000,
                        "endTime": now_ms}})
    closed = [k for k in cs if int(k["T"]) <= now_ms]
    if not closed:
        return None
    k = closed[-1]
    return int(k["t"]), float(k["h"]), float(k["l"]), float(k["c"])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--min-vol", type=float, default=5_000_000)
    ap.add_argument("--interval", type=int, default=60)
    ap.add_argument("--state-prefix", default="state/scalp")
    args = ap.parse_args()

    coins = _liquid(args.top, args.min_vol)
    books = {c: ScalpBook() for c in coins}
    journals = {c: Journal(f"{args.state_prefix}_{c.lower()}") for c in coins}
    last_bar: dict[str, int] = {}
    trade_eq: dict[str, float] = {c: 1.0 for c in coins}       # compounding equity of the OPEN trade
    print(f"SCALP SHADOW (paper) armed: {len(coins)} coins, 1m bars, poll {args.interval}s -> "
          f"{args.state_prefix}_* (one ledger row per COMPLETED trade = its net return)", flush=True)

    while True:
        now_ms = int(time.time() * 1000)
        for coin in coins:
            try:
                bar = _last_closed_1m(coin, now_ms)
                if bar is None or bar[0] == last_bar.get(coin):
                    continue                                   # no new closed bar yet
                t, high, low, close = bar
                last_bar[coin] = t
                action, r = books[coin].observe(high, low, close)
                trade_eq[coin] *= (1.0 + r)                     # accrue entry/hold/exit bars
                if action.startswith("EXIT"):                  # trade closed -> log its net return
                    journals[coin].append_event({"kind": "scalp", "ts": int(t / 1000),
                                                  "r": trade_eq[coin] - 1.0, "exit": action})
                    print(f"[{coin}] trade closed {trade_eq[coin] - 1.0:+.3%} ({action})", flush=True)
                    trade_eq[coin] = 1.0
            except Exception as e:
                print(f"({coin} poll error: {str(e)[:50]})", flush=True)
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
