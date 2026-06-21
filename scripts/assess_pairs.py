"""Run the stat-arb PAIRS strategy through MEASURE -> VALIDATE -> SIZE -> SURVIVE
on real Hyperliquid price data. Contrast with funding-carry: pairs returns are
genuinely volatile, so Kelly is sane (not 15000x) and the ruin gate actually bites.

    python scripts/assess_pairs.py --interval 1h --days 120
"""

from __future__ import annotations

import argparse
import itertools
import json
import sys
import time
import urllib.request

sys.path.insert(0, ".")

from treasuryforge.backtest import backtest_pairs
from treasuryforge.backtest.cv import purged_kfold
from treasuryforge.backtest.metrics import deflated_sharpe_ratio, sharpe_ratio
from treasuryforge.risk import assess_and_report
from treasuryforge.signals.cointegration import engle_granger

INTERVAL_HOURS = {"1h": 1, "4h": 4, "1d": 24}


def _post(b):
    req = urllib.request.Request("https://api.hyperliquid.xyz/info",
        data=json.dumps(b).encode(), method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "treasuryforge/0.1"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode())


def fetch_closes(coin, interval, days):
    now = int(time.time() * 1000); start = now - days * 24 * 3600 * 1000
    out, cur = {}, start
    while cur < now:
        cs = _post({"type": "candleSnapshot", "req": {
            "coin": coin, "interval": interval, "startTime": cur, "endTime": now}})
        new = [c for c in cs if c["t"] not in out]
        if not new:
            break
        for c in new:
            out[c["t"]] = float(c["c"])
        cur = new[-1]["t"] + 1; time.sleep(0.12)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", default="1h", choices=list(INTERVAL_HOURS))
    ap.add_argument("--days", type=int, default=120)
    ap.add_argument("--fee", type=float, default=0.0005)
    ap.add_argument("--coins", default="BTC,ETH,SOL,AVAX,ARB,OP,LINK,LTC,DOGE,BNB")
    args = ap.parse_args()
    ppy = int(24 * 365 / INTERVAL_HOURS[args.interval])

    series = {}
    for c in args.coins.split(","):
        s = fetch_closes(c.strip(), args.interval, args.days)
        if len(s) > 100:
            series[c.strip()] = s
    common = sorted(set.intersection(*[set(s) for s in series.values()]))
    aligned = {c: [series[c][t] for t in common] for c in series}

    results = []
    for x, y in itertools.combinations(sorted(aligned), 2):
        r = engle_granger(aligned[x], aligned[y])
        if r.cointegrated and r.half_life != float("inf"):
            bt = backtest_pairs(aligned[x], aligned[y], alpha=r.alpha, beta=r.beta,
                                window=60, entry_z=2.0, exit_z=0.5, fee_per_leg=args.fee)
            results.append((x, y, r, bt))
    results.sort(key=lambda t: t[3].sharpe(ppy), reverse=True)
    print(f"=== pairs: {len(common)} bars, cointegrated {len(results)} ===")
    if not results:
        print("no cointegrated pairs"); return

    x, y, r, bt = results[0]
    R = bt.returns
    trial_sharpes = [sharpe_ratio(t[3].returns) for t in results]
    dsr = deflated_sharpe_ratio(R, trial_sharpes=trial_sharpes)
    cv_folds = [round(sharpe_ratio([R[i] for i in test], ppy), 1)
                for _tr, test in purged_kfold(len(R), k=5, embargo=24)]

    report = assess_and_report(
        f"PAIRS  {x}/{y}  (half-life {r.half_life:.0f}h)", R,
        dsr=dsr, periods_per_year=ppy, cv_folds=cv_folds,
        dsr_min=0.60, hard_cap=3.0, tail_discount=0.5,
        max_p_ruin=0.05, ruin_drawdown=0.30, max_expected_drawdown=0.20,
        tail_shock_prob=0.005, tail_shock_mult=6.0, paths=4000, seed=1)
    print(report.render())


if __name__ == "__main__":
    main()
