"""Shared cached loader for Binance UM-futures 1m klines (data.binance.vision dumps).

Used by the momentum and TSMOM validators. Reachable from any IP (CDN mirror), unlike
the geo-gated trading API. Read-only research data; no keys.
"""

from __future__ import annotations

import csv
import io
import sys
import urllib.request
import zipfile
from pathlib import Path

CACHE = Path("data/klines")
Bar = tuple[float, float, float, float]   # open, high, low, close

LIQUID = ("BTC ETH SOL XRP DOGE ADA AVAX LINK SUI WLD WIF NEAR APT ARB INJ TIA SEI "
          "ORDI ENA BNB LTC BCH FIL ATOM OP RUNE AAVE UNI FARTCOIN POPCAT ONDO JTO TRUMP").split()


def download(coin: str, month: str) -> list[Bar]:
    """Monthly 1m klines (o,h,l,c), cached locally. Empty list if the dump is missing."""
    CACHE.mkdir(parents=True, exist_ok=True)
    cache = CACHE / f"{coin}USDT-1m-{month}.csv"
    if not cache.exists():
        url = (f"https://data.binance.vision/data/futures/um/monthly/klines/"
               f"{coin}USDT/1m/{coin}USDT-1m-{month}.zip")
        try:
            with urllib.request.urlopen(  # nosec B310
                    urllib.request.Request(url, headers={"User-Agent": "tf/0.1"}), timeout=60) as r:
                z = zipfile.ZipFile(io.BytesIO(r.read()))
            cache.write_text(z.read(z.namelist()[0]).decode())
        except Exception as e:                               # missing month / new listing
            print(f"  ! {coin} {month}: {type(e).__name__}", file=sys.stderr)
            cache.write_text("")
            return []
    rows: list[Bar] = []
    for row in csv.reader(io.StringIO(cache.read_text())):
        if not row or not row[1].replace(".", "").replace("-", "").isdigit():
            continue                                         # skip a stray header line
        rows.append((float(row[1]), float(row[2]), float(row[3]), float(row[4])))
    return rows


def load(coins: list[str], months: list[str]) -> dict[str, dict[str, list[Bar]]]:
    """coin -> month -> 1m bars (only coins with at least one non-empty month)."""
    out: dict[str, dict[str, list[Bar]]] = {}
    for c in coins:
        per_month = {m: download(c, m) for m in months}
        if any(per_month.values()):
            out[c] = per_month
    return out


def resample(bars: list[Bar], factor: int) -> list[Bar]:
    """Aggregate `factor` consecutive 1m bars into one (e.g. 60 -> hourly): open=first,
    high=max, low=min, close=last. Trailing partial bucket is dropped."""
    agg: list[Bar] = []
    for i in range(0, len(bars) - factor + 1, factor):
        chunk = bars[i:i + factor]
        agg.append((chunk[0][0], max(b[1] for b in chunk),
                    min(b[2] for b in chunk), chunk[-1][3]))
    return agg
