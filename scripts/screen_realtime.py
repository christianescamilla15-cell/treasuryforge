"""Near-real-time multi-venue carry screen (Roadmap v2 -- the data-plane spike).

Validates the "monitor broadly, surface a real spread" approach WITHOUT capital. Each tick:
  - HL: one POST returns every perp's funding (cheap, full universe).
  - Binance: one GET (premiumIndex, no symbol) returns every USDT perp's funding.
    (Binance REST works from a residential IP where the VPS gets 451; its WS is gated,
    but funding is slow enough that a ~15s REST poll is 'real-time enough' for carry.)
  - OKX: per-instId, so only the top-K HL-vs-Binance movers are enriched to a true 3-venue
    widest spread (OKX has no all-funding REST; keeps the tick cheap).
Then it ranks by the WIDEST pairwise spread (treasuryforge.venue_spread) and flags any coin
whose widest clears the HONEST break-even floor (treasuryforge.cross_venue_economics, the
queen-metric floor at a 30-day hold). Read-only: no keys, no orders.

    python scripts/screen_realtime.py --interval 15 --top 12
    python scripts/screen_realtime.py --once
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request

sys.path.insert(0, ".")

from treasuryforge.cross_venue_economics import HOURS_PER_YEAR, breakeven_spread_apr
from treasuryforge.venue_spread import pairwise_spreads


def _get(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "treasuryforge/0.1"})
    with urllib.request.urlopen(req, timeout=15) as r:  # nosec B310
        return json.loads(r.read().decode())


def _post(url: str, body: dict):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json",
                                          "User-Agent": "treasuryforge/0.1"})
    with urllib.request.urlopen(req, timeout=15) as r:  # nosec B310
        return json.loads(r.read().decode())


def hl_funding() -> dict[str, float]:
    meta, ctxs = _post("https://api.hyperliquid.xyz/info", {"type": "metaAndAssetCtxs"})
    names = [a["name"] for a in meta["universe"]]
    return {n: float(ctxs[i]["funding"]) * HOURS_PER_YEAR for i, n in enumerate(names)}


def binance_funding() -> dict[str, float]:
    # premiumIndex with NO symbol returns the whole board in one call
    out: dict[str, float] = {}
    for d in _get("https://fapi.binance.com/fapi/v1/premiumIndex"):
        sym = d["symbol"]
        if sym.endswith("USDT"):
            out[sym[:-4]] = float(d["lastFundingRate"]) * 3 * 365
    return out


def binance_24h_volume() -> dict[str, float]:
    """One bulk call -> 24h quote (USDT) volume per perp. A liquidity proxy: a wide spread
    on a thin book is a mirage (slippage + orphan risk eat it). Filters the noise."""
    out: dict[str, float] = {}
    for d in _get("https://fapi.binance.com/fapi/v1/ticker/24hr"):
        sym = d.get("symbol", "")
        if sym.endswith("USDT"):
            out[sym[:-4]] = float(d.get("quoteVolume", 0.0))
    return out


def okx_funding(coin: str) -> float | None:
    try:
        d = _get(f"https://www.okx.com/api/v5/public/funding-rate?instId={coin}-USDT-SWAP")
        return float(d["data"][0]["fundingRate"]) * 3 * 365
    except Exception:
        return None


def screen_once(top: int, floor: float, min_volume: float) -> list[tuple]:
    hl = hl_funding()
    binance = binance_funding()
    vol = binance_24h_volume()
    # universe = on both venues AND liquid enough that slippage won't eat the spread
    overlap = sorted(c for c in set(hl) & set(binance) if vol.get(c, 0.0) >= min_volume)
    # rank cheaply by the 2-venue HL-Binance gap, then enrich the top-K with OKX
    ranked = sorted(overlap, key=lambda c: abs(hl[c] - binance[c]), reverse=True)[:top]
    rows = []
    for coin in ranked:
        funding = {"HL": hl[coin], "OKX": okx_funding(coin), "BIN": binance[coin]}
        m = pairwise_spreads(funding)
        rows.append((coin, m, funding, vol.get(coin, 0.0)))
    rows.sort(key=lambda r: r[1].widest_apr, reverse=True)
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=int, default=15, help="seconds between ticks")
    ap.add_argument("--top", type=int, default=12, help="HL-vs-Binance movers to enrich with OKX")
    ap.add_argument("--hold-hours", type=float, default=720.0, help="hold for the honest floor")
    ap.add_argument("--min-volume", type=float, default=50_000_000.0,
                    help="min Binance 24h USDT volume (liquidity floor; 0 disables)")
    ap.add_argument("--once", action="store_true", help="single tick then exit")
    args = ap.parse_args()
    floor = breakeven_spread_apr(args.hold_hours)
    print(f"honest floor ({args.hold_hours:.0f}h hold): {floor:+.2%} APR  |  liquidity floor: "
          f"${args.min_volume/1e6:.0f}M 24h vol -- below either is a mirage\n", flush=True)
    while True:
        try:
            rows = screen_once(args.top, floor, args.min_volume)
            alerts = [r for r in rows if r[1].widest_apr >= floor]
            print(f"-- tick {time.strftime('%H:%M:%S')}  ({len(alerts)} liquid & above floor) "
                  + "-" * 20, flush=True)
            for coin, m, funding, cvol in rows[:args.top]:
                w = m.widest
                flag = "  ** ABOVE FLOOR **" if m.widest_apr >= floor else ""
                venues = " ".join(f"{v}{f:+.1%}" for v, f in funding.items() if f is not None)
                pair = f"{w.short_venue}-{w.long_venue}" if w else "none"
                print(f"  {coin:8} widest {m.widest_apr:6.2%} via {pair:8} "
                      f"${cvol/1e6:5.0f}M [{venues}]{flag}", flush=True)
        except Exception as e:                               # a tick must never kill the screen
            print(f"  ! tick failed: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        if args.once:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
