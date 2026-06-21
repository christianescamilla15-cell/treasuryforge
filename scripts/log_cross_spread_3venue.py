"""3-venue cross spread logger (Roadmap v2) -- HL + OKX + Binance, measure don't trade.

Runs on a RESIDENTIAL IP (Christian's PC), because Binance's funding API (fapi) 451-blocks
datacenter IPs like the VPS but serves residential ones. Each venue is fetched best-effort:
if one is unreachable this tick it is logged as missing and the widest spread is taken among
the survivors (graceful degradation -- a stale Binance must never crash the logger or poison
the dataset). Writes state/spread3_<coin>/ledger.jsonl. No keys, no orders, no positions.

    python scripts/log_cross_spread_3venue.py --coins XRP,ZEC
"""

from __future__ import annotations

import argparse
import json
import subprocess  # nosec B404  (only ever runs scp/ssh to a fixed host, no shell)
import sys
import time
import urllib.request

sys.path.insert(0, ".")

from treasuryforge.cross_venue_economics import HOURS_PER_YEAR
from treasuryforge.journal import Journal
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


def _hl_all() -> dict[str, float]:
    """One call returns every coin's hourly funding -> annualised APR."""
    meta, ctxs = _post("https://api.hyperliquid.xyz/info", {"type": "metaAndAssetCtxs"})
    names = [a["name"] for a in meta["universe"]]
    return {n: float(ctxs[i]["funding"]) * HOURS_PER_YEAR for i, n in enumerate(names)}


def _okx(coin: str) -> float:
    d = _get(f"https://www.okx.com/api/v5/public/funding-rate?instId={coin}-USDT-SWAP")
    return float(d["data"][0]["fundingRate"]) * 3 * 365      # 8h funding -> APR


def _binance(coin: str) -> float:
    d = _get(f"https://fapi.binance.com/fapi/v1/premiumIndex?symbol={coin}USDT")
    return float(d["lastFundingRate"]) * 3 * 365             # 8h funding -> APR


def _safe(fn, *a):
    """Best-effort: return the funding APR or None (logged as a missing venue)."""
    try:
        return fn(*a)
    except Exception as e:                                   # any venue failure is non-fatal
        print(f"  ! venue fetch failed: {type(e).__name__}: {e}", file=sys.stderr)
        return None


def _push(coin: str, prefix: str, host: str) -> None:
    """Best-effort mirror of one ledger to the VPS (the PC is the sole writer). Never
    raises -- a sync failure must not affect the local measurement."""
    led = f"{prefix}_{coin.lower()}/ledger.jsonl"
    remote_dir = f"/opt/treasuryforge/{prefix}_{coin.lower()}"
    try:
        subprocess.run(["ssh", "-o", "ConnectTimeout=10", "-o", "BatchMode=yes", host,  # nosec B603 B607
                        f"mkdir -p {remote_dir}"], timeout=20, check=False)
        subprocess.run(["scp", "-o", "ConnectTimeout=10", "-o", "BatchMode=yes",  # nosec B603 B607
                        led, f"{host}:{remote_dir}/ledger.jsonl"], timeout=30, check=False)
    except Exception as e:                                   # any sync failure is non-fatal
        print(f"  ! sync to {host} failed: {type(e).__name__}: {e}", file=sys.stderr)


def _tick(coins: list[str], state_prefix: str, push_to: str) -> None:
    hl_all = _safe(_hl_all) or {}
    ts = int(time.time())
    for coin in coins:
        funding = {
            "HL": hl_all.get(coin),
            "OKX": _safe(_okx, coin),
            "BIN": _safe(_binance, coin),
        }
        m = pairwise_spreads(funding)
        w = m.widest
        Journal(f"{state_prefix}_{coin.lower()}").append_event({
            "kind": "spread3", "ts": ts,
            "funding_apr": m.funding_apr, "missing": list(m.missing),
            "widest_apr": m.widest_apr,
            "widest_pair": [w.short_venue, w.long_venue] if w else None,
        })
        venues = " | ".join(f"{v} {f:+.1%}" for v, f in funding.items() if f is not None)
        miss = f"  [missing: {','.join(m.missing)}]" if m.missing else ""
        pair = f"{w.short_venue}-{w.long_venue}" if w else "none"
        print(f"[{coin:5}] widest {m.widest_apr:+.2%} APR via {pair:8}  ({venues}){miss}", flush=True)
        if push_to:
            _push(coin, state_prefix, push_to)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--coins", default="XRP,ZEC")
    ap.add_argument("--state-prefix", default="state/spread3")
    ap.add_argument("--push-to", default="", help="VPS host (e.g. root@1.2.3.4) to mirror ledgers to")
    ap.add_argument("--loop", type=int, default=0, metavar="SECONDS",
                    help="run forever, one tick every SECONDS (0 = single tick, the default)")
    args = ap.parse_args()
    coins = [c.strip() for c in args.coins.split(",")]
    while True:
        try:
            _tick(coins, args.state_prefix, args.push_to)
        except Exception as e:                               # a tick must never kill the loop
            print(f"  ! tick failed: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        if args.loop <= 0:
            break
        time.sleep(args.loop)


if __name__ == "__main__":
    main()
