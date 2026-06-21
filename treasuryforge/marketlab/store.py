"""Market data store — the local 'BD' to test against before prod.

A stdlib SQLite database of REAL historical market data (candles + funding),
synced keyless from Hyperliquid and replayed through the system. No external DB,
no deps. The fetch transport is injectable so the store is fully offline-testable.

Schema:
  candles(coin, interval, t, o, h, l, c, v)   PK (coin, interval, t)
  funding(coin, t, rate)                       PK (coin, t)
"""

from __future__ import annotations

import json
import sqlite3
import time
import urllib.request
from collections.abc import Callable


def _hl_post(body: dict):
    req = urllib.request.Request("https://api.hyperliquid.xyz/info",
        data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "treasuryforge/0.1"})
    # URL is a fixed HTTPS literal above; no user-controlled scheme/host
    with urllib.request.urlopen(req, timeout=25) as r:  # nosec B310
        return json.loads(r.read().decode())


class MarketStore:
    def __init__(self, path: str = "market.db") -> None:
        self.conn = sqlite3.connect(path)
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS candles(
                coin TEXT, interval TEXT, t INTEGER,
                o REAL, h REAL, l REAL, c REAL, v REAL,
                PRIMARY KEY (coin, interval, t));
            CREATE TABLE IF NOT EXISTS funding(
                coin TEXT, t INTEGER, rate REAL,
                PRIMARY KEY (coin, t));
            CREATE TABLE IF NOT EXISTS orderbook(
                coin TEXT, t INTEGER, side TEXT, lvl INTEGER, px REAL, sz REAL,
                PRIMARY KEY (coin, t, side, lvl));
        """)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # -- writes -----------------------------------------------------------
    def upsert_candles(self, coin: str, interval: str, rows: list[dict]) -> int:
        data = [(coin, interval, int(r["t"]), float(r["o"]), float(r["h"]),
                 float(r["l"]), float(r["c"]), float(r.get("v", 0.0))) for r in rows]
        self.conn.executemany(
            "INSERT OR REPLACE INTO candles VALUES (?,?,?,?,?,?,?,?)", data)
        self.conn.commit()
        return len(data)

    def upsert_funding(self, coin: str, rows: list[tuple[int, float]]) -> int:
        data = [(coin, int(t), float(rate)) for t, rate in rows]
        self.conn.executemany("INSERT OR REPLACE INTO funding VALUES (?,?,?)", data)
        self.conn.commit()
        return len(data)

    # -- reads ------------------------------------------------------------
    def closes(self, coin: str, interval: str = "1h") -> list[float]:
        cur = self.conn.execute(
            "SELECT c FROM candles WHERE coin=? AND interval=? ORDER BY t", (coin, interval))
        return [row[0] for row in cur.fetchall()]

    def funding_rates(self, coin: str) -> list[float]:
        cur = self.conn.execute("SELECT rate FROM funding WHERE coin=? ORDER BY t", (coin,))
        return [row[0] for row in cur.fetchall()]

    def summary(self) -> dict:
        c = self.conn.execute(
            "SELECT coin, interval, COUNT(*) FROM candles GROUP BY coin, interval").fetchall()
        f = self.conn.execute(
            "SELECT coin, COUNT(*) FROM funding GROUP BY coin").fetchall()
        return {"candles": {f"{coin}:{iv}": n for coin, iv, n in c},
                "funding": {coin: n for coin, n in f}}

    # -- live sync (keyless) ----------------------------------------------
    def sync_candles(self, coin: str, interval: str, days: int,
                     post: Callable | None = None) -> int:
        post = post or _hl_post
        now = int(time.time() * 1000)
        cur = now - days * 24 * 3600 * 1000
        total, seen = 0, set()
        while cur < now:
            candles = post({"type": "candleSnapshot", "req": {
                "coin": coin, "interval": interval, "startTime": cur, "endTime": now}})
            new = [c for c in candles if c["t"] not in seen]
            if not new:
                break
            for c in new:
                seen.add(c["t"])
            total += self.upsert_candles(coin, interval, new)
            cur = new[-1]["t"] + 1
            time.sleep(0.12)
        return total

    def fetch_orderbook(self, coin: str, post: Callable | None = None) -> dict:
        """Live keyless L2 order book (real depth = real volumetry)."""
        post = post or _hl_post
        return post({"type": "l2Book", "coin": coin})

    def snapshot_orderbook(self, coin: str, ts: int, book: dict) -> int:
        levels = book.get("levels", [[], []])
        rows = []
        for side, side_levels in (("bid", levels[0]), ("ask", levels[1])):
            for i, lv in enumerate(side_levels):
                rows.append((coin, ts, side, i, float(lv["px"]), float(lv["sz"])))
        self.conn.executemany("INSERT OR REPLACE INTO orderbook VALUES (?,?,?,?,?,?)", rows)
        self.conn.commit()
        return len(rows)

    def sync_funding(self, coin: str, days: int, post: Callable | None = None) -> int:
        post = post or _hl_post
        now = int(time.time() * 1000)
        cur = now - days * 24 * 3600 * 1000
        total, seen = 0, set()
        while cur < now:
            rows = post({"type": "fundingHistory", "coin": coin, "startTime": cur})
            new = [r for r in rows if r["time"] not in seen]
            if not new:
                break
            for r in new:
                seen.add(r["time"])
            total += self.upsert_funding(coin, [(r["time"], r["fundingRate"]) for r in new])
            cur = new[-1]["time"] + 1
            time.sleep(0.12)
        return total
