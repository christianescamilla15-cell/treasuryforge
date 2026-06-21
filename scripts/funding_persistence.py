"""Funding persistence analysis (Track C baseline) — from REAL Hyperliquid history.

For each coin it pulls historical hourly funding and measures how long high-funding
episodes last under the carry hysteresis. The carry thesis lives or dies here: at the
+10.95% cap a 2-leg round-trip breaks even in ~40h and reaches a comfortable PAPER in
~120h, so we want median episode durations in the DAYS, not hours. Keyless.

    python scripts/funding_persistence.py --coins HYPE,ZEC,UNI,ENA,BTC,ETH --days 45
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request

sys.path.insert(0, ".")

from treasuryforge.funding_persistence import funding_persistence
from treasuryforge.signals.funding import HyperliquidFundingFeed

HOURS_PER_YEAR = 24 * 365


def _hl_post(body: dict):
    req = urllib.request.Request("https://api.hyperliquid.xyz/info",
        data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "treasuryforge/0.1"})
    with urllib.request.urlopen(req, timeout=25) as r:  # nosec B310 - fixed HTTPS literal
        return json.loads(r.read().decode())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--coins", default="HYPE,ZEC,UNI,ENA,NEAR,BTC,ETH,SOL")
    ap.add_argument("--days", type=int, default=45)
    ap.add_argument("--enter", type=float, default=0.00001)     # ~8.8% APR
    ap.add_argument("--exit", type=float, default=0.000003)     # ~2.6% APR
    ap.add_argument("--breakeven", type=int, default=40, help="hours to cover the round-trip")
    args = ap.parse_args()

    feed = HyperliquidFundingFeed(_hl_post)
    start_ms = int((time.time() - args.days * 86400) * 1000)

    print(f"FUNDING PERSISTENCE -- {args.days}d history, enter>={args.enter*HOURS_PER_YEAR:.1%} APR, "
          f"break-even={args.breakeven}h\n")
    print(f"  {'coin':6}{'samples':>8}{'%high':>7}{'episodes':>9}{'median':>8}{'mean':>7}"
          f"{'>=BE':>7}  durations(h)")
    for coin in (c.strip() for c in args.coins.split(",")):
        hist = feed.funding_history(coin, start_ms)
        if not hist:
            print(f"  {coin:6}  (no history)")
            continue
        pct_high = sum(1 for f in hist if f >= args.enter) / len(hist)
        s = funding_persistence(hist, enter_rate=args.enter, exit_rate=args.exit,
                                breakeven_intervals=args.breakeven)
        top = sorted(s.durations, reverse=True)[:6]
        print(f"  {coin:6}{len(hist):>8}{pct_high:>7.0%}{s.n_episodes:>9}"
              f"{s.median_duration:>7.0f}h{s.mean_duration:>6.0f}h{s.pct_reach_breakeven:>7.0%}"
              f"  {top}{' [open]' if s.last_censored else ''}")
    print(f"\n(>=BE = share of episodes lasting >= {args.breakeven}h, enough to amortize the "
          "round-trip. Want medians in the DAYS for carry to be real.)")


if __name__ == "__main__":
    main()
