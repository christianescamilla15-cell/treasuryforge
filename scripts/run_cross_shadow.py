"""Cross-venue spread shadow (forward-test) -- the XRP/ZEC HL-vs-Binance carry, NO funds.

The cross-venue carry is just a funding carry whose "funding" is the per-hour SPREAD
between venues (short the higher-funding venue, long the lower -> net = the gap). So it
reuses ShadowBook + the age-rule unchanged: feed it spread_hourly = |hl_hr - bn_hr| and
the cross-venue cost (4 legs, ~15bps round-trip). Persists per coin to state/cross_<coin>
so it accumulates the live track record that validates whether the ~30% snapshot spread
actually PERSISTS forward. Keyless (HL /info + Binance public funding).

    python scripts/run_cross_shadow.py --coins XRP,ZEC
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request

sys.path.insert(0, ".")

from treasuryforge.journal import Journal
from treasuryforge.shadow import ShadowBook
from treasuryforge.signals.funding import FundingCarryParams, FundingCarrySignal, annualize

HOURS_PER_YEAR = 24 * 365


def _get(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "treasuryforge/0.1"})
    with urllib.request.urlopen(req, timeout=25) as r:  # nosec B310
        return json.loads(r.read().decode())


def _hl_post(body: dict):
    req = urllib.request.Request("https://api.hyperliquid.xyz/info",
        data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "treasuryforge/0.1"})
    with urllib.request.urlopen(req, timeout=25) as r:  # nosec B310
        return json.loads(r.read().decode())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--coins", default="XRP,ZEC")
    ap.add_argument("--state-prefix", default="state/cross")
    ap.add_argument("--enter-spread-apr", type=float, default=0.20, help="enter when spread >= this APR")
    ap.add_argument("--exit-spread-apr", type=float, default=0.05)
    ap.add_argument("--round-trip", type=float, default=0.0015, help="cross-venue 4-leg cost")
    ap.add_argument("--min-age", type=int, default=24)
    args = ap.parse_args()

    # map APR thresholds -> per-hour, and round-trip -> fee_per_leg (4 legs)
    enter_hr = args.enter_spread_apr / HOURS_PER_YEAR
    exit_hr = args.exit_spread_apr / HOURS_PER_YEAR
    params = FundingCarryParams(enter_rate=enter_hr, exit_rate=exit_hr,
                                fee_per_leg=args.round_trip / 4, legs_round_trip=4)

    meta, ctxs = _hl_post({"type": "metaAndAssetCtxs"})
    names = [a["name"] for a in meta["universe"]]
    ts = int(time.time())
    for coin in (c.strip() for c in args.coins.split(",")):
        hl_hr = float(ctxs[names.index(coin)]["funding"])
        # OKX (reachable from the VPS; Binance is geo-blocked 451 here). 8h funding -> per hour.
        okx = _get(f"https://www.okx.com/api/v5/public/funding-rate?instId={coin}-USDT-SWAP")
        ox_hr = float(okx["data"][0]["fundingRate"]) / 8.0
        spread_hr = abs(hl_hr - ox_hr)                       # net of the favorable direction
        short_venue = "HL" if hl_hr >= ox_hr else "OKX"
        book = ShadowBook(FundingCarrySignal(params, min_age=args.min_age),
                          journal=Journal(f"{args.state_prefix}_{coin.lower()}"))
        action = book.observe(spread_hr, ts=ts)
        rep = book.report()
        print(f"[{coin:5}] spread {annualize(spread_hr, HOURS_PER_YEAR):+.1%} APR (short {short_venue}) "
              f"-> {action.value:5}  net {rep.net_return:+.4%}  ({rep.n_intervals} obs, {rep.n_hold} held)")


if __name__ == "__main__":
    main()
