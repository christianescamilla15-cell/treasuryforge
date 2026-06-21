"""Deep, robust validation of MOMENTUM_IGNITION_V1 -- the honest gate.

Not a one-number pass/fail: it downloads MONTHS of real 1m futures klines from
data.binance.vision for many liquid coins (cached locally), then for a GRID of rule
parameters reports the full distribution, the equity/drawdown, the Sharpe, AND the
Deflated Sharpe Ratio (Bailey & Lopez de Prado) -- which deflates for the number of
configs tried, the exact guard against curve-fitting a sweep. It also breaks results
down by sub-period (per month) and by coin, so a positive expectancy that only exists
in one month / one coin is exposed as fragile rather than promoted.

    python scripts/momentum_validate.py --months 2026-03,2026-04,2026-05 --coins-top 30

Read-only research. No keys, no orders, no capital.
"""

from __future__ import annotations

import argparse
import csv
import io
import sys
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, ".")

from treasuryforge.backtest.metrics import deflated_sharpe_ratio, sharpe_ratio
from treasuryforge.momentum_backtest import backtest_many, backtest_momentum
from treasuryforge.signals.momentum import MomentumParams

CACHE = Path("data/klines")
LIQUID = ("BTC ETH SOL XRP DOGE ADA AVAX LINK SUI WLD PEPE WIF NEAR APT ARB INJ TIA SEI "
          "ORDI ENA BNB LTC BCH FIL ATOM OP RUNE AAVE UNI FARTCOIN POPCAT ONDO JTO TRUMP").split()


def _download(coin: str, month: str) -> list[tuple]:
    """Monthly 1m UM-futures klines (o,h,l,c), cached. Empty list if the dump 404s."""
    CACHE.mkdir(parents=True, exist_ok=True)
    cache = CACHE / f"{coin}USDT-1m-{month}.csv"
    if not cache.exists():
        url = (f"https://data.binance.vision/data/futures/um/monthly/klines/"
               f"{coin}USDT/1m/{coin}USDT-1m-{month}.zip")
        try:
            with urllib.request.urlopen(  # nosec B310
                    urllib.request.Request(url, headers={"User-Agent": "tf/0.1"}), timeout=60) as r:
                z = zipfile.ZipFile(io.BytesIO(r.read()))
            csv_bytes = z.read(z.namelist()[0]).decode()
            cache.write_text(csv_bytes)
        except Exception as e:                               # missing month / new listing
            print(f"  ! {coin} {month}: {type(e).__name__}", file=sys.stderr)
            cache.write_text("")
            return []
    rows = []
    for row in csv.reader(io.StringIO(cache.read_text())):
        if not row or not row[1].replace(".", "").replace("-", "").isdigit():
            continue                                         # skip a stray header line
        rows.append((float(row[1]), float(row[2]), float(row[3]), float(row[4])))
    return rows


def load(coins: list[str], months: list[str]) -> dict[str, dict[str, list[tuple]]]:
    """coin -> month -> bars."""
    out: dict[str, dict[str, list[tuple]]] = {}
    for c in coins:
        per_month = {m: _download(c, m) for m in months}
        if any(per_month.values()):
            out[c] = per_month
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", default="2026-03,2026-04,2026-05")
    ap.add_argument("--coins-top", type=int, default=30)
    ap.add_argument("--cost", type=float, default=0.0013)
    args = ap.parse_args()
    months = [m.strip() for m in args.months.split(",")]
    coins = LIQUID[: args.coins_top]
    print(f"Loading {len(coins)} coins x {len(months)} months from data.binance.vision ...",
          flush=True)
    data = load(coins, months)
    n_bars = sum(len(b) for m in data.values() for b in m.values())
    print(f"  {len(data)} coins, {n_bars:,} 1m bars total\n", flush=True)

    # full series per coin (all months concatenated, time-ordered)
    full = {c: [bar for m in months for bar in data[c].get(m, [])] for c in data}

    grid = [(e, cf, tr, sl) for e in (0.008, 0.012, 0.02, 0.03)
            for cf in (0.0, 0.003) for tr in (0.03, 0.05, 0.08) for sl in (0.05, 0.10)]
    print(f"=== parameter sweep ({len(grid)} configs), pooled across coins ===", flush=True)
    rows = []
    for e, cf, tr, sl in grid:
        p = MomentumParams(enter_1m=e, confirm_1m=cf, trail_frac=tr, stop_frac=sl, cost=args.cost)
        res = backtest_many(full, p)
        if res.n_trades >= 30:
            rows.append((p, res, sharpe_ratio(res.returns)))
    rows.sort(key=lambda r: r[2], reverse=True)
    trial_sharpes = [s for _, _, s in rows]
    print(f"{'enter':>6} {'conf':>5} {'trail':>5} {'stop':>5} | {'trades':>6} {'win%':>5} "
          f"{'exp/trade':>9} {'totNet':>7} {'PF':>5} {'Sharpe':>7} {'maxDD':>6}", flush=True)
    for p, res, sr in rows[:12]:
        print(f"{p.enter_1m:6.1%} {p.confirm_1m:5.1%} {p.trail_frac:5.0%} {p.stop_frac:5.0%} | "
              f"{res.n_trades:6d} {res.win_rate:5.0%} {res.expectancy:+9.3%} {res.total_net:+7.0%} "
              f"{res.profit_factor:5.2f} {sr:7.3f} {res.max_drawdown:6.0%}", flush=True)

    if rows:
        best_p, best_res, _ = rows[0]
        dsr = deflated_sharpe_ratio(best_res.returns, trial_sharpes=trial_sharpes)
        print(f"\n=== best config robustness (DSR deflates for {len(rows)} trials) ===", flush=True)
        print(f"best: enter {best_p.enter_1m:.1%} trail {best_p.trail_frac:.0%} stop "
              f"{best_p.stop_frac:.0%}  |  DSR = {dsr:.3f}  (promotion gate: > 0.95)", flush=True)
        verdict = ("REAL EDGE (survives deflation)" if dsr > 0.95
                   else "NOT VALIDATED -- best config is within what a lucky search would find")
        print(f"VERDICT: {verdict}", flush=True)

        print("\n=== sub-period stability of the best config (per month) ===", flush=True)
        for m in months:
            permon = {c: data[c].get(m, []) for c in data}
            rm = backtest_many(permon, best_p)
            print(f"  {m}: trades={rm.n_trades:4d} win={rm.win_rate:4.0%} "
                  f"exp/trade={rm.expectancy:+.3%} totNet={rm.total_net:+.0%}", flush=True)

        print("\n=== per-coin breakdown of the best config (top/bottom 5 by net) ===", flush=True)
        per_coin = sorted(((c, backtest_momentum(full[c], best_p)) for c in full),
                          key=lambda x: x[1].total_net, reverse=True)
        per_coin = [(c, r) for c, r in per_coin if r.n_trades > 0]
        for c, r in per_coin[:5] + per_coin[-5:]:
            print(f"  {c:10} trades={r.n_trades:3d} win={r.win_rate:4.0%} "
                  f"totNet={r.total_net:+.0%}", flush=True)


if __name__ == "__main__":
    main()
