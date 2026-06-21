"""Multi-venue funding-spread logger — the widest REACHABLE pair across every venue the
VPS can reach (HL / OKX / Gate / Bitget / MEXC / HTX) plus the region-permissive relay
(Binance / Bybit, read from state/relay/funding.json behind a freshness gate). Logs to
state/multivenue_<coin> every 5 min (systemd timer) so the multi-venue opportunity duty
cycle can be measured honestly: with more venues the widest pair is both WIDER and on MORE
of the time. Replaces the 2-venue log_cross_spread and the dead Binance `spread3` phantom.

Keyless. A powered-off relay drops Binance/Bybit to `missing` (never a stale spread).

    python scripts/log_multivenue_spread.py --coins XRP,ZEC
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request

sys.path.insert(0, ".")

from treasuryforge.journal import Journal
from treasuryforge.relay_feed import load_snapshot, relay_funding
from treasuryforge.venue_spread import pairwise_spreads

_HOURS_PER_YEAR = 24 * 365
_FUND_8H = 3 * 365          # 8-hour funded venues -> APR
_RELAY_MAX_AGE_S = 900      # relay snapshot older than 15 min -> Binance/Bybit drop to missing


def _get(url: str, post: dict | None = None) -> dict:
    if post is not None:
        req = urllib.request.Request(url, data=json.dumps(post).encode(), method="POST",
                                     headers={"Content-Type": "application/json",
                                              "User-Agent": "treasuryforge/0.1"})
    else:
        req = urllib.request.Request(url, headers={"User-Agent": "treasuryforge/0.1"})
    with urllib.request.urlopen(req, timeout=15) as r:  # nosec B310
        return json.loads(r.read().decode())


def _hl_all() -> dict[str, float]:
    """One call -> {coin: APR} for every Hyperliquid perp."""
    meta, ctxs = _get("https://api.hyperliquid.xyz/info", post={"type": "metaAndAssetCtxs"})
    return {a["name"]: float(c["funding"]) * _HOURS_PER_YEAR
            for a, c in zip(meta["universe"], ctxs)}


def _okx(coin: str) -> float:
    d = _get(f"https://www.okx.com/api/v5/public/funding-rate?instId={coin}-USDT-SWAP")
    return float(d["data"][0]["fundingRate"]) * _FUND_8H


def _gate(coin: str) -> float:
    return float(_get(f"https://api.gateio.ws/api/v4/futures/usdt/contracts/{coin}_USDT")
                 ["funding_rate"]) * _FUND_8H


def _bitget(coin: str) -> float:
    d = _get(f"https://api.bitget.com/api/v2/mix/market/current-fund-rate?symbol={coin}USDT"
             "&productType=usdt-futures")
    return float(d["data"][0]["fundingRate"]) * _FUND_8H


def _mexc(coin: str) -> float:
    return float(_get(f"https://contract.mexc.com/api/v1/contract/funding_rate/{coin}_USDT")
                 ["data"]["fundingRate"]) * _FUND_8H


def _htx(coin: str) -> float:
    return float(_get("https://api.hbdm.com/linear-swap-api/v1/swap_funding_rate"
                      f"?contract_code={coin}-USDT")["data"]["funding_rate"]) * _FUND_8H


# per-coin fetchers for the venues the VPS reaches directly
_VENUES = {"OKX": _okx, "GATE": _gate, "BITGET": _bitget, "MEXC": _mexc, "HTX": _htx}


def funding_for(coin: str, hl: dict[str, float], snap: dict, now: int) -> dict[str, float | None]:
    """Every venue's annualised funding for `coin`: None where unreachable this tick."""
    out: dict[str, float | None] = {"HL": hl.get(coin)}
    for name, fetch in _VENUES.items():
        try:
            out[name] = fetch(coin)
        except Exception:        # one unreachable venue must not sink the snapshot
            out[name] = None
    out.update(relay_funding(snap, coin, now=now, max_age_s=_RELAY_MAX_AGE_S))   # BIN/BYB
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--coins", default="XRP,ZEC")
    ap.add_argument("--state-prefix", default="state/multivenue")
    ap.add_argument("--relay", default="state/relay/funding.json")
    args = ap.parse_args()

    now = int(time.time())
    hl = _hl_all()
    snap = load_snapshot(args.relay)
    for coin in (c.strip().upper() for c in args.coins.split(",") if c.strip()):
        funding = funding_for(coin, hl, snap, now)
        m = pairwise_spreads(funding)
        w = m.widest
        Journal(f"{args.state_prefix}_{coin.lower()}").append_event({
            "kind": "multivenue", "ts": now,
            "widest_apr": m.widest_apr,
            "short": w.short_venue if w else "", "long": w.long_venue if w else "",
            "n_reachable": len(m.funding_apr), "missing": list(m.missing),
            "funding": {v: round(f, 6) for v, f in m.funding_apr.items()},
        })
        pair = f"short {w.short_venue}/long {w.long_venue}" if w else "no pair"
        print(f"[{coin:5}] widest {m.widest_apr:+.1%} APR  ({pair})  "
              f"{len(m.funding_apr)}/{len(funding)} venues  missing={m.missing}")


if __name__ == "__main__":
    main()
