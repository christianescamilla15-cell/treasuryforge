"""Cross-venue funding-spread scan -- MEASURE if cross-venue carry is worth building.

Pulls current funding from Hyperliquid (/info, hourly) and Binance USD-M futures
(/fapi/v1/premiumIndex, 8h), normalises both to APR, and scores the delta-neutral
spread carry (short the high-funding venue, long the low) net of a DOUBLED round-trip.
If spreads are tiny (they usually are -- funding is arbitraged across venues), this is
another documented dead-end; if some are fat and would clear the gate, it's a YES to
investigate the executor.

    python scripts/cross_venue_scan.py --hold 168
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request

sys.path.insert(0, ".")

from treasuryforge.cross_venue import cross_venue_opp

HOURS_PER_YEAR = 24 * 365


def _get(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "treasuryforge/0.1"})
    with urllib.request.urlopen(req, timeout=25) as r:  # nosec B310 - fixed HTTPS literals
        return json.loads(r.read().decode())


def _post(url: str, body: dict):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json",
                                          "User-Agent": "treasuryforge/0.1"})
    with urllib.request.urlopen(req, timeout=25) as r:  # nosec B310
        return json.loads(r.read().decode())


def _hl_funding_apr() -> dict[str, float]:
    meta, ctxs = _post("https://api.hyperliquid.xyz/info", {"type": "metaAndAssetCtxs"})
    return {a["name"]: float(c.get("funding", 0.0)) * HOURS_PER_YEAR
            for a, c in zip(meta["universe"], ctxs)}


def _binance_funding_apr() -> dict[str, float]:
    # lastFundingRate is per 8h -> 3 payments/day
    rows = _get("https://fapi.binance.com/fapi/v1/premiumIndex")
    out = {}
    for r in rows:
        sym = r.get("symbol", "")
        if sym.endswith("USDT"):
            out[sym[:-4]] = float(r.get("lastFundingRate", 0.0)) * 3 * 365
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hold", type=int, default=168, help="expected holding period (hours)")
    ap.add_argument("--round-trip", type=float, default=0.0015, help="doubled cross-venue cost")
    ap.add_argument("--top", type=int, default=18)
    args = ap.parse_args()

    hl = _hl_funding_apr()
    try:
        bn = _binance_funding_apr()
    except Exception as e:
        print(f"Binance fetch failed ({type(e).__name__}: {e}) -- venue likely geo-blocked here.")
        return

    common = sorted(set(hl) & set(bn))
    opps = [cross_venue_opp(c, hl_apr=hl[c], other_apr=bn[c], hold_hours=args.hold,
                            round_trip=args.round_trip) for c in common]
    opps.sort(key=lambda o: o.spread_apr, reverse=True)

    print(f"CROSS-VENUE (HL vs Binance) -- {len(common)} common coins, hold {args.hold}h, "
          f"round-trip {args.round_trip*1e4:.0f}bps\n")
    print(f"  {'coin':6}{'HL APR':>9}{'BN APR':>9}{'spread':>9}{'short':>9}{'net(bps)':>10}  verdict")
    counts: dict[str, int] = {}
    for o in opps[: args.top]:
        counts[o.verdict] = counts.get(o.verdict, 0) + 1
        print(f"  {o.coin:6}{o.hl_apr:>+8.1%} {o.other_apr:>+8.1%} {o.spread_apr:>8.1%} "
              f"{o.short_venue:>9}{o.net_edge_bps:>+10.1f}  {o.verdict}")
    for o in opps[args.top:]:
        counts[o.verdict] = counts.get(o.verdict, 0) + 1
    tradeable = [o.coin for o in opps if o.verdict == "PAPER"]
    print(f"\nVERDICTS (all {len(opps)}): {dict(sorted(counts.items()))}")
    print(f"PAPER-worthy spreads: {tradeable if tradeable else 'NONE -- spreads too small / arbitraged'}")


if __name__ == "__main__":
    main()
