"""Live shadow runner for the spot-vs-perp BASIS carry across MANY coins — NO funds.

One invocation = one (funding, premium) observation per coin, each persisted to its
own journal (state/basis_<coin>). Runs alongside the funding-carry shadow as a SECOND,
independent strategy track record (it also captures premium convergence). Keyless.

    python scripts/run_shadow_basis.py --coins BTC,ETH,SOL,AVAX,ARB
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request

sys.path.insert(0, ".")

from treasuryforge.carry_screener import ScreenParams, screen_coin
from treasuryforge.journal import Journal
from treasuryforge.shadow_basis import BasisBook
from treasuryforge.signals.basis import BasisParams, BasisSignal
from treasuryforge.signals.funding import HyperliquidFundingFeed, annualize

HOURS_PER_YEAR = 24 * 365


def _hl_post(body: dict):
    req = urllib.request.Request("https://api.hyperliquid.xyz/info",
        data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "treasuryforge/0.1"})
    with urllib.request.urlopen(req, timeout=25) as r:  # nosec B310 - fixed HTTPS literal
        return json.loads(r.read().decode())


def _spread(coin: str) -> float:
    levels = _hl_post({"type": "l2Book", "coin": coin}).get("levels", [[], []])
    if not levels[0] or not levels[1]:
        return 0.001
    bid, ask = float(levels[0][0]["px"]), float(levels[1][0]["px"])
    mid = (bid + ask) / 2.0
    return (ask - bid) / mid if mid > 0 else 0.001


def _hourly_vol(coin: str) -> float:
    import math
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
    ap.add_argument("--coins", default="ETH")
    ap.add_argument("--state-prefix", default="state/basis")
    ap.add_argument("--enter-premium", type=float, default=0.0002)  # 0.02% perp-over-spot to ENTER
    ap.add_argument("--exit-premium", type=float, default=0.00002)  # ~converged to EXIT
    ap.add_argument("--fee-per-leg", type=float, default=0.0003)
    ap.add_argument("--legs", type=int, default=2, help="2 = perp overlay on held spot; 4 = fresh")
    ap.add_argument("--gate-hold", type=int, default=24)
    args = ap.parse_args()

    params = BasisParams(enter_premium=args.enter_premium, exit_premium=args.exit_premium,
                         fee_per_leg=args.fee_per_leg)
    screen = ScreenParams(hold_hours=args.gate_hold, legs=args.legs)
    feed = HyperliquidFundingFeed(_hl_post)
    ts = int(time.time())

    for coin in (c.strip() for c in args.coins.split(",")):
        book = BasisBook(BasisSignal(params), journal=Journal(f"{args.state_prefix}_{coin.lower()}"))
        funding, premium = feed.current_basis(coin)
        gate = ""
        allow_entry = True
        if not book.signal.in_position and premium >= args.enter_premium:
            opp = screen_coin(coin, funding=funding, premium=premium,
                              spread=_spread(coin), vol=_hourly_vol(coin), params=screen)
            allow_entry = opp.net_edge > 0
            gate = f"  [gate {opp.verdict.value} net {opp.net_edge_bps:+.1f}bps]"
        action = book.observe(funding, premium, ts=ts, allow_entry=allow_entry)
        rep = book.report()
        print(f"[{coin:5}] premium={premium:+.6%}  funding={funding:+.8f}/hr "
              f"({annualize(funding, HOURS_PER_YEAR):+.2%} APR) -> {action.value:5}{gate}  "
              f"net {rep.net_return:+.4%}  (conv {rep.realized_convergence:+.5f}, "
              f"{rep.n_intervals} obs, {rep.n_hold} held)")


if __name__ == "__main__":
    main()
