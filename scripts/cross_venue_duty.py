"""Measure the REAL opportunity duty cycle for cross-venue spreads (Roadmap v2 P6).

Builds the HL-vs-OKX spread-APR series from real funding history (HL hourly, OKX 8h,
aligned to the OKX grid by nearest timestamp) and reports: what fraction of the window
the spread cleared the net break-even, the mean spread while on, and the longest streak.
This is the honest answer to "how much of the month is the edge actually ON". Keyless.

    python scripts/cross_venue_duty.py --coins XRP,ZEC --hold 336
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request

sys.path.insert(0, ".")

from treasuryforge.cross_venue_economics import HOURS_PER_YEAR, breakeven_spread_apr
from treasuryforge.opportunity_duty_cycle import opportunity_duty_cycle


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


def _hl_hist(coin):
    rows = _post("https://api.hyperliquid.xyz/info", {"type": "fundingHistory", "coin": coin, "startTime": 0})
    return sorted((int(r["time"]), float(r["fundingRate"]) * HOURS_PER_YEAR) for r in rows)


def _okx_hist(coin):
    d = _get(f"https://www.okx.com/api/v5/public/funding-rate-history?instId={coin}-USDT-SWAP&limit=100")
    return sorted((int(r["fundingTime"]), float(r["fundingRate"]) * 3 * 365) for r in d["data"])


def _nearest(hl, t):
    return min(hl, key=lambda x: abs(x[0] - t))[1] if hl else 0.0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--coins", default="XRP,ZEC")
    ap.add_argument("--hold", type=int, default=336)
    args = ap.parse_args()
    be = breakeven_spread_apr(args.hold)

    print(f"CROSS-VENUE DUTY CYCLE (HL vs OKX) -- break-even spread {be:.1%} APR (hold {args.hold}h)\n")
    print(f"  {'coin':5}{'samples':>8}{'span(d)':>8}{'duty':>7}{'mean-on':>9}{'max-streak':>11}")
    for coin in (c.strip() for c in args.coins.split(",")):
        hl, okx = _hl_hist(coin), _okx_hist(coin)
        if not okx:
            print(f"  {coin:5}  (no OKX history)")
            continue
        spreads = [abs(_nearest(hl, t) - okx_apr) for t, okx_apr in okx]
        span_d = (okx[-1][0] - okx[0][0]) / 86400000.0 if len(okx) >= 2 else 0.0
        d = opportunity_duty_cycle(spreads, breakeven_apr=be)
        print(f"  {coin:5}{d.n:>8}{span_d:>8.0f}{d.fraction:>7.0%}{d.mean_spread_when_on:>+9.1%}"
              f"{d.max_consecutive_on:>9} x8h")
    print("\n(duty = share of 8h windows with spread above break-even. A high gross that is"
          " rarely ON is worthless; effective APR = economics x duty. max-streak = realistic hold.)")


if __name__ == "__main__":
    main()
