"""Show the cross-venue carry ECONOMICS for the live spreads (Roadmap v2 P1).

Pulls the live HL vs OKX funding spread for the candidates and runs the queen-metric
economics: gross spread -> net funding on notional -> NET APR ON TOTAL LOCKED CAPITAL
-> effective APR after a duty-cycle estimate. Makes the "30% gross != 30% return" gap
explicit. Keyless.

    python scripts/cross_venue_econ.py --coins XRP,ZEC --hold 336 --duty 0.5
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request

sys.path.insert(0, ".")

from treasuryforge.cross_venue_economics import HOURS_PER_YEAR, cross_venue_economics


def _get(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "treasuryforge/0.1"})
    with urllib.request.urlopen(req, timeout=25) as r:  # nosec B310
        return json.loads(r.read().decode())


def _post(url: str, body: dict):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json",
                                          "User-Agent": "treasuryforge/0.1"})
    with urllib.request.urlopen(req, timeout=25) as r:  # nosec B310
        return json.loads(r.read().decode())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--coins", default="XRP,ZEC")
    ap.add_argument("--hold", type=int, default=336, help="assumed hold (h)")
    ap.add_argument("--duty", type=float, default=0.5, help="opportunity duty cycle estimate")
    args = ap.parse_args()

    meta, ctxs = _post("https://api.hyperliquid.xyz/info", {"type": "metaAndAssetCtxs"})
    names = [a["name"] for a in meta["universe"]]
    print(f"CROSS-VENUE ECONOMICS (HL vs OKX) -- hold {args.hold}h, duty-cycle {args.duty:.0%}\n")
    print(f"  {'coin':5}{'gross APR':>10}{'amort cost':>11}{'net/notional':>13}"
          f"{'cap ratio':>10}{'NET/CAPITAL':>12}{'effective':>11}")
    for coin in (c.strip() for c in args.coins.split(",")):
        hl = float(ctxs[names.index(coin)]["funding"]) * HOURS_PER_YEAR
        okx = float(_get(f"https://www.okx.com/api/v5/public/funding-rate?instId={coin}-USDT-SWAP")
                    ["data"][0]["fundingRate"]) * 3 * 365
        spread = abs(hl - okx)
        e = cross_venue_economics(spread, hold_hours=args.hold)
        amort = "inf" if e.amortised_trade_cost_apr == float("inf") else f"{e.amortised_trade_cost_apr:+.1%}"
        print(f"  {coin:5}{spread:>+9.1%} {amort:>11}{e.net_funding_apr_on_notional:>+12.1%} "
              f"{e.total_locked_ratio:>9.2f}{e.net_apr_on_total_capital:>+11.1%}"
              f"{e.effective_apr(args.duty):>+11.1%}")
    print("\n(NET/CAPITAL is the queen metric -- net on TOTAL locked capital, 2x for dual collateral."
          " effective = that x duty-cycle. The gross spread is NOT the return.)")


if __name__ == "__main__":
    main()
