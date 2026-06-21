"""Cross-venue spread persistence + liquidity (Roadmap b, the rigor layer).

The snapshot scan found 57 PAPER coins with 40-130% APR spreads -- but all illiquid
alts, and a snapshot annualizes an instantaneous rate (likely a transient spike). This
applies the same discipline that closed single-venue carry:

  1. LIQUIDITY: keep only coins liquid on BOTH venues (HL daily volume + Binance 24h
     quote volume floors) -- where a ~15bp round-trip is even defensible.
  2. PERSISTENCE: compare the SNAPSHOT spread to the MEAN realized spread over ~20 days
     of funding history (position fixed by the snapshot direction). If the mean << the
     snapshot, the snapshot was a spike and there is no edge.
  3. REALISTIC GATE: score the net edge with the MEAN spread, not the snapshot.

A liquid coin whose MEAN spread clears the gate is a real cross-venue candidate; if
none do, cross-venue joins the documented dead-ends. Keyless reads only.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request

sys.path.insert(0, ".")

from treasuryforge.cross_venue import cross_venue_opp
from treasuryforge.signals.funding import HyperliquidFundingFeed

HOURS_PER_YEAR = 24 * 365


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


def _mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def _bn_funding_hist_apr(symbol: str) -> float:
    rows = _get(f"https://fapi.binance.com/fapi/v1/fundingRate?symbol={symbol}&limit=60")
    rates = [float(r["fundingRate"]) for r in rows]      # 8h rates
    return _mean(rates) * 3 * 365


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hold", type=int, default=168)
    ap.add_argument("--round-trip", type=float, default=0.0015)
    ap.add_argument("--hl-vol", type=float, default=20e6, help="HL daily $vol floor")
    ap.add_argument("--bn-vol", type=float, default=50e6, help="Binance 24h $vol floor")
    ap.add_argument("--min-snap-spread", type=float, default=0.20, help="pre-filter snapshot spread APR")
    args = ap.parse_args()

    meta, ctxs = _post("https://api.hyperliquid.xyz/info", {"type": "metaAndAssetCtxs"})
    hl = {a["name"]: {"funding": float(c.get("funding", 0.0)) * HOURS_PER_YEAR,
                      "vol": float(c.get("dayNtlVlm", 0.0))}
          for a, c in zip(meta["universe"], ctxs)}
    try:
        bn_tick = {t["symbol"]: float(t.get("quoteVolume", 0.0))
                   for t in _get("https://fapi.binance.com/fapi/v1/ticker/24hr")}
        bn_snap = {t["symbol"]: float(t.get("lastFundingRate", 0.0)) * 3 * 365
                   for t in _get("https://fapi.binance.com/fapi/v1/premiumIndex")}
    except Exception as e:
        print(f"Binance fetch failed ({type(e).__name__}: {e}) -- venue likely geo-blocked.")
        return

    # liquid on both + a meaningful snapshot spread = worth the deep history pull
    cands = []
    for coin, d in hl.items():
        sym = coin + "USDT"
        if d["vol"] < args.hl_vol or bn_tick.get(sym, 0) < args.bn_vol or sym not in bn_snap:
            continue
        if abs(d["funding"] - bn_snap[sym]) < args.min_snap_spread:
            continue
        cands.append((coin, sym))

    feed = HyperliquidFundingFeed(lambda b: _post("https://api.hyperliquid.xyz/info", b))
    print(f"CROSS-VENUE PERSISTENCE -- liquid both venues (HL>${args.hl_vol:,.0f}, BN>${args.bn_vol:,.0f}) "
          f"+ snapshot spread >{args.min_snap_spread:.0%}: {len(cands)} candidates\n")
    print(f"  {'coin':6}{'snap spd':>9}{'mean spd':>9}{'persist':>8}{'net@mean':>10}  verdict")
    survivors = []
    for coin, sym in cands:
        hl_hist = feed.funding_history(coin, 0)
        hl_mean = _mean(hl_hist) * HOURS_PER_YEAR
        bn_mean = _bn_funding_hist_apr(sym)
        snap = abs(hl[coin]["funding"] - bn_snap[sym])
        mean_spread = abs(bn_mean - hl_mean)
        persist = mean_spread / snap if snap > 0 else 0.0      # 1.0 = fully persistent
        o = cross_venue_opp(coin, hl_apr=hl_mean, other_apr=bn_mean, hold_hours=args.hold,
                            round_trip=args.round_trip)
        if o.verdict == "PAPER":
            survivors.append(coin)
        print(f"  {coin:6}{snap:>+8.0%} {mean_spread:>+8.0%} {persist:>7.0%}"
              f"{o.net_edge_bps:>+10.1f}  {o.verdict}")
    print(f"\nLIQUID survivors of persistence+cost (PAPER on MEAN spread): "
          f"{survivors if survivors else 'NONE -- snapshots were spikes / spreads not persistent on liquid coins'}")


if __name__ == "__main__":
    main()
