"""Scalp/momentum movers monitor (read-only intel, no orders) -- what is MOVING right now
on the liquid Hyperliquid perps: short-window momentum (1/5/15/30 min from 1m candles),
funding APR, 24h move, $ volume and open interest. The cockpit screen a discretionary
scalper refreshes; it INFORMS your calls, it does not place them.

    python scripts/scalp_monitor.py            # top movers by 5-min momentum
    python scripts/scalp_monitor.py --top 20 --by 15m

Keyless. Honest at $20: HL round-trip is ~9bps taker, so a scalp must clear ~9bps net to
win; this screen helps you pick moves big/liquid enough to bother.
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.request

_H = 24 * 365


def _post(body: dict) -> object:
    req = urllib.request.Request("https://api.hyperliquid.xyz/info",
                                 data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": "tf/0.1"})
    with urllib.request.urlopen(req, timeout=20) as r:  # nosec B310
        return json.loads(r.read().decode())


def _mom(closes: list[float], n: int) -> float:
    """% change over the last n 1-min candles (0 if not enough history)."""
    if len(closes) <= n or closes[-n - 1] == 0:
        return 0.0
    return closes[-1] / closes[-n - 1] - 1.0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--by", default="5m", choices=["1m", "5m", "15m", "30m"])
    ap.add_argument("--min-vol", type=float, default=5_000_000, help="min 24h $ volume")
    args = ap.parse_args()

    meta, ctxs = _post({"type": "metaAndAssetCtxs"})
    rows = []
    for a, c in zip(meta["universe"], ctxs):
        vol = float(c.get("dayNtlVlm", 0) or 0)
        if vol < args.min_vol:
            continue
        mark = float(c.get("markPx", 0) or 0)
        prev = float(c.get("prevDayPx", 0) or 0)
        rows.append({"coin": a["name"], "mark": mark, "vol": vol,
                     "oi": float(c.get("openInterest", 0) or 0) * mark,
                     "funding_apr": float(c.get("funding", 0) or 0) * _H,
                     "chg24h": (mark / prev - 1.0) if prev else 0.0})

    rows.sort(key=lambda r: r["vol"], reverse=True)
    pool = rows[:40]                                       # only fetch candles for the liquid pool
    now_ms = int(time.time() * 1000)
    start = now_ms - 35 * 60 * 1000
    for r in pool:
        try:
            cs = _post({"type": "candleSnapshot",
                        "req": {"coin": r["coin"], "interval": "1m", "startTime": start, "endTime": now_ms}})
            closes = [float(k["c"]) for k in cs]
            r["m1"], r["m5"], r["m15"], r["m30"] = (_mom(closes, 1), _mom(closes, 5),
                                                    _mom(closes, 15), _mom(closes, 30))
        except Exception:
            r["m1"] = r["m5"] = r["m15"] = r["m30"] = 0.0

    key = {"1m": "m1", "5m": "m5", "15m": "m15", "30m": "m30"}[args.by]
    pool.sort(key=lambda r: abs(r.get(key, 0.0)), reverse=True)

    print(f"HL SCALP MONITOR  (movers by |{args.by}| momentum, liquid >{args.min_vol/1e6:.0f}M/24h)")
    print(f"  {'coin':7}{'price':>11}{'1m':>8}{'5m':>8}{'15m':>8}{'30m':>8}"
          f"{'fund%':>8}{'24h':>8}{'vol$M':>8}{'OI$M':>8}")
    for r in pool[:args.top]:
        print(f"  {r['coin']:7}{r['mark']:>11.4g}{r.get('m1',0):>+8.2%}{r.get('m5',0):>+8.2%}"
              f"{r.get('m15',0):>+8.2%}{r.get('m30',0):>+8.2%}{r['funding_apr']:>+8.0%}"
              f"{r['chg24h']:>+8.1%}{r['vol']/1e6:>8.0f}{r['oi']/1e6:>8.0f}")
    print("  momentum = % move over the window; fund% = funding APR (sign = who pays);")
    print("  a scalp needs to clear ~9bps round-trip -- favour big moves on deep books.")


if __name__ == "__main__":
    main()
