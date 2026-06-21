"""Build the local market 'BD' from REAL Hyperliquid data (keyless, no funds).

    python scripts/build_market_db.py --coins BTC,ETH,SOL --days 120

Populates market.db with real candles + funding + a live L2 depth snapshot per
coin — the high-fidelity dataset to backtest / replay / stress against before
ever touching prod. Real volumetry, not a toy random walk.
"""

from __future__ import annotations

import argparse
import sys
import time

sys.path.insert(0, ".")

from treasuryforge.marketlab import MarketStore


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="market.db")
    ap.add_argument("--coins", default="BTC,ETH,SOL")
    ap.add_argument("--days", type=int, default=120)
    ap.add_argument("--interval", default="1h")
    args = ap.parse_args()

    s = MarketStore(args.db)
    for coin in (c.strip() for c in args.coins.split(",")):
        nc = s.sync_candles(coin, args.interval, args.days)
        nf = s.sync_funding(coin, args.days)
        nb = s.snapshot_orderbook(coin, int(time.time() * 1000), s.fetch_orderbook(coin))
        print(f"{coin}: {nc} candles, {nf} funding rows, {nb} L2 depth levels")

    print("\nDB summary:", s.summary())
    print(f"-> {args.db} ready — real market data to test against before prod")


if __name__ == "__main__":
    main()
