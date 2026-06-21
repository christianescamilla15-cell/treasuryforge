"""Live carry screener (Roadmap A3) — rank the universe by NET edge, gate on cost.

Keyless. For each coin it pulls funding + premium (mark vs oracle), the live spread
(l2 book) and realized hourly vol (recent candles), then scores net edge = expected
funding over the hold + contango convergence - REALISTIC maker-first round-trip cost.
Verdicts: NO_TRADE / WATCH / PAPER (risk-gate verdicts MICRO/LIVE need the shadow DSR).

    python scripts/carry_screen.py --coins BTC,ETH,SOL,AVAX,ARB --hold 24

This is the cost-gate the churning shadow lacks: it only says PAPER when the funding it
can actually collect over the hold beats the round-trip cost.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
import urllib.request

sys.path.insert(0, ".")

from treasuryforge.carry_screener import ScreenParams, screen
from treasuryforge.universe import liquid_candidates

HOURS_PER_YEAR = 24 * 365


def _hl_post(body: dict):
    req = urllib.request.Request("https://api.hyperliquid.xyz/info",
        data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "treasuryforge/0.1"})
    with urllib.request.urlopen(req, timeout=25) as r:  # nosec B310 - fixed HTTPS literal
        return json.loads(r.read().decode())


def _spread(coin: str) -> float:
    book = _hl_post({"type": "l2Book", "coin": coin})
    levels = book.get("levels", [[], []])
    if not levels[0] or not levels[1]:
        return 0.001
    bid, ask = float(levels[0][0]["px"]), float(levels[1][0]["px"])
    mid = (bid + ask) / 2.0
    return (ask - bid) / mid if mid > 0 else 0.001


def _hourly_vol(coin: str) -> float:
    now = int(time.time() * 1000)
    candles = _hl_post({"type": "candleSnapshot", "req": {
        "coin": coin, "interval": "1h", "startTime": now - 48 * 3600 * 1000, "endTime": now}})
    closes = [float(c["c"]) for c in candles][-25:]
    if len(closes) < 3:
        return 0.001
    rets = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes)) if closes[i - 1] > 0]
    mean = sum(rets) / len(rets)
    return (sum((x - mean) ** 2 for x in rets) / len(rets)) ** 0.5


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--coins", default="BTC,ETH,SOL,AVAX,ARB")
    ap.add_argument("--universe", action="store_true", help="scan ALL liquid perps")
    ap.add_argument("--min-vol-usd", type=float, default=5e6, help="daily volume floor (universe)")
    ap.add_argument("--top", type=int, default=15, help="deep-screen the top-N by funding")
    ap.add_argument("--hold", type=int, default=24, help="expected holding period (hours)")
    ap.add_argument("--legs", type=int, default=4, help="2 = perp overlay on held spot; 4 = fresh")
    args = ap.parse_args()
    params = ScreenParams(hold_hours=args.hold, legs=args.legs)

    data = _hl_post({"type": "metaAndAssetCtxs"})
    if args.universe:
        cands = liquid_candidates(data, min_vol_usd=args.min_vol_usd, top=args.top)
        print(f"universe: {len(data[1])} perps, {len(cands)} liquid (>${args.min_vol_usd:,.0f}/day),"
              f" deep-screening top {len(cands)} by funding")
    else:
        names = [a["name"] for a in data[0]["universe"]]
        cands = []
        for coin in (c.strip() for c in args.coins.split(",")):
            c = data[1][names.index(coin)]
            mark, oracle = float(c.get("markPx", 0.0)), float(c.get("oraclePx", 0.0))
            cands.append({"coin": coin, "funding": float(c["funding"]),
                          "premium": (mark - oracle) / oracle if oracle > 0 else 0.0})

    candidates = []
    for c in cands:
        candidates.append({"coin": c["coin"], "funding": c["funding"], "premium": c["premium"],
                           "spread": _spread(c["coin"]), "vol": _hourly_vol(c["coin"])})
        time.sleep(0.1)

    ranked = screen(candidates, params)
    print(f"CARRY SCREENER -- hold {args.hold}h, legs {args.legs}, n_candidates={len(ranked)} "
          f"(= n_trials for any downstream DSR)\n")
    print(f"  {'coin':5}{'fund APR':>9}{'premium':>9}{'spread':>8}{'vol/hr':>8}"
          f"{'gross':>8}{'cost':>8}{'net':>8}  verdict")
    counts: dict[str, int] = {}
    for o in ranked:
        counts[o.verdict.value] = counts.get(o.verdict.value, 0) + 1
        cand = next(c for c in candidates if c["coin"] == o.coin)
        print(f"  {o.coin:5}{o.funding_apr:>+8.2%} {o.expected_convergence:>+8.4%} "
              f"{cand['spread']:>7.4%}{cand['vol']:>8.4f}"
              f"{o.gross * 1e4:>+7.1f}{o.round_trip_cost * 1e4:>8.1f}{o.net_edge_bps:>+8.1f}  {o.verdict.value}")
    tradeable = [o.coin for o in ranked if o.verdict.value in ("PAPER", "MICRO_ELIGIBLE", "LIVE_ELIGIBLE")]
    print(f"\nVERDICTS: {dict(sorted(counts.items()))}")
    print(f"TRADEABLE NOW (PAPER+): {tradeable if tradeable else 'NONE -- no carry clears the cost-gate'}")
    print("\n(bps over the hold. NET = funding-over-hold + contango convergence - realistic "
          "maker-first round-trip. PAPER+ requires NET > 0 and costs < 35% of gross.)")


if __name__ == "__main__":
    main()
