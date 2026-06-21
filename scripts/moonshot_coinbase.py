"""Moonshot test on COINBASE -- Christian's 11,000% thesis where he actually traded.

Runs the ignition + LET-IT-RUN (wide trailing) rule across the whole Coinbase USD universe
(majors skipped; they don't ignite +15%/1h), over months of 1h candles, and reports the FULL
distribution + expected value per bet + the fat tail -- the only honest judge of a convex
lottery strategy. CAVEAT: only LIVE Coinbase products -> delisted coins absent -> OPTIMISTIC.
No capital.

    python scripts/moonshot_coinbase.py --days 120 --enter 0.15
"""

from __future__ import annotations

import argparse
import statistics as st
import sys

sys.path.insert(0, ".")

from _coinbase import klines_1h, usd_products

from treasuryforge.momentum_backtest import backtest_momentum
from treasuryforge.signals.momentum import MomentumParams

MAJORS = {"BTC", "ETH", "SOL", "XRP", "DOGE", "ADA", "AVAX", "LINK", "LTC", "BCH", "DOT",
          "MATIC", "UNI", "ATOM", "ETC", "XLM", "USDT", "USDC", "DAI", "EUR", "GBP"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=120)
    ap.add_argument("--enter", type=float, default=0.15, help="1h ignition return to enter")
    ap.add_argument("--trail", type=float, default=0.40, help="WIDE trailing (let it run)")
    ap.add_argument("--stop", type=float, default=0.30)
    ap.add_argument("--cost", type=float, default=0.005)
    ap.add_argument("--limit", type=int, default=400, help="max products to scan")
    args = ap.parse_args()

    prods = [p for p in usd_products() if p.split("-")[0] not in MAJORS][: args.limit]
    print(f"COINBASE: scanning {len(prods)} non-major USD products, {args.days}d of 1h", flush=True)
    print("CAVEAT: delisted coins absent -> OPTIMISTIC\n", flush=True)
    p = MomentumParams(enter_1m=args.enter, confirm_1m=0.0, trail_frac=args.trail,
                       stop_frac=args.stop, max_hold=args.days * 24, cost=args.cost)
    trades: list[float] = []
    loaded = 0
    for prod in prods:
        bars = klines_1h(prod, args.days)
        if len(bars) < 48:
            continue
        loaded += 1
        trades.extend(backtest_momentum(bars, p).returns)
    n = len(trades)
    if not n:
        print("no trades / no data")
        return

    wins = [t for t in trades if t > 0]
    losers = [t for t in trades if t <= 0]
    ev = st.mean(trades)
    eq = 1.0
    for t in trades:
        eq *= 1.0 + t / n
    print(f"coins with data: {loaded}   signals (bets): {n}", flush=True)
    print(f"win rate: {len(wins)/n:.0%}   avg win: {st.mean(wins) if wins else 0:+.1%}   "
          f"avg loss: {st.mean(losers) if losers else 0:+.1%}", flush=True)
    print(f"\nEXPECTED VALUE per bet (net of {args.cost:.1%} cost): {ev:+.2%}", flush=True)
    print(f"equal-1/{n}-stake portfolio total: {eq-1:+.1%}", flush=True)
    print("\n-- the fat tail (the whole game) --", flush=True)
    for thr, lbl in ((99.0, ">=100x"), (9.0, ">=10x"), (4.0, ">=5x"), (1.0, ">=2x"), (0.0, ">0")):
        k = sum(1 for t in trades if t >= thr)
        print(f"  bets {lbl:7}: {k:4d}  ({k/n:.1%})", flush=True)
    for thr in (-0.5, -0.9):
        k = sum(1 for t in trades if t <= thr)
        print(f"  bets <= {thr*100:.0f}% : {k:4d}  ({k/n:.1%})", flush=True)
    print(f"  best bet: {max(trades):+.0%}   worst: {min(trades):+.0%}", flush=True)
    pos = "POSITIVE -- the tail pays for the losers (optimistic; delisted absent -> real lower)"
    neg = "NEGATIVE -- losers eat the moonshots, even before counting delisted coins"
    print(f"\nVERDICT: EV {pos if ev > 0 else neg}", flush=True)


if __name__ == "__main__":
    main()
