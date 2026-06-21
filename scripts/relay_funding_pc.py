"""Funding relay (region-permissive leg) -- run on a host that CAN reach the venues
the VPS cannot (Binance / Bybit 451 the German datacenter IP, but a Mexican residential
IP reaches them fine). Fetches their funding rates, prints one JSON snapshot to stdout.

    python scripts/relay_funding_pc.py --coins XRP,ZEC

A wrapper (Windows Task Scheduler every 5 min) pipes the output to the VPS:
    python scripts/relay_funding_pc.py | ssh root@VPS 'cat > /opt/treasuryforge/state/relay/funding.json'

The VPS spread logger reads that file as extra venues, behind a FRESHNESS gate: if the
snapshot is older than its budget, those venues drop to `missing` (venue_spread.py already
handles that), so a powered-off relay degrades cleanly instead of serving stale spreads.

Keyless, pure stdlib. Both venues fund every 8h -> APR = rate * 3 * 365.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request

_FUND_PER_YEAR = 3 * 365            # 8-hour funding -> annualised


def _get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "treasuryforge-relay/0.1"})
    with urllib.request.urlopen(req, timeout=15) as r:  # nosec B310
        return json.loads(r.read().decode())


def binance_funding_apr(coin: str) -> float:
    d = _get(f"https://fapi.binance.com/fapi/v1/premiumIndex?symbol={coin}USDT")
    return float(d["lastFundingRate"]) * _FUND_PER_YEAR


def bybit_funding_apr(coin: str) -> float:
    d = _get(f"https://api.bybit.com/v5/market/tickers?category=linear&symbol={coin}USDT")
    return float(d["result"]["list"][0]["fundingRate"]) * _FUND_PER_YEAR


_VENUES = {"BIN": binance_funding_apr, "BYB": bybit_funding_apr}


def snapshot(coins: list[str], now: int) -> dict:
    venues: dict[str, dict[str, float]] = {v: {} for v in _VENUES}
    missing: list[str] = []
    for venue, fetch in _VENUES.items():
        for coin in coins:
            try:
                venues[venue][coin] = fetch(coin)
            except Exception:  # one bad coin/venue must not sink the whole snapshot
                missing.append(f"{venue}:{coin}")
    return {"ts": now, "source": "pc-relay-mx", "venues": venues, "missing": missing}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--coins", default="XRP,ZEC")
    args = ap.parse_args()
    coins = [c.strip().upper() for c in args.coins.split(",") if c.strip()]
    snap = snapshot(coins, int(time.time()))
    json.dump(snap, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
