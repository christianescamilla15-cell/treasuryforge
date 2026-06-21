"""Moonshot hunt -- does catching explosive micro-cap pumps have positive EV (Christian's
11,000% thesis), measured HONESTLY across the whole universe including the losers?

This is the test the earlier validation skipped: it filtered to liquid majors and a tight
trailing exit, which throws away exactly the universe (micro-caps / new listings) and the
exit (let-it-run) where 100x moves live. Here:
  - universe = the SMALLEST-volume perps (where pumps and rugs both live), not the majors;
  - exit = a WIDE trailing stop, so a winner is allowed to run into the fat tail instead of
    being clipped at the first 8% pullback;
  - the report is the FULL DISTRIBUTION + expected value per bet, because a convex / lottery
    strategy is judged by whether the rare fat-tail winners pay for the many losers -- NOT by
    win rate or Sharpe.

HONESTY CAVEAT, stated loudly: Binance exchangeInfo lists only LIVE symbols, so fully
delisted rugs are MISSING from the universe. This biases the result OPTIMISTIC. If EV is
negative even here, that is decisive; if positive, the true (survivorship-corrected) number
is lower. Read-only research, no capital.

    python scripts/moonshot_scan.py --months 2026-03,2026-04,2026-05 --n-small 100
"""

from __future__ import annotations

import argparse
import json
import statistics as st
import sys
import urllib.request

sys.path.insert(0, ".")

from _klines import download

from treasuryforge.momentum_backtest import backtest_momentum
from treasuryforge.signals.momentum import MomentumParams


def _smallest_perps(n: int) -> list[str]:
    """The n lowest-24h-volume USDT perps -- the micro-cap universe (pumps + rugs)."""
    req = urllib.request.Request("https://fapi.binance.com/fapi/v1/ticker/24hr",
                                 headers={"User-Agent": "tf/0.1"})
    data = json.load(urllib.request.urlopen(req, timeout=20))  # nosec B310
    vols = [(d["symbol"][:-4], float(d.get("quoteVolume", 0.0)))
            for d in data if d.get("symbol", "").endswith("USDT")]
    vols = [(c, v) for c, v in vols if v > 0]
    vols.sort(key=lambda x: x[1])
    return [c for c, _ in vols[:n]]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", default="2026-03,2026-04,2026-05")
    ap.add_argument("--n-small", type=int, default=100, help="how many smallest-vol perps")
    ap.add_argument("--enter", type=float, default=0.03, help="ignition: 1m return to enter")
    ap.add_argument("--trail", type=float, default=0.40, help="WIDE trailing stop (let it run)")
    ap.add_argument("--stop", type=float, default=0.30, help="hard stop below entry")
    ap.add_argument("--max-hold", type=int, default=10080, help="bars (10080 = 7 days of 1m)")
    ap.add_argument("--cost", type=float, default=0.003, help="round-trip incl micro-cap slippage")
    args = ap.parse_args()
    months = [m.strip() for m in args.months.split(",")]

    coins = _smallest_perps(args.n_small)
    print(f"universe: {len(coins)} SMALLEST-volume perps, {len(months)} months", flush=True)
    print("CAVEAT: delisted rugs are absent -> result is OPTIMISTIC\n", flush=True)
    p = MomentumParams(enter_1m=args.enter, confirm_1m=0.0, trail_frac=args.trail,
                       stop_frac=args.stop, max_hold=args.max_hold, cost=args.cost)
    trades: list[float] = []
    loaded = 0
    for c in coins:
        bars = [b for m in months for b in download(c, m)]
        if len(bars) < 100:
            continue
        loaded += 1
        trades.extend(backtest_momentum(bars, p).returns)
    n = len(trades)
    if not n:
        print("no trades")
        return

    wins = [t for t in trades if t > 0]
    losers = [t for t in trades if t <= 0]
    ev = st.mean(trades)
    # equal tiny stake on every signal -> the portfolio's compounded result
    eq = 1.0
    for t in trades:
        eq *= 1.0 + t / n              # 1/n of capital per bet (diversified across all signals)
    print(f"coins with data: {loaded}   signals (bets): {n}", flush=True)
    print(f"win rate: {len(wins)/n:.0%}   avg win: {st.mean(wins) if wins else 0:+.1%}   "
          f"avg loss: {st.mean(losers) if losers else 0:+.1%}", flush=True)
    print(f"\nEXPECTED VALUE per bet (net of {args.cost:.1%} cost): {ev:+.2%}", flush=True)
    print(f"equal-1/{n}-stake portfolio total: {eq-1:+.1%}", flush=True)
    print("\n-- the tail (the whole game for a convex strategy) --", flush=True)
    for thr in (10, 5, 2, 1):
        k = sum(1 for t in trades if t >= thr)
        print(f"  bets returning >= {thr*100:5.0f}% : {k:3d}  ({k/n:.1%})", flush=True)
    for thr in (-0.5, -0.9):
        k = sum(1 for t in trades if t <= thr)
        print(f"  bets returning <= {thr*100:5.0f}% : {k:3d}  ({k/n:.1%})", flush=True)
    print(f"  best bet: {max(trades):+.0%}   worst: {min(trades):+.0%}", flush=True)
    print(f"\nVERDICT: EV {'POSITIVE -- the tail pays for the losers (optimistic; rugs missing)' if ev > 0 else 'NEGATIVE -- the losers eat the moonshots, even before counting delisted rugs'}",
          flush=True)


if __name__ == "__main__":
    main()
