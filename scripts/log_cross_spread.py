"""High-frequency cross-venue spread logger (Roadmap v2 P4) -- measure, don't trade.

Logs the live HL-vs-OKX funding spread for the candidates every few minutes (driven by a
5-min systemd timer) to state/spread_<coin>/ledger.jsonl. Pure measurement: no keys, no
orders, no positions. This builds the UNBIASED forward dataset the duty-cycle needs (the
historical alignment was biased by HL's short funding history). From this we get the real
collapse speed, the hours-of-day it appears, and an honest opportunity duty cycle.

    python scripts/log_cross_spread.py --coins XRP,ZEC
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request

sys.path.insert(0, ".")

from treasuryforge.cross_venue_economics import HOURS_PER_YEAR
from treasuryforge.journal import Journal


def _get(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "treasuryforge/0.1"})
    with urllib.request.urlopen(req, timeout=20) as r:  # nosec B310
        return json.loads(r.read().decode())


def _post(url: str, body: dict):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json",
                                          "User-Agent": "treasuryforge/0.1"})
    with urllib.request.urlopen(req, timeout=20) as r:  # nosec B310
        return json.loads(r.read().decode())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--coins", default="XRP,ZEC")
    ap.add_argument("--state-prefix", default="state/spread")
    args = ap.parse_args()

    meta, ctxs = _post("https://api.hyperliquid.xyz/info", {"type": "metaAndAssetCtxs"})
    names = [a["name"] for a in meta["universe"]]
    ts = int(time.time())
    for coin in (c.strip() for c in args.coins.split(",")):
        hl = float(ctxs[names.index(coin)]["funding"]) * HOURS_PER_YEAR
        okx = float(_get(f"https://www.okx.com/api/v5/public/funding-rate?instId={coin}-USDT-SWAP")
                    ["data"][0]["fundingRate"]) * 3 * 365
        spread = abs(hl - okx)
        Journal(f"{args.state_prefix}_{coin.lower()}").append_event(
            {"kind": "spread", "ts": ts, "spread_apr": spread, "hl_apr": hl, "okx_apr": okx})
        print(f"[{coin:5}] spread {spread:+.2%} APR  (HL {hl:+.1%} | OKX {okx:+.1%})")


if __name__ == "__main__":
    main()
