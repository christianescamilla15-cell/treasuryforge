"""Gate.io spot fetcher for the moonshot test -- the wild micro-cap universe (2000+ USDT
pairs) where 100x moves and rugs both live, unlike Binance's curated listings.

Candle field order (Gate v4 spot): [ts, quote_vol, close, high, low, open, base_vol, closed].
Cached locally. SURVIVORSHIP: the API lists only LIVE pairs, so fully-delisted rugs are
absent -> any result here is OPTIMISTIC. Read-only research.
"""

from __future__ import annotations

import csv
import json
import sys
import time
import urllib.request
from pathlib import Path

CACHE = Path("data/gate")
Bar = tuple[float, float, float, float]   # open, high, low, close


def _get(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "tf/0.1"})
    with urllib.request.urlopen(req, timeout=30) as r:  # nosec B310
        return json.loads(r.read().decode())


def universe_by_volume() -> list[tuple[str, float]]:
    """All live USDT spot pairs, (coin, approx 24h USD volume), one call. Sorted desc."""
    tickers = _get("https://api.gateio.ws/api/v4/spot/tickers")
    out = []
    for t in tickers:
        cp = t.get("currency_pair", "")
        if cp.endswith("_USDT"):
            try:
                vol = float(t.get("base_volume", 0.0)) * float(t.get("last", 0.0))
            except ValueError:
                continue
            out.append((cp[:-5], vol))
    out.sort(key=lambda x: x[1], reverse=True)
    return out


def klines_1h(coin: str, days: int) -> list[Bar]:
    """`days` of 1h candles (o,h,l,c), paginated and cached. Empty list on failure."""
    CACHE.mkdir(parents=True, exist_ok=True)
    cache = CACHE / f"{coin}_USDT-1h-{days}d.csv"
    if cache.exists():
        rows = []
        for r in csv.reader(cache.open()):
            if r:
                rows.append((float(r[0]), float(r[1]), float(r[2]), float(r[3])))
        return rows
    end = None
    spans, got = [], 0
    start = int(time.time()) - days * 86400
    cursor = start
    pair = f"{coin}_USDT"
    try:
        while cursor < int(time.time()) and got < days * 24 + 50:
            url = (f"https://api.gateio.ws/api/v4/spot/candlesticks?currency_pair={pair}"
                   f"&interval=1h&from={cursor}&limit=1000")
            chunk = _get(url)
            if not chunk:
                break
            spans.extend(chunk)
            got += len(chunk)
            last_ts = int(chunk[-1][0])
            if last_ts <= cursor:
                break
            cursor = last_ts + 3600
            end = last_ts
            time.sleep(0.12)                              # polite to the public endpoint
    except Exception as e:
        print(f"  ! {coin}: {type(e).__name__}", file=sys.stderr)
        cache.write_text("")
        return []
    _ = end
    bars: list[Bar] = []
    seen = set()
    for c in spans:
        ts = c[0]
        if ts in seen:
            continue
        seen.add(ts)
        # [ts, quote_vol, close, high, low, open, ...]
        bars.append((float(c[5]), float(c[3]), float(c[4]), float(c[2])))
    with cache.open("w", newline="") as f:
        w = csv.writer(f)
        for o, h, low, cl in bars:
            w.writerow([o, h, low, cl])
    return bars
