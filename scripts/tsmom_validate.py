"""Deep, robust validation of TSMOM_VOLSCALED_V2 -- same gate that rejected V1.

Loads months of real 1m futures klines (data.binance.vision), resamples to HOURLY (minute
TSMOM is pure noise + cost), then sweeps the vol-scaled momentum params and reports each
config's annualised Sharpe, the equal-weight portfolio return, turnover/exposure, AND the
Deflated Sharpe Ratio across the sweep (anti-curve-fit), plus per-month stability. If the
best config's DSR <= 0.95 it is NOT validated -- exactly as V1 was rejected.

    python scripts/tsmom_validate.py --months 2026-03,2026-04,2026-05 --coins-top 30 --hours 1

Read-only research. No keys, no orders, no capital.
"""

from __future__ import annotations

import argparse
import sys

sys.path.insert(0, ".")

from _klines import LIQUID, load, resample

from treasuryforge.backtest.metrics import deflated_sharpe_ratio
from treasuryforge.signals.tsmom import TsmomParams
from treasuryforge.tsmom_backtest import backtest_tsmom_many


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", default="2026-03,2026-04,2026-05")
    ap.add_argument("--coins-top", type=int, default=30)
    ap.add_argument("--hours", type=int, default=1, help="bar size in hours (resample factor)")
    ap.add_argument("--cost", type=float, default=0.0006)
    args = ap.parse_args()
    months = [m.strip() for m in args.months.split(",")]
    coins = LIQUID[: args.coins_top]
    factor = 60 * args.hours
    ppy = int(24 * 365 / args.hours)                         # periods per year for annualised Sharpe

    print(f"Loading {len(coins)} coins x {len(months)} months, resampling to {args.hours}h bars ...",
          flush=True)
    data = load(coins, months)
    full = {c: resample([bar for m in months for bar in data[c].get(m, [])], factor) for c in data}
    full = {c: b for c, b in full.items() if len(b) > 60}
    nbars = sum(len(b) for b in full.values())
    print(f"  {len(full)} coins, {nbars:,} {args.hours}h bars\n", flush=True)

    grid = [(lb, vw, tv, ls) for lb in (6, 12, 24, 48) for vw in (24, 48)
            for tv in (0.005, 0.01, 0.02) for ls in (True, False)]
    print(f"=== sweep ({len(grid)} configs), equal-weight portfolio, {args.hours}h bars ===",
          flush=True)
    rows = []
    for lb, vw, tv, ls in grid:
        p = TsmomParams(lookback=lb, vol_window=vw, target_vol=tv, long_short=ls, cost=args.cost)
        res = backtest_tsmom_many(full, p)
        if res.n_periods >= 30:
            rows.append((p, res, res.sharpe()))             # non-annualised Sharpe for DSR
    rows.sort(key=lambda r: r[2], reverse=True)
    trial_sharpes = [s for _, _, s in rows]
    print(f"{'look':>4} {'volw':>4} {'tgt':>5} {'L/S':>3} | {'Sharpe_ann':>10} {'totNet':>7} "
          f"{'maxDD':>6} {'turn':>5} {'expo':>5}", flush=True)
    for p, res, _ in rows[:12]:
        print(f"{p.lookback:4d} {p.vol_window:4d} {p.target_vol:5.1%} {'LS' if p.long_short else 'L':>3} | "
              f"{res.sharpe(ppy):10.2f} {res.total_net:+7.0%} {res.max_drawdown:6.0%} "
              f"{res.turnover:5.2f} {res.exposure:5.2f}", flush=True)

    if rows:
        best_p, best_res, _ = rows[0]
        dsr = deflated_sharpe_ratio(best_res.returns, trial_sharpes=trial_sharpes)
        print(f"\n=== best-config robustness (DSR deflates for {len(rows)} trials) ===", flush=True)
        print(f"best: look {best_p.lookback} volw {best_p.vol_window} tgt {best_p.target_vol:.1%} "
              f"{'LS' if best_p.long_short else 'L'}  |  Sharpe_ann {best_res.sharpe(ppy):.2f}  "
              f"|  DSR = {dsr:.3f}  (gate > 0.95)", flush=True)
        print(f"VERDICT: {'REAL EDGE (survives deflation)' if dsr > 0.95 else 'NOT VALIDATED'}",
              flush=True)
        print("\n=== sub-period stability (best config, per month) ===", flush=True)
        for m in months:
            permon = {c: resample(data[c].get(m, []), factor) for c in data}
            permon = {c: b for c, b in permon.items() if len(b) > 60}
            rm = backtest_tsmom_many(permon, best_p)
            print(f"  {m}: periods={rm.n_periods:4d} Sharpe_ann={rm.sharpe(ppy):6.2f} "
                  f"totNet={rm.total_net:+.0%}", flush=True)


if __name__ == "__main__":
    main()
