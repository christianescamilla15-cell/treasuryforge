"""Scalp ignition alerter (read-only, no orders) -- emits ONE line when any liquid HL perp
moves more than --pct within the --window, so you don't have to stare at the screen. Polls
all-mids (one cheap call) every --interval seconds; each fresh ignition is one stdout line
(flushed), so it drops straight into a terminal OR the harness Monitor for in-chat pings.

    python scripts/scalp_alert.py --pct 0.5 --window 300      # 0.5% in 5 min
    python scripts/scalp_alert.py --pct 0.8 --window 120 --interval 15

A coin re-alerts only after it falls back under the threshold (no spam while it trends).
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.request

_H = 24 * 365


def _post(body: dict):
    req = urllib.request.Request("https://api.hyperliquid.xyz/info",
        data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "treasuryforge/0.1"})
    with urllib.request.urlopen(req, timeout=15) as r:  # nosec B310
        return json.loads(r.read().decode())


def _liquid(min_vol: float) -> dict[str, float]:
    """{coin: funding_apr} for perps with 24h volume above the floor."""
    meta, ctxs = _post({"type": "metaAndAssetCtxs"})
    out = {}
    for a, c in zip(meta["universe"], ctxs):
        if float(c.get("dayNtlVlm", 0) or 0) >= min_vol:
            out[a["name"]] = float(c.get("funding", 0) or 0) * _H
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pct", type=float, default=0.5, help="ignition threshold, percent")
    ap.add_argument("--window", type=int, default=300, help="lookback seconds")
    ap.add_argument("--interval", type=int, default=20, help="poll seconds")
    ap.add_argument("--min-vol", type=float, default=5_000_000)
    args = ap.parse_args()

    funding = _liquid(args.min_vol)
    hist: dict[str, list[tuple[float, float]]] = {}      # coin -> [(ts, price)]
    armed: dict[str, bool] = {}                          # coin -> ready to alert (fell back under)
    last_ctx = time.time()
    print(f"SCALP ALERT armed: |move| > {args.pct}% in {args.window}s, {len(funding)} liquid perps, "
          f"poll {args.interval}s", flush=True)

    while True:
        try:
            mids = _post({"type": "allMids"})
            now = time.time()
            if now - last_ctx > 300:                      # refresh liquid set + funding every 5 min
                funding = _liquid(args.min_vol)
                last_ctx = now
            for coin in funding:
                px = float(mids.get(coin, 0) or 0)
                if px <= 0:
                    continue
                h = hist.setdefault(coin, [])
                h.append((now, px))
                while h and now - h[0][0] > args.window + args.interval:
                    h.pop(0)
                ref = next((p for t, p in h if now - t >= args.window), h[0][1] if h else px)
                chg = px / ref - 1.0 if ref else 0.0
                if abs(chg) >= args.pct / 100 and armed.get(coin, True):
                    arrow = "UP " if chg > 0 else "DOWN"
                    print(f"IGNITION {arrow} {coin:7} {chg:+.2%} in {args.window // 60}m  "
                          f"px {px:.4g}  funding {funding[coin]:+.0%}", flush=True)
                    armed[coin] = False
                elif abs(chg) < args.pct / 100 * 0.6:     # re-arm once it cools well under
                    armed[coin] = True
        except Exception as e:
            print(f"(poll error: {str(e)[:60]})", flush=True)
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
