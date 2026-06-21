"""Coinbase Exchange spot fetcher for the moonshot test -- where Christian actually traded.

More curated and less survivorship-biased than Gate/MEXC (Coinbase delists slowly), so a
cleaner honest test, though 100x moves are rarer on a curated venue. Candle field order
(Coinbase): [time, low, high, open, close, volume]. Cached. Read-only research.
"""

from __future__ import annotations

import csv
import json
import sys
import time
import urllib.request
from pathlib import Path

CACHE = Path("data/coinbase")
Bar = tuple[float, float, float, float]   # open, high, low, close
API = "https://api.exchange.coinbase.com"


def _get(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "tf/0.1"})
    with urllib.request.urlopen(req, timeout=30) as r:  # nosec B310
        return json.loads(r.read().decode())


def usd_products() -> list[str]:
    """Online USD/USDT/USDC-quoted product ids (the tradeable universe)."""
    prods = _get(f"{API}/products")
    return [p["id"] for p in prods
            if p.get("quote_currency") in ("USD", "USDT", "USDC")
            and p.get("status") == "online" and not p.get("trading_disabled")]


def recent_1h(product: str, n: int = 8) -> list[Bar]:
    """The last n 1h candles (o,h,l,c), uncached -- for the live detector / resolver."""
    try:
        raw = _get(f"{API}/products/{product}/candles?granularity=3600")
    except Exception:
        return []
    out: list[Bar] = []
    for c in sorted(raw, key=lambda x: x[0])[-n:]:
        # [time, low, high, open, close, volume]
        out.append((float(c[3]), float(c[2]), float(c[1]), float(c[4])))
    return out


def path_since(product: str, since_ts: int) -> list[Bar]:
    """1h candles from `since_ts` to now (o,h,l,c), for resolving an ignition's outcome."""
    import time as _t
    raw: list[list] = []
    end = int(_t.time())
    try:
        while end > since_ts:
            start = max(since_ts, end - 300 * 3600)
            chunk = _get(f"{API}/products/{product}/candles?granularity=3600&start={start}&end={end}")
            if not chunk:
                break
            raw.extend(chunk)
            oldest = min(int(c[0]) for c in chunk)
            if oldest >= end:
                break
            end = oldest - 3600
            _t.sleep(0.18)
    except Exception:
        return []
    out: list[Bar] = []
    seen = set()
    for c in sorted(raw, key=lambda x: x[0]):
        if c[0] in seen or int(c[0]) < since_ts:
            continue
        seen.add(c[0])
        out.append((float(c[3]), float(c[2]), float(c[1]), float(c[4])))
    return out


def klines_1h(product: str, days: int) -> list[Bar]:
    """`days` of 1h candles (o,h,l,c), paged backward (max ~300/call) and cached."""
    CACHE.mkdir(parents=True, exist_ok=True)
    cache = CACHE / f"{product}-1h-{days}d.csv"
    if cache.exists():
        rows = []
        for r in csv.reader(cache.open()):
            if r:
                rows.append((float(r[0]), float(r[1]), float(r[2]), float(r[3])))
        return rows
    now = int(time.time())
    floor = now - days * 86400
    raw: list[list] = []
    end = now
    try:
        while end > floor:
            start = max(floor, end - 300 * 3600)
            url = f"{API}/products/{product}/candles?granularity=3600&start={start}&end={end}"
            chunk = _get(url)
            if not chunk:
                break
            raw.extend(chunk)
            oldest = min(int(c[0]) for c in chunk)
            if oldest >= end:
                break
            end = oldest - 3600
            time.sleep(0.18)                             # polite to the public endpoint
    except Exception as e:
        print(f"  ! {product}: {type(e).__name__}", file=sys.stderr)
        cache.write_text("")
        return []
    bars: list[Bar] = []
    seen = set()
    for c in sorted(raw, key=lambda x: x[0]):
        ts = c[0]
        if ts in seen:
            continue
        seen.add(ts)
        # [time, low, high, open, close, volume]
        bars.append((float(c[3]), float(c[2]), float(c[1]), float(c[4])))
    with cache.open("w", newline="") as f:
        w = csv.writer(f)
        for o, h, low, cl in bars:
            w.writerow([o, h, low, cl])
    return bars
